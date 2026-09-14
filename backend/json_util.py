from __future__ import annotations

import json
import math
from evidence import trace_fields, normalize_brief
import re
from typing import Any

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = _THINK_BLOCK.sub("", text).strip()
    cleaned = _FENCE.sub("", cleaned).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as original_error:
        # Plain-text fallback responses may contain a short lead-in or trailing
        # explanation. Decode the first complete JSON object without attempting
        # to guess or rewrite malformed model output.
        decoder = json.JSONDecoder()
        data = None
        for index, character in enumerate(cleaned):
            if character != "{":
                continue
            try:
                candidate, _end = decoder.raw_decode(cleaned[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                data = candidate
                break
        if data is None:
            raise original_error
    if not isinstance(data, dict):
        raise ValueError("Model output was not a JSON object")
    return data


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def as_confidence(value: Any) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return 0.0
    if n > 1.0:
        n = n / 100.0
    return clamp(n, 0.0, 1.0)


def as_score_100(value: Any) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(n):
        return 0.0
    return clamp(n, 0.0, 100.0)


def normalize_domain_output(raw: dict[str, Any]) -> dict[str, Any]:
    effects = []
    raw_effects = raw.get("metric_effects") or raw.get("effects") or raw.get("impacts") or []
    if isinstance(raw_effects, dict):
        raw_effects = [
            {"metric": metric, **value} if isinstance(value, dict) else {"metric": metric, "magnitude": value}
            for metric, value in raw_effects.items()
        ]
    if not isinstance(raw_effects, list):
        raw_effects = []
    for item in raw_effects:
        if not isinstance(item, dict):
            continue
        direction = str(item.get("direction") or item.get("trend") or "flat").lower()
        if direction not in {"up", "down", "flat"}:
            direction = "flat"
        magnitude = str(item.get("magnitude") or item.get("size") or "moderate").lower()
        if magnitude not in {"small", "moderate", "large"}:
            magnitude = "moderate"
        effects.append(
            {
                **trace_fields(item),
                "metric": str(item.get("metric") or item.get("name") or item.get("indicator") or ""),
                "direction": direction,
                "magnitude": magnitude,
                "confidence": as_confidence(item.get("confidence", item.get("confidence_score", 0))),
            }
        )
    weights: dict[str, float] = {}
    raw_weights = raw.get("affected_states_weight") or {}
    if isinstance(raw_weights, dict):
        for name, val in raw_weights.items():
            try:
                weights[str(name)] = float(val)
            except (TypeError, ValueError):
                continue
    confidence = round(
        sum(effect["confidence"] for effect in effects) / len(effects), 4
    ) if effects else 0.0
    return {
        **trace_fields(raw),
        "metric_effects": effects,
        "confidence": confidence,
        "confidence_basis": {
            "method": "arithmetic_mean_of_metric_confidences",
            "metric_confidences": [effect["confidence"] for effect in effects],
            "formula": "sum(metric confidence) / metric count",
        },
        "reasoning": str(
            raw.get("reasoning")
            or raw.get("analysis")
            or raw.get("summary")
            or raw.get("justification")
            or ""
        ),
        "affected_states_weight": weights,
    }


def normalize_risk_output(raw: dict[str, Any]) -> dict[str, Any]:
    level = str(raw.get("risk_level") or "Medium")
    if level not in {"Low", "Medium", "High"}:
        lowered = level.lower()
        level = {"low": "Low", "medium": "Medium", "high": "High"}.get(lowered, "Medium")
    return {
        **trace_fields(raw),
        "risk_level": level,
        "justification": str(raw.get("justification") or ""),
        "confidence": as_confidence(raw.get("confidence", 0)),
        "confidence_rationale": str(raw.get("confidence_rationale") or ""),
        "confidence_basis": {
            "method": "llm_self_assessed_evidence_support",
            "note": "Not a statistical probability of risk occurring.",
        },
    }


def normalize_parsed_policy(raw: dict[str, Any]) -> dict[str, Any]:
    def str_list(key: str) -> list[str]:
        val = raw.get(key) or []
        if isinstance(val, str):
            return [val]
        return [str(x) for x in val if x is not None]

    years = raw.get("timeline_years")
    try:
        years = int(float(years))
    except (TypeError, ValueError):
        years = None
    return {
        "domain": str(raw.get("domain") or "Unspecified"),
        "goals": str_list("goals"),
        "stakeholders": str_list("stakeholders"),
        "affected_sectors": str_list("affected_sectors"),
        "timeline_years": years,
        "known_assumptions": [str(x) for x in raw.get("known_assumptions", []) if isinstance(x, str)] if isinstance(raw.get("known_assumptions"), list) else [],
    }


def normalize_synthesis(raw: dict[str, Any]) -> dict[str, Any]:
    level = str(raw.get("risk_level") or "Medium")
    if level not in {"Low", "Medium", "High"}:
        lowered = level.lower()
        level = {"low": "Low", "medium": "Medium", "high": "High"}.get(lowered, "Medium")
    effects = raw.get("top_3_effects") or []
    if isinstance(effects, str):
        effects = [effects]
    effects = [str(x) for x in effects][:3]
    while len(effects) < 3:
        effects.append("")
    return {
        "brief": normalize_brief(raw.get("brief")),
        "overall_impact_score": as_score_100(raw.get("overall_impact_score", 0)),
        "impact_score_rationale": str(raw.get("impact_score_rationale") or ""),
        "verdict": str(raw.get("verdict") or ""),
        "top_3_effects": effects,
        **trace_fields(raw),
        "risk_level": level,
        "confidence": as_confidence(raw.get("confidence", 0)),
    }


def normalize_scenario_output(raw: dict[str, Any]) -> dict[str, Any]:
    entries = raw.get("scenarios") or []
    if isinstance(entries, dict):
        entries = [
            {"label": label, **value} if isinstance(value, dict) else {"label": label, "body": value}
            for label, value in entries.items()
        ]
    if not isinstance(entries, list):
        entries = []

    def canonical_label(value: Any) -> str:
        label = str(value or "").strip().lower()
        if "optim" in label or "best" in label:
            return "Optimistic"
        if "real" in label or "base" in label or "likely" in label:
            return "Realistic"
        if "worst" in label or "pessim" in label or "adverse" in label:
            return "Worst-case"
        return str(value or "").strip()

    by_label: dict[str, dict[str, Any]] = {}
    unknown: list[dict[str, Any]] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        label = canonical_label(item.get("label") or item.get("name") or item.get("type"))
        title = str(item.get("title") or item.get("heading") or "")
        body = str(item.get("body") or item.get("description") or item.get("narrative") or "")
        points = item.get("points") or item.get("key_points") or []
        if isinstance(points, str):
            points = [points]
        if not isinstance(points, list):
            points = []
        normalized_item = {
            **trace_fields(item),
            "label": label,
            "probability": float(item.get("probability", 0) or 0),
            "probability_raw": float(item.get("probability", 0) or 0),
            "probability_rationale": str(
                item.get("probability_rationale")
                or item.get("likelihood_rationale")
                or item.get("probability_reason")
                or ""
            ),
            "title": title,
            "body": body,
            "points": [str(p) for p in points[:4] if str(p).strip()],
        }
        if label in {"Optimistic", "Realistic", "Worst-case"}:
            by_label.setdefault(label, normalized_item)
        else:
            unknown.append(normalized_item)

    normalized = [
        by_label[label]
        for label in ("Optimistic", "Realistic", "Worst-case")
        if label in by_label
    ]
    normalized.extend(unknown)

    # Preserve the model's relative likelihood assessment while repairing
    # harmless rounding errors (for example 34 + 33 + 32 = 99). Missing or
    # invalid probabilities remain invalid so validation can request a repair.
    if len(normalized) == 3:
        probabilities = [item["probability"] for item in normalized]
        if all(math.isfinite(value) and 5 <= value <= 90 for value in probabilities) and 98 <= sum(probabilities) <= 102:
            total = sum(probabilities)
            scaled = [(value / total) * 100 for value in probabilities]
            floors = [int(value) for value in scaled]
            remaining = 100 - sum(floors)
            order = sorted(
                range(3),
                key=lambda index: scaled[index] - floors[index],
                reverse=True,
            )
            for index in order[:remaining]:
                floors[index] += 1
            for item, probability in zip(normalized, floors):
                item["probability"] = probability
    return {"scenarios": normalized}


def normalize_recommendation_output(raw: dict[str, Any]) -> dict[str, Any]:
    entries = raw.get("recommendations") or []
    if not isinstance(entries, list):
        entries = []
    normalized: list[dict[str, Any]] = []
    for item in entries[:5]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("action") or "")
        description = str(item.get("description") or item.get("detail") or "")
        why = str(item.get("why") or item.get("rationale") or item.get("reasoning") or "")
        priority = str(item.get("priority") or "Medium priority")
        supporting = item.get("supporting_signals") or []
        if isinstance(supporting, str):
            supporting = [supporting]
        normalized.append(
            {
                **trace_fields(item),
                "priority": priority,
                "title": title,
                "description": description,
                "why": why,
                "supporting_signals": [str(v) for v in supporting if str(v).strip()],
            }
        )
    return {"recommendations": normalized}


normalize_parsed_policy = normalize_parsed_policy
