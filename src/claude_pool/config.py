from __future__ import annotations

import ipaddress
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

LOOPBACK_HOST_NAMES = frozenset({"localhost"})


def is_loopback_host(host: str) -> bool:
    if host in LOOPBACK_HOST_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass
class PoolConfig:
    min_workers: int = 4
    max_workers: int = 30
    model: str = "sonnet"
    host: str = "127.0.0.1"
    port: int = 8756
    default_timeout_sec: float = 120.0
    acquire_timeout_sec: float = 60.0
    idle_timeout_sec: float = 60.0
    scale_down_interval_sec: float = 30.0
    # Background jobs: how long a finished job stays readable, and a hard cap
    # so a caller that never collects results cannot grow the store forever.
    job_retention_sec: float = 600.0
    max_jobs: int = 500
    scratch_dir: Path = field(
        default_factory=lambda: Path.home() / ".claude-pool" / "scratch"
    )
    claude_cmd: list[str] = field(default_factory=lambda: ["claude"])

    def __post_init__(self) -> None:
        # The API has no auth layer by design; that is only safe while the
        # daemon is unreachable from off-host. Fail loudly rather than coerce.
        if not is_loopback_host(self.host):
            raise ValueError(
                f"host must be a loopback address (e.g. 127.0.0.1, localhost, ::1), "
                f"got {self.host!r}: claude-pool exposes an unauthenticated API and "
                f"must not be bound off-loopback"
            )
        # Splatted straight into argv, so a bare string would be spread one
        # character per argument instead of failing. Reject it at the boundary.
        if not isinstance(self.claude_cmd, list) or not self.claude_cmd:
            raise ValueError(
                f"claude_cmd must be a non-empty list of strings, got {self.claude_cmd!r}"
            )
        if not all(isinstance(part, str) for part in self.claude_cmd):
            raise ValueError(
                f"claude_cmd must contain only strings, got {self.claude_cmd!r}"
            )

    @classmethod
    def from_env(cls) -> "PoolConfig":
        claude_cmd_json = os.environ.get("CLAUDE_POOL_CLAUDE_CMD_JSON")
        if claude_cmd_json:
            try:
                claude_cmd = json.loads(claude_cmd_json)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"CLAUDE_POOL_CLAUDE_CMD_JSON is not valid JSON: {exc}"
                ) from exc
        else:
            claude_cmd = ["claude"]

        scratch_dir_env = os.environ.get("CLAUDE_POOL_SCRATCH_DIR")
        scratch_dir = (
            Path(scratch_dir_env)
            if scratch_dir_env
            else Path.home() / ".claude-pool" / "scratch"
        )

        return cls(
            min_workers=int(os.environ.get("CLAUDE_POOL_MIN_WORKERS", 4)),
            max_workers=int(os.environ.get("CLAUDE_POOL_MAX_WORKERS", 30)),
            model=os.environ.get("CLAUDE_POOL_MODEL", "sonnet"),
            host=os.environ.get("CLAUDE_POOL_HOST", "127.0.0.1"),
            port=int(os.environ.get("CLAUDE_POOL_PORT", 8756)),
            default_timeout_sec=float(os.environ.get("CLAUDE_POOL_TIMEOUT_SEC", 120.0)),
            acquire_timeout_sec=float(
                os.environ.get("CLAUDE_POOL_ACQUIRE_TIMEOUT_SEC", 60.0)
            ),
            idle_timeout_sec=float(os.environ.get("CLAUDE_POOL_IDLE_TIMEOUT_SEC", 60.0)),
            scale_down_interval_sec=float(
                os.environ.get("CLAUDE_POOL_SCALE_DOWN_INTERVAL_SEC", 30.0)
            ),
            job_retention_sec=float(
                os.environ.get("CLAUDE_POOL_JOB_RETENTION_SEC", 600.0)
            ),
            max_jobs=int(os.environ.get("CLAUDE_POOL_MAX_JOBS", 500)),
            scratch_dir=scratch_dir,
            claude_cmd=claude_cmd,
        )
