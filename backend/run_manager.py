"""One durable FIFO of analyses, with cancellable work and restart recovery."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

import db


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunManager:
    def __init__(self, runner: Callable[[str], Awaitable[None]]):
        self.runner = runner
        self._queued: dict[str, None] = {}
        self._lock = asyncio.Lock()
        self._wake = asyncio.Event()
        self._worker: asyncio.Task | None = None
        self._active_task: asyncio.Task | None = None
        self._active_id: str | None = None
        self._stopping = False

    async def start(self) -> None:
        self._stopping = False
        await db.init_db()
        for run_id in await db.list_incomplete_runs():
            await self.enqueue(run_id, recovered=True)
        self._worker = asyncio.create_task(self._work(), name="polaris-analysis-queue")

    async def stop(self) -> None:
        self._stopping = True
        if self._worker:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
        # Pending and interrupted runs retain checkpoints for the next start.
        self._worker = None

    async def enqueue(self, run_id: str, *, recovered: bool = False) -> None:
        async with self._lock:
            if run_id in self._queued or run_id == self._active_id:
                return
            payload = await db.get_run(run_id)
            if payload is None or payload.get("status") in db.TERMINAL_STATUSES:
                return

            def queued(p: dict[str, Any]) -> None:
                p["status"] = "pending"
                lifecycle = p.setdefault("lifecycle", {})
                lifecycle.setdefault("queued_at", utc_now())
                if recovered:
                    lifecycle["recovered_at"] = utc_now()
                    telemetry = p.get("telemetry") or {}
                    telemetry.update(wait_until=None, wait_reason=None)
                    p["telemetry"] = telemetry

            await db.patch_run(run_id, queued)
            self._queued[run_id] = None
            self._wake.set()

    def run_state(self, run_id: str) -> dict[str, Any]:
        position = None
        if run_id == self._active_id:
            position = 0
        elif run_id in self._queued:
            position = list(self._queued).index(run_id) + 1
        return {"queue_position": position, "active": run_id == self._active_id}

    def snapshot(self) -> dict[str, Any]:
        return {"active_run_id": self._active_id, "queued_runs": len(self._queued), "concurrency": 1}

    async def cancel(self, run_id: str) -> dict[str, Any]:
        async with self._lock:
            payload = await db.get_run(run_id)
            if payload is None:
                raise KeyError(run_id)
            if payload.get("status") in db.TERMINAL_STATUSES:
                return payload
            self._queued.pop(run_id, None)
            def cancelled(p: dict[str, Any]) -> None:
                # A completed transaction wins if the last stage finished first.
                if p.get("status") in db.TERMINAL_STATUSES:
                    return
                p["status"] = "cancelled"
                p["error"] = None
                p.setdefault("lifecycle", {})["cancelled_at"] = utc_now()
                p["lifecycle"]["finished_at"] = utc_now()
                for key, state in p.get("stages", {}).items():
                    if state == "running":
                        p["stages"][key] = "cancelled"
                for agent in p.get("agents", {}).values():
                    if agent.get("status") == "running":
                        agent["status"] = "cancelled"
                if isinstance(p.get("telemetry"), dict):
                    p["telemetry"].update(wait_until=None, wait_reason=None, current_stage="cancelled")

            payload = await db.patch_run(run_id, cancelled)
            if self._active_id == run_id and self._active_task:
                self._active_task.cancel()
                await asyncio.gather(self._active_task, return_exceptions=True)
            return payload

    async def _execute_job(self, run_id: str) -> None:
        def started(p: dict[str, Any]) -> None:
            p.setdefault("lifecycle", {}).setdefault("started_at", utc_now())

        await db.patch_run(run_id, started)
        try:
            await self.runner(run_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Provider errors are handled by the pipeline; unexpected failures
            # must also leave a recoverable, visible terminal state.
            def failed(p: dict[str, Any]) -> None:
                p["status"] = "error"
                p["error"] = "Analysis interrupted by an unexpected error. You can retry this policy."
            await db.patch_run(run_id, failed)

        def finished(p: dict[str, Any]) -> None:
            if p.get("status") in db.TERMINAL_STATUSES:
                p.setdefault("lifecycle", {})["finished_at"] = utc_now()
                if p.get("status") == "complete":
                    p["lifecycle"]["completed_at"] = p["lifecycle"]["finished_at"]

        await db.patch_run(run_id, finished)

    async def _work(self) -> None:
        while True:
            await self._wake.wait()
            async with self._lock:
                if not self._queued:
                    self._wake.clear()
                    continue
                run_id = next(iter(self._queued))
                del self._queued[run_id]
                self._active_id = run_id
                task = asyncio.create_task(self._execute_job(run_id), name=f"analysis-{run_id}")
                self._active_task = task
            try:
                await task
            except asyncio.CancelledError:
                if self._stopping:
                    raise
            finally:
                async with self._lock:
                    self._active_id = None
                    self._active_task = None
