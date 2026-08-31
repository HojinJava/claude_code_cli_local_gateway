from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path

from aiohttp import web

from .config import PoolConfig
from .jobs import JobStore
from .pool import WorkerPool
from .server import create_app


def pid_file(config: PoolConfig) -> Path:
    """Per-port, so stopping one daemon never touches another.

    Running a second daemon on another port for a different model is a
    supported setup, which is exactly what matching on the command line
    would get wrong -- every daemon shares the same one.
    """
    return config.scratch_dir / f"daemon-{config.port}.pid"


async def run_daemon(config: PoolConfig) -> None:
    config.scratch_dir.mkdir(parents=True, exist_ok=True)
    pool = WorkerPool(config)
    jobs = JobStore(pool, retention_sec=config.job_retention_sec, max_jobs=config.max_jobs)
    runner: web.AppRunner | None = None
    try:
        await pool.start()
        app = create_app(pool, jobs)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host=config.host, port=config.port)
        await site.start()
        pid_file(config).write_text(str(os.getpid()), encoding="utf-8")
        await _wait_for_shutdown_signal()
    finally:
        # A hard kill never reaches this, so readers must treat the file as a
        # hint and verify the pid is really this daemon before acting on it.
        pid_file(config).unlink(missing_ok=True)
        try:
            if runner is not None:
                await runner.cleanup()
        finally:
            # Jobs first: cancelling them releases their workers back through
            # the pool, so pool.stop() can then drain and kill everything.
            await jobs.shutdown()
            await pool.stop()


async def _wait_for_shutdown_signal() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, AttributeError, ValueError):
            pass  # unsupported on Windows / non-main thread; Ctrl+C still unwinds
    await stop.wait()


def main() -> None:
    config = PoolConfig.from_env()
    asyncio.run(run_daemon(config))


if __name__ == "__main__":
    main()
