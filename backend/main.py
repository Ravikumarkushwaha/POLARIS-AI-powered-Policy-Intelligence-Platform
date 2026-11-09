from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

import db
from models import (
    AnalysisMode, CreateRunRequest, CreateRunResponse, HealthResponse,
    MAX_POLICY_CHARACTERS, UploadRunResponse, new_run_payload,
)
from groq_client import quota_snapshot
from pipeline import run_pipeline, regenerate_recommendations, regenerate_scenarios
from run_cache import cache_ttls, run_cache_key
from run_manager import RunManager
import workspace

load_dotenv(Path(__file__).resolve().parent / ".env")
load_dotenv(Path(__file__).resolve().parent / ".env.local", override=True)
load_dotenv()

_instance_guard: object | None = None
_submission_lock = asyncio.Lock()


def _acquire_instance_guard() -> object:
    """Prevent two POLARIS backends from spending the same Groq quota."""
    if os.name == "nt":
        import ctypes

        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.CreateMutexW(None, False, "Local\\POLARIS_Backend_Groq_Quota")
        if not handle:
            raise RuntimeError("Could not create the POLARIS backend instance guard")
        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(handle)
            raise RuntimeError("Another POLARIS backend is already running")
        return handle

    import fcntl

    handle = (Path(__file__).resolve().parent / ".polaris-backend.lock").open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        raise RuntimeError("Another POLARIS backend is already running") from exc
    return handle


def _release_instance_guard(handle: object) -> None:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        ctypes.windll.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        ctypes.windll.kernel32.CloseHandle(handle)
    else:
        handle.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _instance_guard
    _instance_guard = _acquire_instance_guard()
    async def dispatch(run_id: str):
        payload = await db.get_run(run_id)
        if payload and payload.get("_job_kind"):
            await workspace.run_workspace_job(run_id)
        else:
            await run_pipeline(run_id)
    manager = RunManager(dispatch)
    _app.state.run_manager = manager
    try:
        await manager.start()
        yield
    finally:
        await manager.stop()
        if _instance_guard is not None:
            _release_instance_guard(_instance_guard)
            _instance_guard = None


app = FastAPI(title="POLARIS Backend", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _extract_policy_text(filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".txt", ".md", ".csv", ".json"}:
        return content.decode("utf-8-sig", errors="replace")
    if suffix == ".pdf":
        from pypdf import PdfReader
        import io

        return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)
    if suffix == ".docx":
        from docx import Document
        import io

        return "\n".join(paragraph.text for paragraph in Document(io.BytesIO(content)).paragraphs)
    raise HTTPException(status_code=415, detail="Upload a PDF, DOCX, TXT, Markdown, CSV, or JSON policy")


@app.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


def _manager() -> RunManager:
    manager = getattr(app.state, "run_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Analysis queue is starting. Please try again shortly.")
    return manager


@app.get("/api/runtime")
async def runtime() -> dict:
    return {
        "configured": bool(os.getenv("GROQ_API_KEY", "").strip()),
        "provider": "groq",
        "queue": _manager().snapshot(),
        "quota": quota_snapshot(),
        "cache": cache_ttls(),
        "modes": {"balanced": {"planned_calls": 4}, "deep": {"planned_calls": 8}},
    }


async def _submit_run(
    policy_text: str, domain_hint: str | None, web_enabled: bool,
    analysis_mode: AnalysisMode, force_refresh: bool, source_name: str | None = None,
) -> CreateRunResponse:
    policy_text = policy_text.strip()
    domain_hint = (domain_hint.strip() or None) if domain_hint else None
    if not policy_text:
        raise HTTPException(status_code=422, detail="policy_text is required")
    if len(policy_text) > MAX_POLICY_CHARACTERS:
        policy_text = policy_text[:MAX_POLICY_CHARACTERS]
    if domain_hint and len(domain_hint) > 200:
        raise HTTPException(status_code=422, detail="Domain hint must be at most 200 characters")
    manager = _manager()
    candidate_id = str(uuid.uuid4())
    payload = new_run_payload(candidate_id, policy_text, domain_hint, web_enabled, analysis_mode)
    if source_name:
        payload["policy_input"]["source_name"] = source_name
    cache_key = run_cache_key(policy_text, domain_hint, web_enabled, analysis_mode)
    ttl = cache_ttls()["web_ttl_seconds" if web_enabled else "document_ttl_seconds"]
    # Cancellation cannot leave a committed submission without a live queue
    # entry, and concurrent submissions cannot schedule the same job twice.
    async def commit_submission() -> tuple[str, str | None]:
        async with _submission_lock:
            run_id, reason = await db.create_or_reuse_run(payload, cache_key, ttl, force_refresh)
            if reason != "cached":
                await manager.enqueue(run_id)
            return run_id, reason

    submission = asyncio.create_task(commit_submission())
    try:
        run_id, reason = await asyncio.shield(submission)
    except asyncio.CancelledError:
        await submission
        raise
    return CreateRunResponse(
        run_id=run_id, reused=reason is not None, reuse_reason=reason,
        queue_position=manager.run_state(run_id)["queue_position"],
    )


@app.post("/api/runs", response_model=CreateRunResponse)
async def create_run(body: CreateRunRequest) -> CreateRunResponse:
    return await _submit_run(
        body.policy_text, body.domain_hint, body.web_enabled, body.analysis_mode, body.force_refresh,
    )


@app.post("/api/runs/upload", response_model=UploadRunResponse)
async def create_run_from_upload(
    file: UploadFile = File(...),
    domain_hint: str | None = Form(None),
    web_enabled: bool = Form(True),
    analysis_mode: AnalysisMode = Form("balanced"),
    force_refresh: bool = Form(False),
) -> UploadRunResponse:
    if not file.filename:
        raise HTTPException(status_code=422, detail="file is required")
    content = await file.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Policy files must be smaller than 10 MB")
    try:
        policy_text = (await asyncio.to_thread(_extract_policy_text, file.filename, content)).strip()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Could not read this document. Try a text-based PDF, DOCX, or TXT file.") from exc
    if not policy_text:
        raise HTTPException(status_code=422, detail="The uploaded policy contains no readable text")
    source_name = Path(file.filename.replace("\\", "/")).name[:200]
    result = await _submit_run(
        policy_text, domain_hint, web_enabled, analysis_mode, force_refresh, source_name,
    )
    return UploadRunResponse(
        **result.model_dump(),
        source_name=source_name,
        extracted_characters=len(policy_text),
    )


def _history_title(payload: dict) -> str:
    policy_input = payload.get("policy_input") or {}
    if policy_input.get("source_name"):
        return str(policy_input["source_name"])[:160]
    text = str(policy_input.get("policy_text") or "")
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if (
        len(first_line) >= 12
        and len(first_line.split()) >= 3
        and any(character.isalpha() for character in first_line)
    ):
        return first_line[:160]
    parsed = payload.get("parsed_policy") or {}
    goals = parsed.get("goals") or []
    domain = str(parsed.get("domain") or "Policy analysis")
    return str(f"{domain} â€” {goals[0]}" if goals else domain)[:160]


@app.get("/api/runs")
async def list_runs(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    total, rows = await db.list_runs(limit=limit, offset=offset)
    items = []
    for row in rows:
        payload = row["payload"]
        agents = payload.get("agents") or {}
        synthesis = payload.get("synthesis") or {}
        parsed = payload.get("parsed_policy") or {}
        items.append(
            {
                "run_id": payload.get("run_id"),
                "title": _history_title(payload),
                "status": payload.get("status", "error"),
                "analysis_mode": payload.get("policy_input", {}).get("analysis_mode", "deep"),
                "domain": parsed.get("domain") or payload.get("policy_input", {}).get("domain_hint"),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "confidence": synthesis.get("confidence"),
                "impact_score": synthesis.get("overall_impact_score"),
                "risk_level": synthesis.get("risk_level")
                or ((agents.get("risk") or {}).get("output") or {}).get("risk_level"),
                "agents_complete": sum(
                    1 for agent in agents.values() if (agent or {}).get("status") == "done"
                ),
                "web_sources": len(payload.get("web_sources") or []),
                "error": payload.get("error"),
                "telemetry": payload.get("telemetry"),
            }
        )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    payload = await db.get_run(run_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="run not found")
    payload["runtime"] = _manager().run_state(run_id)
    return payload


@app.post("/api/runs/{run_id}/recommendations/refresh")
async def refresh_recommendations(run_id: str) -> dict:
    if await db.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    try:
        return await regenerate_recommendations(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/runs/{run_id}/scenarios/refresh")
async def refresh_scenarios(run_id: str) -> dict:
    if await db.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    try:
        return await regenerate_scenarios(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/runs/{run_id}/cancel")
async def cancel_run(run_id: str) -> dict:
    try:
        payload = await _manager().cancel(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    payload["runtime"] = _manager().run_state(run_id)
    return payload


@app.delete("/api/runs/{run_id}")
async def delete_run(run_id: str) -> dict:
    payload = await db.get_run(run_id)
    if payload is None or payload.get("_job_kind"):
        raise HTTPException(status_code=404, detail="run not found")
    try:
        await _manager().cancel(run_id)
    except KeyError:
        pass
    await db.delete_run(run_id)
    return {"deleted": True}


workspace.configure(_manager)
app.include_router(workspace.router)

@app.post("/api/runs/{run_id}/resume")
async def resume_run(run_id: str) -> dict:
    async with _submission_lock:
        payload = await db.get_run(run_id)
        if payload is None or payload.get("_job_kind"):
            raise HTTPException(404, "Policy analysis not found")
        if payload.get("status") not in {"error", "cancelled"}:
            payload["runtime"] = _manager().run_state(run_id)
            return payload
        def resume(p):
            p.update(status="pending", error=None)
            lifecycle = p.setdefault("lifecycle", {})
            for key in ("finished_at", "cancelled_at", "completed_at"):
                lifecycle.pop(key, None)
        await db.patch_run(run_id, resume, allow_cancelled=True)
        await _manager().enqueue(run_id)
        payload = await db.get_run(run_id)
        payload["runtime"] = _manager().run_state(run_id)
        return payload
