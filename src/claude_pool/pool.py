from __future__ import annotations

import asyncio
from collections import deque

from .config import PoolConfig
from .worker import Worker


class WorkerPool:
    def __init__(self, config: PoolConfig):
        self.config = config
        self._idle: deque[Worker] = deque()
        self._total = 0
        self._waiting = 0
        self._cond = asyncio.Condition()

    async def start(self) -> None:
        async with self._cond:
            for _ in range(self.config.min_workers):
                await self._spawn_and_add_idle_locked()

    async def _spawn_and_add_idle_locked(self) -> None:
        """Caller must hold self._cond."""
        worker = Worker(self.config)
        await worker.start()
        self._idle.append(worker)
        self._total += 1
        self._cond.notify()

    async def acquire(self) -> Worker:
        async with self._cond:
            if not self._idle and self._total < self.config.max_workers:
                asyncio.ensure_future(self._grow_by_one())
            if not self._idle:
                self._waiting += 1
                try:
                    while not self._idle:
                        await self._cond.wait()
                finally:
                    self._waiting -= 1
            return self._idle.popleft()

    async def _grow_by_one(self) -> None:
        async with self._cond:
            if self._total >= self.config.max_workers:
                return
            await self._spawn_and_add_idle_locked()

    async def release(self, worker: Worker) -> None:
        async with self._cond:
            self._total -= 1
            below_min = self._total < self.config.min_workers
            queued_demand = self._waiting > 0 and self._total < self.config.max_workers
            if below_min or queued_demand:
                await self._spawn_and_add_idle_locked()

    def stats(self) -> dict:
        busy = self._total - len(self._idle)
        return {
            "min_workers": self.config.min_workers,
            "max_workers": self.config.max_workers,
            "total": self._total,
            "idle": len(self._idle),
            "busy": busy,
        }
