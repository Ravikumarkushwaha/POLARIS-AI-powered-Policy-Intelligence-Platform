"""Conservative exact-input cache keys; document and live evidence age separately."""
from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path

from groq_client import _configured_models


def cache_ttls() -> dict[str, int]:
    def bounded(name: str, default: int) -> int:
        try:
            return max(0, min(default, int(os.getenv(name, str(default)))))
        except ValueError:
            return default

    # Configuration may shorten these windows or disable reuse entirely.
    return {
        "web_ttl_seconds": bounded("POLARIS_WEB_CACHE_TTL_SECONDS", 3600),
        "document_ttl_seconds": bounded("POLARIS_DOCUMENT_CACHE_TTL_SECONDS", 86400),
    }


@lru_cache(maxsize=1)
def _analysis_revision() -> str:
    digest = hashlib.sha256(b"polaris-run-cache-v1")
    directory = Path(__file__).resolve().parent
    for filename in (
        "pipeline.py", "prompts.py", "json_util.py", "rag.py",
        "state_seed_data.json", "web_retriever.py", "groq_client.py", "evidence.py",
    ):
        digest.update((directory / filename).read_bytes())
    return digest.hexdigest()


def run_cache_key(policy_text: str, domain_hint: str | None, web_enabled: bool, analysis_mode: str) -> str:
    # Keep interior whitespace and case: even punctuation can change a policy.
    settings = {
        "policy_text": policy_text.strip(),
        "domain_hint": domain_hint.strip() if domain_hint else None,
        "web_enabled": web_enabled,
        "analysis_mode": analysis_mode,
        "models": _configured_models(),
        "analysis_revision": _analysis_revision(),
    }
    return hashlib.sha256(json.dumps(settings, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
