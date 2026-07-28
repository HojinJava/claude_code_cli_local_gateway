import asyncio
import sys
import time
from pathlib import Path

import pytest

from claude_pool.config import PoolConfig
from claude_pool.pool import PoolUnavailableError, WorkerPool
from claude_pool.worker import Worker, WorkerState

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_claude_cli.py"
MISSING_BINARY = ["claude-pool-no-such-binary-xyz"]


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


async def test_start_primes_min_workers(tmp_path, make_pool):
    pool = make_pool(make_config(tmp_path))
    await pool.start()
    stats = pool.stats()
    assert stats["total"] == 2
    assert stats["idle"] == 2
    assert stats["busy"] == 0


async def test_acquire_and_release_serves_one_request_then_replenishes(tmp_path, make_pool):
    pool = make_pool(make_config(tmp_path))
    await pool.start()

    worker = await pool.acquire()
    assert pool.stats()["busy"] == 1
    result = await worker.run("hi", timeout_sec=5.0)
    assert result["text"] == "hi"
    await pool.release(worker)

    stats = pool.stats()
    assert stats["total"] == 2  # replenished back to min_workers
    assert stats["busy"] == 0


async def test_acquire_beyond_idle_capacity_grows_and_waits(tmp_path, make_pool):
    pool = make_pool(make_config(tmp_path, min_workers=1, max_workers=3))
    await pool.start()

    w1 = await pool.acquire()  # consumes the only idle worker, triggers growth
    w2 = await pool.acquire()  # should be satisfied by the grown worker
    assert pool.stats()["total"] <= 3
    assert pool.stats()["busy"] == 2

    await pool.release(w1)
    await pool.release(w2)


async def test_acquire_never_exceeds_max_workers(tmp_path, make_pool):
    pool = make_pool(make_config(tmp_path, min_workers=1, max_workers=2))
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


async def test_scale_down_shrinks_idle_workers_back_to_min(tmp_path, make_pool):
    pool = make_pool(make_config(tmp_path, min_workers=1, max_workers=3))
    await pool.start()

    w1 = await pool.acquire()  # forces growth to 2 total
    w2 = await pool.acquire()  # forces growth to 3 total (still under max? min=1,max=3 -> ok)
    await pool.release(w1)
    await pool.release(w2)

    # right after release, replenish-to-min may have already run, but the
    # grown extras should still be sitting idle above min_workers
    assert pool.stats()["total"] >= pool.config.min_workers

    # idle_timeout_sec=0.2 and scale_down_interval_sec=0.1 in make_config —
    # wait past both so the sweep has a chance to run and trim excess idle
    await asyncio.sleep(0.6)
    assert pool.stats()["total"] == pool.config.min_workers
    assert pool.stats()["idle"] == pool.config.min_workers


async def test_scale_down_loop_kills_only_expired_excess_idle_workers(tmp_path, make_pool):
    # Sequential acquire()/release() can never leave more than min_workers
    # workers sitting in self._idle at once in this one-shot worker model
    # (see test_scale_down_shrinks_idle_workers_back_to_min above, which
    # passes identically whether or not the scale-down loop exists). To
    # actually prove the sweep trims excess idle workers, seed self._idle
    # directly with pre-expired workers instead of relying on timing.
    pool = make_pool(
        make_config(
            tmp_path,
            min_workers=2,
            max_workers=5,
            idle_timeout_sec=1.0,
            scale_down_interval_sec=0.05,
        )
    )
    await pool.start()
    originals = list(pool._idle)
    assert len(originals) == 2

    extras = [Worker(pool.config), Worker(pool.config)]
    for w in extras:
        w.became_idle_at = time.monotonic() - (pool.config.idle_timeout_sec + 10.0)
        pool._idle.append(w)
    pool._total += len(extras)

    assert pool.stats()["total"] == 4
    assert pool.stats()["idle"] == 4

    # Several sweep ticks (interval 0.05s) pass, but the originals are only
    # ~0.3s idle — far short of idle_timeout_sec=1.0 — so only the
    # pre-expired extras should be killed.
    await asyncio.sleep(0.3)

    stats = pool.stats()
    assert stats["total"] == pool.config.min_workers
    assert stats["idle"] == pool.config.min_workers
    for w in extras:
        assert w.state == WorkerState.DONE
    for w in originals:
        assert w.state == WorkerState.IDLE
        assert w in pool._idle


async def test_release_kills_worker_whose_run_was_cancelled(tmp_path, make_pool):
    # A client disconnect cancels the handler mid-run; unwinding out of
    # communicate() does NOT kill the subprocess, so release() must.
    pool = make_pool(
        make_config(
            tmp_path,
            min_workers=1,
            claude_cmd=[
                sys.executable, str(FAKE_CLI),
                "--fake-mode", "echo", "--fake-delay-sec", "5.0",
            ],
        )
    )
    await pool.start()

    worker = await pool.acquire()
    run = asyncio.ensure_future(worker.run("hi", timeout_sec=30.0))
    await asyncio.sleep(0.3)
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run

    assert worker.is_alive()  # cancellation alone leaves it running
    await pool.release(worker)
    assert not worker.is_alive()


async def test_acquire_discards_dead_idle_workers(tmp_path, make_pool):
    pool = make_pool(make_config(tmp_path, min_workers=2, max_workers=4))
    await pool.start()

    dead = pool._idle[0]
    await dead.kill()
    assert not dead.is_alive()

    worker = await pool.acquire()
    assert worker is not dead
    assert worker.is_alive()
    assert pool.stats()["total"] == 1  # the dead one was discarded, not handed out

    await pool.release(worker)


async def test_acquire_fails_fast_when_worker_spawn_fails(tmp_path, make_pool):
    pool = make_pool(
        make_config(tmp_path, min_workers=0, max_workers=2, claude_cmd=MISSING_BINARY)
    )
    await pool.start()

    # The outer wait_for is the safety net: before the fix this hung forever.
    with pytest.raises(PoolUnavailableError):
        await asyncio.wait_for(pool.acquire(), timeout=5.0)


async def test_acquire_times_out_when_pool_is_exhausted(tmp_path, make_pool):
    pool = make_pool(
        make_config(tmp_path, min_workers=1, max_workers=1, acquire_timeout_sec=0.3)
    )
    await pool.start()

    held = await pool.acquire()
    with pytest.raises(PoolUnavailableError):
        await pool.acquire()
    await pool.release(held)


async def test_release_never_propagates_a_failed_replenish(tmp_path, make_pool):
    pool = make_pool(make_config(tmp_path, min_workers=1, max_workers=2))
    await pool.start()
    worker = await pool.acquire()

    pool.config.claude_cmd = MISSING_BINARY
    await pool.release(worker)  # must not raise into the caller's finally block

    assert pool.stats()["total"] == 0


async def test_stop_kills_idle_workers_and_cancels_scale_down_loop(tmp_path):
    pool = WorkerPool(make_config(tmp_path, min_workers=2))
    await pool.start()
    idle_workers = list(pool._idle)
    assert all(w.is_alive() for w in idle_workers)

    await pool.stop()

    assert all(not w.is_alive() for w in idle_workers)
    assert pool.stats()["total"] == 0
    assert pool._scale_down_task is None


async def test_stop_wakes_parked_acquire_waiters(tmp_path):
    # acquire_timeout_sec is deliberately long: a pass here must come from
    # stop() waking the waiter, not from the timeout backstop firing.
    pool = WorkerPool(
        make_config(tmp_path, min_workers=1, max_workers=1, acquire_timeout_sec=30.0)
    )
    await pool.start()
    held = await pool.acquire()

    waiter = asyncio.ensure_future(pool.acquire())
    await asyncio.sleep(0.1)
    assert not waiter.done()

    await pool.stop()
    with pytest.raises(PoolUnavailableError):
        await asyncio.wait_for(waiter, timeout=2.0)

    await pool.release(held)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only job object behavior")
async def test_pool_workers_die_if_job_handle_closes_without_stop(tmp_path):
    import win32api
    import win32con
    import win32process

    def is_running(pid: int) -> bool:
        try:
            handle = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION, False, pid)
        except Exception:
            return False
        code = win32process.GetExitCodeProcess(handle)
        handle.Close()
        return code == 259  # STILL_ACTIVE

    pool = WorkerPool(make_config(tmp_path, min_workers=2))
    await pool.start()
    pids = [w._proc.pid for w in pool._idle]
    assert all(is_running(pid) for pid in pids)

    # Simulate the daemon process being killed outright -- no chance to run
    # pool.stop(), just the job handle closing, exactly what the OS does on
    # its own when a process holding it dies for any reason.
    pool._job.Close()

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and any(is_running(pid) for pid in pids):
        await asyncio.sleep(0.1)
    assert all(not is_running(pid) for pid in pids)
