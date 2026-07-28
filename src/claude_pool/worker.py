from __future__ import annotations

import asyncio
import json
import time
from enum import Enum

from . import winjob
from .config import PoolConfig


class WorkerState(Enum):
    STARTING = "starting"
    IDLE = "idle"
    BUSY = "busy"
    DONE = "done"


class WorkerError(Exception):
    """Raised when a worker process exits non-zero or returns unparsable output."""


class Worker:
    def __init__(self, config: PoolConfig, job: object | None = None):
        self.config = config
        self.job = job
        self.state = WorkerState.STARTING
        self.became_idle_at: float = 0.0
        self._proc: asyncio.subprocess.Process | None = None

    def _build_argv(self) -> list[str]:
        return [
            *self.config.claude_cmd,
            "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
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
        # Kernel-enforced: if the daemon process dies for any reason
        # (crash, kill -9, power loss) before it gets a chance to run
        # WorkerPool.stop(), Windows itself terminates this process when
        # the job's last handle closes.
        winjob.assign_process_to_job(self.job, self._proc.pid)
        self.state = WorkerState.IDLE
        self.became_idle_at = time.monotonic()

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def run(self, prompt: str, timeout_sec: float) -> dict:
        if self._proc is None:
            raise WorkerError("worker not started")
        self.state = WorkerState.BUSY
        message = json.dumps({
            "type": "user",
            "message": {"role": "user", "content": prompt},
        }) + "\n"
        try:
            stdout_data, stderr_data = await asyncio.wait_for(
                self._proc.communicate(input=message.encode("utf-8")),
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

        result_line = None
        for line in stdout_data.decode("utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("type") == "result":
                result_line = payload
                break

        if result_line is None:
            raise WorkerError("no 'result' line found in worker stream-json output")

        return {
            "text": result_line.get("result", ""),
            "duration_ms": result_line.get("duration_ms", 0),
            "is_error": bool(result_line.get("is_error", False)),
        }

    async def kill(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            self._proc.kill()
            await self._proc.wait()
        self.state = WorkerState.DONE
