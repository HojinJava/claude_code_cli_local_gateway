import asyncio
import sys
from pathlib import Path

import pytest

from claude_pool.config import PoolConfig
from claude_pool.worker import Worker, WorkerError, WorkerState

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_claude_cli.py"


def make_config(tmp_path, *fake_args, **overrides):
    defaults = dict(
        scratch_dir=tmp_path,
        claude_cmd=[sys.executable, str(FAKE_CLI), *fake_args],
    )
    defaults.update(overrides)
    return PoolConfig(**defaults)


async def test_start_puts_worker_in_idle_state(tmp_path):
    worker = Worker(make_config(tmp_path, "--fake-mode", "echo"))
    await worker.start()
    try:
        assert worker.state == WorkerState.IDLE
        assert worker.is_alive()
        assert worker.became_idle_at > 0
    finally:
        await worker.kill()


async def test_run_returns_parsed_result(tmp_path):
    worker = Worker(make_config(tmp_path, "--fake-mode", "echo"))
    await worker.start()
    result = await worker.run("hello", timeout_sec=5.0)
    assert result == {"text": "hello", "duration_ms": 1, "is_error": False}
    assert worker.state == WorkerState.DONE
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
