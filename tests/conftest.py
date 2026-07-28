import socket

import pytest

from claude_pool.config import PoolConfig
from claude_pool.pool import WorkerPool


@pytest.fixture
def unused_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def make_pool():
    """Build WorkerPools that are stopped (workers killed) at teardown."""
    pools: list[WorkerPool] = []

    def factory(config: PoolConfig) -> WorkerPool:
        pool = WorkerPool(config)
        pools.append(pool)
        return pool

    yield factory

    for pool in pools:
        await pool.stop()
