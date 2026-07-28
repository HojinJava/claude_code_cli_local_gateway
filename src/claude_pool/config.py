from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PoolConfig:
    min_workers: int = 4
    max_workers: int = 30
    model: str = "sonnet"
    host: str = "127.0.0.1"
    port: int = 8756
    default_timeout_sec: float = 120.0
    idle_timeout_sec: float = 60.0
    scale_down_interval_sec: float = 30.0
    scratch_dir: Path = field(
        default_factory=lambda: Path.home() / ".claude-pool" / "scratch"
    )
    claude_cmd: list[str] = field(default_factory=lambda: ["claude"])

    @classmethod
    def from_env(cls) -> "PoolConfig":
        claude_cmd_json = os.environ.get("CLAUDE_POOL_CLAUDE_CMD_JSON")
        claude_cmd = json.loads(claude_cmd_json) if claude_cmd_json else ["claude"]
        return cls(
            min_workers=int(os.environ.get("CLAUDE_POOL_MIN_WORKERS", 4)),
            max_workers=int(os.environ.get("CLAUDE_POOL_MAX_WORKERS", 30)),
            model=os.environ.get("CLAUDE_POOL_MODEL", "sonnet"),
            host=os.environ.get("CLAUDE_POOL_HOST", "127.0.0.1"),
            port=int(os.environ.get("CLAUDE_POOL_PORT", 8756)),
            default_timeout_sec=float(os.environ.get("CLAUDE_POOL_TIMEOUT_SEC", 120.0)),
            idle_timeout_sec=float(os.environ.get("CLAUDE_POOL_IDLE_TIMEOUT_SEC", 60.0)),
            scale_down_interval_sec=float(
                os.environ.get("CLAUDE_POOL_SCALE_DOWN_INTERVAL_SEC", 30.0)
            ),
            claude_cmd=claude_cmd,
        )
