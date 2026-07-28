import asyncio
import sys
from pathlib import Path

from claude_pool.config import PoolConfig
from claude_pool.pool import WorkerPool

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_claude_cli.py"


def make_config(tmp_path, **overrides):
    defaults = dict(
        min_workers=2,
        max_workers=4,
        scratch_dir=tmp_path,
        claude_cmd=[sys.executable, str(FAKE_CLI), "--fake-mode", "echo"],
        idle_timeout_sec=0.2,
        scale_down_interval_sec=0.1,
    )
    defaults.update(overrides)
    return PoolConfig(**defaults)


async def test_start_primes_min_workers(tmp_path):
    pool = WorkerPool(make_config(tmp_path))
    await pool.start()
    stats = pool.stats()
    assert stats["total"] == 2
    assert stats["idle"] == 2
    assert stats["busy"] == 0


async def test_acquire_and_release_serves_one_request_then_replenishes(tmp_path):
    pool = WorkerPool(make_config(tmp_path))
    await pool.start()

    worker = await pool.acquire()
    assert pool.stats()["busy"] == 1
    result = await worker.run("hi", timeout_sec=5.0)
    assert result["text"] == "hi"
    await pool.release(worker)

    stats = pool.stats()
    assert stats["total"] == 2  # replenished back to min_workers
    assert stats["busy"] == 0


async def test_acquire_beyond_idle_capacity_grows_and_waits(tmp_path):
    pool = WorkerPool(make_config(tmp_path, min_workers=1, max_workers=3))
    await pool.start()

    w1 = await pool.acquire()  # consumes the only idle worker, triggers growth
    w2 = await pool.acquire()  # should be satisfied by the grown worker
    assert pool.stats()["total"] <= 3
    assert pool.stats()["busy"] == 2

    await pool.release(w1)
    await pool.release(w2)


async def test_acquire_never_exceeds_max_workers(tmp_path):
    pool = WorkerPool(make_config(tmp_path, min_workers=1, max_workers=2))
    await pool.start()

    acquired = [await pool.acquire(), await pool.acquire()]
    assert pool.stats()["total"] == 2

    # a third acquire must wait — prove it doesn't exceed max by racing
    # it against a short timeout and confirming it hasn't resolved yet
    third = asyncio.ensure_future(pool.acquire())
    await asyncio.sleep(0.1)
    assert not third.done()
    assert pool.stats()["total"] == 2

    await pool.release(acquired[0])
    worker3 = await asyncio.wait_for(third, timeout=5.0)
    await pool.release(worker3)
    await pool.release(acquired[1])
