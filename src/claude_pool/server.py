from __future__ import annotations

import asyncio
import json

from aiohttp import web

from .pool import PoolUnavailableError, WorkerPool
from .worker import WorkerError


def create_app(pool: WorkerPool) -> web.Application:
    app = web.Application()
    app["pool"] = pool
    app.router.add_post("/generate", handle_generate)
    app.router.add_get("/health", handle_health)
    return app


async def handle_generate(request: web.Request) -> web.Response:
    pool: WorkerPool = request.app["pool"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid JSON body"}, status=400)

    if not isinstance(body, dict):
        return web.json_response({"error": "request body must be a JSON object"}, status=400)

    prompt = body.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        return web.json_response({"error": "'prompt' is required"}, status=400)

    try:
        timeout_sec = float(body.get("timeout_sec", pool.config.default_timeout_sec))
    except (ValueError, TypeError):
        return web.json_response({"error": "'timeout_sec' must be numeric"}, status=400)

    try:
        worker = await pool.acquire()
    except PoolUnavailableError as exc:
        return web.json_response({"error": str(exc)}, status=503)

    try:
        result = await worker.run(prompt, timeout_sec=timeout_sec)
    except asyncio.TimeoutError:
        return web.json_response({"error": "worker timed out"}, status=504)
    except WorkerError as exc:
        return web.json_response({"error": str(exc)}, status=502)
    finally:
        # Detached and shielded so that cancelling this handler (client
        # disconnect, shutdown) still runs the release — and therefore the
        # worker kill — to completion under the pool's own task tracking.
        await asyncio.shield(pool.release_in_background(worker))

    if result["is_error"]:
        return web.json_response({"error": result["text"]}, status=502)
    return web.json_response({"text": result["text"], "duration_ms": result["duration_ms"]})


async def handle_health(request: web.Request) -> web.Response:
    pool: WorkerPool = request.app["pool"]
    return web.json_response(pool.stats())
