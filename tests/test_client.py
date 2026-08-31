import asyncio
import json
import sys
import threading
import time
from pathlib import Path

import pytest

from claude_pool.client import ClaudePoolClient, ClaudePoolError
from claude_pool.config import PoolConfig
from claude_pool.daemon import run_daemon

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_claude_cli.py"


def _run_daemon_in_thread(config: PoolConfig) -> None:
    def target():
        asyncio.run(run_daemon(config))
    t = threading.Thread(target=target, daemon=True)
    t.start()


@pytest.fixture
def running_daemon(tmp_path, unused_tcp_port):
    config = PoolConfig(
        min_workers=1,
        max_workers=2,
        port=unused_tcp_port,
        scratch_dir=tmp_path,
        claude_cmd=[sys.executable, str(FAKE_CLI), "--fake-mode", "echo"],
    )
    _run_daemon_in_thread(config)
    deadline = time.monotonic() + 5.0
    client = ClaudePoolClient(port=config.port, auto_start=False)
    while time.monotonic() < deadline:
        try:
            client.health()
            break
        except Exception:
            time.sleep(0.1)
    return config.port


def test_client_generate_returns_text(running_daemon):
    client = ClaudePoolClient(port=running_daemon, auto_start=False)
    text = client.generate("hello there")
    assert text == "hello there"


def test_client_health_reports_stats(running_daemon):
    client = ClaudePoolClient(port=running_daemon, auto_start=False)
    stats = client.health()
    assert stats["min_workers"] == 1


def test_client_raises_on_missing_daemon_when_auto_start_disabled():
    with pytest.raises(Exception):
        ClaudePoolClient(port=1, auto_start=False).health()


def test_auto_start_passes_client_host_and_port_to_daemon(monkeypatch, unused_tcp_port):
    captured: dict = {}

    def fake_popen(argv, **kwargs):
        captured["argv"] = argv
        captured["env"] = kwargs["env"]
        raise _StopStartup

    monkeypatch.setattr("claude_pool.client.subprocess.Popen", fake_popen)
    with pytest.raises(_StopStartup):
        ClaudePoolClient(port=unused_tcp_port, auto_start=True, start_timeout_sec=0.1)

    assert captured["argv"][1:] == ["-m", "claude_pool.daemon"]
    assert captured["env"]["CLAUDE_POOL_PORT"] == str(unused_tcp_port)
    assert captured["env"]["CLAUDE_POOL_HOST"] == "127.0.0.1"


class _StopStartup(Exception):
    """Aborts __init__ right after the spawn so no daemon is actually launched."""


def _http_error(status, body, headers=None):
    import io
    import urllib.error
    from email.message import Message

    msg = Message()
    for k, v in (headers or {}).items():
        msg[k] = v
    return urllib.error.HTTPError(
        "http://127.0.0.1/generate", status, "err", msg,
        io.BytesIO(json.dumps(body).encode() if body is not None else b"<html>"),
    )


def test_error_carries_the_daemons_classification():
    exc = ClaudePoolClient._error_from(
        _http_error(
            429,
            {"error": "usage limit reached", "kind": "rate_limited", "retryable": True},
            {"Retry-After": "30"},
        )
    )
    assert isinstance(exc, ClaudePoolError)
    assert str(exc) == "usage limit reached"
    assert exc.kind == "rate_limited"
    assert exc.retryable is True
    assert exc.retry_after_sec == 30


def test_error_marks_non_retryable_failures():
    exc = ClaudePoolClient._error_from(
        _http_error(503, {"error": "please run /login", "kind": "not_authenticated",
                          "retryable": False})
    )
    assert exc.kind == "not_authenticated"
    assert exc.retryable is False
    assert exc.retry_after_sec is None


def test_error_survives_a_non_json_error_body():
    # A proxy or crash page must still raise ClaudePoolError, not a decode
    # error thrown from inside the client.
    exc = ClaudePoolClient._error_from(_http_error(502, None))
    assert isinstance(exc, ClaudePoolError)
    assert str(exc) == "HTTP 502"
    assert exc.kind == "unknown"
    assert exc.retryable is False


def test_error_ignores_a_non_numeric_retry_after_header():
    exc = ClaudePoolClient._error_from(
        _http_error(429, {"error": "slow down", "kind": "rate_limited", "retryable": True},
                    {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
    )
    assert exc.retryable is True
    assert exc.retry_after_sec is None


def test_client_submit_and_wait_runs_in_the_background(running_daemon):
    client = ClaudePoolClient(port=running_daemon, auto_start=False)

    job_id = client.submit("hello there")
    assert isinstance(job_id, str) and job_id

    # submit() returned without waiting for the completion; wait() collects it.
    assert client.wait(job_id, poll_interval_sec=0.05) == "hello there"

    job = client.job(job_id)
    assert job["status"] == "succeeded"
    assert job["text"] == "hello there"


def test_client_batches_prompts_without_holding_a_connection(running_daemon):
    client = ClaudePoolClient(port=running_daemon, auto_start=False)
    ids = [client.submit(f"p{i}") for i in range(3)]
    assert len(set(ids)) == 3
    assert [client.wait(i, poll_interval_sec=0.05) for i in ids] == ["p0", "p1", "p2"]


def test_client_lists_jobs(running_daemon):
    client = ClaudePoolClient(port=running_daemon, auto_start=False)
    job_id = client.submit("listed")
    client.wait(job_id, poll_interval_sec=0.05)
    assert job_id in [j["job_id"] for j in client.jobs()]


def test_client_wait_gives_up_on_its_own_timeout(running_daemon, monkeypatch):
    client = ClaudePoolClient(port=running_daemon, auto_start=False)
    monkeypatch.setattr(client, "job", lambda _id: {"status": "running"})
    with pytest.raises(ClaudePoolError) as excinfo:
        client.wait("stuck", poll_interval_sec=0.01, timeout_sec=0.05)
    assert excinfo.value.retryable is True
    assert excinfo.value.kind == "timeout"


def test_client_wait_raises_the_jobs_own_classification(running_daemon, monkeypatch):
    client = ClaudePoolClient(port=running_daemon, auto_start=False)
    monkeypatch.setattr(client, "job", lambda _id: {
        "status": "failed", "error": "usage limit reached",
        "kind": "rate_limited", "retryable": True, "retry_after_sec": 30,
    })
    with pytest.raises(ClaudePoolError) as excinfo:
        client.wait("j", poll_interval_sec=0.01)
    assert excinfo.value.kind == "rate_limited"
    assert excinfo.value.retry_after_sec == 30


def test_client_cancel_reports_the_cancelled_job(running_daemon):
    client = ClaudePoolClient(port=running_daemon, auto_start=False)
    job_id = client.submit("hello there")
    assert client.cancel(job_id)["status"] in ("cancelled", "succeeded")


def test_client_unknown_job_raises(running_daemon):
    client = ClaudePoolClient(port=running_daemon, auto_start=False)
    with pytest.raises(ClaudePoolError):
        client.job("no-such-job")


def test_client_reads_the_daemons_self_description(running_daemon):
    client = ClaudePoolClient(port=running_daemon, auto_start=False)
    info = client.api_info()
    assert info["name"] == "claude-pool"
    assert "POST /jobs" in info["endpoints"]
