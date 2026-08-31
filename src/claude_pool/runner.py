"""One prompt, start to finish: acquire a worker, run it, retire it.

Shared by the blocking `POST /generate` and the background job runner, so
both spend a worker the same way — in particular, both retire it through
`release_in_background`, which is the only thing standing between a
cancelled caller and an orphaned `claude` process.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .errors import Failure, classify
from .pool import PoolUnavailableError, WorkerPool
from .worker import WorkerError


@dataclass(frozen=True)
class Outcome:
    """The result of one run, transport-agnostic."""

    succeeded: bool
    text: str = ""
    duration_ms: int = 0
    error: str = ""
    failure: Failure | None = None

    @classmethod
    def ok(cls, text: str, duration_ms: int) -> "Outcome":
        return cls(succeeded=True, text=text, duration_ms=duration_ms)

    @classmethod
    def failed(cls, error: str, failure: Failure, duration_ms: int = 0) -> "Outcome":
        return cls(succeeded=False, error=error, failure=failure, duration_ms=duration_ms)


async def execute(pool: WorkerPool, prompt: str, timeout_sec: float) -> Outcome:
    """Run one prompt on a pooled worker. Records the outcome on the pool so
    /health can explain a daemon that looks healthy but is not answering."""
    try:
        worker = await pool.acquire()
    except PoolUnavailableError as exc:
        # Queue pressure, not a broken pool: the same request works once a
        # worker frees up, so say so rather than leaving the caller to guess.
        return _note(pool, Outcome.failed(
            str(exc), Failure("pool_unavailable", 503, retryable=True)
        ))

    try:
        result = await worker.run(prompt, timeout_sec=timeout_sec)
    except asyncio.TimeoutError:
        return _note(pool, Outcome.failed(
            "worker timed out", Failure("timeout", 504, retryable=True)
        ))
    except WorkerError as exc:
        return _note(pool, Outcome.failed(str(exc), classify(str(exc))))
    finally:
        # Detached and shielded so that cancelling this call (client
        # disconnect, job cancellation, shutdown) still runs the release —
        # and therefore the worker kill — under the pool's own task tracking.
        await asyncio.shield(pool.release_in_background(worker))

    if result["is_error"]:
        return _note(pool, Outcome.failed(
            result["text"], classify(result["text"]), result["duration_ms"]
        ))
    return _note(pool, Outcome.ok(result["text"], result["duration_ms"]))


def _note(pool: WorkerPool, outcome: Outcome) -> Outcome:
    if outcome.succeeded:
        pool.note_success()
    else:
        pool.note_failure(outcome.error)
    return outcome
