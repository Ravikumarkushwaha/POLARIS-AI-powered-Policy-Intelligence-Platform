from __future__ import annotations

import asyncio
import hashlib
import json
import time
import math
import re
from evidence import build_catalog, model_catalog, CITATION_INSTRUCTION, BRIEF_INSTRUCTION
from pathlib import Path
from typing import Any, Callable

import httpx

import db
from groq_client import GroqError, chat_json, set_progress_callback, reset_progress_callback
from json_util import (
    normalize_domain_output,
    normalize_parsed_policy,
    normalize_recommendation_output,
    normalize_risk_output,
    normalize_scenario_output,
    normalize_synthesis,
)
from prompts import (
    BALANCED_SPECIALISTS_SYSTEM,
    BALANCED_RISK_SYNTHESIS_SYSTEM,
    ECONOMIC_SYSTEM,
    ENVIRONMENT_SYSTEM,
    LEGAL_BUDGET_SYSTEM,
    PARSER_SYSTEM,
    RECOMMENDATION_SYSTEM,
    RISK_SYSTEM,
    SCENARIO_SYSTEM,
    SOCIAL_SYSTEM,
    SYNTHESIS_SYSTEM,
)
from rag import compact_policy_text, compact_text, retrieve_chunks
from web_retriever import retrieve_web_sources

SEED_PATH = Path(__file__).resolve().parent / "state_seed_data.json"
JSON_REPAIR_SYSTEM = """You repair a malformed or incomplete JSON response.
Return only one complete valid JSON object with no markdown or prose. Preserve supported content from previous_response, fix every validation error, and use only grounding_context. Do not invent facts, evidence, metrics, states, or policy claims."""

# Track active runs to prevent duplicate simultaneous analysis
_active_runs: dict[str, str] = {}  # policy_hash -> run_id
_active_runs_lock = asyncio.Lock()
_pipeline_semaphore = asyncio.Semaphore(1)


def _agent_evidence(
    parsed: dict[str, Any],
    state_seed: dict[str, Any],
    retrieved_context: list[dict[str, Any]],
    web_sources: list[dict[str, Any]],
    agent_name: str,
    domain_hint: str | None = None,
) -> dict[str, Any]:
    """Trim repeated evidence per domain agent so each model call receives only the most relevant context."""
    local = [
        {
            "chunk_id": item.get("chunk_id"),
            "text": compact_text(str(item.get("text", "")), 260),
            "relevance": item.get("relevance", 0),
        }
        for item in retrieved_context[:2]
    ]

    priority_terms = {
        "economic": ["growth", "investment", "jobs", "industry", "budget", "trade", "market"],
        "environment": ["emissions", "pollution", "climate", "water", "land", "energy", "waste"],
        "social": ["equity", "health", "livelihood", "access", "education", "housing", "inclusion"],
        "legal_budget": ["budget", "cost", "funding", "jurisdiction", "compliance", "regulation", "authority"],
    }

    filters = priority_terms.get(agent_name, [])
    filtered_web = []
    for item in web_sources[:4]:
        url_text = f"{item.get('title', '')} {item.get('text', '')}".lower()
        if filters and not any(term in url_text for term in filters):
            continue
        filtered_web.append(
            {
                "title": item.get("title"),
                "source": item.get("source"),
                "url": item.get("url"),
                "text": compact_text(str(item.get("text", "")), 220),
            }
        )
    if not filtered_web:
        filtered_web = [
            {
                "title": item.get("title"),
                "source": item.get("source"),
                "url": item.get("url"),
                "text": compact_text(str(item.get("text", "")), 220),
            }
            for item in web_sources[:2]
        ]

    return {
        "parsed_policy": parsed,
        "state_seed_data": state_seed,
        "retrieved_context": local,
        "web_sources": filtered_web,
        "domain_hint": domain_hint,
    }


def _model_evidence(
    parsed: dict[str, Any],
    state_seed: dict[str, Any],
    retrieved_context: list[dict[str, Any]],
    web_sources: list[dict[str, Any]],
) -> dict[str, Any]:
    """Backward-compatible evidence bundle for the existing flow."""
    local = [
        {
            "chunk_id": item.get("chunk_id"),
            "text": compact_text(str(item.get("text", "")), 500),
            "relevance": item.get("relevance", 0),
        }
        for item in retrieved_context[:3]
    ]
    web = [
        {
            "title": item.get("title"),
            "source": item.get("source"),
            "url": item.get("url"),
            "text": compact_text(str(item.get("text", "")), 450),
        }
        for item in web_sources[:3]
    ]
    return {
        "parsed_policy": parsed,
        "state_seed_data": state_seed,
        "retrieved_context": local,
        "web_sources": web,
    }


def _load_state_seed() -> dict[str, Any]:
    # TODO: replace with real sourced data
    with SEED_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _domain_confidence(output: dict[str, Any]) -> float:
    """Arithmetic mean of the LLM's per-metric evidence confidence values."""
    values = [
        float(effect.get("confidence", 0))
        for effect in output.get("metric_effects", [])
        if isinstance(effect, dict) and isinstance(effect.get("confidence"), (int, float))
    ]
    return sum(values) / len(values) if values else 0.0


def _aggregate_agent_confidence(outputs: dict[str, dict[str, Any]]) -> tuple[float, dict[str, Any]]:
    """Compute a transparent equal-weight mean across the five completed agents."""
    components = {
        name: (_domain_confidence(output) if name != "risk" else float(output.get("confidence", 0)))
        for name, output in outputs.items()
    }
    value = sum(components.values()) / len(components) if components else 0.0
    return round(value, 4), {
        "method": "equal_weighted_agent_mean",
        "components": {name: round(component, 4) for name, component in components.items()},
        "formula": "(economic + environment + social + legal_budget + risk) / 5",
        "note": "Domain values are arithmetic means of their metric confidences; risk is the Risk agent's confidence.",
    }


def _combine_state_impact(agents: dict[str, Any]) -> dict[str, float]:
    maps = []
    for name in ("economic", "environment", "social"):
        weights = ((agents.get(name) or {}).get("output") or {}).get("affected_states_weight") or {}
        if isinstance(weights, dict) and weights:
            maps.append(weights)
    if not maps:
        return {}
    keys: set[str] = set()
    for m in maps:
        keys.update(m.keys())
    averaged = {}
    for key in keys:
        vals = []
        for m in maps:
            try:
                vals.append(float(m.get(key, 0) or 0))
            except (TypeError, ValueError):
                vals.append(0.0)
        averaged[key] = sum(vals) / len(maps)
    max_val = max(averaged.values()) if averaged else 0.0
    scale = 100.0 if max_val <= 1.5 else 1.0
    return {k: round(max(0.0, min(100.0, v * scale)), 2) for k, v in averaged.items()}


async def _set_status(run_id: str, status: str, error: str | None = None) -> None:
    def mutate(p: dict[str, Any]) -> None:
        p["status"] = status
        if error is not None:
            p["error"] = error

    await db.patch_run(run_id, mutate)


async def _set_agent(
    run_id: str, name: str, *, status: str, output: dict[str, Any] | None = None
) -> None:
    def mutate(p: dict[str, Any]) -> None:
        p["agents"][name]["status"] = status
        if output is not None or status in {"done", "error"}:
            p["agents"][name]["output"] = output

    await db.patch_run(run_id, mutate)


def _stage_timing(stage_name: str, elapsed: float) -> str:
    """Format stage timing for logging."""
    return f"{stage_name}: {elapsed:.2f}s"


def _validate_domain_output(output: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    effects = output.get("metric_effects") or []
    reasoning = str(output.get("reasoning") or "").strip()
    if not effects:
        errors.append("metric_effects must contain at least one evidence-grounded domain effect")
    if len(reasoning) < 40:
        errors.append("reasoning must contain a substantive evidence-grounded analysis")
    for index, effect in enumerate(effects):
        if not str(effect.get("metric") or "").strip():
            errors.append(f"metric_effects[{index}].metric is empty")
        confidence = effect.get("confidence", 0)
        if not isinstance(confidence, (int, float)) or confidence <= 0:
            errors.append(f"metric_effects[{index}].confidence must be greater than zero")
    return errors


def _validate_risk_output(output: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if output.get("risk_level") not in {"Low", "Medium", "High"}:
        errors.append("risk_level must be Low, Medium, or High")
    if len(str(output.get("justification") or "").strip()) < 40:
        errors.append("justification must contain a substantive analysis of the completed agents")
    if not isinstance(output.get("confidence"), (int, float)) or output.get("confidence", 0) <= 0:
        errors.append("confidence must be greater than zero")
    if len(str(output.get("confidence_rationale") or "").strip()) < 30:
        errors.append("confidence_rationale must explain the evidence supporting certainty")
    return errors


def _validate_synthesis_output(output: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    score = output.get("overall_impact_score")
    if not isinstance(score, (int, float)) or not 0 <= score <= 100:
        errors.append("overall_impact_score must be between 0 and 100")
    if len(str(output.get("impact_score_rationale") or "").strip()) < 40:
        errors.append("impact_score_rationale must explain the model-assessed impact index")
    if len(str(output.get("verdict") or "").strip()) < 20:
        errors.append("verdict must be substantive")
    if len([item for item in output.get("top_3_effects", []) if str(item).strip()]) != 3:
        errors.append("top_3_effects must contain exactly three non-empty findings")
    if output.get("risk_level") not in {"Low", "Medium", "High"}:
        errors.append("risk_level must be Low, Medium, or High")
    return errors


def _validate_scenario_output(output: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    scenarios = output.get("scenarios") or []
    expected_labels = ["Optimistic", "Realistic", "Worst-case"]
    labels = [str(item.get("label") or "") for item in scenarios if isinstance(item, dict)]
    if labels != expected_labels:
        errors.append("scenarios must contain exactly Optimistic, Realistic, and Worst-case")
    probabilities = [item.get("probability", 0) for item in scenarios if isinstance(item, dict)]
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in probabilities) or abs(sum(probabilities) - 100) > 0.01:
        errors.append("scenario probabilities must total 100")
    fingerprints: set[str] = set()
    for index, scenario in enumerate(scenarios):
        if not isinstance(scenario, dict):
            errors.append(f"scenarios[{index}] must be an object")
            continue
        probability = scenario.get("probability")
        raw_probability = scenario.get("probability_raw", probability)
        if any(not isinstance(v, (int, float)) or not math.isfinite(v) or not 5 <= v <= 90 for v in (probability, raw_probability)):
            errors.append("scenario probability must be between 5 and 90")
        if len(str(scenario.get("probability_rationale") or "").strip()) < 20:
            errors.append("scenario probability_rationale must explain the likelihood")
        title = str(scenario.get("title") or "").strip()
        body = str(scenario.get("body") or "").strip()
        points = scenario.get("points") or []
        if len(title) < 8:
            errors.append(f"{scenario.get('label') or index} title is incomplete")
        if len(body) < 60:
            errors.append(f"{scenario.get('label') or index} body is incomplete")
        if not isinstance(points, list) or len([point for point in points if str(point).strip()]) < 3:
            errors.append(f"{scenario.get('label') or index} must contain three concrete evidence points")
        fingerprint = f"{title.lower()} {body.lower()}"
        if fingerprint in fingerprints:
            errors.append("scenario narratives must be distinct")
        fingerprints.add(fingerprint)
    return errors


def _validate_recommendation_output(output: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    recommendations = output.get("recommendations") or []
    if len(recommendations) < 3:
        errors.append("recommendations must contain at least three evidence-grounded actions")
    for index, item in enumerate(recommendations):
        if len(str(item.get("title") or "").strip()) < 8:
            errors.append(f"recommendations[{index}].title is incomplete")
        if len(str(item.get("description") or "").strip()) < 30:
            errors.append(f"recommendations[{index}].description is incomplete")
        if len(str(item.get("why") or "").strip()) < 30:
            errors.append(f"recommendations[{index}].why is incomplete")
        if not item.get("supporting_signals"):
            errors.append(f"recommendations[{index}] needs supporting evidence signals")
    return errors


def _parse_policy_locally(policy_text: str, domain_hint: str | None) -> dict[str, Any]:
    """Extract a useful policy profile without spending a model request."""
    clean = " ".join(policy_text.split())
    lowered = clean.lower()
    domain_terms = {
        "Energy": ("energy", "solar", "power", "electricity", "renewable"),
        "Agriculture": ("agriculture", "farmer", "crop", "irrigation", "rural"),
        "Health": ("health", "hospital", "medical", "patient", "insurance"),
        "Education": ("education", "school", "student", "university", "training"),
        "Transport": ("transport", "rail", "road", "freight", "mobility"),
        "Economic": ("industry", "manufacturing", "enterprise", "trade", "employment"),
        "Digital policy": ("digital", "data", "technology", "internet", "electronics"),
        "Social policy": ("welfare", "housing", "poverty", "women", "inclusion"),
    }
    domain = (domain_hint or "").strip()
    if not domain:
        domain = max(domain_terms, key=lambda name: sum(lowered.count(term) for term in domain_terms[name]))
    sentences = [part.strip(" -•\t") for part in re.split(r"(?<=[.!?])\s+|[\r\n]+", policy_text) if len(part.strip()) >= 18]
    goal_words = ("aim", "goal", "objective", "propose", "programme", "policy", "scheme", "support", "reduce", "increase", "improve")
    goals = [sentence[:220] for sentence in sentences if any(word in sentence.lower() for word in goal_words)][:3]
    if not goals:
        goals = [clean[:220] or "Assess the submitted policy"]
    stakeholder_map = {
        "government": "Government agencies", "state": "State governments", "farmer": "Farmers",
        "business": "Businesses", "enterprise": "Enterprises", "student": "Students",
        "household": "Households", "worker": "Workers", "consumer": "Consumers",
    }
    stakeholders = [label for term, label in stakeholder_map.items() if term in lowered][:5] or ["Implementing agencies", "Affected communities"]
    sectors = [name for name, terms in domain_terms.items() if any(term in lowered for term in terms)][:4] or [domain]
    year_match = re.search(r"\b(\d{1,2})\s*[- ]?years?\b", lowered)
    return normalize_parsed_policy({
        "domain": domain, "goals": goals, "stakeholders": stakeholders,
        "affected_sectors": sectors, "timeline_years": int(year_match.group(1)) if year_match else None,
        "known_assumptions": [],
    })


async def _chat_json_validated(
    client: httpx.AsyncClient,
    *,
    system: str,
    user_payload: dict[str, Any],
    max_tokens: int,
    stage_name: str,
    normalize: Callable[[dict[str, Any]], dict[str, Any]],
    validate: Callable[[dict[str, Any]], list[str]],
    validation_retries: int = 2,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Retry structurally valid but incomplete model output without inventing data."""
    current_payload: dict[str, Any] = user_payload
    for attempt in range(validation_retries + 1):
        raw = await chat_json(
            client,
            system=system if attempt == 0 else system + "\nRepair the previous response to satisfy the listed validation errors. Use grounding_context only. Return the same complete JSON schema.",
            user=json.dumps(current_payload, default=str),
            max_tokens=max_tokens,
            stage_name=stage_name if attempt == 0 else f"{stage_name} validation repair",
        )
        normalized = None
        normalized = None
        try:
            normalized = normalize(raw)
            errors = validate(normalized)
        except (ValueError, TypeError, AttributeError, OverflowError):
            errors = ["response fields do not match the required JSON types"]
        if not errors:
            return raw, normalized
        print(
            f"[VALIDATION RETRY] {stage_name} output incomplete: {'; '.join(errors)}"
        )
        if attempt >= validation_retries:
            raise GroqError(f"{stage_name} returned incomplete output: {'; '.join(errors)}")
        repair_context = _compact_repair_context(user_payload)
        repair_context["evidence_catalog"] = user_payload.get("evidence_catalog", [])
        current_payload = {
            "grounding_context": repair_context,
            "previous_response": normalized if isinstance(normalized, dict) else raw,
            "validation_errors": errors,
            "repair_instruction": (
                "Return a complete replacement JSON object in the required schema. Preserve supported "
                "findings from the previous response, fill omitted fields only from grounding_context, and "
                "do not invent evidence, findings, figures, states, or policy facts."
            ),
        }
    raise GroqError(f"{stage_name} validation failed")


def _compact_repair_context(user_payload: dict[str, Any]) -> dict[str, Any]:
    """Keep findings needed for repair without repeating bulky raw evidence."""
    agent_keys = {"economic", "environment", "social", "legal_budget", "risk"}
    if agent_keys.intersection(user_payload):
        selected: dict[str, Any] = {}
        if "parsed_policy" in user_payload:
            selected["parsed_policy"] = user_payload["parsed_policy"]
        for name in ("economic", "environment", "social", "legal_budget"):
            output = user_payload.get(name)
            if not isinstance(output, dict):
                continue
            selected[name] = {
                "metric_effects": output.get("metric_effects", [])[:4],
                "reasoning": compact_text(str(output.get("reasoning", "")), 240),
            }
        risk = user_payload.get("risk")
        if isinstance(risk, dict):
            selected["risk"] = {
                "risk_level": risk.get("risk_level"),
                "confidence": risk.get("confidence"),
                "justification": compact_text(str(risk.get("justification", "")), 240),
            }
        if "scenarios" in user_payload:
            selected["scenarios"] = user_payload["scenarios"]
    else:
        selected = user_payload
    # Reuse the same loss-aware compactor: reasoning is shortened, while
    # parsed policy fields and metric effects remain present.
    from groq_client import _compact_request_value

    return _compact_request_value(selected, 4)


def _compact_agent_finding(output: dict[str, Any]) -> dict[str, Any]:
    """Keep a specialist's supported conclusions without UI/provenance fields."""
    effects = []
    for effect in (output.get("metric_effects") or [])[:3]:
        if not isinstance(effect, dict):
            continue
        effects.append(
            {
                key: effect.get(key)
                for key in ("metric", "direction", "magnitude", "confidence", "evidence_ids")
                if effect.get(key) is not None
            }
        )

    state_weights = output.get("affected_states_weight") or {}
    ranked_states = []
    if isinstance(state_weights, dict):
        ranked_states = sorted(
            state_weights.items(),
            key=lambda item: abs(float(item[1])) if isinstance(item[1], (int, float)) else 0,
            reverse=True,
        )[:3]

    return {
        "metric_effects": effects,
        "reasoning": compact_text(str(output.get("reasoning", "")), 220),
        "top_affected_states": dict(ranked_states),
        "evidence_ids": output.get("evidence_ids", []),
        "uncertainty": compact_text(str(output.get("uncertainty", "")), 180),
    }


def _build_recommendation_payload(
    parsed: dict[str, Any],
    agents: dict[str, dict[str, Any]],
    risk: dict[str, Any],
    scenarios: list[dict[str, Any]],
    retrieved_context: list[dict[str, Any]],
    web_sources: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a bounded, evidence-grounded recommendation input.

    The recommendation agent needs the conclusions, not a second copy of every
    verbose model response. Keep all specialists and all three scenarios, then
    include only the highest-ranked local and web evidence excerpts.
    """
    compact_scenarios = []
    for scenario in scenarios[:3]:
        if not isinstance(scenario, dict):
            continue
        compact_scenarios.append(
            {
                "label": scenario.get("label"),
                "probability": scenario.get("probability"),
                "title": compact_text(str(scenario.get("title", "")), 110),
                "probability_rationale": compact_text(
                    str(scenario.get("probability_rationale", "")), 160
                ),
                "body": compact_text(str(scenario.get("body", "")), 220),
                "points": [
                    compact_text(str(point), 130)
                    for point in (scenario.get("points") or [])[:2]
                ],
            }
        )

    return {
        "parsed_policy": parsed,
        **{
            name: _compact_agent_finding(agents[name])
            for name in ("economic", "environment", "social", "legal_budget")
        },
        "risk": {
            "risk_level": risk.get("risk_level"),
            "confidence": risk.get("confidence"),
            "justification": compact_text(str(risk.get("justification", "")), 240),
        },
        "scenarios": compact_scenarios,
        "evidence_bundle": {
            "retrieved_context": [
                {
                    "chunk_id": item.get("chunk_id"),
                    "text": compact_text(str(item.get("text", "")), 180),
                    "relevance": item.get("relevance", 0),
                }
                for item in retrieved_context[:1]
            ],
            "web_sources": [
                {
                    "title": compact_text(str(item.get("title", "")), 100),
                    "source": item.get("source"),
                    "url": item.get("url"),
                    "text": compact_text(str(item.get("text", "")), 140),
                }
                for item in web_sources[:1]
            ],
        },
    }


async def _run_domain_agent(
    client: httpx.AsyncClient,
    run_id: str,
    name: str,
    system: str,
    evidence_bundle: dict[str, Any],
) -> dict[str, Any] | None:
    await _set_agent(run_id, name, status="running")
    try:
        _raw, output = await _chat_json_validated(
            client,
            system=system,
            user_payload={"evidence_bundle": evidence_bundle},
            max_tokens=900,
            stage_name=name.replace("_", " ").title(),
            normalize=normalize_domain_output,
            validate=_validate_domain_output,
        )
        await _set_agent(run_id, name, status="done", output=output)
        return output
    except GroqError as exc:
        print(f"[ERROR] {name.replace('_', ' ').title()} agent failed: {exc}")
        await _set_agent(
            run_id,
            name,
            status="error",
            output={
                "metric_effects": [],
                "reasoning": f"Agent failed: {exc}",
                "affected_states_weight": {},
            },
        )
        return None


DOMAIN_NAMES = ("economic", "environment", "social", "legal_budget")


def _normalize_specialists(raw: dict[str, Any]) -> dict[str, Any]:
    return {name: normalize_domain_output(raw.get(name) or {}) for name in DOMAIN_NAMES}


def _validate_specialists(output: dict[str, Any]) -> list[str]:
    return [
        f"{name}: {error}"
        for name in DOMAIN_NAMES
        for error in _validate_domain_output(output.get(name) or {})
    ]


def _normalize_risk_synthesis(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "risk": normalize_risk_output(raw.get("risk") or {}),
        "synthesis": normalize_synthesis(raw.get("synthesis") or {}),
    }


def _validate_risk_synthesis(output: dict[str, Any]) -> list[str]:
    errors = _validate_risk_output(output.get("risk") or {})
    errors += _validate_synthesis_output(output.get("synthesis") or {})
    if (output.get("risk") or {}).get("risk_level") != (output.get("synthesis") or {}).get("risk_level"):
        errors.append("synthesis risk_level must match the risk assessment")
    return errors


def _balanced_evidence(
    parsed: dict[str, Any], state_seed: dict[str, Any],
    retrieved_context: list[dict[str, Any]], web_sources: list[dict[str, Any]],
) -> dict[str, Any]:
    # Column names occur once, saving tokens while retaining every supplied state.
    columns = ["manufacturing_share", "agri_share", "population_share"]
    return {
        "parsed_policy": parsed,
        "state_reference": {
            "basis": "Illustrative unsourced seed data; geographic exposure is heuristic.",
            "columns": ["state", *columns],
            "rows": [[name, *(row.get(column, 0) for column in columns)]
                     for name, row in state_seed.items()],
        },
        "retrieved_context": [
            {"chunk_id": item.get("chunk_id"), "text": compact_text(str(item.get("text", "")), 380)}
            for item in retrieved_context[:3]
        ],
        "web_sources": [
            {"title": item.get("title"), "url": item.get("url"),
             "text": compact_text(str(item.get("text", "")), 240)}
            for item in web_sources[:2]
        ],
    }


def _valid_checkpoint(output: Any, validate: Callable[[dict[str, Any]], list[str]]) -> bool:
    if not isinstance(output, dict):
        return False
    try:
        return not validate(output)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return False


async def _checkpoint_stage(
    run_id: str, name: str, action: Callable, cached: Any,
    validate: Callable[[dict[str, Any]], list[str]],
) -> dict[str, Any]:
    """Persist each validated stage so restart/retry consumes only missing calls."""
    if _valid_checkpoint(cached, validate):
        def resumed(p: dict[str, Any]) -> None:
            telemetry = p.setdefault("telemetry", {})
            stages = telemetry.setdefault("resumed_stages", [])
            if name not in stages:
                stages.append(name)
            telemetry["current_stage"] = name
            p.setdefault("stages", {})[name] = "completed"
        await db.patch_run(run_id, resumed)
        return cached

    started = time.monotonic()
    def starting(p: dict[str, Any]) -> None:
        p.setdefault("telemetry", {})["current_stage"] = name
        p.setdefault("stages", {})[name] = "running"
    await db.patch_run(run_id, starting)
    result = await action()
    elapsed = round(time.monotonic() - started, 3)
    def checkpoint(p: dict[str, Any]) -> None:
        p.setdefault("_checkpoints", {})[name] = result
        p.setdefault("stages", {})[name] = "completed"
        p.setdefault("telemetry", {}).setdefault("stage_timings", {})[name] = elapsed
    await db.patch_run(run_id, checkpoint)
    return result


async def run_pipeline(run_id: str) -> None:
    # Keep both run and provider concurrency at one. A queued/cancelled run must
    # never consume a model call just because a previous worker woke up.
    async with _pipeline_semaphore:
        payload = await db.get_run(run_id)
        if payload is None or payload.get("status") in {"complete", "cancelled"}:
            return
        mode = payload["policy_input"].get("analysis_mode", "deep")
        def initialize(p: dict[str, Any]) -> None:
            telemetry = p.setdefault("telemetry", {})
            telemetry.update({
                "analysis_mode": mode, "planned_calls": 4 if mode == "balanced" else 8,
                "wait_until": None, "wait_reason": None,
            })
            for key in ("api_requests", "tokens_used", "rate_limit_retries"):
                telemetry.setdefault(key, 0)
            telemetry.setdefault("stage_timings", {})
            telemetry["resumed_stages"] = []
        await db.patch_run(run_id, initialize)

        async def report(event: dict[str, Any]) -> None:
            def mutate(p: dict[str, Any]) -> None:
                telemetry = p.setdefault("telemetry", {})
                kind = event.get("event")
                if kind == "request":
                    telemetry["api_requests"] = telemetry.get("api_requests", 0) + 1
                    telemetry["last_model"] = event.get("model")
                elif kind == "usage":
                    try:
                        tokens = max(0, int(event.get("tokens") or 0))
                    except (TypeError, ValueError):
                        tokens = 0
                    telemetry["tokens_used"] = telemetry.get("tokens_used", 0) + tokens
                elif kind == "rate_limited":
                    telemetry["rate_limit_retries"] = telemetry.get("rate_limit_retries", 0) + 1
                for key in ("wait_until", "wait_reason", "current_stage"):
                    if key in event:
                        telemetry[key] = event[key]
            await db.patch_run(run_id, mutate)

        token = set_progress_callback(report)
        started = time.monotonic()
        try:
            await _execute(run_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            latest = await db.get_run(run_id)
            stage = ((latest or {}).get("telemetry") or {}).get("current_stage", "Analysis")
            def failed(p: dict[str, Any]) -> None:
                p["status"] = "error"
                p["error"] = f"{stage}: {str(exc)[:350]}"
                for key, value in p.get("stages", {}).items():
                    if value == "running":
                        p["stages"][key] = "failed"
                for agent in p.get("agents", {}).values():
                    if agent.get("status") == "running":
                        agent["status"] = "error"
            await db.patch_run(run_id, failed)
        finally:
            reset_progress_callback(token)
            def ended(p: dict[str, Any]) -> None:
                telemetry = p.setdefault("telemetry", {})
                telemetry.update({"wait_until": None, "wait_reason": None})
                telemetry["elapsed_seconds"] = round(
                    telemetry.get("elapsed_seconds", 0) + time.monotonic() - started, 3
                )
            await db.patch_run(run_id, ended)


async def regenerate_recommendations(run_id: str) -> dict[str, Any]:
    """Regenerate only the action plan from completed findings under the shared quota guard."""
    async with _pipeline_semaphore:
        payload = await db.get_run(run_id)
        if payload is None:
            raise ValueError("run not found")
        agents = payload.get("agents") or {}
        domains = {name: (agents.get(name) or {}).get("output") for name in DOMAIN_NAMES}
        risk = (agents.get("risk") or {}).get("output")
        if not all(domains.values()) or not risk:
            raise ValueError("complete specialist and risk findings are required")
        catalog = payload.get("evidence_catalog") or []
        request = _build_recommendation_payload(
            payload.get("parsed_policy") or {}, domains, risk,
            (payload.get("scenario_set") or {}).get("scenarios") or [],
            payload.get("retrieved_context") or [], payload.get("web_sources") or [],
        )
        request["evidence_catalog"] = model_catalog(catalog)
        async with httpx.AsyncClient() as client:
            _, recommendations = await _chat_json_validated(
                client, system=RECOMMENDATION_SYSTEM + CITATION_INSTRUCTION,
                user_payload=request, max_tokens=1100, stage_name="Recommendation",
                normalize=normalize_recommendation_output, validate=_validate_recommendation_output,
                validation_retries=1,
            )
        await db.patch_run(run_id, lambda p: p.update(
            recommendations=recommendations, recommendation_source="groq"
        ))
        return recommendations


async def regenerate_scenarios(run_id: str) -> dict[str, Any]:
    """Regenerate possible futures from completed findings without rerunning analysis."""
    async with _pipeline_semaphore:
        payload = await db.get_run(run_id)
        if payload is None:
            raise ValueError("run not found")
        agents = payload.get("agents") or {}
        domains = {name: (agents.get(name) or {}).get("output") for name in DOMAIN_NAMES}
        risk = (agents.get("risk") or {}).get("output")
        if not all(domains.values()) or not risk:
            raise ValueError("complete specialist and risk findings are required")
        findings = {name: _compact_agent_finding(domains[name]) for name in DOMAIN_NAMES}
        request = {
            "parsed_policy": payload.get("parsed_policy") or {}, **findings,
            "risk": {key: risk.get(key) for key in ("risk_level", "justification", "confidence", "confidence_rationale")},
            "evidence_catalog": model_catalog(payload.get("evidence_catalog") or []),
        }
        async with httpx.AsyncClient() as client:
            _, scenarios = await _chat_json_validated(
                client, system=SCENARIO_SYSTEM + CITATION_INSTRUCTION,
                user_payload=request, max_tokens=1200, stage_name="Scenario",
                normalize=normalize_scenario_output, validate=_validate_scenario_output,
                validation_retries=1,
            )
        await db.patch_run(run_id, lambda p: p.update(scenario_set=scenarios, scenario_source="groq"))
        return scenarios


async def _execute(run_id: str) -> None:
    payload = await db.get_run(run_id)
    if payload is None or payload.get("status") in {"cancelled", "complete"}:
        return
    policy_input = payload["policy_input"]
    policy_text = policy_input["policy_text"]
    domain_hint = policy_input.get("domain_hint")
    web_enabled = policy_input.get("web_enabled", True)
    balanced = policy_input.get("analysis_mode", "deep") == "balanced"
    policy_hash = hashlib.sha256(
        json.dumps(policy_input, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    async with _active_runs_lock:
        if policy_hash in _active_runs and _active_runs[policy_hash] != run_id:
            raise GroqError("An identical policy analysis is already active.")
        _active_runs[policy_hash] = run_id

    checkpoints = payload.get("_checkpoints") or {}
    catalog = payload.get("evidence_catalog") or []

    async def stage(name, system, data, max_tokens, normalize, validate, cached=None, validation_retries=2):
        async def call():
            prompt = system + CITATION_INSTRUCTION
            if name in {"synthesis", "risk_synthesis"}:
                prompt += BRIEF_INSTRUCTION if name == "risk_synthesis" else BRIEF_INSTRUCTION.replace("inside synthesis", "at the root of the response")
            grounded = {**data, "evidence_catalog": model_catalog(catalog)}
            def validate_fresh(output):
                errors = validate(output)
                if name in {"synthesis", "risk_synthesis"}:
                    target = output.get("synthesis", {}) if name == "risk_synthesis" else output
                    brief = target.get("brief")
                    if not brief or any(not brief.get(key) for key in ("policy", "benefits", "risks", "affected", "uncertainty", "actions")):
                        errors.append("synthesis brief must contain all six non-empty sections")
                return errors
            _, output = await _chat_json_validated(
                client, system=prompt, user_payload=grounded, max_tokens=max_tokens,
                stage_name=name.replace("_", " ").title(), normalize=normalize, validate=validate_fresh,
                validation_retries=validation_retries,
            )
            return output
        return await _checkpoint_stage(
            run_id, name, call, cached if cached is not None else checkpoints.get(name), validate
        )

    try:
        async with httpx.AsyncClient() as client:
            await _set_status(run_id, "parsing")
            async def local_parse():
                return _parse_policy_locally(policy_text, domain_hint)
            parsed = await _checkpoint_stage(
                run_id, "parser", local_parse, payload.get("parsed_policy"),
                lambda item: [] if item.get("domain") and item.get("goals") else ["domain and goals are required"],
            )
            await db.patch_run(run_id, lambda p: p.__setitem__("parsed_policy", parsed))

            await _set_status(run_id, "retrieving_context")
            await db.patch_run(run_id, lambda p: p.setdefault("stages", {}).update(retrieval="running"))
            if checkpoints.get("retrieval"):
                retrieved_context = payload.get("retrieved_context") or []
                web_sources = payload.get("web_sources") or []
            else:
                query = " ".join([parsed.get("domain", ""), *parsed.get("goals", []),
                                  *parsed.get("affected_sectors", [])])
                retrieved_context = retrieve_chunks(policy_text, query)
                web_sources = await retrieve_web_sources(
                    client, query + " India current policy research data"
                ) if web_enabled else []
                def store_evidence(p: dict[str, Any]) -> None:
                    p["retrieved_context"] = retrieved_context
                    p["web_sources"] = web_sources
                    p.setdefault("_checkpoints", {})["retrieval"] = True
                await db.patch_run(run_id, store_evidence)
            await db.patch_run(run_id, lambda p: p.setdefault("stages", {}).update(retrieval="completed"))
            catalog = build_catalog(retrieved_context, web_sources, policy_input.get("source_name"))
            await db.patch_run(run_id, lambda p: p.update(evidence_catalog=catalog, citation_version=1))
            state_seed = _load_state_seed()
            await _set_status(run_id, "analyzing")

            previous_agents = payload.get("agents") or {}
            old_domains = {name: (previous_agents.get(name) or {}).get("output") for name in DOMAIN_NAMES}
            if balanced:
                for name in DOMAIN_NAMES:
                    await _set_agent(run_id, name, status="running")
                domains = await stage(
                    "specialists", BALANCED_SPECIALISTS_SYSTEM,
                    _balanced_evidence(parsed, state_seed, retrieved_context, web_sources),
                    1800, _normalize_specialists, _validate_specialists,
                    old_domains if _valid_checkpoint(old_domains, _validate_specialists) else None,
                )
                for name in DOMAIN_NAMES:
                    await _set_agent(run_id, name, status="done", output=domains[name])
            else:
                domains = {}
                prompts = dict(zip(DOMAIN_NAMES, (
                    ECONOMIC_SYSTEM, ENVIRONMENT_SYSTEM, SOCIAL_SYSTEM, LEGAL_BUDGET_SYSTEM
                )))
                for name in DOMAIN_NAMES:
                    await _set_agent(run_id, name, status="running")
                    domains[name] = await stage(
                        name, prompts[name],
                        {"evidence_bundle": _agent_evidence(
                            parsed, state_seed if name != "legal_budget" else {},
                            retrieved_context, web_sources, name, domain_hint,
                        )},
                        900, normalize_domain_output, _validate_domain_output, old_domains[name],
                    )
                    await _set_agent(run_id, name, status="done", output=domains[name])

            # Keep every domain's conclusions, removing duplicated UI provenance
            # and raw state seeds from downstream stages.
            findings = {name: _compact_agent_finding(domains[name]) for name in DOMAIN_NAMES}
            if not balanced:
                for name in DOMAIN_NAMES:
                    findings[name]["reasoning"] = compact_text(str(domains[name].get("reasoning", "")), 600)
                    findings[name]["metric_effects"] = domains[name].get("metric_effects", [])[:4]
            findings_input = {"parsed_policy": parsed, **findings}
            await _set_agent(run_id, "risk", status="running")
            old_risk = (previous_agents.get("risk") or {}).get("output")
            if balanced:
                old_pair = {"risk": old_risk, "synthesis": payload.get("synthesis")}
                pair = await stage(
                    "risk_synthesis", BALANCED_RISK_SYNTHESIS_SYSTEM, findings_input,
                    1800, _normalize_risk_synthesis, _validate_risk_synthesis,
                    old_pair if _valid_checkpoint(old_pair, _validate_risk_synthesis) else None,
                )
                risk, synthesis = pair["risk"], pair["synthesis"]
                await db.patch_run(run_id, lambda p: p.__setitem__("synthesis", synthesis))
            else:
                risk = await stage(
                    "risk", RISK_SYSTEM, findings_input, 550,
                    normalize_risk_output, _validate_risk_output, old_risk,
                )
            await _set_agent(run_id, "risk", status="done", output=risk)
            if balanced:
                synthesis["confidence"], synthesis["confidence_basis"] = _aggregate_agent_confidence({**domains, "risk": risk})
                await db.patch_run(run_id, lambda p: p.update(synthesis=synthesis))
            await _set_status(run_id, "synthesizing")

            scenario_data = await stage(
                "scenario", SCENARIO_SYSTEM,
                {**findings_input, "risk": {
                    key: risk[key] for key in ("risk_level", "justification", "confidence", "confidence_rationale")
                }},
                1200, normalize_scenario_output, _validate_scenario_output,
                payload.get("scenario_set") if payload.get("scenario_source") == "groq" else None,
                validation_retries=1,
            )
            await db.patch_run(run_id, lambda p: p.update(scenario_set=scenario_data, scenario_source="groq"))
            recommendations = await stage(
                "recommendation", RECOMMENDATION_SYSTEM,
                _build_recommendation_payload(
                    parsed, domains, risk, scenario_data["scenarios"], retrieved_context, web_sources
                ),
                1100, normalize_recommendation_output, _validate_recommendation_output,
                payload.get("recommendations") if payload.get("recommendation_source") == "groq" else None,
                validation_retries=1,
            )
            await db.patch_run(run_id, lambda p: p.update(recommendations=recommendations, recommendation_source="groq"))
            if not balanced:
                synthesis = await stage(
                    "synthesis", SYNTHESIS_SYSTEM, {**findings_input, "risk": risk},
                    1400, normalize_synthesis, _validate_synthesis_output, payload.get("synthesis"),
                )

            aggregate_confidence, confidence_basis = _aggregate_agent_confidence({**domains, "risk": risk})
            synthesis["confidence"] = aggregate_confidence
            synthesis["confidence_basis"] = confidence_basis
            synthesis["impact_score_basis"] = {
                "method": "llm_assessed_impact_magnitude",
                "rationale": synthesis.get("impact_score_rationale", ""),
                "note": "A 0-100 impact magnitude index, not a measured percentage or forecast probability.",
            }
            all_agents = {name: {"status": "done", "output": output}
                          for name, output in {**domains, "risk": risk}.items()}
            def finish(p: dict[str, Any]) -> None:
                p.update({
                    "agents": all_agents, "synthesis": synthesis, "scenario_set": scenario_data,
                    "recommendations": recommendations, "state_impact": _combine_state_impact(all_agents),
                    "state_impact_basis": {
                        "method": "heuristic_seed_weighting",
                        "note": "Illustrative exposure derived from unsourced seed data; not a measured state impact.",
                    },
                    "status": "complete", "error": None,
                })
                p.setdefault("telemetry", {})["current_stage"] = "complete"
            await db.patch_run(run_id, finish)
    finally:
        async with _active_runs_lock:
            if _active_runs.get(policy_hash) == run_id:
                del _active_runs[policy_hash]
