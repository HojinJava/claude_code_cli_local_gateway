from __future__ import annotations

import asyncio
import time
from collections import deque

from . import winjob
from .config import PoolConfig
from .worker import Worker

STOP_DRAIN_TIMEOUT_SEC = 5.0


class PoolUnavailableError(Exception):
    """Raised when the pool cannot hand out a worker (spawn failure or timeout)."""


class WorkerPool:
    def __init__(self, config: PoolConfig):
        self.config = config
        # Kill-on-close job: even if this daemon process is killed outright
        # with no chance to run stop(), Windows terminates every worker
        # assigned to this job the moment its last handle closes. None on
        # non-Windows platforms (no-op there).
        self._job = winjob.create_kill_on_close_job()
        self._idle: deque[Worker] = deque()
        self._total = 0
        self._waiting = 0
        self._cond = asyncio.Condition()
        self._last_spawn_error: BaseException | None = None
        # Last request failure, kept so /health can report *why* a
        # healthy-looking pool is not answering (expired login, rate limit)
        # instead of only how many workers it has counted.
        self._last_error: str | None = None
        self._pending_grows = 0
        self._scale_down_task: asyncio.Task | None = None
        self._background_tasks: set[asyncio.Task] = set()
        self._stopped = False

    async def start(self) -> None:
        async with self._cond:
            for _ in range(self.config.min_workers):
                await self._spawn_and_add_idle_locked()
        self._scale_down_task = asyncio.ensure_future(self._scale_down_loop())

    async def stop(self) -> None:
        """Shut the pool down: stop the scale-down sweep and kill idle workers.

        Busy workers are deliberately left alone — they belong to in-flight
        requests, whose release() kills them on the way out.
        """
        self._stopped = True
        if self._scale_down_task is not None:
            self._scale_down_task.cancel()
            try:
                await self._scale_down_task
            except asyncio.CancelledError:
                pass
            self._scale_down_task = None

        # Let in-flight spawns and releases land so their workers get killed
        # below rather than orphaned by a mid-exec cancellation.
        pending = list(self._background_tasks)
        if pending:
            await asyncio.wait(pending, timeout=STOP_DRAIN_TIMEOUT_SEC)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

        async with self._cond:
            doomed = list(self._idle)
            self._idle.clear()
            # Waiters can never be satisfied now, so wake them to fail fast
            # instead of sitting out their full acquire timeout.
            self._cond.notify_all()
        for worker in doomed:
            # Decrement per worker so an interrupted shutdown leaves the count
            # matching the processes actually killed.
            await worker.kill()
            async with self._cond:
                self._total -= 1

    async def _spawn_and_add_idle_locked(self) -> None:
        """Caller must hold self._cond."""
        worker = Worker(self.config, job=self._job)
        await worker.start()
        self._idle.append(worker)
        self._total += 1
        self._last_spawn_error = None
        self._cond.notify()

    async def _try_spawn_and_add_idle_locked(self) -> bool:
        """Spawn without ever raising. Caller must hold self._cond.

        A failed spawn still notifies so no acquire() waiter is left blocked
        with nothing to wake it; the recorded error makes them fail fast.
        """
        try:
            await self._spawn_and_add_idle_locked()
        except Exception as exc:
            self._last_spawn_error = exc
            self._cond.notify()
            return False
        return True

    def note_failure(self, error: str) -> None:
        self._last_error = error

    def note_success(self) -> None:
        self._last_error = None

    def _track(self, task: asyncio.Task) -> asyncio.Task:
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    def _schedule_grow(self) -> None:
        self._pending_grows += 1
        self._track(asyncio.ensure_future(self._grow_by_one()))

    async def acquire(self) -> Worker:
        try:
            return await asyncio.wait_for(
                self._acquire(), timeout=self.config.acquire_timeout_sec
            )
        except asyncio.TimeoutError as exc:
            raise PoolUnavailableError(
                f"no worker available within {self.config.acquire_timeout_sec}s"
            ) from exc

    async def _acquire(self) -> Worker:
        async with self._cond:
            while True:
                if self._stopped:
                    raise PoolUnavailableError("pool is shutting down")

                while self._idle:
                    worker = self._idle.popleft()
                    if worker.is_alive():
                        return worker
                    # Idle workers can die on their own, so drop the ones
                    # already known to be dead. This is a filter, not a
                    # guarantee — see Worker.is_alive(): a worker that died
                    # moments ago still reports alive and will be handed out,
                    # and run() is what surfaces its exit code and stderr.
                    self._total -= 1
                    await worker.kill()

                if self._total < self.config.max_workers:
                    self._schedule_grow()

                self._waiting += 1
                try:
                    await self._cond.wait()
                finally:
                    self._waiting -= 1

                # Only give up once no other spawn is still in flight — another
                # waiter's grow may yet succeed and satisfy this caller.
                if (
                    not self._idle
                    and self._pending_grows == 0
                    and self._last_spawn_error is not None
                ):
                    raise PoolUnavailableError(
                        f"worker spawn failed: {self._last_spawn_error}"
                    ) from self._last_spawn_error

    async def _grow_by_one(self) -> None:
        try:
            async with self._cond:
                if self._total >= self.config.max_workers or self._stopped:
                    return
                await self._try_spawn_and_add_idle_locked()
        finally:
            # Runs before this task yields again, so a waiter woken by the
            # notify above already sees the updated count.
            self._pending_grows -= 1

    def release_in_background(self, worker: Worker) -> asyncio.Task:
        """Release as a tracked task, so a cancelled caller cannot abandon it
        and stop() waits for it before declaring the pool drained."""
        return self._track(asyncio.ensure_future(self.release(worker)))

    async def release(self, worker: Worker) -> None:
        # Every worker is one-shot and dead-or-dying by now. Killing here
        # covers every exit path — success, error, timeout, and the client
        # disconnect that cancels the handler mid-run — so no `claude`
        # subprocess is ever orphaned with nowhere to send its answer.
        await worker.kill()
        async with self._cond:
            self._total -= 1
            below_min = self._total < self.config.min_workers
            queued_demand = self._waiting > 0 and self._total < self.config.max_workers
            if (below_min or queued_demand) and not self._stopped:
                # Must not raise: this runs in the caller's finally block, where
                # an exception would turn an already-computed response into a 500.
                await self._try_spawn_and_add_idle_locked()

    async def _scale_down_loop(self) -> None:
        while True:
            await asyncio.sleep(self.config.scale_down_interval_sec)
            async with self._cond:
                now = time.monotonic()
                excess_allowed = max(0, len(self._idle) - self.config.min_workers)
                survivors: deque[Worker] = deque()
                to_kill: list[Worker] = []
                for w in self._idle:
                    if (
                        len(to_kill) < excess_allowed
                        and (now - w.became_idle_at) > self.config.idle_timeout_sec
                    ):
                        to_kill.append(w)
                    else:
                        survivors.append(w)
                self._idle = survivors
            for w in to_kill:
                # Per-worker decrement so cancelling this sweep (stop() does)
                # can't leave workers counted as gone but never killed.
                await w.kill()
                async with self._cond:
                    self._total -= 1

    def stats(self) -> dict:
        """Pool state for /health.

        `idle` is a counter; `idle_alive` is a liveness probe. They diverge
        exactly when the pool is holding pre-warmed workers whose `claude`
        process has already died — a logged-out CLI, an exhausted quota, a
        bad flag — which is the case a counters-only health check reported
        as perfectly healthy.
        """
        idle_alive = sum(1 for w in self._idle if w.is_alive())
        return {
            "min_workers": self.config.min_workers,
            "max_workers": self.config.max_workers,
            "total": self._total,
            "idle": len(self._idle),
            "idle_alive": idle_alive,
            "busy": self._total - len(self._idle),
            # True when every worker the pool is counting as idle really is
            # one. Vacuously true for an empty pool (min_workers=0 spawns on
            # demand), false exactly when pre-warmed workers have died under it.
            "healthy": idle_alive == len(self._idle),
            "last_spawn_error": (
                str(self._last_spawn_error) if self._last_spawn_error else None
            ),
            "last_error": self._last_error,
        }
