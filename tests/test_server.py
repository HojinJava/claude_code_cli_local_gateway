# tests/test_server.py
import sys
from pathlib import Path

import pytest

from claude_pool.config import PoolConfig
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
async def client(aiohttp_client, tmp_path, make_pool):
    pool = make_pool(make_config(tmp_path))
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


async def test_generate_surfaces_worker_error(aiohttp_client, tmp_path, make_pool):
    pool = make_pool(make_config(tmp_path, claude_cmd=[sys.executable, str(FAKE_CLI), "--fake-mode", "crash"]))
    await pool.start()
    app = create_app(pool)
    client = await aiohttp_client(app)
    resp = await client.post("/generate", json={"prompt": "hello"})
    assert resp.status == 502
    data = await resp.json()
    assert "error" in data


async def test_generate_returns_503_when_no_worker_can_be_acquired(
    aiohttp_client, tmp_path, make_pool
):
    pool = make_pool(
        make_config(
            tmp_path,
            min_workers=0,
            max_workers=1,
            acquire_timeout_sec=2.0,
            claude_cmd=["claude-pool-no-such-binary-xyz"],
        )
    )
    await pool.start()
    app = create_app(pool)
    client = await aiohttp_client(app)
    resp = await client.post("/generate", json={"prompt": "hello"})
    assert resp.status == 503
    data = await resp.json()
    assert "error" in data


async def test_generate_rejects_non_dict_json_body(client):
    resp = await client.post("/generate", json=[1, 2])
    assert resp.status == 400
    data = await resp.json()
    assert "error" in data

    resp = await client.post("/generate", json="hello")
    assert resp.status == 400
    data = await resp.json()
    assert "error" in data


async def test_generate_rejects_non_numeric_timeout_sec(client):
    resp = await client.post("/generate", json={"prompt": "hello", "timeout_sec": "abc"})
    assert resp.status == 400
    data = await resp.json()
    assert "error" in data


async def test_health_reports_liveness_not_just_counters(client):
    resp = await client.get("/health")
    data = await resp.json()
    assert data["idle_alive"] == data["idle"]
    assert data["healthy"] is True
    assert data["last_spawn_error"] is None
    assert data["last_error"] is None


async def test_health_reports_dead_prewarmed_workers_as_not_alive(
    aiohttp_client, tmp_path, make_pool
):
    # The failure a counters-only /health used to hide: workers were spawned
    # and counted, but every `claude` process died on its own immediately.
    pool = make_pool(make_config(tmp_path))
    await pool.start()
    for worker in pool._idle:
        await worker.kill()

    client = await aiohttp_client(create_app(pool))
    data = await (await client.get("/health")).json()
    assert data["idle"] == 1
    assert data["idle_alive"] == 0
    assert data["healthy"] is False


async def test_generate_classifies_rate_limit_as_retryable_429(
    aiohttp_client, tmp_path, make_pool
):
    pool = make_pool(
        make_config(
            tmp_path,
            claude_cmd=[
                sys.executable, str(FAKE_CLI),
                "--fake-mode", "error",
                "--fake-error-text", "Claude AI usage limit reached, try again in 30 seconds",
            ],
        )
    )
    await pool.start()
    client = await aiohttp_client(create_app(pool))
    resp = await client.post("/generate", json={"prompt": "hello"})

    assert resp.status == 429
    assert resp.headers["Retry-After"] == "30"
    data = await resp.json()
    assert data["kind"] == "rate_limited"
    assert data["retryable"] is True
    assert data["duration_ms"] == 1


async def test_generate_classifies_logged_out_cli_as_not_retryable(
    aiohttp_client, tmp_path, make_pool
):
    pool = make_pool(
        make_config(
            tmp_path,
            claude_cmd=[
                sys.executable, str(FAKE_CLI),
                "--fake-mode", "crash",
                "--fake-error-text", "Invalid API key - please run /login",
            ],
        )
    )
    await pool.start()
    client = await aiohttp_client(create_app(pool))
    resp = await client.post("/generate", json={"prompt": "hello"})

    assert resp.status == 503
    data = await resp.json()
    assert data["kind"] == "not_authenticated"
    assert data["retryable"] is False
    assert "Retry-After" not in resp.headers

    # and the reason is now visible on /health instead of vanishing
    health = await (await client.get("/health")).json()
    assert "login" in health["last_error"]


async def test_successful_run_clears_the_last_error(client):
    await client.post("/generate", json={})  # a 400 must not touch run state
    await client.post("/generate", json={"prompt": "hello"})
    health = await (await client.get("/health")).json()
    assert health["last_error"] is None


async def test_pool_exhaustion_is_reported_as_retryable(
    aiohttp_client, tmp_path, make_pool
):
    pool = make_pool(
        make_config(
            tmp_path, min_workers=0, max_workers=1, acquire_timeout_sec=2.0,
            claude_cmd=["claude-pool-no-such-binary-xyz"],
        )
    )
    await pool.start()
    client = await aiohttp_client(create_app(pool))
    data = await (await client.post("/generate", json={"prompt": "hi"})).json()
    assert data["kind"] == "pool_unavailable"
    assert data["retryable"] is True


async def test_an_empty_on_demand_pool_is_not_reported_unhealthy(
    aiohttp_client, tmp_path, make_pool
):
    # min_workers=0 means "no pre-warmed workers", not "every worker died".
    pool = make_pool(make_config(tmp_path, min_workers=0))
    await pool.start()
    client = await aiohttp_client(create_app(pool))
    data = await (await client.get("/health")).json()
    assert data["idle"] == 0
    assert data["healthy"] is True
