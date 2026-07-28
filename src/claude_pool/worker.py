from __future__ import annotations

import asyncio
import json
import time
from enum import Enum

from .config import PoolConfig


class WorkerState(Enum):
    STARTING = "starting"
    IDLE = "idle"
    BUSY = "busy"
    DONE = "done"


class WorkerError(Exception):
    """Raised when a worker process exits non-zero or returns unparsable output."""


class Worker:
    def __init__(self, config: PoolConfig):
        self.config = config
        self.state = WorkerState.STARTING
        self.became_idle_at: float = 0.0
        self._proc: asyncio.subprocess.Process | None = None

    def _build_argv(self) -> list[str]:
        return [
            *self.config.claude_cmd,
            "-p",
            "--input-format", "text",
            "--output-format", "json",
            "--no-session-persistence",
            "--tools", "",
            "--strict-mcp-config",
            "--safe-mode",
            "--model", self.config.model,
        ]

    async def start(self) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            *self._build_argv(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.config.scratch_dir),
        )
        self.state = WorkerState.IDLE
        self.became_idle_at = time.monotonic()

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def run(self, prompt: str, timeout_sec: float) -> dict:
        if self._proc is None:
            raise WorkerError("worker not started")
        self.state = WorkerState.BUSY
        try:
            stdout_data, stderr_data = await asyncio.wait_for(
                self._proc.communicate(input=prompt.encode("utf-8")),
                timeout=timeout_sec,
            )
        except asyncio.TimeoutError:
            await self.kill()
            raise
        finally:
            self.state = WorkerState.DONE

        if self._proc.returncode != 0:
            raise WorkerError(
                f"worker exited with code {self._proc.returncode}: "
                f"{stderr_data.decode('utf-8', errors='replace')}"
            )
        try:
            payload = json.loads(stdout_data.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise WorkerError(f"invalid worker output: {exc}") from exc
        return {
            "text": payload.get("result", ""),
            "duration_ms": payload.get("duration_ms", 0),
            "is_error": bool(payload.get("is_error", False)),
        }

    async def kill(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            self._proc.kill()
            await self._proc.wait()
        self.state = WorkerState.DONE
