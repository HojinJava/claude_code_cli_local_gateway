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


def test_idle_scale_to_zero_defaults_to_a_minute():
    assert PoolConfig().idle_scale_to_zero_sec == 60.0


def test_idle_scale_to_zero_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("CLAUDE_POOL_IDLE_SCALE_TO_ZERO_SEC", "300")
    assert PoolConfig.from_env().idle_scale_to_zero_sec == 300.0


def test_idle_scale_to_zero_can_be_disabled_with_zero(monkeypatch):
    monkeypatch.setenv("CLAUDE_POOL_IDLE_SCALE_TO_ZERO_SEC", "0")
    assert PoolConfig.from_env().idle_scale_to_zero_sec == 0.0


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


def test_scratch_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_POOL_SCRATCH_DIR", str(tmp_path / "scratch"))
    assert PoolConfig.from_env().scratch_dir == tmp_path / "scratch"


def test_scratch_dir_defaults_under_home(monkeypatch):
    monkeypatch.delenv("CLAUDE_POOL_SCRATCH_DIR", raising=False)
    assert PoolConfig.from_env().scratch_dir.name == "scratch"


@pytest.mark.parametrize("bad", ["claude", [], ["claude", 3], {"a": 1}, None])
def test_claude_cmd_must_be_a_non_empty_list_of_strings(bad):
    # A bare string would otherwise be splatted one character per argv entry.
    with pytest.raises(ValueError, match="claude_cmd"):
        PoolConfig(claude_cmd=bad)


def test_from_env_rejects_unparsable_claude_cmd_json(monkeypatch):
    monkeypatch.setenv("CLAUDE_POOL_CLAUDE_CMD_JSON", "{not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        PoolConfig.from_env()


def test_from_env_rejects_claude_cmd_json_that_is_not_a_list(monkeypatch):
    monkeypatch.setenv("CLAUDE_POOL_CLAUDE_CMD_JSON", '"claude"')
    with pytest.raises(ValueError, match="claude_cmd"):
        PoolConfig.from_env()
