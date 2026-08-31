"""Background jobs: hand the prompt over and collect the answer later.

`POST /generate` holds the HTTP connection for the whole completion, which
can be minutes. A caller that would rather not sit on an open socket — a
script firing a batch, an agent that must not block its shell — submits the
same prompt to `POST /jobs`, gets an id back immediately, and polls
`GET /jobs/{id}`.

The worker lifecycle is identical either way: one prompt, one worker,
retired on the way out. The only difference is who waits.
"""
from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass, field

from .errors import Failure
from .pool import WorkerPool
from .runner import Outcome, execute

RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
CANCELLED = "cancelled"

TERMINAL_STATUSES = frozenset({SUCCEEDED, FAILED, CANCELLED})

# Enough of the prompt to tell jobs apart in a listing without holding whole
# prompts in memory for the retention window.
PROMPT_PREVIEW_CHARS = 80


@dataclass
class Job:
    id: str
    prompt_preview: str
    timeout_sec: float
    status: str = RUNNING
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    text: str = ""
    duration_ms: int = 0
    error: str = ""
    failure: Failure | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def to_dict(self) -> dict:
        body = {
            "job_id": self.id,
            "status": self.status,
            "prompt_preview": self.prompt_preview,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }
        if self.status == SUCCEEDED:
            body["text"] = self.text
            body["duration_ms"] = self.duration_ms
        elif self.status == FAILED:
            body["error"] = self.error
            body["kind"] = self.failure.kind if self.failure else "worker_failed"
            body["retryable"] = bool(self.failure and self.failure.retryable)
            if self.failure and self.failure.retry_after_sec is not None:
                body["retry_after_sec"] = self.failure.retry_after_sec
            if self.duration_ms:
                body["duration_ms"] = self.duration_ms
        return body


class JobStore:
    """Runs submitted prompts in the background and keeps their results.

    Finished jobs are reaped on submit rather than by a sweep task: the store
    only grows when someone submits, so that is the only moment it can need
    trimming, and it saves a second background loop to shut down cleanly.
    """

    def __init__(self, pool: WorkerPool, retention_sec: float, max_jobs: int):
        self._pool = pool
        self._retention_sec = retention_sec
        self._max_jobs = max_jobs
        self._jobs: dict[str, Job] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    def submit(self, prompt: str, timeout_sec: float) -> Job:
        self._reap()
        job = Job(
            # Unguessable rather than sequential: the daemon has no auth
            # layer, so an id must not be something another local process
            # can enumerate to read someone else's completion.
            id=secrets.token_urlsafe(12),
            prompt_preview=prompt[:PROMPT_PREVIEW_CHARS],
            timeout_sec=timeout_sec,
        )
        self._jobs[job.id] = job
        task = asyncio.ensure_future(self._run(job, prompt, timeout_sec))
        self._tasks[job.id] = task
        task.add_done_callback(lambda _t, jid=job.id: self._tasks.pop(jid, None))
        return job

    async def _run(self, job: Job, prompt: str, timeout_sec: float) -> None:
        try:
            outcome = await execute(self._pool, prompt, timeout_sec)
        except asyncio.CancelledError:
            self._finish(job, CANCELLED, error="cancelled")
            raise
        except Exception as exc:
            # A job task has no caller to raise into, so an unexpected error
            # must land on the job instead of vanishing into a dead task.
            self._finish(
                job, FAILED,
                error=f"unexpected error: {exc!r}",
                failure=Failure("worker_failed", 502, retryable=False),
            )
        else:
            if outcome.succeeded:
                self._finish(job, SUCCEEDED, text=outcome.text,
                             duration_ms=outcome.duration_ms)
            else:
                self._finish(job, FAILED, error=outcome.error,
                             failure=outcome.failure, duration_ms=outcome.duration_ms)

    @staticmethod
    def _finish(job: Job, status: str, **fields) -> None:
        job.status = status
        job.finished_at = time.time()
        for key, value in fields.items():
            setattr(job, key, value)

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        self._reap()
        return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    async def cancel(self, job_id: str) -> Job | None:
        """Cancel a running job, or forget a finished one."""
        job = self._jobs.get(job_id)
        if job is None:
            return None
        task = self._tasks.get(job_id)
        if task is not None and not task.done():
            task.cancel()
            # Await it so the worker is actually killed before we answer;
            # otherwise "cancelled" would be a claim, not a fact.
            await asyncio.gather(task, return_exceptions=True)
        elif not job.is_terminal:
            self._finish(job, CANCELLED, error="cancelled")
        return job

    async def shutdown(self) -> None:
        """Cancel every running job so no worker outlives the daemon."""
        tasks = [t for t in self._tasks.values() if not t.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _reap(self) -> None:
        now = time.time()
        for job_id, job in list(self._jobs.items()):
            if (
                job.is_terminal
                and job.finished_at is not None
                and now - job.finished_at > self._retention_sec
            ):
                del self._jobs[job_id]

        # A caller that submits and never collects would otherwise grow the
        # store without bound inside the retention window. Running jobs are
        # never dropped — their results still have somewhere to land.
        finished = sorted(
            (j for j in self._jobs.values() if j.is_terminal),
            key=lambda j: j.finished_at or 0.0,
        )
        overflow = len(self._jobs) - self._max_jobs
        for job in finished[:max(0, overflow)]:
            del self._jobs[job.id]

    def stats(self) -> dict:
        running = sum(1 for j in self._jobs.values() if j.status == RUNNING)
        return {"total": len(self._jobs), "running": running}
