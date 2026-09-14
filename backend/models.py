from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

RunStatus = Literal[
    "pending",
    "parsing",
    "retrieving_context",
    "analyzing",
    "synthesizing",
    "complete",
    "error",
    "cancelled",
]
AgentStatus = Literal["pending", "running", "done", "error", "cancelled"]
RiskLevel = Literal["Low", "Medium", "High"]
Direction = Literal["up", "down", "flat"]
Magnitude = Literal["small", "moderate", "large"]
AnalysisMode = Literal["balanced", "deep"]
MAX_POLICY_CHARACTERS = 200_000


class CreateRunRequest(BaseModel):
    policy_text: str = Field(min_length=1, max_length=MAX_POLICY_CHARACTERS)
    domain_hint: str | None = Field(default=None, max_length=200)
    web_enabled: bool = True
    analysis_mode: AnalysisMode = "balanced"
    force_refresh: bool = False


class CreateRunResponse(BaseModel):
    run_id: str
    reused: bool = False
    reuse_reason: Literal["active", "cached"] | None = None
    queue_position: int | None = None


class UploadRunResponse(CreateRunResponse):
    source_name: str
    extracted_characters: int


class HealthResponse(BaseModel):
    status: str


def empty_agents() -> dict[str, dict[str, Any]]:
    slot = {"status": "pending", "output": None}
    return {
        "economic": dict(slot),
        "environment": dict(slot),
        "social": dict(slot),
        "legal_budget": dict(slot),
        "risk": dict(slot),
    }


def new_run_payload(
    run_id: str, policy_text: str, domain_hint: str | None, web_enabled: bool = True,
    analysis_mode: AnalysisMode = "balanced",
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "status": "pending",
        "policy_input": {
            "policy_text": policy_text,
            "domain_hint": domain_hint,
            "web_enabled": web_enabled,
            "analysis_mode": analysis_mode,
        },
        "retrieved_context": [],
        "web_sources": [],
        "parsed_policy": None,
        "agents": empty_agents(),
        "synthesis": None,
        "scenario_set": None,
        "recommendations": None,
        "state_impact": None,
        "error": None,
    }
