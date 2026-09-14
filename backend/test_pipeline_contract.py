import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from json_util import (
    normalize_domain_output,
    normalize_recommendation_output,
    normalize_scenario_output,
    parse_json_object,
)
from pipeline import (
    _aggregate_agent_confidence,
    _build_recommendation_payload,
    _compact_repair_context,
    _validate_domain_output,
    _validate_recommendation_output,
    _validate_scenario_output,
)
from groq_client import _prepare_user_for_token_budget
from prompts import RECOMMENDATION_SYSTEM
from rag import compact_policy_text


def test_overall_confidence_is_equal_weight_mean_of_five_agent_values():
    def domain(*values: float):
        return {"metric_effects": [{"confidence": value} for value in values]}

    confidence_value, basis = _aggregate_agent_confidence(
        {
            "economic": domain(0.8, 0.6),
            "environment": domain(0.5, 0.7),
            "social": domain(0.9),
            "legal_budget": domain(0.4),
            "risk": {"confidence": 0.8},
        }
    )

    assert confidence_value == 0.68
    assert basis["components"] == {
        "economic": 0.7,
        "environment": 0.6,
        "social": 0.9,
        "legal_budget": 0.4,
        "risk": 0.8,
    }
    assert basis["method"] == "equal_weighted_agent_mean"


def test_validation_repair_drops_duplicate_evidence_but_keeps_agent_findings():
    payload = {
        "parsed_policy": {"domain": "Education", "goals": ["Universal access"]},
        "economic": {"reasoning": "Supported economic finding", "metric_effects": []},
        "environment": {"reasoning": "Supported environment finding", "metric_effects": []},
        "social": {"reasoning": "Supported social finding", "metric_effects": []},
        "legal_budget": {"reasoning": "Supported legal finding", "metric_effects": []},
        "risk": {"justification": "Supported risk finding"},
        "evidence_bundle": {"web_sources": [{"text": "duplicate evidence " * 500}]},
        "web_sources": [{"text": "duplicate evidence " * 500}],
    }

    repaired = _compact_repair_context(payload)

    assert "evidence_bundle" not in repaired
    assert "web_sources" not in repaired
    assert repaired["parsed_policy"] == payload["parsed_policy"]
    assert set(("economic", "environment", "social", "legal_budget", "risk")) <= repaired.keys()


def test_long_policy_compaction_samples_across_document_and_end():
    policy = "A" * 9000 + "MIDDLE_MARKER" + "B" * 9000 + "END_MARKER"

    compacted = compact_policy_text(policy, max_characters=3000, segments=6)

    assert compacted.startswith("\n[Policy excerpt 1/6]\n")
    assert "[Policy excerpt 3/6]" in compacted
    assert "A" in compacted and "B" in compacted
    assert "END_MARKER" in compacted
    assert len(compacted) <= 3000


def test_recommendation_payload_limits_evidence_and_fits_safe_ceiling(monkeypatch):
    monkeypatch.setenv("GROQ_TOKENS_PER_MINUTE", "8000")
    monkeypatch.setenv("GROQ_TPM_SAFETY_RATIO", "0.70")
    monkeypatch.setenv("GROQ_MAX_REQUEST_TOKENS", "5500")
    parsed = {
        "domain": "Infrastructure",
        "goals": ["Improve multimodal connectivity", "Reduce logistics costs"],
        "stakeholders": ["Union ministries", "State governments"],
        "affected_sectors": ["Roads", "Railways"],
        "timeline_years": 5,
    }
    finding = {
        "metric_effects": [
            {"metric": f"metric {index}", "direction": "up", "magnitude": "moderate", "confidence": 0.7}
            for index in range(6)
        ],
        "reasoning": "supported specialist reasoning " * 200,
        "affected_states_weight": {f"State {index}": 1 - index / 20 for index in range(15)},
    }
    agents = {name: finding for name in ("economic", "environment", "social", "legal_budget")}
    scenarios = [
        {
            "label": label,
            "probability": probability,
            "probability_rationale": "supported probability rationale " * 80,
            "title": f"{label} infrastructure path",
            "body": "scenario grounded in completed findings " * 200,
            "points": ["supported scenario mechanism " * 30 for _ in range(5)],
        }
        for label, probability in (("Optimistic", 30), ("Realistic", 50), ("Worst-case", 20))
    ]
    evidence = [{"chunk_id": str(i), "text": "local evidence " * 500, "relevance": 1} for i in range(8)]
    web = [{"title": f"Source {i}", "url": f"https://example.com/{i}", "text": "web evidence " * 500} for i in range(8)]

    payload = _build_recommendation_payload(
        parsed,
        agents,
        {"risk_level": "Medium", "confidence": 0.7, "justification": "supported risk " * 100},
        scenarios,
        evidence,
        web,
    )
    prepared, estimated = _prepare_user_for_token_budget(
        RECOMMENDATION_SYSTEM, json.dumps(payload), 1100
    )

    assert estimated <= 5500
    assert len(payload["evidence_bundle"]["retrieved_context"]) == 1
    assert len(payload["evidence_bundle"]["web_sources"]) == 1
    assert len(payload["scenarios"]) == 3
    assert all(name in json.loads(prepared) for name in agents)


def test_parse_json_object_extracts_object_from_plain_text_fallback():
    result = parse_json_object('Here is the requested result:\n{"domain":"Energy"}\nDone.')

    assert result == {"domain": "Energy"}


def test_parse_json_object_ignores_qwen_thinking_block():
    result = parse_json_object(
        '<think>The schema example is {"wrong":true}, but the final answer follows.</think>\n'
        '{"domain":"Infrastructure","goals":["Multimodal connectivity"]}'
    )

    assert result["domain"] == "Infrastructure"


def test_domain_normalizer_preserves_common_llm_field_aliases():
    normalized = normalize_domain_output(
        {
            "effects": [
                {
                    "indicator": "industrial emissions",
                    "trend": "up",
                    "size": "large",
                    "confidence_score": 0.72,
                }
            ],
            "analysis": "Manufacturing expansion increases energy demand and emissions unless cleaner production controls are implemented.",
        }
    )

    assert normalized["metric_effects"][0]["metric"] == "industrial emissions"
    assert normalized["reasoning"].startswith("Manufacturing expansion")
    assert _validate_domain_output(normalized) == []


def test_partial_scenarios_are_rejected_instead_of_padded_with_placeholders():
    normalized = normalize_scenario_output(
        {
            "scenarios": [
                {
                    "label": "Optimistic",
                    "title": "Accelerated manufacturing investment",
                    "body": "Coordinated infrastructure and approvals increase manufacturing investment while safeguards reduce the main social and environmental risks.",
                    "points": ["Investment rises.", "Jobs expand.", "Safeguards limit pollution."],
                }
            ]
        }
    )

    assert len(normalized["scenarios"]) == 1
    assert "exactly Optimistic" in _validate_scenario_output(normalized)[0]
    assert all(item["title"] != "Scenario pending" for item in normalized["scenarios"])


def test_empty_recommendations_are_rejected():
    errors = _validate_recommendation_output({"recommendations": []})

    assert errors == ["recommendations must contain at least three evidence-grounded actions"]


def test_normalize_scenario_output_keeps_policy_specific_shape():
    raw = {
        "scenarios": [
            {
                "label": "Optimistic",
                "probability": 39,
                "title": "Rapid EV charging rollout reduces travel delays",
                "body": "If charging deployment and grid upgrades keep pace, commuters and freight operators should see smoother travel and fewer outages.",
                "points": [
                    "Grid upgrades support faster charging capacity before peak demand.",
                    "Freight operators experience fewer route interruptions.",
                    "Public confidence rises as reliability improves."
                ],
            },
            {
                "label": "Realistic",
                "probability": 27,
                "title": "Implementation progresses unevenly across corridors",
                "body": "Benefits will be strongest in the first metro corridors while rural deployments trail behind staffing and permitting constraints.",
                "points": [
                    "Early gains concentrate in major urban corridors.",
                    "Operating costs remain elevated until network density improves.",
                    "Local permitting and utility coordination remain critical." 
                ],
            },
            {
                "label": "Worst-case",
                "probability": 34,
                "title": "Delay in charging buildout worsens network bottlenecks",
                "body": "If installation and grid upgrades slip, demand will outrun infrastructure and reliability may worsen.",
                "points": [
                    "Charging demand outruns grid capacity in key districts.",
                    "Freight delays increase because charging access remains inconsistent.",
                    "User costs rise as waiting times and outages become common."
                ]
            }
        ]
    }

    normalized = normalize_scenario_output(raw)

    assert normalized["scenarios"][0]["label"] == "Optimistic"
    assert normalized["scenarios"][0]["probability"] == 39
    assert normalized["scenarios"][0]["title"].startswith("Rapid")
    assert len(normalized["scenarios"]) == 3


def test_scenario_probabilities_preserve_model_weights_and_repair_rounding():
    rationales = {
        "Optimistic": "High delivery capacity and strong economic confidence support upside execution.",
        "Realistic": "Fiscal constraints and coordination risks make phased implementation most plausible.",
        "Worst-case": "Environmental and legal uncertainties create a material but smaller downside path.",
    }
    raw = {
        "scenarios": [
            {
                "label": label,
                "probability": probability,
                "probability_rationale": rationales[label],
                "title": f"{label} policy-specific implementation path",
                "body": "This policy-specific scenario follows the completed agent findings and identifies concrete implementation mechanisms and constraints.",
                "points": ["First supported mechanism.", "Second supported mechanism.", "Third supported mechanism."],
            }
            for label, probability in [("Optimistic", 31), ("Realistic", 44), ("Worst-case", 26)]
        ]
    }

    normalized = normalize_scenario_output(raw)

    assert [item["probability"] for item in normalized["scenarios"]] == [31, 43, 26]
    assert sum(item["probability"] for item in normalized["scenarios"]) == 100
    assert _validate_scenario_output(normalized) == []


def test_normalize_recommendation_output_preserves_supporting_reasoning():
    raw = {
        "recommendations": [
            {
                "priority": "High priority",
                "title": "Phase deployment by corridor",
                "description": "Sequence charging expansion around the busiest freight and commuter corridors before scaling statewide.",
                "why": "This matches the identified network bottleneck and the concentration of expected benefits in urban corridors.",
                "supporting_signals": ["Urban corridor congestion", "Grid upgrade dependency"]
            },
            {
                "priority": "Medium priority",
                "title": "Publish a maintenance and utility coordination plan",
                "description": "Require utility and municipal coordination before major rollout milestones are approved.",
                "why": "The policy relies on grid readiness and easing jurisdictional delays to avoid implementation slippage.",
                "supporting_signals": ["Permitting constraints", "Utility coordination risk"]
            }
        ]
    }

    normalized = normalize_recommendation_output(raw)

    assert len(normalized["recommendations"]) == 2
    assert normalized["recommendations"][0]["priority"] == "High priority"
    assert "corridor" in normalized["recommendations"][0]["title"].lower()
    assert "supports" in normalized["recommendations"][0]["why"].lower() or "matches" in normalized["recommendations"][0]["why"].lower()
