import asyncio
import sys
from pathlib import Path

import pytest

from claude_pool.config import PoolConfig
from claude_pool.worker import Worker, WorkerError

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_claude_cli.py"


def make_config(tmp_path, *fake_args, **overrides):
    defaults = dict(
        scratch_dir=tmp_path,
        claude_cmd=[sys.executable, str(FAKE_CLI), *fake_args],
    )
    defaults.update(overrides)
    return PoolConfig(**defaults)


async def test_start_leaves_worker_alive_and_timestamped(tmp_path):
    worker = Worker(make_config(tmp_path, "--fake-mode", "echo"))
    await worker.start()
    try:
        assert worker.is_alive()
        assert worker.became_idle_at > 0
    finally:
        await worker.kill()


async def test_run_returns_parsed_result(tmp_path):
    worker = Worker(make_config(tmp_path, "--fake-mode", "echo"))
    await worker.start()
    result = await worker.run("hello", timeout_sec=5.0)
    assert result == {
        "text": "hello", "duration_ms": 1, "is_error": False, "subtype": "",
    }
    assert not worker.is_alive()


async def test_run_raises_on_error_flagged_result(tmp_path):
    worker = Worker(make_config(tmp_path, "--fake-mode", "error"))
    await worker.start()
    result = await worker.run("hello", timeout_sec=5.0)
    assert result["is_error"] is True


async def test_run_raises_worker_error_on_crash(tmp_path):
    worker = Worker(make_config(tmp_path, "--fake-mode", "crash"))
    await worker.start()
    with pytest.raises(WorkerError):
        await worker.run("hello", timeout_sec=5.0)


async def test_run_raises_timeout_and_kills_process(tmp_path):
    worker = Worker(make_config(tmp_path, "--fake-delay-sec", "5.0"))
    await worker.start()
    with pytest.raises(asyncio.TimeoutError):
        await worker.run("hello", timeout_sec=0.2)
    assert not worker.is_alive()


async def test_build_argv_uses_stream_json_protocol(tmp_path):
    worker = Worker(make_config(tmp_path, "--fake-mode", "echo"))
    argv = worker._build_argv()
    assert "--input-format" in argv
    assert argv[argv.index("--input-format") + 1] == "stream-json"
    assert "--output-format" in argv
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in argv



async def test_kill_is_idempotent(tmp_path):
    worker = Worker(make_config(tmp_path, "--fake-mode", "echo"))
    await worker.start()
    await worker.kill()
    await worker.kill()
    assert not worker.is_alive()


async def test_kill_before_start_is_a_no_op(tmp_path):
    await Worker(make_config(tmp_path)).kill()


async def test_worker_spawns_without_allocating_a_console_window(tmp_path, monkeypatch):
    # The daemon runs console-less, so without CREATE_NO_WINDOW Windows gives
    # every worker a fresh console — which the default terminal app renders as
    # a real window. Measured before the flag: one window per spawn.
    captured = {}
    real = asyncio.create_subprocess_exec

    async def spy(*args, **kwargs):
        captured.update(kwargs)
        return await real(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy)
    worker = Worker(make_config(tmp_path, "--fake-mode", "echo"))
    await worker.start()
    try:
        assert "creationflags" in captured
        if sys.platform == "win32":
            import subprocess
            assert captured["creationflags"] & subprocess.CREATE_NO_WINDOW
        else:
            # Popen rejects a non-zero creationflags off Windows.
            assert captured["creationflags"] == 0
    finally:
        await worker.kill()
