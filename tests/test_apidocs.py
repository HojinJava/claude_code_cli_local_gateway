import sys
from pathlib import Path

import pytest

from claude_pool.apidocs import FAILURE_KINDS, api_info, openapi_spec, render_html
from claude_pool.config import PoolConfig
from claude_pool.errors import classify
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
    pool = make_pool(make_config(tmp_path, model="haiku", max_workers=7))
    await pool.start()
    return await aiohttp_client(create_app(pool))


async def test_index_describes_the_api(client):
    data = await (await client.get("/")).json()
    assert data["name"] == "claude-pool"
    for endpoint in ("POST /generate", "POST /jobs", "GET /jobs/{job_id}", "GET /health"):
        assert endpoint in data["endpoints"], endpoint
    assert data["example"]["curl"].startswith("curl ")


async def test_index_reflects_this_daemon_not_the_defaults(client):
    # The point of serving config live: a caller must not be told "sonnet"
    # by a daemon that is actually running haiku.
    data = await (await client.get("/")).json()
    assert data["config"]["model"] == "haiku"
    assert data["config"]["max_workers"] == 7
    assert PoolConfig().model != "haiku"


async def test_index_warns_about_the_quota_it_spends(client):
    data = await (await client.get("/")).json()
    joined = " ".join(data["constraints"]) + data["summary"]
    assert "quota" in joined
    assert any("no conversation memory" in c.lower() for c in data["constraints"])


async def test_docs_serves_a_self_contained_html_page(client):
    resp = await client.get("/docs")
    assert resp.status == 200
    assert resp.content_type == "text/html"
    body = await resp.text()
    assert body.startswith("<!doctype html>")
    # No CDN: the page must render on a box with no internet.
    assert "http://" not in body.replace("http://127.0.0.1", "")
    assert "https://" not in body


async def test_openapi_is_served_and_covers_every_route(client):
    spec = await (await client.get("/openapi.json")).json()
    assert spec["openapi"] == "3.1.0"
    assert set(spec["paths"]) == {
        "/generate", "/jobs", "/jobs/{job_id}", "/health", "/", "/docs", "/openapi.json",
    }
    assert spec["servers"][0]["url"].startswith("http://127.0.0.1")


async def test_openapi_documents_both_meanings_of_503(client):
    spec = await (await client.get("/openapi.json")).json()
    desc = spec["paths"]["/generate"]["post"]["responses"]["503"]["description"]
    # Two distinct failures share 503; neither may overwrite the other.
    assert "pool_unavailable" in desc
    assert "not_authenticated" in desc


async def test_openapi_429_carries_the_retry_after_header(client):
    spec = await (await client.get("/openapi.json")).json()
    assert "Retry-After" in spec["paths"]["/generate"]["post"]["responses"]["429"]["headers"]


async def test_docs_endpoints_are_behind_the_host_guard(client):
    for path in ("/", "/docs", "/openapi.json"):
        resp = await client.get(path, headers={"Host": "evil.example.com"})
        assert resp.status == 403, path


@pytest.mark.parametrize(
    "text,kind",
    [
        ("usage limit reached", "rate_limited"),
        ("please run /login", "not_authenticated"),
        ("boom", "worker_failed"),
    ],
)
def test_documented_failures_match_what_the_classifier_actually_returns(text, kind):
    # Guards against the docs drifting away from errors.classify.
    documented = {f["kind"]: f for f in FAILURE_KINDS}
    failure = classify(text)
    assert failure.kind == kind
    assert failure.status == documented[kind]["status"]
    assert failure.retryable is documented[kind]["retryable"]


def test_every_documented_kind_is_unique():
    kinds = [f["kind"] for f in FAILURE_KINDS]
    assert len(kinds) == len(set(kinds))


def test_render_html_escapes_config_values(tmp_path):
    # Config is operator-supplied, but it still must not break the page.
    page = render_html(make_config(tmp_path, model="<script>x</script>"))
    assert "<script>x</script>" not in page
    assert "&lt;script&gt;" in page


def test_api_info_and_spec_agree_on_version(tmp_path):
    config = make_config(tmp_path)
    assert api_info(config)["version"] == openapi_spec(config)["info"]["version"]


async def test_index_shows_how_to_run_in_the_background(client):
    example = (await (await client.get("/")).json())["example"]["background"]
    assert "/jobs" in example
    assert "job_id" in example


async def test_docs_page_explains_background_jobs(client):
    body = await (await client.get("/docs")).text()
    assert "Background jobs" in body
    assert "/jobs" in body
