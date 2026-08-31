from __future__ import annotations

import json

from aiohttp import web

from .apidocs import api_info, openapi_spec, render_html
from .config import is_loopback_host
from .errors import Failure
from .jobs import JobStore
from .pool import WorkerPool
from .runner import Outcome, execute


def hostname_from_host_header(host: str) -> str:
    """Strip the port (and IPv6 brackets) off a Host header value."""
    if not host:
        return ""
    if host.startswith("["):
        end = host.find("]")
        return host[1:end] if end != -1 else host[1:]
    head, sep, tail = host.rpartition(":")
    if sep and tail.isdigit():
        return head
    return host


@web.middleware
async def require_loopback_host(request: web.Request, handler):
    """Reject requests whose Host header is not a loopback literal.

    Binding to 127.0.0.1 stops remote TCP but not DNS rebinding: a page can
    point a hostname it owns at 127.0.0.1, which makes the daemon same-origin
    for that page and lets it POST /generate — burning the user's
    subscription quota. A rebinding request necessarily carries the
    attacker's hostname in Host, so requiring a loopback literal there closes
    it without adding an auth layer.
    """
    if not is_loopback_host(hostname_from_host_header(request.host)):
        return web.json_response(
            {
                "error": f"Host header {request.host!r} is not a loopback address",
                "kind": "forbidden_host",
                "retryable": False,
            },
            status=403,
        )
    return await handler(request)


def create_app(pool: WorkerPool, jobs: JobStore | None = None) -> web.Application:
    app = web.Application(middlewares=[require_loopback_host])
    app["pool"] = pool
    app["jobs"] = jobs if jobs is not None else JobStore(
        pool, retention_sec=pool.config.job_retention_sec, max_jobs=pool.config.max_jobs
    )
    app.router.add_post("/generate", handle_generate)
    app.router.add_get("/health", handle_health)
    # Background jobs: same worker lifecycle, but the caller does not hold
    # the connection open for the whole completion.
    app.router.add_post("/jobs", handle_submit_job)
    app.router.add_get("/jobs", handle_list_jobs)
    app.router.add_get("/jobs/{job_id}", handle_get_job)
    app.router.add_delete("/jobs/{job_id}", handle_cancel_job)
    # The daemon documents itself: whoever finds this port open can learn how
    # to use it — and what it costs — without a README in reach.
    app.router.add_get("/", handle_index)
    app.router.add_get("/docs", handle_docs)
    app.router.add_get("/openapi.json", handle_openapi)
    return app


class BadRequest(Exception):
    """A malformed request body; carries the message sent to the caller."""


async def _read_prompt_request(request: web.Request) -> tuple[str, float]:
    """Parse and validate the body shared by /generate and /jobs."""
    pool: WorkerPool = request.app["pool"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise BadRequest("invalid JSON body") from None

    if not isinstance(body, dict):
        raise BadRequest("request body must be a JSON object")

    prompt = body.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        raise BadRequest("'prompt' is required")

    try:
        timeout_sec = float(body.get("timeout_sec", pool.config.default_timeout_sec))
    except (ValueError, TypeError):
        raise BadRequest("'timeout_sec' must be numeric") from None

    return prompt, timeout_sec


def _failure_response(outcome: Outcome) -> web.Response:
    failure: Failure = outcome.failure
    body = {
        "error": outcome.error,
        "kind": failure.kind,
        "retryable": failure.retryable,
    }
    if outcome.duration_ms:
        body["duration_ms"] = outcome.duration_ms
    headers = {}
    if failure.retry_after_sec is not None:
        headers["Retry-After"] = str(failure.retry_after_sec)
    return web.json_response(body, status=failure.status, headers=headers)


async def handle_generate(request: web.Request) -> web.Response:
    try:
        prompt, timeout_sec = await _read_prompt_request(request)
    except BadRequest as exc:
        return web.json_response({"error": str(exc)}, status=400)

    outcome = await execute(request.app["pool"], prompt, timeout_sec)
    if not outcome.succeeded:
        return _failure_response(outcome)
    return web.json_response({"text": outcome.text, "duration_ms": outcome.duration_ms})


async def handle_submit_job(request: web.Request) -> web.Response:
    try:
        prompt, timeout_sec = await _read_prompt_request(request)
    except BadRequest as exc:
        return web.json_response({"error": str(exc)}, status=400)

    job = request.app["jobs"].submit(prompt, timeout_sec)
    body = job.to_dict()
    body["url"] = f"/jobs/{job.id}"
    return web.json_response(body, status=202, headers={"Location": body["url"]})


async def handle_get_job(request: web.Request) -> web.Response:
    job = request.app["jobs"].get(request.match_info["job_id"])
    if job is None:
        return web.json_response({"error": "no such job"}, status=404)
    # 200 even for a failed job: the *query* succeeded, and the job's own
    # outcome is in the body. The caller polls one status code, not two.
    return web.json_response(job.to_dict())


async def handle_list_jobs(request: web.Request) -> web.Response:
    jobs = request.app["jobs"].list()
    return web.json_response({"jobs": [j.to_dict() for j in jobs]})


async def handle_cancel_job(request: web.Request) -> web.Response:
    job = await request.app["jobs"].cancel(request.match_info["job_id"])
    if job is None:
        return web.json_response({"error": "no such job"}, status=404)
    return web.json_response(job.to_dict())


async def handle_health(request: web.Request) -> web.Response:
    stats = request.app["pool"].stats()
    stats["jobs"] = request.app["jobs"].stats()
    return web.json_response(stats)


async def handle_index(request: web.Request) -> web.Response:
    return web.json_response(api_info(request.app["pool"].config))


async def handle_openapi(request: web.Request) -> web.Response:
    return web.json_response(openapi_spec(request.app["pool"].config))


async def handle_docs(request: web.Request) -> web.Response:
    page = render_html(request.app["pool"].config)
    return web.Response(text=page, content_type="text/html")
