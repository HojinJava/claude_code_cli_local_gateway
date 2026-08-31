from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time

from . import winjob
from .config import PoolConfig

# The daemon normally runs with no console of its own (the client starts it
# DETACHED_PROCESS). Spawning a console application from a console-less
# parent makes Windows allocate a fresh console for the child — and on
# Windows 11 that console is hosted by the default terminal app, so a
# terminal window pops open for every single worker. Measured: one visible
# WindowsTerminal window per spawn without this flag, zero with it. The
# worker's stdio is piped either way, so the console was never good for
# anything but flashing at the user.
CREATION_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class WorkerError(Exception):
    """Raised when a worker process exits non-zero or returns unparsable output."""


class Worker:
    def __init__(self, config: PoolConfig, job: object | None = None):
        self.config = config
        self.job = job
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
            creationflags=CREATION_FLAGS,
        )
        # Kernel-enforced: if the daemon process dies for any reason
        # (crash, kill -9, power loss) before it gets a chance to run
        # WorkerPool.stop(), Windows itself terminates this process when
        # the job's last handle closes.
        winjob.assign_process_to_job(self.job, self._proc.pid)
        self.became_idle_at = time.monotonic()

    def is_alive(self) -> bool:
        """Best-effort liveness, not a guarantee.

        `returncode` only flips once asyncio has reaped the child, so a
        process that has just died still reports alive for a short window —
        measured: a CLI that exits ~150ms after spawn is still handed out.
        Callers must therefore treat a handed-out worker as possibly dead and
        rely on run() surfacing its exit code and stderr; this check only
        keeps *known*-dead workers out of circulation.
        """
        return self._proc is not None and self._proc.returncode is None

    async def run(self, prompt: str, timeout_sec: float) -> dict:
        if self._proc is None:
            raise WorkerError("worker not started")
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

        if self._proc.returncode != 0:
            raise WorkerError(
                f"worker exited with code {self._proc.returncode}: "
                f"{stderr_data.decode('utf-8', errors='replace')}"
            )

        result_line = None
        # errors="replace" so a stray non-UTF-8 byte surfaces as a WorkerError
        # the server can classify, not a UnicodeDecodeError that becomes a 500.
        for line in stdout_data.decode("utf-8", errors="replace").splitlines():
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
            "subtype": result_line.get("subtype", ""),
        }

    async def kill(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            self._proc.kill()
            await self._proc.wait()
