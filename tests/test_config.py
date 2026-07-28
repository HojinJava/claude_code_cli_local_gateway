import pytest

from claude_pool.config import PoolConfig


def test_defaults():
    config = PoolConfig()
    assert config.min_workers == 4
    assert config.max_workers == 30
    assert config.model == "sonnet"
    assert config.host == "127.0.0.1"
    assert config.port == 8756
    assert config.claude_cmd == ["claude"]


def test_from_env_reads_overrides(monkeypatch):
    monkeypatch.setenv("CLAUDE_POOL_MIN_WORKERS", "2")
    monkeypatch.setenv("CLAUDE_POOL_MAX_WORKERS", "8")
    monkeypatch.setenv("CLAUDE_POOL_PORT", "9999")
    monkeypatch.setenv("CLAUDE_POOL_CLAUDE_CMD_JSON", '["python", "fake.py"]')
    config = PoolConfig.from_env()
    assert config.min_workers == 2
    assert config.max_workers == 8
    assert config.port == 9999
    assert config.claude_cmd == ["python", "fake.py"]


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.2", "localhost", "::1"])
def test_loopback_hosts_are_accepted(host):
    assert PoolConfig(host=host).host == host


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "example.com", ""])
def test_non_loopback_host_is_rejected(host):
    with pytest.raises(ValueError, match="loopback"):
        PoolConfig(host=host)


def test_from_env_rejects_non_loopback_host(monkeypatch):
    monkeypatch.setenv("CLAUDE_POOL_HOST", "0.0.0.0")
    with pytest.raises(ValueError, match="loopback"):
        PoolConfig.from_env()
