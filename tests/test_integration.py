import asyncio
import sys
import time
from pathlib import Path

import pytest

from claude_pool.config import PoolConfig
from claude_pool.pool import WorkerPool
from claude_pool.server import create_app
from claude_pool.worker import Worker

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_claude_cli.py"


async def test_concurrent_requests_do_not_bleed_context(aiohttp_client, tmp_path):
    config = PoolConfig(
        min_workers=2,
        max_workers=4,
        scratch_dir=tmp_path,
        claude_cmd=[sys.executable, str(FAKE_CLI), "--fake-mode", "echo"],
    )
    pool = WorkerPool(config)
    await pool.start()
    app = create_app(pool)
    client = await aiohttp_client(app)

    prompts = [f"unique-prompt-{i}" for i in range(6)]
    responses = await asyncio.gather(
        *[client.post("/generate", json={"prompt": p}) for p in prompts]
    )
    bodies = await asyncio.gather(*[r.json() for r in responses])
    returned_texts = {b["text"] for b in bodies}
    assert returned_texts == set(prompts)


async def test_burst_scales_up_and_idle_scales_back_down(aiohttp_client, tmp_path):
    config = PoolConfig(
        min_workers=1,
        max_workers=4,
        scratch_dir=tmp_path,
        claude_cmd=[sys.executable, str(FAKE_CLI), "--fake-mode", "echo", "--fake-delay-sec", "0.3"],
        idle_timeout_sec=0.2,
        scale_down_interval_sec=0.1,
    )
    pool = WorkerPool(config)
    await pool.start()
    app = create_app(pool)
    client = await aiohttp_client(app)

    # NOTE: client.post(...) returns an unstarted awaitable — putting bare
    # calls in a list and later gathering them means nothing runs during an
    # intervening sleep (verified empirically: the server handler doesn't
    # fire until gather actually drives them). Wrap each in create_task so
    # all 4 are genuinely in flight before we sleep and inspect pool state.
    burst = [
        asyncio.create_task(client.post("/generate", json={"prompt": f"p{i}"}))
        for i in range(4)
    ]
    # give requests a moment to be admitted and trigger growth before they all finish.
    # Growth is one subprocess spawn per queued acquire (measured ~5-17ms each on this
    # machine, serialized), well under this budget and under fake-delay-sec=0.3, so
    # this reliably catches mid-flight growth without racing the burst to completion.
    await asyncio.sleep(0.2)
    assert pool.stats()["total"] > config.min_workers

    responses = await asyncio.gather(*burst)
    assert all(r.status == 200 for r in responses)

    # At this point release()'s below-min replenish logic will already have brought
    # total back down to min_workers on its own, whether or not the scale_down_loop
    # sweep works at all — organic acquire/release traffic here never leaves genuine
    # excess idle workers sitting around (matches the same discrimination gap found
    # in test_pool.py's test_scale_down_shrinks_idle_workers_back_to_min). To actually
    # prove the scale_down_loop running inside this live pool/server reaps excess idle
    # workers, seed some directly above min and confirm they get killed.
    assert pool.stats()["total"] == config.min_workers
    extras = [Worker(config), Worker(config)]
    for w in extras:
        w.became_idle_at = time.monotonic() - (config.idle_timeout_sec + 10.0)
        pool._idle.append(w)
    pool._total += len(extras)
    assert pool.stats()["total"] == config.min_workers + 2

    await asyncio.sleep(0.6)  # past idle_timeout_sec + scale_down_interval_sec
    assert pool.stats()["total"] == config.min_workers
    assert pool.stats()["idle"] == config.min_workers
