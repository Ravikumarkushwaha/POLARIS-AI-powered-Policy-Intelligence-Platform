import asyncio
import json
import os
import sys
from unittest.mock import patch

import httpx
import pytest

sys.path.insert(0, os.path.dirname(__file__))

import groq_client


@pytest.fixture(autouse=True)
def reset_token_pacer(monkeypatch):
    monkeypatch.setenv("POLARIS_AI_PROVIDER", "groq")
    groq_client._token_windows.clear()
    groq_client._model_cooldown_until.clear()
    monkeypatch.setenv("GROQ_TOKENS_PER_MINUTE", "1000000")


def _response(status: int, *, headers=None, body=None) -> httpx.Response:
    return httpx.Response(
        status,
        headers=headers,
        json=body or {"error": {"message": "error"}},
        request=httpx.Request("POST", groq_client.GROQ_URL),
    )


def test_retry_wait_understands_groq_reset_headers_and_message():
    response = _response(
        429,
        headers={"x-ratelimit-reset-tokens": "1m2.5s"},
        body={"error": {"message": "Rate limit reached. Please try again in 4.2s."}},
    )
    with patch("groq_client.random.uniform", return_value=0.1):
        assert groq_client._retry_after_seconds(response, 0) == 62.6


def test_retry_wait_ignores_a_non_exhausted_request_window():
    response = _response(
        429,
        headers={
            "x-ratelimit-remaining-tokens": "0",
            "x-ratelimit-reset-tokens": "7.5s",
            "x-ratelimit-remaining-requests": "1000",
            "x-ratelimit-reset-requests": "2m",
        },
    )
    with patch("groq_client.random.uniform", return_value=0.1):
        assert groq_client._retry_after_seconds(response, 0) == 7.6


def test_chat_json_retries_429_and_uses_runtime_model(monkeypatch):
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return _response(429, headers={"retry-after": "0"})
        return _response(
            200,
            body={"choices": [{"message": {"content": '{"ok": true}'}}]},
        )

    async def no_sleep(_seconds: float) -> None:
        groq_client._cooldown_until = 0.0

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("GROQ_MODEL", "runtime-model")
    monkeypatch.setenv("GROQ_FALLBACK_MODELS", "")
    monkeypatch.setenv("GROQ_MAX_RETRIES", "2")
    monkeypatch.setattr(groq_client.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(groq_client.random, "uniform", lambda _a, _b: 0.0)
    groq_client._cooldown_until = 0.0

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await groq_client.chat_json(client, system="system", user="user")

    assert asyncio.run(run()) == {"ok": True}
    assert len(calls) == 2
    assert calls[0]["model"] == "runtime-model"


def test_chat_json_does_not_retry_non_rate_limit_http_errors(monkeypatch):
    call_count = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return _response(401)

    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await groq_client.chat_json(client, system="system", user="user")

    try:
        asyncio.run(run())
    except groq_client.GroqError as exc:
        assert "HTTP 401: error" in str(exc)
    else:
        raise AssertionError("Expected GroqError")
    assert call_count == 1


def test_chat_json_retries_transient_failed_generation(monkeypatch):
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return _response(
                400,
                body={"error": {"message": "Failed to generate JSON. See 'failed_generation'."}},
            )
        return _response(
            200,
            body={"choices": [{"message": {"content": '{"ok": true}'}}]},
        )

    async def no_sleep(_seconds: float) -> None:
        groq_client._cooldown_until = 0.0

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(groq_client.asyncio, "sleep", no_sleep)
    groq_client._cooldown_until = 0.0

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await groq_client.chat_json(client, system="system", user="user")

    assert asyncio.run(run()) == {"ok": True}
    assert len(requests) == 2
    assert requests[1]["temperature"] == 0
    assert "response_format" not in requests[1]


def test_failed_to_validate_json_is_retryable():
    response = _response(
        400,
        body={
            "error": {
                "message": "Failed to validate JSON. Please adjust your prompt. See 'failed_generation'."
            }
        },
    )
    assert groq_client._is_retryable_generation_error(response)


def test_rate_limit_and_generation_retries_have_independent_budgets(monkeypatch):
    call_count = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count in {1, 3, 5, 7}:
            return _response(429, headers={"retry-after": "0"})
        if call_count in {2, 4, 6, 8}:
            return _response(
                400,
                body={"error": {"message": "Failed to validate JSON. See failed_generation."}},
            )
        return _response(
            200,
            body={"choices": [{"message": {"content": '{"ok": true}'}}]},
        )

    async def no_sleep(_seconds: float) -> None:
        groq_client._cooldown_until = 0.0

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("GROQ_MAX_RETRIES", "4")
    monkeypatch.setenv("GROQ_FALLBACK_MODELS", "")
    monkeypatch.setattr(groq_client.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(groq_client.random, "uniform", lambda _a, _b: 0.0)
    groq_client._cooldown_until = 0.0

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await groq_client.chat_json(client, system="system", user="user")

    assert asyncio.run(run()) == {"ok": True}
    assert call_count == 9


def test_chat_json_falls_back_to_second_model_on_429(monkeypatch):
    models = []

    async def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        models.append(model)
        if model == "primary-model":
            return _response(429, headers={"retry-after": "60"})
        return _response(
            200,
            body={"choices": [{"message": {"content": '{"ok": true}'}}]},
        )

    async def no_sleep(_seconds: float) -> None:
        groq_client._cooldown_until = 0.0

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("GROQ_MODEL", "primary-model")
    monkeypatch.setenv("GROQ_FALLBACK_MODELS", "fallback-model")
    monkeypatch.setattr(groq_client.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(groq_client.random, "uniform", lambda _a, _b: 0.0)
    groq_client._cooldown_until = 0.0

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await groq_client.chat_json(client, system="system", user="user")

    assert asyncio.run(run()) == {"ok": True}
    assert models == ["primary-model", "fallback-model"]


def test_chat_json_returns_to_primary_after_fallback_json_failure(monkeypatch):
    models = []

    async def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        models.append(model)
        if len(models) == 1:
            return _response(429, headers={"retry-after": "0"})
        if len(models) == 2:
            return _response(
                200,
                body={"choices": [{"message": {"content": "truncated {"}}]},
            )
        return _response(
            200,
            body={"choices": [{"message": {"content": '{"ok": true}'}}]},
        )

    async def no_sleep(_seconds: float) -> None:
        groq_client._cooldown_until = 0.0

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("GROQ_MODEL", "primary-model")
    monkeypatch.setenv("GROQ_FALLBACK_MODELS", "fallback-model")
    monkeypatch.setattr(groq_client.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(groq_client.random, "uniform", lambda _a, _b: 0.0)
    groq_client._cooldown_until = 0.0

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await groq_client.chat_json(client, system="system", user="user")

    assert asyncio.run(run()) == {"ok": True}
    assert models == ["primary-model", "fallback-model", "primary-model"]


def test_token_pacer_waits_before_rolling_window_would_exceed_limit(monkeypatch):
    waits = []
    monkeypatch.setenv("GROQ_TOKENS_PER_MINUTE", "100")
    monkeypatch.setenv("GROQ_TPM_SAFETY_RATIO", "1")

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)
        groq_client._token_windows[groq_client._token_window_key("test-model")].clear()

    monkeypatch.setattr(groq_client.asyncio, "sleep", fake_sleep)

    async def run():
        first = await groq_client._reserve_token_budget("test-model", 60)
        second = await groq_client._reserve_token_budget("test-model", 60)
        return first, second

    first, second = asyncio.run(run())
    assert first["tokens"] == 60
    assert second["tokens"] == 60
    assert len(waits) == 1


def test_oversized_request_compacts_evidence_but_preserves_core_policy(monkeypatch):
    monkeypatch.setenv("GROQ_TOKENS_PER_MINUTE", "8000")
    monkeypatch.setenv("GROQ_TPM_SAFETY_RATIO", "0.9")
    core_policy = "PM Gati Shakti coordinates multimodal infrastructure across ministries and states."
    payload = {
        "parsed_policy": {"domain": "Infrastructure", "goals": ["Reduce logistics costs"]},
        "policy_text": core_policy,
        "retrieved_context": [
            {"chunk_id": f"chunk-{index}", "text": "relevant local evidence " * 500, "relevance": 1 - index / 10}
            for index in range(5)
        ],
        "web_sources": [
            {"title": f"Source {index}", "url": f"https://example.com/{index}", "text": "web evidence " * 500}
            for index in range(4)
        ],
        "state_seed_data": {f"State {index}": {"population_share": index} for index in range(40)},
    }

    prepared, estimated = groq_client._prepare_user_for_token_budget(
        "Return structured risk JSON.", json.dumps(payload), 700
    )
    compacted = json.loads(prepared)

    assert estimated <= 7200
    assert compacted["policy_text"] == core_policy
    assert compacted["parsed_policy"] == payload["parsed_policy"]
    assert len(compacted["retrieved_context"]) < len(payload["retrieved_context"])
    assert len(compacted["web_sources"]) < len(payload["web_sources"])


def test_risk_synthesis_payload_compacts_nested_findings_to_ceiling(monkeypatch):
    monkeypatch.setenv("GROQ_TOKENS_PER_MINUTE", "8000")
    monkeypatch.setenv("GROQ_TPM_SAFETY_RATIO", "0.7")
    monkeypatch.setenv("GROQ_MAX_REQUEST_TOKENS", "5500")

    domains = {}
    for name in ("economic", "environment", "social", "legal_budget"):
        domains[name] = {
            "metric_effects": [
                {
                    "metric": f"{name} impact {idx}",
                    "direction": "positive",
                    "magnitude": "High",
                    "confidence": 0.88,
                    "evidence_ids": [f"doc-{name}-{idx}-{j}" for j in range(10)],
                }
                for idx in range(8)
            ],
            "reasoning": ("Evidence-heavy response " * 300) + "This policy affects many groups and sectors.",
            "uncertainty": "Large uncertainty remains given incomplete local evidence. " * 200,
            "affected_states_weight": {f"State {idx}": 0.9 for idx in range(30)},
            "evidence_ids": [f"doc-{name}-{idx}" for idx in range(12)],
        }

    payload = {
        "parsed_policy": {
            "domain": "Infrastructure",
            "goals": ["Reduce logistics costs", "Improve regional connectivity"],
            "stakeholders": ["farmers", "transporters", "state agencies"],
            "affected_sectors": ["logistics", "energy", "housing"],
        },
        **domains,
        "risk": {
            "risk_level": "High",
            "confidence": 0.82,
            "justification": ("Risk is elevated because implementation capacity is uneven " * 250),
            "confidence_rationale": "The evidence is consistent across domain experts. " * 300,
        },
    }

    prepared, estimated = groq_client._prepare_user_for_token_budget(
        "Return complete risk synthesis JSON.", json.dumps(payload), 1800
    )

    assert estimated <= 5500
    compacted = json.loads(prepared)
    assert compacted["parsed_policy"]["domain"] == "Infrastructure"
    assert len(compacted["economic"]["metric_effects"]) <= 4


def test_token_budget_is_shared_across_models_by_default(monkeypatch):
    waits = []
    monkeypatch.setenv("GROQ_TOKENS_PER_MINUTE", "100")
    monkeypatch.setenv("GROQ_TPM_SAFETY_RATIO", "1")
    monkeypatch.setenv("GROQ_TOKEN_BUDGET_SCOPE", "shared")

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)
        groq_client._token_windows["__shared__"].clear()

    monkeypatch.setattr(groq_client.asyncio, "sleep", fake_sleep)

    async def run():
        await groq_client._reserve_token_budget("model-a", 60)
        await groq_client._reserve_token_budget("model-b", 60)

    asyncio.run(run())
    assert len(waits) == 1


def test_model_cooldown_is_reused_by_the_next_pipeline_stage(monkeypatch):
    models = []

    async def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        models.append(model)
        if model == "primary-model":
            return _response(429, headers={"retry-after": "60"})
        return _response(
            200,
            body={"choices": [{"message": {"content": '{"ok": true}'}}]},
        )

    async def no_sleep(_seconds: float) -> None:
        groq_client._cooldown_until = 0.0

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("GROQ_MODEL", "primary-model")
    monkeypatch.setenv("GROQ_FALLBACK_MODELS", "fallback-model")
    monkeypatch.setattr(groq_client.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(groq_client.random, "uniform", lambda _a, _b: 0.0)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await groq_client.chat_json(client, system="stage one", user="input")
            await groq_client.chat_json(client, system="stage two", user="input")

    asyncio.run(run())
    assert models == ["primary-model", "fallback-model", "fallback-model"]


def test_model_rotation_removes_gpt_oss_reasoning_effort_for_qwen():
    payload = {"model": "openai/gpt-oss-20b", "reasoning_effort": "low"}

    groq_client._set_payload_model(payload, "qwen/qwen3.6-27b", "low")

    assert payload == {"model": "qwen/qwen3.6-27b", "reasoning_effort": "none"}


def test_repair_drops_invalid_completion_before_raising_ceiling(monkeypatch):
    monkeypatch.setenv("GROQ_TOKENS_PER_MINUTE", "8000")
    monkeypatch.setenv("GROQ_MAX_REQUEST_TOKENS", "5500")
    bad = {f"field_{i}": "unusable response " * 100 for i in range(100)}
    data = {"grounding_context": {"policy_text": "Policy eligibility: rural households only.",
            "evidence_catalog": [{"evidence_id": "doc-one", "text": "The original policy evidence."}]},
            "previous_response": bad, "validation_errors": ["brief is missing"]}
    prepared, estimate = groq_client._prepare_user_for_token_budget("Return a complete JSON schema. " * 50, json.dumps(data), 1800)
    assert estimate <= 5500
    result = json.loads(prepared)
    assert "previous_response" not in result
    assert result["grounding_context"]["policy_text"] == data["grounding_context"]["policy_text"]
    assert "doc-one" in prepared


@pytest.mark.skip(reason="Gemini provider support was removed; POLARIS is Groq-only")
def test_gemini_uses_same_budget_and_sanitizes_sources(monkeypatch):
    async def scenario():
        monkeypatch.setenv("POLARIS_AI_PROVIDER", "gemini")
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setenv("GROQ_TOKENS_PER_MINUTE", "8000")
        monkeypatch.setattr(groq_client, "_groq_semaphore", asyncio.Semaphore(1))
        monkeypatch.setattr(groq_client, "_token_window_lock", asyncio.Lock())
        monkeypatch.setattr(groq_client, "_request_window", [])
        requests = []
        def transport(request):
            body = json.loads(request.content)
            requests.append(body)
            assert request.headers["x-goog-api-key"] == "test-key"
            assert body["generationConfig"]["thinkingConfig"]["thinkingBudget"] == 0
            return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps({"answer": "Result", "evidence_ids": ["doc-real", "fake"]})}]}}], "usageMetadata": {"totalTokenCount": 30}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            result = await groq_client.chat_json(client, system="Return JSON.", user=json.dumps({"evidence_catalog": [{"evidence_id": "doc-real", "text": "Source passage"}]}), max_tokens=100)
        assert result["evidence_ids"] == ["doc-real"]
        assert len(requests) == 1
        assert groq_client._model_cooldown_until["gemini-2.5-flash"] > groq_client.time.monotonic()
    asyncio.run(scenario())


@pytest.mark.skip(reason="Gemini provider support was removed; POLARIS is Groq-only")
def test_gemini_honors_retry_info_without_unbounded_retries(monkeypatch):
    async def scenario():
        monkeypatch.setenv("POLARIS_AI_PROVIDER", "gemini")
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setattr(groq_client, "_groq_semaphore", asyncio.Semaphore(1))
        monkeypatch.setattr(groq_client, "_token_window_lock", asyncio.Lock())
        monkeypatch.setattr(groq_client, "_request_window", [])
        waits, calls = [], []
        async def no_wait(seconds, reason):
            waits.append(seconds)
        monkeypatch.setattr(groq_client, "_reported_wait", no_wait)
        def transport(request):
            calls.append(request)
            if len(calls) == 1:
                return httpx.Response(429, json={"error": {"details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "59s"}]}})
            return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "{\"ok\":true}"}]}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            result = await groq_client.chat_json(client, system="Return JSON", user="{}", max_tokens=100)
        assert result["ok"]
        assert len(calls) == 2
        assert max(waits) > 59
    asyncio.run(scenario())
