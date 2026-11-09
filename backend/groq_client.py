from __future__ import annotations

import asyncio
import copy
import email.utils
import json
import math
import os
import random
import re
import time
from datetime import datetime, timezone
from contextvars import ContextVar
from typing import Any, Awaitable, Callable

import httpx

from json_util import parse_json_object
from evidence import supplied_ids, sanitize_citations

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# Prefer Groq's supported OSS and Llama models instead of an outdated Qwen
# ID that can return 404s for accounts without access to that specific model.
DEFAULT_MODEL = "openai/gpt-oss-20b"
DEFAULT_FALLBACK_MODELS = "openai/gpt-oss-120b,llama-3.3-70b-versatile"
TEMPERATURE = 0.3

# Groq's free-tier limits are shared by every pipeline stage. Serializing calls
# prevents the four specialist agents (and simultaneous runs) from creating a
# burst that immediately exhausts the request/token window.
_groq_semaphore = asyncio.Semaphore(1)
_cooldown_lock = asyncio.Lock()
_cooldown_until = 0.0
_token_window_lock = asyncio.Lock()
_token_windows: dict[str, list[dict[str, float]]] = {}
_model_cooldown_until: dict[str, float] = {}
_request_window: list[float] = []
_progress_callback: ContextVar[Callable[[dict[str, Any]], Awaitable[None]] | None] = ContextVar(
    "groq_progress_callback", default=None
)


def set_progress_callback(callback: Callable[[dict[str, Any]], Awaitable[None]]):
    """Associate provider activity with the current run, never another queued run."""
    return _progress_callback.set(callback)


def reset_progress_callback(token) -> None:
    _progress_callback.reset(token)


async def _emit_progress(**event: Any) -> None:
    callback = _progress_callback.get()
    if callback is not None:
        await callback(event)


async def _reported_wait(seconds: float, reason: str) -> None:
    if seconds <= 0:
        return
    await _emit_progress(
        event="waiting", wait_reason=reason,
        wait_until=datetime.fromtimestamp(time.time() + seconds, timezone.utc).isoformat(),
    )
    await asyncio.sleep(seconds)
    await _emit_progress(event="resumed", wait_reason=None, wait_until=None)


def quota_snapshot() -> dict[str, Any]:
    """Public pacing configuration and local reservations; contains no secrets."""
    configured = _env_int("GROQ_TOKENS_PER_MINUTE", 8000, 1)
    ratio = min(_env_float("GROQ_TPM_SAFETY_RATIO", 0.70, 0.1), 1.0)
    window_seconds = _env_float("GROQ_TOKEN_WINDOW_SECONDS", 65.0, 1.0)
    now = time.monotonic()
    return {
        "tokens_per_minute": configured,
        "safe_tokens_per_window": max(1, int(configured * ratio)),
        "max_request_tokens": min(_env_int("GROQ_MAX_REQUEST_TOKENS", 5500, 1), max(1, int(configured * ratio))),
        "window_seconds": window_seconds,
        "requests_per_minute": _env_int("GROQ_REQUESTS_PER_MINUTE", 30, 1),
        "provider_requests_per_minute": _env_int("GROQ_REQUESTS_PER_MINUTE", 30, 1),
        "reserved_tokens": int(sum(entry["tokens"] for window in _token_windows.values()
                                   for entry in window if now - entry["at"] < window_seconds)),
        "request_spacing_seconds": _env_float("GROQ_REQUEST_SPACING", 0.75),
        "budget_scope": os.getenv("GROQ_TOKEN_BUDGET_SCOPE", "shared"),
        "concurrency": 1,
    }


async def _reserve_request_budget() -> None:
    """Pace every HTTP attempt, including failures, within one shared RPM window."""
    budget = _env_int("GROQ_REQUESTS_PER_MINUTE", 30, 1)
    while True:
        now = time.monotonic()
        _request_window[:] = [at for at in _request_window if now - at < 60.0]
        if len(_request_window) < budget:
            _request_window.append(now)
            return
        await _reported_wait(max(0.1, _request_window[0] + 60.1 - now), "request_budget")

_DURATION_PART = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>ms|[smh])", re.IGNORECASE)
_RETRY_MESSAGE = re.compile(
    r"(?:try again|retry(?:ing)?(?: in| after)?)\D{0,24}"
    r"(?P<duration>(?:\d+(?:\.\d+)?\s*(?:ms|[smh])\s*)+)",
    re.IGNORECASE,
)


class GroqError(Exception):
    pass


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(os.getenv(name, str(default))))
    except ValueError:
        return default


def _configured_models() -> list[str]:
    primary = os.getenv("GROQ_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    fallback_value = os.getenv("GROQ_FALLBACK_MODELS", DEFAULT_FALLBACK_MODELS)
    models: list[str] = []
    for model in (primary, *(item.strip() for item in fallback_value.split(","))):
        if model and model not in models:
            models.append(model)
    return models


def _estimated_request_tokens(system: str, user: str, max_tokens: int | None) -> int:
    """Conservatively estimate total tokens reserved in Groq's TPM window."""
    # UTF-8 bytes are safer than character counts for Hindi and other Indic
    # scripts, which Qwen can tokenize much less efficiently than English.
    bytes_per_token = _env_float("GROQ_BYTES_PER_TOKEN_ESTIMATE", 2.0, 1.0)
    prompt_bytes = len(system.encode("utf-8")) + len(user.encode("utf-8"))
    prompt_tokens = math.ceil(prompt_bytes / bytes_per_token) + 64
    completion_tokens = max_tokens if max_tokens is not None else 1024
    return prompt_tokens + completion_tokens


def _truncate_preserving_ends(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit < 80:
        return value[:limit]
    head = int(limit * 0.72)
    tail = limit - head
    return value[:head].rstrip() + " â€¦[compacted]â€¦ " + value[-tail:].lstrip()


def _compact_repair_response(value: Any, level: int) -> Any:
    """Keep every schema key/section while bounding verbose failed completions."""
    if isinstance(value, dict):
        return {key: (item if key in {"evidence_ids", "conflicting_evidence_ids"} else _compact_repair_response(item, level)) for key, item in value.items()}
    if isinstance(value, list):
        return [_compact_repair_response(item, level) for item in value[:5]]
    if isinstance(value, str):
        return _truncate_preserving_ends(value, max(90, 360 - level * 27))
    return value


def _compact_request_value(value: Any, level: int, key: str = "") -> Any:
    """Compact low-priority evidence while retaining policy and agent findings."""
    if key == "previous_response":
        return _compact_repair_response(value, level)
    if isinstance(value, list):
        limit = None
        if key == "web_sources":
            # Web retrieval remains stored on the run for citation/display, but
            # downstream model calls may omit it once completed findings carry
            # the relevant signal.
            limit = max(0, 3 - level)
        elif key == "retrieved_context":
            limit = max(0, 3 - level // 2)
        elif key == "points":
            limit = max(1, 3 - level // 4)
        elif key == "metric_effects":
            limit = max(1, 3 - level // 3)
        elif key == "evidence_ids":
            limit = max(0, 3 - level // 2)
        elif key == "affected_states_weight":
            limit = max(3, 8 - level)
        elif key in {"goals", "stakeholders", "affected_sectors", "top_affected_states"}:
            limit = max(3, 9 - level)
        items = value[:limit] if limit is not None else value
        return [_compact_request_value(item, level, key) for item in items]

    if not isinstance(value, dict):
        if isinstance(value, str):
            if key == "policy_text" and len(value) > max(600, 5000 - level * 450):
                from rag import compact_policy_text
                return compact_policy_text(value, max_characters=max(600, 5000 - level * 450))
            text_caps = {
                "text": max(100, 500 - level * 90),
                "reasoning": max(160, 700 - level * 110),
                "analysis": max(160, 700 - level * 110),
                "justification": max(180, 600 - level * 90),
                "body": max(140, 500 - level * 60),
                "probability_rationale": max(100, 300 - level * 40),
                "confidence_rationale": max(100, 300 - level * 40),
                "description": max(140, 400 - level * 45),
                "why": max(120, 300 - level * 35),
                "title": max(80, 180 - level * 17),
                "uncertainty": max(80, 200 - level * 18),
                "metric": max(90, 200 - level * 20),
            }
            if key in text_caps:
                return _truncate_preserving_ends(value, text_caps[key])
        return value

    if level >= 1 and key in {"evidence_ids", "conflicting_evidence_ids", "top_affected_states", "affected_states_weight", "state_reference", "state_seed_data"}:
        return {"compacted": True, "note": "Downstream synthesis keeps only the strongest findings, not raw evidence lists."}

    if key == "state_seed_data" and level >= 3:
        # Downstream Risk/Scenario calls already receive state weights computed
        # by the specialist agents, so repeating all raw state seed rows is the
        # least relevant evidence when a request is oversized.
        return {"compacted": True, "state_count": len(value)}

    compacted: dict[str, Any] = {}
    for child_key, child_value in value.items():
        if level >= 1 and child_key in {
            "confidence_basis",
            "impact_score_basis",
            "probability_raw",
        }:
            # Calculation provenance is returned to the frontend but is not
            # substantive evidence for another LLM stage.
            continue
        if child_key == "affected_states_weight" and isinstance(child_value, dict):
            keep = max(5, 14 - level * 2)
            ranked = sorted(
                child_value.items(),
                key=lambda item: abs(float(item[1])) if isinstance(item[1], (int, float)) else 0,
                reverse=True,
            )[:keep]
            compacted[child_key] = dict(ranked)
            continue
        compacted[child_key] = _compact_request_value(child_value, level, child_key)
    return compacted


def _prepare_user_for_token_budget(
    system: str, user: str, max_tokens: int | None
) -> tuple[str, int]:
    """Guarantee estimated input + maximum output fits the configured ceiling."""
    tpm_limit = _env_int("GROQ_TOKENS_PER_MINUTE", 8000, 1)
    safety_ratio = min(_env_float("GROQ_TPM_SAFETY_RATIO", 0.70, 0.1), 1.0)
    rolling_budget = max(1, int(tpm_limit * safety_ratio))
    hard_ceiling = min(_env_int("GROQ_MAX_REQUEST_TOKENS", 5500, 1), rolling_budget)
    # JSON whitespace and ASCII escapes consume quota without adding evidence.
    # Canonicalize even requests already under the ceiling (especially Indic text).
    try:
        original = json.loads(user)
        user = json.dumps(original, ensure_ascii=False, separators=(",", ":"), default=str)
    except (json.JSONDecodeError, TypeError):
        original = {"policy_text": user}
    estimated = _estimated_request_tokens(system, user, max_tokens)
    if estimated <= hard_ceiling:
        return user, estimated

    for level in range(1, 11):
        compacted = _compact_request_value(copy.deepcopy(original), level)
        prepared = json.dumps(compacted, ensure_ascii=False, separators=(",", ":"), default=str)
        estimated = _estimated_request_tokens(system, prepared, max_tokens)
        if estimated <= hard_ceiling:
            print(
                f"[TOKEN COMPACTION] Request reduced to an estimated {estimated}/{hard_ceiling} "
                f"tokens at evidence compaction level {level}"
            )
            return prepared, estimated

    # Failed completions are not evidence. If preserving one would crowd out
    # grounding, regenerate from that grounding and the validation errors.
    if isinstance(original, dict) and "previous_response" in original:
        fresh = {key: value for key, value in original.items() if key != "previous_response"}
        fresh["repair_instruction"] = "Regenerate the full required schema from grounding_context. Address validation_errors. The previous invalid response was omitted to preserve the input budget."
        for level in range(0, 11):
            prepared = json.dumps(_compact_request_value(fresh, level), ensure_ascii=False, separators=(",", ":"), default=str)
            estimated = _estimated_request_tokens(system, prepared, max_tokens)
            if estimated <= hard_ceiling:
                return prepared, estimated

    raise GroqError(
        f"Request cannot fit the safe {hard_ceiling}-token ceiling even after compacting "
        "secondary evidence. The core policy context was preserved and no oversized request was sent."
    )


def _token_window_key(model: str) -> str:
    scope = os.getenv("GROQ_TOKEN_BUDGET_SCOPE", "shared").strip().lower()
    return model if scope == "per_model" else "__shared__"


def _set_payload_model(payload: dict[str, Any], model: str, reasoning_effort: str) -> None:
    payload["model"] = model
    if "gpt-oss" in model and reasoning_effort in {"low", "medium", "high"}:
        payload["reasoning_effort"] = reasoning_effort
    elif model.startswith("qwen/"):
        payload["reasoning_effort"] = "none"
    else:
        payload.pop("reasoning_effort", None)


async def _reserve_token_budget(model: str, requested_tokens: int) -> dict[str, float]:
    """Reserve capacity in a conservative rolling, per-model TPM window."""
    configured_limit = _env_int("GROQ_TOKENS_PER_MINUTE", 8000, 1)
    safety_ratio = min(_env_float("GROQ_TPM_SAFETY_RATIO", 0.70, 0.1), 1.0)
    budget = max(1, int(configured_limit * safety_ratio))
    if requested_tokens > budget:
        raise GroqError(
            f"Refusing to send an estimated {requested_tokens}-token request against the "
            f"safe {budget}-token limit. Evidence compaction must run first."
        )
    window_seconds = _env_float("GROQ_TOKEN_WINDOW_SECONDS", 65.0, 1.0)
    reservation_tokens = requested_tokens
    window_key = _token_window_key(model)

    while True:
        now = time.monotonic()
        async with _token_window_lock:
            window = _token_windows.setdefault(window_key, [])
            window[:] = [entry for entry in window if now - entry["at"] < window_seconds]
            used = sum(entry["tokens"] for entry in window)
            if used + reservation_tokens <= budget:
                reservation = {"at": now, "tokens": float(reservation_tokens)}
                window.append(reservation)
                return reservation
            wait = max(0.1, window[0]["at"] + window_seconds - now + 0.1)
        print(
            f"[TOKEN PACER] {model} has {int(used)}/{budget} reserved tokens; "
            f"waiting {wait:.1f}s before the next request"
        )
        await _reported_wait(wait, "token_budget")


async def _release_token_reservation(model: str, reservation: dict[str, float]) -> None:
    """Release requests rejected before Groq consumed any tokens (HTTP 429)."""
    async with _token_window_lock:
        window = _token_windows.get(_token_window_key(model), [])
        if reservation in window:
            window.remove(reservation)


async def _reconcile_token_reservation(
    model: str, reservation: dict[str, float], actual_tokens: Any
) -> None:
    try:
        actual = max(0, int(actual_tokens))
    except (TypeError, ValueError):
        return
    async with _token_window_lock:
        if reservation in _token_windows.get(_token_window_key(model), []):
            reservation["tokens"] = float(actual)


def _duration_seconds(value: str | None) -> float | None:
    """Parse Groq reset values such as ``1m20.5s`` or ``850ms``."""
    if not value:
        return None
    stripped = value.strip()
    try:
        return max(0.0, float(stripped))
    except ValueError:
        pass

    total = 0.0
    matches = list(_DURATION_PART.finditer(stripped))
    if not matches:
        return None
    multipliers = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
    for match in matches:
        total += float(match.group("value")) * multipliers[match.group("unit").lower()]
    return total


def _quota_exhausted(value: str | None) -> bool:
    try:
        return value is not None and float(value) <= 0
    except ValueError:
        return False


def _response_error_detail(response: httpx.Response) -> str:
    """Extract a useful provider error without logging request credentials."""
    try:
        message = response.json().get("error", {}).get("message")
        if message:
            return f"HTTP {response.status_code}: {str(message)[:240]}"
    except (ValueError, AttributeError, TypeError):
        pass
    return f"HTTP {response.status_code}"


def _is_retryable_generation_error(response: httpx.Response) -> bool:
    if response.status_code != 400:
        return False
    detail = _response_error_detail(response).lower()
    return any(
        marker in detail
        for marker in ("failed to generate json", "failed to validate json", "failed_generation")
    )


def _retry_after_seconds(response: httpx.Response, attempt: int) -> float:
    """Return the provider's reset time, falling back to exponential backoff."""
    candidates: list[float] = []
    retry_after = response.headers.get("retry-after")
    parsed_retry_after = _duration_seconds(retry_after)
    if parsed_retry_after is not None:
        candidates.append(parsed_retry_after)
    elif retry_after:
        try:
            retry_at = email.utils.parsedate_to_datetime(retry_after)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            candidates.append(max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds()))
        except (TypeError, ValueError, OverflowError):
            pass

    quota_windows = (
        ("x-ratelimit-remaining-tokens", "x-ratelimit-reset-tokens"),
        ("x-ratelimit-remaining-requests", "x-ratelimit-reset-requests"),
    )
    for remaining_header, reset_header in quota_windows:
        if _quota_exhausted(response.headers.get(remaining_header)):
            reset = _duration_seconds(response.headers.get(reset_header))
            if reset is not None:
                candidates.append(reset)

    # Older responses sometimes omit `remaining` but still include the token
    # reset header. Token quota is the common limiting factor for this pipeline.
    if not any(response.headers.get(pair[0]) is not None for pair in quota_windows):
        token_reset = _duration_seconds(response.headers.get("x-ratelimit-reset-tokens"))
        if token_reset is not None:
            candidates.append(token_reset)

    # Some Groq 429 responses put the only useful reset duration in the JSON
    # error message (for example, "Please try again in 1m2.5s").
    try:
        detail = str(response.json().get("error", {}).get("message", ""))
    except (ValueError, AttributeError, TypeError):
        detail = response.text
    message_match = _RETRY_MESSAGE.search(detail)
    if message_match:
        message_wait = _duration_seconds(message_match.group("duration"))
        if message_wait is not None:
            candidates.append(message_wait)

    fallback = min(2.0 * (2**attempt), 30.0)
    requested_wait = max(candidates, default=fallback)
    # A small jitter stops multiple backend processes from retrying together.
    # Never shorten a provider reset window: that creates avoidable 429s.
    if not candidates:
        requested_wait = min(requested_wait, _env_float("GROQ_MAX_RETRY_DELAY", 120.0, 1.0))
    return requested_wait + random.uniform(0.1, 0.6)


async def _wait_for_cooldown() -> None:
    async with _cooldown_lock:
        wait = _cooldown_until - time.monotonic()
    if wait > 0:
        await _reported_wait(wait, "provider_cooldown")


async def _set_cooldown(seconds: float) -> None:
    global _cooldown_until
    async with _cooldown_lock:
        _cooldown_until = max(_cooldown_until, time.monotonic() + seconds)


async def _groq_chat_json(
    client: httpx.AsyncClient,
    *,
    system: str,
    user: str,
    max_tokens: int | None = None,
    temperature: float | None = None,
    stage_name: str | None = None,
) -> dict[str, Any]:
    """Call Groq, queueing and retrying safely across provider quota windows."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise GroqError("GROQ_API_KEY is not set")

    user, estimated_request_tokens = _prepare_user_for_token_budget(system, user, max_tokens)

    # Read the model here rather than at import time. main.py loads backend/.env
    # after importing the pipeline, so an import-time value ignored GROQ_MODEL.
    models = _configured_models()
    for model in models:
        _model_cooldown_until.setdefault(model, 0.0)
    payload: dict[str, Any] = {
        "model": models[0],
        "temperature": temperature if temperature is not None else TEMPERATURE,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    reasoning_effort = os.getenv("GROQ_REASONING_EFFORT", "low").strip().lower()
    _set_payload_model(payload, str(payload["model"]), reasoning_effort)
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    max_retries = _env_int("GROQ_MAX_RETRIES", 12)
    last_error: Exception | None = None
    started = time.monotonic()
    stage_info = f" ({stage_name})" if stage_name else ""
    rate_limit_retries = 0
    generation_retries = 0
    transport_retries = 0

    async with _groq_semaphore:
        await _emit_progress(event="stage", current_stage=stage_name or "Analysis")
        # Rate-limit, generation, and transport failures have independent
        # budgets. Groq can alternate 429 and failed_generation responses; one
        # shared counter caused otherwise recoverable calls to fail early.
        for _request_attempt in range(1 + max_retries * 3):
            await _wait_for_cooldown()
            now = time.monotonic()
            current_model = str(payload["model"])
            if _model_cooldown_until[current_model] > now:
                available = [model for model in models if _model_cooldown_until[model] <= now]
                if available:
                    _set_payload_model(payload, available[0], reasoning_effort)
                else:
                    next_model = min(models, key=lambda item: _model_cooldown_until[item])
                    model_wait = max(0.0, _model_cooldown_until[next_model] - now)
                    print(
                        f"[MODEL PACER] All Groq models are in known quota windows; "
                        f"waiting {model_wait:.1f}s for {next_model}{stage_info}"
                    )
                    await _reported_wait(model_wait, "provider_cooldown")
                    _set_payload_model(payload, next_model, reasoning_effort)
            request_model = str(payload["model"])
            reservation = await _reserve_token_budget(
                request_model,
                estimated_request_tokens,
            )
            await _reserve_request_budget()
            # A request-window wait may outlast the original reservation. No
            # other call can run under the semaphore, so refresh its timestamp
            # at dispatch to cover the real provider token window accurately.
            reservation["at"] = time.monotonic()
            try:
                await _emit_progress(event="request", model=request_model, estimated_tokens=estimated_request_tokens)
                response = await client.post(
                    GROQ_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=httpx.Timeout(90.0, connect=15.0),
                )

                if response.status_code == 429:
                    await _emit_progress(event="rate_limited")
                    await _release_token_reservation(request_model, reservation)
                    wait = _retry_after_seconds(response, rate_limit_retries)
                    current_model = str(payload["model"])
                    _model_cooldown_until[current_model] = max(
                        _model_cooldown_until[current_model], time.monotonic() + wait
                    )
                    if rate_limit_retries >= max_retries:
                        elapsed = time.monotonic() - started
                        raise GroqError(
                            f"RATE_LIMITED: Groq quota did not reset after {max_retries} retries "
                            f"and {elapsed:.1f}s{stage_info}. All configured Groq models are still "
                            "quota-limited."
                        )
                    rate_limit_retries += 1

                    # Groq quotas are model-specific. Prefer any compatible model
                    # whose own reset window is currently open.
                    now = time.monotonic()
                    available = [
                        model
                        for model in models
                        if model != current_model and _model_cooldown_until[model] <= now
                    ]
                    if available:
                        _set_payload_model(payload, available[0], reasoning_effort)
                        print(
                            f"[MODEL ROTATION] Groq rate-limited {current_model}{stage_info}; "
                            f"continuing with {payload['model']}"
                        )
                        continue

                    # Every model is cooling down. Queue the request until the
                    # earliest model-specific window opens, then try that model.
                    next_model = min(models, key=lambda item: _model_cooldown_until[item])
                    model_wait = max(0.0, _model_cooldown_until[next_model] - now)
                    _set_payload_model(payload, next_model, reasoning_effort)
                    await _set_cooldown(model_wait)
                    print(
                        f"[RATE LIMIT] All Groq models cooling down{stage_info}; queued retry "
                        f"{rate_limit_retries}/{max_retries} on {next_model} in {model_wait:.1f}s"
                    )
                    continue

                if _is_retryable_generation_error(response):
                    if generation_retries >= max_retries:
                        raise GroqError(_response_error_detail(response))
                    wait = min(1.0 * (2**generation_retries), 8.0)
                    payload["temperature"] = 0
                    # Groq's constrained JSON decoder can reject an otherwise
                    # usable completion before returning it. On retry, ask for
                    # plain text and validate/extract the JSON locally.
                    payload.pop("response_format", None)
                    await _set_cooldown(wait)
                    generation_retries += 1
                    primary_model = models[0]
                    if (
                        payload["model"] != primary_model
                        and _model_cooldown_until[primary_model] <= time.monotonic()
                    ):
                        print(
                            f"[MODEL ROTATION] Returning to {primary_model}{stage_info} "
                            "after fallback JSON failure"
                        )
                        _set_payload_model(payload, primary_model, reasoning_effort)
                    print(
                        f"[JSON RETRY] Groq could not produce valid JSON{stage_info}; "
                        f"retry {generation_retries}/{max_retries} in {wait:.1f}s"
                    )
                    continue

                if response.status_code == 413:
                    raise GroqError(
                        "Groq rejected the request as too large. Try a shorter policy document."
                    )

                response.raise_for_status()
                body = response.json()
                await _reconcile_token_reservation(
                    request_model,
                    reservation,
                    (body.get("usage") or {}).get("total_tokens"),
                )
                await _emit_progress(event="usage", tokens=(body.get("usage") or {}).get("total_tokens", 0))
                content = body["choices"][0]["message"]["content"]
                parsed = parse_json_object(content)
                _model_cooldown_until[request_model] = 0.0
                elapsed = time.monotonic() - started
                print(f"Groq call completed{stage_info} with {payload['model']} in {elapsed:.2f}s")

                # If this successful call exhausted a window, queue the next
                # stage until Groq says that window resets.
                remaining_tokens = response.headers.get("x-ratelimit-remaining-tokens")
                remaining_requests = response.headers.get("x-ratelimit-remaining-requests")
                if _quota_exhausted(remaining_tokens) or _quota_exhausted(remaining_requests):
                    resets = [
                        _duration_seconds(response.headers.get(reset))
                        for remaining, reset in (
                            ("x-ratelimit-remaining-tokens", "x-ratelimit-reset-tokens"),
                            ("x-ratelimit-remaining-requests", "x-ratelimit-reset-requests"),
                        ) if _quota_exhausted(response.headers.get(remaining))
                    ]
                    await _set_cooldown(max((value for value in resets if value is not None), default=0.0))
                else:
                    await asyncio.sleep(_env_float("GROQ_REQUEST_SPACING", 0.75))
                try:
                    allowed = supplied_ids(json.loads(user))
                except (ValueError, TypeError):
                    allowed = set()
                return sanitize_citations(parsed, allowed)

            except GroqError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if transport_retries >= max_retries:
                    break
                wait = min(2.0 * (2**transport_retries), 30.0)
                await _set_cooldown(wait)
                transport_retries += 1
            except httpx.HTTPStatusError as exc:
                # Bad credentials and unsupported models will not improve by
                # repeatedly consuming the user's quota.
                elapsed = time.monotonic() - started
                detail = _response_error_detail(exc.response)
                raise GroqError(f"Groq call failed{stage_info} after {elapsed:.1f}s: {detail}") from exc
            except (ValueError, KeyError, TypeError) as exc:
                # A successful HTTP response can still contain truncated or
                # malformed model JSON. Retry deterministically before failing.
                last_error = exc
                if generation_retries >= max_retries:
                    break
                wait = min(1.0 * (2**generation_retries), 8.0)
                payload["temperature"] = 0
                payload.pop("response_format", None)
                await _set_cooldown(wait)
                generation_retries += 1
                primary_model = models[0]
                if (
                    payload["model"] != primary_model
                    and _model_cooldown_until[primary_model] <= time.monotonic()
                ):
                    print(
                        f"[MODEL ROTATION] Returning to {primary_model}{stage_info} "
                        "after fallback JSON failure"
                    )
                    _set_payload_model(payload, primary_model, reasoning_effort)
                print(
                    f"[JSON RETRY] Invalid Groq JSON{stage_info}; "
                    f"retry {generation_retries}/{max_retries} in {wait:.1f}s"
                )

    elapsed = time.monotonic() - started
    detail = str(last_error)[:160] if last_error else "unknown transport error"
    raise GroqError(f"Groq call failed{stage_info} after {elapsed:.1f}s: {detail}")


async def chat_json(client, *, system, user, max_tokens=None, temperature=None, stage_name=None):
    return await _groq_chat_json(client, system=system, user=user, max_tokens=max_tokens,
                                 temperature=temperature, stage_name=stage_name)
