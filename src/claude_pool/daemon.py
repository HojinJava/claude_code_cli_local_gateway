from __future__ import annotations

import asyncio
import signal

from aiohttp import web

from .config import PoolConfig
from .pool import WorkerPool
from .server import create_app


async def run_daemon(config: PoolConfig) -> None:
    config.scratch_dir.mkdir(parents=True, exist_ok=True)
    pool = WorkerPool(config)
    runner: web.AppRunner | None = None
    try:
        await pool.start()
        app = create_app(pool)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host=config.host, port=config.port)
        await site.start()
        await _wait_for_shutdown_signal()
    finally:
        try:
            if runner is not None:
                await runner.cleanup()
        finally:
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
