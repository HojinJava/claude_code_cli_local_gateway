# tests/test_server.py
import sys
from pathlib import Path

import pytest

from claude_pool.config import PoolConfig
from claude_pool.pool import WorkerPool
from claude_pool.server import create_app

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_claude_cli.py"


def make_config(tmp_path, **overrides):
    defaults = dict(
        min_workers=1,
        max_workers=2,
        scratch_dir=tmp_path,
        claude_cmd=[sys.executable, str(FAKE_CLI), "--fake-mode", "echo"],
    )
    defaults.update(overrides)
    return PoolConfig(**defaults)


@pytest.fixture
async def client(aiohttp_client, tmp_path):
    pool = WorkerPool(make_config(tmp_path))
    await pool.start()
    app = create_app(pool)
    return await aiohttp_client(app)


async def test_generate_returns_text(client):
    resp = await client.post("/generate", json={"prompt": "hello"})
    assert resp.status == 200
    data = await resp.json()
    assert data["text"] == "hello"
    assert "duration_ms" in data


async def test_generate_requires_prompt(client):
    resp = await client.post("/generate", json={})
    assert resp.status == 400
    data = await resp.json()
    assert "error" in data


async def test_generate_rejects_invalid_json(client):
    resp = await client.post("/generate", data="not json", headers={"Content-Type": "application/json"})
    assert resp.status == 400


async def test_health_reports_pool_stats(client):
    resp = await client.get("/health")
    assert resp.status == 200
    data = await resp.json()
    assert data["min_workers"] == 1
    assert data["max_workers"] == 2
    assert "idle" in data and "busy" in data


async def test_generate_surfaces_worker_error(aiohttp_client, tmp_path):
    pool = WorkerPool(make_config(tmp_path, claude_cmd=[sys.executable, str(FAKE_CLI), "--fake-mode", "crash"]))
    await pool.start()
    app = create_app(pool)
    client = await aiohttp_client(app)
    resp = await client.post("/generate", json={"prompt": "hello"})
    assert resp.status == 502
    data = await resp.json()
    assert "error" in data
