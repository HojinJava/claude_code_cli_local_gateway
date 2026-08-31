"""The daemon binds loopback and has no auth layer, so the Host header is
the only thing standing between it and a DNS-rebinding page that points a
hostname it owns at 127.0.0.1 to burn the user's subscription quota."""
import sys
from pathlib import Path

import pytest

from claude_pool.config import PoolConfig
from claude_pool.server import create_app, hostname_from_host_header

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_claude_cli.py"


@pytest.fixture
async def client(aiohttp_client, tmp_path, make_pool):
    pool = make_pool(
        PoolConfig(
            min_workers=1,
            max_workers=2,
            scratch_dir=tmp_path,
            claude_cmd=[sys.executable, str(FAKE_CLI), "--fake-mode", "echo"],
        )
    )
    await pool.start()
    return await aiohttp_client(create_app(pool))


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("127.0.0.1:8756", "127.0.0.1"),
        ("127.0.0.1", "127.0.0.1"),
        ("localhost:8756", "localhost"),
        ("[::1]:8756", "::1"),
        ("[::1]", "::1"),
        ("evil.example.com:8756", "evil.example.com"),
        ("", ""),
    ],
)
def test_hostname_from_host_header(raw, expected):
    assert hostname_from_host_header(raw) == expected


@pytest.mark.parametrize("host", ["evil.example.com", "rebind.test:8756", "example.com"])
async def test_non_loopback_host_header_is_rejected(client, host):
    resp = await client.post("/generate", json={"prompt": "hi"}, headers={"Host": host})
    assert resp.status == 403
    data = await resp.json()
    assert data["kind"] == "forbidden_host"


@pytest.mark.parametrize("host", ["127.0.0.1:8756", "localhost:1234", "[::1]:8756"])
async def test_loopback_host_headers_are_accepted(client, host):
    resp = await client.post("/generate", json={"prompt": "hi"}, headers={"Host": host})
    assert resp.status == 200


async def test_health_is_guarded_too(client):
    resp = await client.get("/health", headers={"Host": "evil.example.com"})
    assert resp.status == 403
