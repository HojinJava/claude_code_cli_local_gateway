import asyncio
import sys
from pathlib import Path

import pytest

from claude_pool.config import PoolConfig
from claude_pool.jobs import CANCELLED, FAILED, RUNNING, SUCCEEDED, JobStore
from claude_pool.server import create_app

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_claude_cli.py"


def make_config(tmp_path, *fake_args, **overrides):
    defaults = dict(
        min_workers=1,
        max_workers=3,
        scratch_dir=tmp_path,
        claude_cmd=[sys.executable, str(FAKE_CLI), "--fake-mode", "echo", *fake_args],
    )
    defaults.update(overrides)
    return PoolConfig(**defaults)


async def _await_terminal(store, job, timeout=10.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not job.is_terminal:
        assert asyncio.get_running_loop().time() < deadline, f"job stuck in {job.status}"
        await asyncio.sleep(0.02)
    return job


@pytest.fixture
async def store(tmp_path, make_pool):
    pool = make_pool(make_config(tmp_path))
    await pool.start()
    js = JobStore(pool, retention_sec=60.0, max_jobs=100)
    yield js
    await js.shutdown()


async def test_submit_returns_immediately_and_completes_in_the_background(store):
    job = store.submit("hello", timeout_sec=5.0)
    # The whole point: submit does not wait for the completion.
    assert job.status == RUNNING
    assert job.text == ""

    await _await_terminal(store, job)
    assert job.status == SUCCEEDED
    assert job.text == "hello"


async def test_job_ids_are_unguessable(store):
    ids = {store.submit(f"p{i}", timeout_sec=5.0).id for i in range(5)}
    assert len(ids) == 5
    assert all(len(job_id) >= 16 for job_id in ids)


async def test_a_failed_run_lands_on_the_job_with_its_classification(
    tmp_path, make_pool
):
    pool = make_pool(
        make_config(
            tmp_path,
            claude_cmd=[
                sys.executable, str(FAKE_CLI), "--fake-mode", "error",
                "--fake-api-error-status", "429",
                "--fake-error-text", "usage limit reached",
            ],
        )
    )
    await pool.start()
    js = JobStore(pool, retention_sec=60.0, max_jobs=100)
    job = await _await_terminal(js, js.submit("hi", timeout_sec=5.0))

    assert job.status == FAILED
    assert job.failure.kind == "rate_limited"
    body = job.to_dict()
    assert body["retryable"] is True
    assert body["retry_after_sec"] == 60
    await js.shutdown()


async def test_cancel_kills_the_running_worker(tmp_path, make_pool):
    pool = make_pool(make_config(tmp_path, "--fake-delay-sec", "10.0"))
    await pool.start()
    js = JobStore(pool, retention_sec=60.0, max_jobs=100)

    job = js.submit("slow", timeout_sec=30.0)
    await asyncio.sleep(0.2)
    assert job.status == RUNNING

    cancelled = await js.cancel(job.id)
    assert cancelled.status == CANCELLED
    # cancel() only answers once release() has actually retired the worker,
    # so the pool must already be back to its idle baseline.
    assert pool.stats()["busy"] == 0
    await js.shutdown()


async def test_cancel_of_an_unknown_job_returns_none(store):
    assert await store.cancel("nope") is None


async def test_shutdown_cancels_running_jobs(tmp_path, make_pool):
    pool = make_pool(make_config(tmp_path, "--fake-delay-sec", "10.0"))
    await pool.start()
    js = JobStore(pool, retention_sec=60.0, max_jobs=100)
    job = js.submit("slow", timeout_sec=30.0)
    await asyncio.sleep(0.2)

    await js.shutdown()
    assert job.status == CANCELLED
    assert pool.stats()["busy"] == 0


async def test_finished_jobs_are_reaped_after_retention(tmp_path, make_pool):
    pool = make_pool(make_config(tmp_path))
    await pool.start()
    js = JobStore(pool, retention_sec=0.0, max_jobs=100)

    old = await _await_terminal(js, js.submit("first", timeout_sec=5.0))
    await asyncio.sleep(0.05)
    js.submit("second", timeout_sec=5.0)  # submitting is what triggers the reap

    assert js.get(old.id) is None
    await js.shutdown()


async def test_max_jobs_drops_oldest_finished_but_never_running_ones(
    tmp_path, make_pool
):
    pool = make_pool(make_config(tmp_path, min_workers=2, max_workers=4))
    await pool.start()
    js = JobStore(pool, retention_sec=3600.0, max_jobs=2)

    finished = []
    for i in range(3):
        finished.append(await _await_terminal(js, js.submit(f"p{i}", timeout_sec=5.0)))
    js.submit("newest", timeout_sec=5.0)

    assert js.get(finished[0].id) is None, "oldest finished job should be evicted"
    assert len(js.list()) <= 3  # cap plus the still-running submission
    await js.shutdown()


# ---- HTTP surface ----


@pytest.fixture
async def client(aiohttp_client, tmp_path, make_pool):
    pool = make_pool(make_config(tmp_path))
    await pool.start()
    return await aiohttp_client(create_app(pool))


async def test_post_jobs_returns_202_with_a_location(client):
    resp = await client.post("/jobs", json={"prompt": "hello"})
    assert resp.status == 202
    body = await resp.json()
    assert body["status"] == RUNNING
    assert resp.headers["Location"] == f"/jobs/{body['job_id']}"


async def test_polling_a_job_eventually_yields_the_text(client):
    job_id = (await (await client.post("/jobs", json={"prompt": "hello"})).json())["job_id"]

    for _ in range(200):
        body = await (await client.get(f"/jobs/{job_id}")).json()
        if body["status"] != RUNNING:
            break
        await asyncio.sleep(0.02)

    assert body["status"] == SUCCEEDED
    assert body["text"] == "hello"
    assert "duration_ms" in body


async def test_querying_a_failed_job_still_returns_200(aiohttp_client, tmp_path, make_pool):
    # The query succeeded; the job's own outcome lives in the body, so a
    # poller checks one status code instead of two.
    pool = make_pool(
        make_config(
            tmp_path,
            claude_cmd=[sys.executable, str(FAKE_CLI), "--fake-mode", "error",
                        "--fake-api-error-code", "authentication_failed",
                        "--fake-error-text", "please run /login"],
        )
    )
    await pool.start()
    client = await aiohttp_client(create_app(pool))
    job_id = (await (await client.post("/jobs", json={"prompt": "hi"})).json())["job_id"]

    for _ in range(200):
        resp = await client.get(f"/jobs/{job_id}")
        body = await resp.json()
        if body["status"] != RUNNING:
            break
        await asyncio.sleep(0.02)

    assert resp.status == 200
    assert body["status"] == FAILED
    assert body["kind"] == "not_authenticated"
    assert body["retryable"] is False


async def test_unknown_job_is_404(client):
    assert (await client.get("/jobs/nope")).status == 404
    assert (await client.delete("/jobs/nope")).status == 404


async def test_jobs_validate_the_body_like_generate_does(client):
    assert (await client.post("/jobs", json={})).status == 400
    assert (await client.post("/jobs", json=[1, 2])).status == 400
    assert (await client.post("/jobs", json={"prompt": "x", "timeout_sec": "abc"})).status == 400


async def test_list_jobs_is_newest_first(client):
    for i in range(3):
        await client.post("/jobs", json={"prompt": f"p{i}"})
    jobs = (await (await client.get("/jobs")).json())["jobs"]
    assert [j["prompt_preview"] for j in jobs] == ["p2", "p1", "p0"]


async def test_health_reports_job_counts(client):
    await client.post("/jobs", json={"prompt": "hello"})
    stats = await (await client.get("/health")).json()
    assert stats["jobs"]["total"] >= 1


async def test_job_endpoints_are_behind_the_host_guard(client):
    evil = {"Host": "evil.example.com"}
    assert (await client.post("/jobs", json={"prompt": "x"}, headers=evil)).status == 403
    assert (await client.get("/jobs", headers=evil)).status == 403


async def test_a_running_job_holds_off_the_idle_drain(tmp_path, make_pool):
    # A job keeps its worker out of the pool, so the drain must not fire
    # while it runs — and must not take the job's worker with it.
    pool = make_pool(
        make_config(
            tmp_path, "--fake-delay-sec", "0.6",
            min_workers=2,
            idle_scale_to_zero_sec=0.1,
            idle_timeout_sec=10.0,
            scale_down_interval_sec=0.05,
        )
    )
    await pool.start()
    js = JobStore(pool, retention_sec=60.0, max_jobs=100)
    job = js.submit("slow", timeout_sec=10.0)

    await asyncio.sleep(0.3)
    assert job.status == RUNNING
    assert pool.stats()["busy"] == 1

    await _await_terminal(js, job)
    assert job.status == SUCCEEDED
    await js.shutdown()
