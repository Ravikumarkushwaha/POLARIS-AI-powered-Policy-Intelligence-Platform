from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent / "polaris.db"

_lock = asyncio.Lock()
_initialized = False
TERMINAL_STATUSES = {"complete", "error", "cancelled"}
ACTIVE_STATUSES = {"pending", "parsing", "retrieving_context", "analyzing", "synthesizing"}


async def _in_thread(function, *args):
    """Keep the DB lock until SQLite finishes, including during job cancellation."""
    operation = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(operation)
    except asyncio.CancelledError:
        await operation
        raise


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _init_sync() -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(runs)")}
        if "cache_key" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN cache_key TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS runs_cache_key ON runs(cache_key, updated_at)")
        conn.commit()
    finally:
        conn.close()


async def init_db() -> None:
    global _initialized
    async with _lock:
        if _initialized:
            return
        await _in_thread(_init_sync)
        _initialized = True


def _get_sync(run_id: str) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute("SELECT payload FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return json.loads(row["payload"])
    finally:
        conn.close()


def _save_sync(payload: dict[str, Any]) -> None:
    conn = _connect()
    try:
        encoded = json.dumps(payload)
        conn.execute(
            """
            INSERT INTO runs (run_id, payload, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(run_id) DO UPDATE SET
                payload = excluded.payload,
                updated_at = datetime('now')
            """,
            (payload["run_id"], encoded),
        )
        conn.commit()
    finally:
        conn.close()


def _list_incomplete_sync() -> list[str]:
    """Return runs that were interrupted while the backend was offline."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT run_id, payload FROM runs ORDER BY updated_at ASC"
        ).fetchall()
        incomplete: list[str] = []
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except (TypeError, json.JSONDecodeError):
                continue
            if payload.get("status") in ACTIVE_STATUSES:
                incomplete.append(str(row["run_id"]))
        return incomplete
    finally:
        conn.close()


def _list_runs_sync(limit: int, offset: int) -> tuple[int, list[dict[str, Any]]]:
    """Return newest runs with timestamps without exposing database details."""
    conn = _connect()
    try:
        total = int(conn.execute("SELECT COUNT(*) FROM runs WHERE json_extract(payload, '$._job_kind') IS NULL").fetchone()[0])
        rows = conn.execute(
            """
            SELECT payload, created_at, updated_at
            FROM runs
            WHERE json_extract(payload, '$._job_kind') IS NULL
            ORDER BY created_at DESC, updated_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except (TypeError, json.JSONDecodeError):
                continue
            items.append(
                {
                    "payload": payload,
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
        return total, items
    finally:
        conn.close()


async def get_run(run_id: str) -> dict[str, Any] | None:
    await init_db()
    async with _lock:
        return await _in_thread(_get_sync, run_id)


async def save_run(payload: dict[str, Any]) -> None:
    await init_db()
    async with _lock:
        await _in_thread(_save_sync, payload)


async def list_incomplete_runs() -> list[str]:
    await init_db()
    async with _lock:
        return await _in_thread(_list_incomplete_sync)


async def list_runs(limit: int = 100, offset: int = 0) -> tuple[int, list[dict[str, Any]]]:
    await init_db()
    async with _lock:
        return await _in_thread(_list_runs_sync, limit, offset)


async def patch_run(run_id: str, mutator, *, allow_cancelled: bool = False) -> dict[str, Any]:
    """Load, mutate, persist under the DB lock. mutator(payload) -> None."""
    await init_db()
    async with _lock:
        payload = await _in_thread(_get_sync, run_id)
        if payload is None:
            raise KeyError(run_id)
        if payload.get("status") == "cancelled" and not allow_cancelled:
            return payload
        mutator(payload)
        await _in_thread(_save_sync, payload)
        return payload


def _create_or_reuse_sync(
    payload: dict[str, Any], cache_key: str, ttl_seconds: int, force_refresh: bool,
) -> tuple[str, str | None]:
    conn = _connect()
    try:
        # The transaction and DB lock make concurrent identical submissions one job.
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            """SELECT run_id, payload,
                      (julianday('now') - julianday(updated_at)) * 86400 AS age_seconds
               FROM runs WHERE cache_key = ? ORDER BY updated_at DESC""",
            (cache_key,),
        ).fetchall()
        cached_id: str | None = None
        for row in rows:
            try:
                previous = json.loads(row["payload"])
            except (TypeError, json.JSONDecodeError):
                continue
            if previous.get("status") in ACTIVE_STATUSES:
                return str(row["run_id"]), "active"
            age = row["age_seconds"]
            if (
                not force_refresh and ttl_seconds > 0 and cached_id is None
                and previous.get("status") == "complete"
                and age is not None and 0 <= age <= ttl_seconds
            ):
                cached_id = str(row["run_id"])
        if cached_id:
            return cached_id, "cached"
        conn.execute(
            "INSERT INTO runs (run_id, payload, cache_key) VALUES (?, ?, ?)",
            (payload["run_id"], json.dumps(payload), cache_key),
        )
        conn.commit()
        return str(payload["run_id"]), None
    finally:
        conn.close()


async def create_or_reuse_run(
    payload: dict[str, Any], cache_key: str, ttl_seconds: int, force_refresh: bool = False,
) -> tuple[str, str | None]:
    await init_db()
    async with _lock:
        return await _in_thread(_create_or_reuse_sync, payload, cache_key, ttl_seconds, force_refresh)

def _related_sync(parent_run_id: str, kind: str) -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute("SELECT payload FROM runs WHERE json_extract(payload, '$.parent_run_id') = ? AND json_extract(payload, '$._job_kind') = ? ORDER BY created_at ASC, rowid ASC", (parent_run_id, kind)).fetchall()
        return [json.loads(row["payload"]) for row in rows]
    finally:
        conn.close()

async def related_jobs(parent_run_id: str, kind: str) -> list[dict]:
    await init_db()
    async with _lock:
        return await _in_thread(_related_sync, parent_run_id, kind)

def _delete_job_sync(run_id: str) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM runs WHERE run_id = ? AND json_extract(payload, '$._job_kind') = 'scenario'", (run_id,))
        conn.commit()
    finally:
        conn.close()

async def delete_scenario(run_id: str) -> None:
    await init_db()
    async with _lock:
        await _in_thread(_delete_job_sync, run_id)
