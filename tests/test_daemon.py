import asyncio
import sys
from pathlib import Path

import pytest
from aiohttp import ClientSession

from claude_pool.config import PoolConfig
from claude_pool.daemon import run_daemon
from claude_pool.pool import WorkerPool

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_claude_cli.py"


async def _wait_until_healthy(session, port) -> None:
    for _ in range(50):
        try:
            async with session.get(f"http://127.0.0.1:{port}/health") as resp:
                if resp.status == 200:
                    return
        except Exception:
            pass
        await asyncio.sleep(0.1)
    pytest.fail("daemon never became healthy")


async def test_run_daemon_serves_generate_requests(tmp_path, unused_tcp_port):
    config = PoolConfig(
        min_workers=1,
        max_workers=2,
        host="127.0.0.1",
        port=unused_tcp_port,
        scratch_dir=tmp_path,
        claude_cmd=[sys.executable, str(FAKE_CLI), "--fake-mode", "echo"],
    )
    task = asyncio.ensure_future(run_daemon(config))
    try:
        async with ClientSession() as session:
            for _ in range(50):
                try:
                    async with session.get(f"http://127.0.0.1:{config.port}/health") as resp:
                        if resp.status == 200:
                            break
                except Exception:
                    pass
                await asyncio.sleep(0.1)
            else:
                pytest.fail("daemon never became healthy")

            async with session.post(
                f"http://127.0.0.1:{config.port}/generate", json={"prompt": "hi"}
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["text"] == "hi"
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def test_run_daemon_kills_pool_workers_on_shutdown(
    tmp_path, unused_tcp_port, monkeypatch
):
    pools: list[WorkerPool] = []

    class RecordingPool(WorkerPool):
        def __init__(self, config):
            super().__init__(config)
            pools.append(self)

    monkeypatch.setattr("claude_pool.daemon.WorkerPool", RecordingPool)
    config = PoolConfig(
        min_workers=2,
        max_workers=2,
        port=unused_tcp_port,
        scratch_dir=tmp_path,
        claude_cmd=[sys.executable, str(FAKE_CLI), "--fake-mode", "echo"],
    )
    task = asyncio.ensure_future(run_daemon(config))
    async with ClientSession() as session:
        await _wait_until_healthy(session, config.port)

    workers = list(pools[0]._idle)
    assert len(workers) == 2
    assert all(w.is_alive() for w in workers)

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert all(not w.is_alive() for w in workers)
