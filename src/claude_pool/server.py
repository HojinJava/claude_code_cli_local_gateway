from __future__ import annotations

import asyncio
import json

from aiohttp import web

from .pool import WorkerPool
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

    worker = await pool.acquire()
    try:
        result = await worker.run(prompt, timeout_sec=timeout_sec)
    except asyncio.TimeoutError:
        return web.json_response({"error": "worker timed out"}, status=504)
    except WorkerError as exc:
        return web.json_response({"error": str(exc)}, status=502)
    finally:
        await pool.release(worker)

    if result["is_error"]:
        return web.json_response({"error": result["text"]}, status=502)
    return web.json_response({"text": result["text"], "duration_ms": result["duration_ms"]})


async def handle_health(request: web.Request) -> web.Response:
    pool: WorkerPool = request.app["pool"]
    return web.json_response(pool.stats())
