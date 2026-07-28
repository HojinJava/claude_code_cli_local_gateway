from __future__ import annotations

import asyncio

from aiohttp import web

from .config import PoolConfig
from .pool import WorkerPool
from .server import create_app


async def run_daemon(config: PoolConfig) -> None:
    config.scratch_dir.mkdir(parents=True, exist_ok=True)
    pool = WorkerPool(config)
    await pool.start()
    app = create_app(pool)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=config.host, port=config.port)
    await site.start()
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await runner.cleanup()


def main() -> None:
    config = PoolConfig.from_env()
    asyncio.run(run_daemon(config))


if __name__ == "__main__":
    main()
