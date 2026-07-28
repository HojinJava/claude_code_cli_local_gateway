import os
from pathlib import Path

from claude_pool.config import PoolConfig


def test_defaults():
    config = PoolConfig()
    assert config.min_workers == 4
    assert config.max_workers == 30
    assert config.model == "sonnet"
    assert config.host == "127.0.0.1"
    assert config.port == 8756
    assert config.claude_cmd == ["claude"]


def test_from_env_reads_overrides(monkeypatch):
    monkeypatch.setenv("CLAUDE_POOL_MIN_WORKERS", "2")
    monkeypatch.setenv("CLAUDE_POOL_MAX_WORKERS", "8")
    monkeypatch.setenv("CLAUDE_POOL_PORT", "9999")
    monkeypatch.setenv("CLAUDE_POOL_CLAUDE_CMD_JSON", '["python", "fake.py"]')
    config = PoolConfig.from_env()
    assert config.min_workers == 2
    assert config.max_workers == 8
    assert config.port == 9999
    assert config.claude_cmd == ["python", "fake.py"]
