import asyncio
import json
import sys
import threading
import time
from pathlib import Path

import pytest

from claude_pool.client import ClaudePoolClient, ClaudePoolError
from claude_pool.config import PoolConfig
from claude_pool.daemon import run_daemon

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_claude_cli.py"


def _run_daemon_in_thread(config: PoolConfig) -> None:
    def target():
        asyncio.run(run_daemon(config))
    t = threading.Thread(target=target, daemon=True)
    t.start()


@pytest.fixture
def running_daemon(tmp_path, unused_tcp_port):
    config = PoolConfig(
        min_workers=1,
        max_workers=2,
        port=unused_tcp_port,
        scratch_dir=tmp_path,
        claude_cmd=[sys.executable, str(FAKE_CLI), "--fake-mode", "echo"],
    )
    _run_daemon_in_thread(config)
    deadline = time.monotonic() + 5.0
    client = ClaudePoolClient(port=config.port, auto_start=False)
    while time.monotonic() < deadline:
        try:
            client.health()
            break
        except Exception:
            time.sleep(0.1)
    return config.port


def test_client_generate_returns_text(running_daemon):
    client = ClaudePoolClient(port=running_daemon, auto_start=False)
    text = client.generate("hello there")
    assert text == "hello there"


def test_client_health_reports_stats(running_daemon):
    client = ClaudePoolClient(port=running_daemon, auto_start=False)
    stats = client.health()
    assert stats["min_workers"] == 1


def test_client_raises_on_missing_daemon_when_auto_start_disabled():
    with pytest.raises(Exception):
        ClaudePoolClient(port=1, auto_start=False).health()


def test_auto_start_passes_client_host_and_port_to_daemon(monkeypatch, unused_tcp_port):
    captured: dict = {}

    def fake_popen(argv, **kwargs):
        captured["argv"] = argv
        captured["env"] = kwargs["env"]
        raise _StopStartup

    monkeypatch.setattr("claude_pool.client.subprocess.Popen", fake_popen)
    with pytest.raises(_StopStartup):
        ClaudePoolClient(port=unused_tcp_port, auto_start=True, start_timeout_sec=0.1)

    assert captured["argv"][1:] == ["-m", "claude_pool.daemon"]
    assert captured["env"]["CLAUDE_POOL_PORT"] == str(unused_tcp_port)
    assert captured["env"]["CLAUDE_POOL_HOST"] == "127.0.0.1"


class _StopStartup(Exception):
    """Aborts __init__ right after the spawn so no daemon is actually launched."""
