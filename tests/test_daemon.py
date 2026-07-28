import asyncio
import sys
from pathlib import Path

import pytest
from aiohttp import ClientSession

from claude_pool.config import PoolConfig
from claude_pool.daemon import run_daemon

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_claude_cli.py"


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
