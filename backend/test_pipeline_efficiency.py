"""No-network integration checks for call savings, quota bounds and stage recovery."""
import asyncio
import copy
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import groq_client
import pipeline
from models import new_run_payload


def domain(name):
    return {
        "metric_effects": [
            {"metric": f"{name} delivery", "direction": "up", "magnitude": "moderate", "confidence": 0.7},
            {"metric": f"{name} costs", "direction": "down", "magnitude": "small", "confidence": 0.6},
        ],
        "reasoning": f"The rail policy affects {name} through improved freight access, subject to funding and delivery constraints.",
        "affected_states_weight": {"Maharashtra": 0.7} if name != "legal_budget" else {},
    }


def outputs():
    domains = {name: domain(name) for name in pipeline.DOMAIN_NAMES}
    risk = {
        "risk_level": "Medium",
        "justification": "Freight corridor delivery depends on financing and coordination across authorities. Land acquisition can delay implementation.",
        "confidence": 0.6,
        "confidence_rationale": "The findings consistently identify delivery constraints, but provide limited empirical cost data.",
    }
    synthesis = {
        "brief": {key: [{"text": "Funding and authority coordination determine freight access.", "evidence_ids": []}] for key in ("policy", "benefits", "risks", "affected", "uncertainty", "actions")},
        "overall_impact_score": 62,
        "impact_score_rationale": "Freight access supports several sectors while implementation constraints limit near-term effects. This is a qualitative magnitude index.",
        "verdict": "Phased rail investment can improve access if funding and coordination constraints are addressed.",
        "top_3_effects": ["Improved freight access", "Higher delivery coordination needs", "Reduced logistics friction"],
        "risk_level": "Medium",
    }
    return {
        "Parser": {
            "domain": "Transport", "goals": ["Improve freight access"],
            "stakeholders": ["Rail operators", "State governments"],
            "affected_sectors": ["Transport"], "timeline_years": 5,
        },
        "Specialists": domains,
        **{name.replace("_", " ").title(): finding for name, finding in domains.items()},
        "Risk Synthesis": {"risk": risk, "synthesis": synthesis},
        "Risk": risk,
        "Synthesis": synthesis,
        "Scenario": {"scenarios": [
            {
                "label": label, "probability": probability,
                "probability_rationale": "The balance of corridor delivery risks and freight access benefits supports this scenario.",
                "title": f"{label} freight corridor implementation",
                "body": f"{label} delivery depends on corridor financing and authority coordination, which change freight access and the timing of logistics benefits.",
                "points": ["Funding controls rollout speed.", "Coordination affects access.", "Land approvals affect delivery."],
            }
            for label, probability in (("Optimistic", 30), ("Realistic", 50), ("Worst-case", 20))
        ]},
        "Recommendation": {"recommendations": [
            {
                "priority": "High priority", "title": f"Phase freight corridor delivery {index}",
                "description": "Sequence corridor investments according to verified funding and authority readiness.",
                "why": "Financing and coordination constraints identified in the findings can otherwise delay freight access.",
                "supporting_signals": ["Funding dependency", "Authority coordination"],
            } for index in range(3)
        ]},
    }


@pytest.fixture
def fake_storage(monkeypatch):
    saved = new_run_payload("run-test", "Expand railway freight corridors with phased funding.", "Transport", False)
    saved["policy_input"]["analysis_mode"] = "balanced"

    async def get_run(_run_id):
        return copy.deepcopy(saved)

    async def patch_run(_run_id, mutator):
        mutator(saved)
        return copy.deepcopy(saved)

    monkeypatch.setattr(pipeline.db, "get_run", get_run)
    monkeypatch.setattr(pipeline.db, "patch_run", patch_run)
    monkeypatch.setenv("GROQ_TOKENS_PER_MINUTE", "8000")
    monkeypatch.setenv("GROQ_TPM_SAFETY_RATIO", "0.70")
    monkeypatch.setenv("GROQ_MAX_REQUEST_TOKENS", "5500")
    return saved


def install_fake_model(monkeypatch, calls, *, fail_stage=None):
    response_by_stage = outputs()

    async def chat(_client, *, stage_name, system, user, max_tokens, **_kwargs):
        # Run the real budget preparation, then deliberately avoid the network.
        _, estimated = groq_client._prepare_user_for_token_budget(system, user, max_tokens)
        assert estimated <= 5500
        calls.append(stage_name)
        await groq_client._emit_progress(event="request", model="mock")
        if stage_name == fail_stage:
            raise groq_client.GroqError("Simulated transport failure")
        await groq_client._emit_progress(event="usage", tokens=100)
        return copy.deepcopy(response_by_stage[stage_name])

    monkeypatch.setattr(pipeline, "chat_json", chat)


@pytest.mark.parametrize("mode,expected", [("balanced", 4), ("deep", 8)])
def test_modes_produce_complete_grounded_results_with_bounded_requests(
    monkeypatch, fake_storage, mode, expected
):
    fake_storage["policy_input"]["analysis_mode"] = mode
    calls = []
    install_fake_model(monkeypatch, calls)

    asyncio.run(pipeline.run_pipeline("run-test"))

    assert fake_storage["status"] == "complete", fake_storage.get("error")
    assert len(calls) == expected
    assert fake_storage["telemetry"]["api_requests"] == expected
    assert fake_storage["telemetry"]["tokens_used"] == expected * 100
    assert fake_storage["telemetry"]["planned_calls"] == expected
    assert all(agent["status"] == "done" for agent in fake_storage["agents"].values())
    assert sum(item["probability"] for item in fake_storage["scenario_set"]["scenarios"]) == 100
    assert len(fake_storage["recommendations"]["recommendations"]) == 3
    assert fake_storage["synthesis"]["confidence_basis"]["method"] == "equal_weighted_agent_mean"
    assert fake_storage["state_impact_basis"]["method"] == "heuristic_seed_weighting"
    assert groq_client._progress_callback.get() is None


def test_retry_resumes_validated_stages_instead_of_repeating_model_calls(monkeypatch, fake_storage):
    calls = []
    install_fake_model(monkeypatch, calls, fail_stage="Risk Synthesis")
    asyncio.run(pipeline.run_pipeline("run-test"))
    assert fake_storage["status"] == "error"
    assert calls == ["Specialists", "Risk Synthesis"]

    calls.clear()
    install_fake_model(monkeypatch, calls)
    fake_storage["status"] = "pending"
    asyncio.run(pipeline.run_pipeline("run-test"))

    assert fake_storage["status"] == "complete", fake_storage.get("error")
    assert calls == ["Risk Synthesis", "Scenario", "Recommendation"]
    assert fake_storage["telemetry"]["resumed_stages"] == [
        "parser", "specialists"
    ]


def test_cancelled_run_never_consumes_a_request(monkeypatch, fake_storage):
    fake_storage["status"] = "cancelled"
    calls = []
    install_fake_model(monkeypatch, calls)
    asyncio.run(pipeline.run_pipeline("run-test"))
    assert calls == []
    assert fake_storage["status"] == "cancelled"


def test_legacy_run_without_mode_keeps_deep_pipeline(monkeypatch, fake_storage):
    fake_storage["policy_input"].pop("analysis_mode")
    calls = []
    install_fake_model(monkeypatch, calls)
    asyncio.run(pipeline.run_pipeline("run-test"))
    assert fake_storage["status"] == "complete", fake_storage.get("error")
    assert len(calls) == 8


def test_balanced_evidence_retains_all_reference_states_inside_existing_ceiling(monkeypatch):
    monkeypatch.setenv("GROQ_TOKENS_PER_MINUTE", "8000")
    monkeypatch.setenv("GROQ_TPM_SAFETY_RATIO", "0.70")
    monkeypatch.setenv("GROQ_MAX_REQUEST_TOKENS", "5500")
    seeds = pipeline._load_state_seed()
    evidence = pipeline._balanced_evidence(
        outputs()["Parser"], seeds,
        [{"chunk_id": str(i), "text": "Freight funding and delivery evidence. " * 30} for i in range(5)],
        [{"title": f"Freight research {i}", "url": f"https://example.org/{i}",
          "text": "Research identifies authority coordination constraints. " * 20} for i in range(4)],
    )
    prepared, estimated = groq_client._prepare_user_for_token_budget(
        pipeline.BALANCED_SPECIALISTS_SYSTEM, json.dumps(evidence), 1800
    )
    assert estimated <= 5500
    assert len(json.loads(prepared)["state_reference"]["rows"]) == len(seeds)

