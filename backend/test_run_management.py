import asyncio
import json
import os
import sqlite3
import sys
import threading

import httpx
import pytest

sys.path.insert(0, os.path.dirname(__file__))

import db
import main
from models import new_run_payload
from run_cache import cache_ttls, run_cache_key
from run_manager import RunManager


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "runs.db")
    monkeypatch.setattr(db, "_initialized", False)
    monkeypatch.setattr(db, "_lock", asyncio.Lock())
    monkeypatch.setattr(main, "_submission_lock", asyncio.Lock())
    return db.DB_PATH


def test_atomic_submission_reuses_active_then_fresh_completed_and_respects_refresh(isolated_db):
    async def scenario():
        results = await asyncio.gather(*[
            db.create_or_reuse_run(new_run_payload(str(i), "Policy text", None), "same", 3600)
            for i in range(8)
        ])
        first_id = results[0][0]
        assert {item[0] for item in results} == {first_id}
        assert sum(reason is None for _, reason in results) == 1
        # Explicit refresh must still reuse work already in progress.
        assert await db.create_or_reuse_run(new_run_payload("refresh", "Policy text", None), "same", 3600, True) == (first_id, "active")
        await db.patch_run(first_id, lambda p: p.update(status="complete"))
        assert await db.create_or_reuse_run(new_run_payload("cached", "Policy text", None), "same", 3600) == (first_id, "cached")
        assert await db.create_or_reuse_run(new_run_payload("refresh", "Policy text", None), "same", 3600, True) == ("refresh", None)
        total, _ = await db.list_runs()
        assert total == 2

    asyncio.run(scenario())


def test_expired_error_and_cancelled_runs_never_reused(isolated_db):
    async def scenario():
        for name, status in (("old", "complete"), ("failed", "error"), ("stopped", "cancelled")):
            payload = new_run_payload(name, "Policy text", None)
            payload["status"] = status
            await db.create_or_reuse_run(payload, name, 3600)
        with sqlite3.connect(isolated_db) as connection:
            connection.execute("UPDATE runs SET updated_at = datetime('now', '-2 hours') WHERE run_id = 'old'")
        for name in ("old", "failed", "stopped"):
            assert await db.create_or_reuse_run(new_run_payload(name + "-new", "Policy text", None), name, 3600) == (name + "-new", None)

    asyncio.run(scenario())


def test_cache_keys_separate_evidence_mode_domain_model_and_exact_text(monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", "model-a")
    base = run_cache_key("Policy: 10% target", None, True, "balanced")
    assert base == run_cache_key("  Policy: 10% target\n", None, True, "balanced")
    variants = [
        ("Policy: 10% target", "Energy", True, "balanced"),
        ("Policy: 10% target", None, False, "balanced"),
        ("Policy: 10% target", None, True, "deep"),
        ("Policy:  10% target", None, True, "balanced"),
    ]
    assert all(run_cache_key(*variant) != base for variant in variants)
    monkeypatch.setenv("GROQ_MODEL", "model-b")
    assert run_cache_key("Policy: 10% target", None, True, "balanced") != base
    monkeypatch.setenv("POLARIS_WEB_CACHE_TTL_SECONDS", "999999")
    monkeypatch.setenv("POLARIS_DOCUMENT_CACHE_TTL_SECONDS", "0")
    assert cache_ttls() == {"web_ttl_seconds": 3600, "document_ttl_seconds": 0}


def test_delete_run_removes_parent_and_related_jobs(isolated_db):
    async def scenario():
        parent = new_run_payload("parent", "Policy text", None)
        child = {
            **new_run_payload("child", "Child policy", None),
            "parent_run_id": parent["run_id"],
            "_job_kind": "chat",
        }
        await db.save_run(parent)
        await db.save_run(child)

        await db.delete_run(parent["run_id"])

        assert await db.get_run(parent["run_id"]) is None
        assert await db.get_run(child["run_id"]) is None

    asyncio.run(scenario())


def test_existing_database_migrates_without_losing_history(isolated_db):
    payload = new_run_payload("legacy", "Prior policy", None)
    with sqlite3.connect(isolated_db) as connection:
        connection.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now')))")
        connection.execute("INSERT INTO runs (run_id, payload) VALUES (?, ?)", ("legacy", json.dumps(payload)))

    async def scenario():
        await db.init_db()
        assert (await db.get_run("legacy"))["policy_input"]["policy_text"] == "Prior policy"
        assert await db.create_or_reuse_run(new_run_payload("new", "New policy", None), "key", 3600) == ("new", None)

    asyncio.run(scenario())


def test_fifo_queue_cancel_and_recovery_preserve_partial_results(isolated_db):
    async def scenario():
        started = asyncio.Event()
        invocations = []

        async def blocked_runner(run_id):
            invocations.append(run_id)
            await db.patch_run(run_id, lambda p: p.update(status="analyzing", parsed_policy={"domain": "Energy"}))
            started.set()
            await asyncio.Event().wait()

        for run_id in ("first", "second", "third"):
            await db.save_run(new_run_payload(run_id, "Policy", None))
        manager = RunManager(blocked_runner)
        await manager.start()
        await asyncio.wait_for(started.wait(), 2)
        assert manager.snapshot()["queued_runs"] == 2
        assert manager.run_state("second")["queue_position"] == 1
        assert (await manager.cancel("second"))["status"] == "cancelled"
        started.clear()
        stopped = await manager.cancel("first")
        assert stopped["status"] == "cancelled"
        assert stopped["parsed_policy"] == {"domain": "Energy"}
        await asyncio.wait_for(started.wait(), 2)
        assert invocations == ["first", "third"]
        await manager.stop()
        assert await db.list_incomplete_runs() == ["third"]
        recovered = asyncio.Event()

        async def resumed_runner(run_id):
            assert run_id == "third"
            assert (await db.get_run(run_id))["parsed_policy"] == {"domain": "Energy"}
            await db.patch_run(run_id, lambda p: p.update(status="complete"))
            recovered.set()

        restored = RunManager(resumed_runner)
        await restored.start()
        await asyncio.wait_for(recovered.wait(), 2)
        await restored.stop()
        assert (await db.get_run("third"))["status"] == "complete"
        assert (await db.get_run("second"))["status"] == "cancelled"

    asyncio.run(scenario())


def test_http_contract_dedup_upload_cancel_runtime_and_validation(isolated_db, monkeypatch):
    monkeypatch.setattr(main, "_acquire_instance_guard", lambda: object())
    monkeypatch.setattr(main, "_release_instance_guard", lambda handle: None)
    monkeypatch.setenv("GROQ_API_KEY", "do-not-expose-this-test-key")

    async def blocked_runner(run_id):
        await asyncio.Event().wait()

    monkeypatch.setattr(main, "run_pipeline", blocked_runner)

    async def scenario():
        async with main.lifespan(main.app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
                body = {"policy_text": "A clean energy policy.", "web_enabled": False, "analysis_mode": "balanced"}
                first = (await client.post("/api/runs", json=body)).json()
                assert not first["reused"]
                duplicate = (await client.post("/api/runs", json=body)).json()
                assert duplicate["run_id"] == first["run_id"]
                assert duplicate["reuse_reason"] == "active"
                uploaded = await client.post("/api/runs/upload", files={"file": ("policy.txt", body["policy_text"])}, data={"web_enabled": "false"})
                assert uploaded.status_code == 200
                assert uploaded.json()["run_id"] == first["run_id"]
                runtime = await client.get("/api/runtime")
                assert runtime.json()["queue"]["concurrency"] == 1
                assert runtime.json()["modes"]["balanced"]["planned_calls"] == 4
                assert "do-not-expose" not in runtime.text
                assert runtime.json()["configured"] is True
                cancelled = await client.post(f"/api/runs/{first['run_id']}/cancel")
                assert cancelled.json()["status"] == "cancelled"
                assert (await client.get(f"/api/runs/{first['run_id']}")).json()["status"] == "cancelled"
                history = (await client.get("/api/runs")).json()
                assert history["total"] == 1
                assert history["items"][0]["analysis_mode"] == "balanced"
                assert (await client.post("/api/runs/missing/cancel")).status_code == 404
                assert (await client.post("/api/runs", json={"policy_text": "   "})).status_code == 422
                assert (await client.post("/api/runs", json={**body, "analysis_mode": "unlimited"})).status_code == 422
                assert (await client.post("/api/runs", json={"policy_text": "x" * 200001})).status_code == 200
                assert (await client.post("/api/runs/upload", files={"file": ("policy.exe", b"hello")})).status_code == 415

    asyncio.run(scenario())


def test_long_policy_text_is_truncated_for_analysis(isolated_db):
    async def scenario():
        payload = "A" * 250_000
        created = await main._submit_run(payload, None, False, "balanced", False)
        run = await db.get_run(created.run_id)
        assert run is not None
        assert len(run["policy_input"]["policy_text"]) == 200_000

    asyncio.run(scenario())


def test_disconnected_submission_still_enters_queue(isolated_db, monkeypatch):
    async def scenario():
        committed = asyncio.Event()
        release = asyncio.Event()
        original_create = db.create_or_reuse_run

        async def delayed_create(*args, **kwargs):
            result = await original_create(*args, **kwargs)
            committed.set()
            await release.wait()
            return result

        async def unused_runner(run_id):
            raise AssertionError("This test must not execute analyses")

        manager = RunManager(unused_runner)
        monkeypatch.setattr(main.app.state, "run_manager", manager)
        monkeypatch.setattr(db, "create_or_reuse_run", delayed_create)
        submission = asyncio.create_task(main._submit_run("A policy", None, False, "balanced", False))
        await asyncio.wait_for(committed.wait(), 2)
        submission.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await submission
        total, rows = await db.list_runs()
        assert total == 1
        assert manager.run_state(rows[0]["payload"]["run_id"])["queue_position"] == 1

    asyncio.run(scenario())


def test_cancelled_database_write_keeps_lock_until_sqlite_finishes(isolated_db, monkeypatch):
    started = threading.Event()
    release = threading.Event()
    original_save = db._save_sync

    def delayed_save(payload):
        started.set()
        assert release.wait(timeout=3)
        original_save(payload)

    monkeypatch.setattr(db, "_save_sync", delayed_save)

    async def scenario():
        operation = asyncio.create_task(db.save_run(new_run_payload("saving", "A policy", None)))
        assert await asyncio.to_thread(started.wait, 2)
        operation.cancel()
        reader = asyncio.create_task(db.get_run("saving"))
        await asyncio.sleep(0)
        assert not reader.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await operation
        assert (await reader)["run_id"] == "saving"

    asyncio.run(scenario())


def test_resume_keeps_checkpoints_and_enqueues_once(isolated_db, monkeypatch):
    async def scenario():
        async def unused_runner(run_id):
            raise AssertionError("Resume test must not call a provider")
        manager = RunManager(unused_runner)
        monkeypatch.setattr(main.app.state, "run_manager", manager)
        payload = new_run_payload("resume-test", "Saved policy", None)
        payload.update(status="cancelled", error="Interrupted", _checkpoints={"parser": {"domain": "social"}})
        payload["lifecycle"] = {"cancelled_at": "2026-09-14T00:00:00Z"}
        await db.save_run(payload)
        first = await main.resume_run("resume-test")
        second = await main.resume_run("resume-test")
        assert first["status"] == second["status"] == "pending"
        assert first["_checkpoints"] == payload["_checkpoints"]
        assert "cancelled_at" not in first["lifecycle"]
        assert manager.run_state("resume-test")["queue_position"] == 1
        assert first["error"] is None
    asyncio.run(scenario())
