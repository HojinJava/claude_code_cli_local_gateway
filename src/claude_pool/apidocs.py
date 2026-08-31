"""Self-description for the daemon: what it is, how to call it, what it costs.

The gateway's usual discoverer is an agent or a script that found port 8756
open and has nothing else to go on — no README in reach, no operator to ask.
So the daemon carries its own docs: `GET /` answers in JSON, `GET /docs`
renders the same facts for a browser, and `GET /openapi.json` is the machine
contract. All three are built from the live PoolConfig, so they describe the
daemon that is actually running rather than the defaults.
"""
from __future__ import annotations

import html
from importlib.metadata import PackageNotFoundError, version

from .config import PoolConfig
from .errors import DEFAULT_RETRY_AFTER_SEC

try:
    VERSION = version("claude-pool")
except PackageNotFoundError:  # running from a source tree without an install
    VERSION = "0+unknown"

SUMMARY = (
    "Local HTTP gateway that exposes the authenticated `claude` CLI as an "
    "LLM endpoint. No API key: it spends the machine owner's Claude "
    "subscription quota."
)

# Kept beside the classifier it mirrors: errors.classify decides these, and a
# caller reading only the docs still needs to know which are worth a retry.
FAILURE_KINDS = [
    {"kind": "pool_unavailable", "status": 503, "retryable": True,
     "meaning": "All workers busy; the same request succeeds once one frees up."},
    {"kind": "rate_limited", "status": 429, "retryable": True,
     "meaning": f"Subscription rate/usage limit. Honour Retry-After "
                f"(default {DEFAULT_RETRY_AFTER_SEC}s)."},
    {"kind": "timeout", "status": 504, "retryable": True,
     "meaning": "The worker exceeded timeout_sec."},
    {"kind": "not_authenticated", "status": 503, "retryable": False,
     "meaning": "The `claude` CLI needs a human to log in again. Do not retry."},
    {"kind": "worker_failed", "status": 502, "retryable": False,
     "meaning": "Any other worker failure; the message carries the CLI's stderr."},
    {"kind": "forbidden_host", "status": 403, "retryable": False,
     "meaning": "Host header was not a loopback literal (DNS-rebinding guard)."},
]

CONSTRAINTS = [
    "Spends the machine owner's Claude subscription quota — check before bulk calls.",
    "No conversation memory: every request gets a fresh worker, by design. "
    "Put all context in the prompt.",
    'No tool use (--tools ""): text generation only, no file access or code execution.',
    "No streaming: the full completion arrives at once — use POST /jobs if you "
    "would rather not hold the connection open.",
    "One model per daemon; run a second daemon on another port for a different model.",
    "Loopback-only and unauthenticated; requests whose Host header is not a "
    "loopback literal are refused.",
]

CURL_EXAMPLE = (
    "curl -s -X POST {base}/generate -H 'Content-Type: application/json' "
    '-d \'{{"prompt": "reply with the single word PONG"}}\''
)

PYTHON_EXAMPLE = (
    "from claude_pool.client import ClaudePoolClient\n"
    "client = ClaudePoolClient()\n"
    "text = client.generate('...')                    # blocks\n"
    "job_id = client.submit('...'); client.wait(job_id)  # runs in the background"
)

# /generate holds the connection open for the whole completion. This is the
# way out for a caller that must not sit on a socket for minutes.
BACKGROUND_EXAMPLE = (
    'curl -s -X POST {base}/jobs -H \'Content-Type: application/json\' '
    '-d \'{{"prompt": "..."}}\'\n'
    '  -> 202 {{"job_id": "abc123", "status": "running"}}\n'
    'curl -s {base}/jobs/abc123\n'
    '  -> {{"status": "succeeded", "text": "...", "duration_ms": 1078}}'
)


def api_info(config: PoolConfig) -> dict:
    """The JSON served at GET / — a README a program can read."""
    base = f"http://{config.host}:{config.port}"
    return {
        "name": "claude-pool",
        "version": VERSION,
        "summary": SUMMARY,
        "base_url": base,
        "endpoints": {
            "POST /generate": "Run one prompt. Body: {prompt: str, timeout_sec?: float}. "
                              "Returns {text, duration_ms}.",
            "POST /jobs": "Same body as /generate, but runs in the background. "
                          "Returns 202 {job_id, status} immediately.",
            "GET /jobs/{job_id}": "Poll one job. Always 200; read `status` "
                                  "(running/succeeded/failed/cancelled).",
            "GET /jobs": "List known jobs, newest first.",
            "DELETE /jobs/{job_id}": "Cancel a running job (kills its worker) "
                                     "or forget a finished one.",
            "GET /health": "Pool state. `idle` is a counter, `idle_alive` is a liveness "
                           "probe; they diverge when pre-warmed workers have died.",
            "GET /": "This document.",
            "GET /docs": "The same, rendered for a browser.",
            "GET /openapi.json": "OpenAPI 3.1 description.",
        },
        "example": {
            "curl": CURL_EXAMPLE.format(base=base),
            "python": PYTHON_EXAMPLE,
            "background": BACKGROUND_EXAMPLE.format(base=base),
        },
        "failure_kinds": FAILURE_KINDS,
        "constraints": CONSTRAINTS,
        "config": {
            "model": config.model,
            "min_workers": config.min_workers,
            "max_workers": config.max_workers,
            "default_timeout_sec": config.default_timeout_sec,
        },
    }


_ERROR_SCHEMA = {
    "type": "object",
    "properties": {
        "error": {"type": "string"},
        "kind": {"type": "string", "enum": [f["kind"] for f in FAILURE_KINDS]},
        "retryable": {"type": "boolean"},
        "duration_ms": {"type": "integer"},
    },
    "required": ["error"],
}

_JSON_ERROR = {"content": {"application/json": {"schema": _ERROR_SCHEMA}}}


def _generate_responses() -> dict:
    """One OpenAPI response per status /generate can return.

    not_authenticated and pool_unavailable share 503, so their descriptions
    are merged rather than one silently overwriting the other.
    """
    responses = {
        "200": {
            "description": "Completion",
            "content": {"application/json": {"schema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "duration_ms": {"type": "integer"},
                },
                "required": ["text", "duration_ms"],
            }}},
        },
        "400": {"description": "Malformed request body", **_JSON_ERROR},
    }
    for failure in FAILURE_KINDS:
        status = str(failure["status"])
        line = f"{failure['kind']}: {failure['meaning']}"
        previous = responses.get(status, {}).get("description")
        responses[status] = {
            "description": f"{previous}\n\n{line}" if previous else line,
            **_JSON_ERROR,
        }
    responses["429"]["headers"] = {
        "Retry-After": {"schema": {"type": "integer"},
                        "description": "Seconds to wait before retrying"}
    }
    return responses


_HEALTH_SCHEMA = {
    "type": "object",
    "properties": {
        "min_workers": {"type": "integer"},
        "max_workers": {"type": "integer"},
        "total": {"type": "integer"},
        "idle": {"type": "integer"},
        "idle_alive": {"type": "integer"},
        "busy": {"type": "integer"},
        "healthy": {"type": "boolean"},
        "jobs": {"type": "object", "properties": {
            "total": {"type": "integer"}, "running": {"type": "integer"}}},
        "last_spawn_error": {"type": ["string", "null"]},
        "last_error": {"type": ["string", "null"]},
    },
}


_JOB_SCHEMA = {
    "type": "object",
    "properties": {
        "job_id": {"type": "string"},
        "status": {"type": "string",
                   "enum": ["running", "succeeded", "failed", "cancelled"]},
        "prompt_preview": {"type": "string"},
        "created_at": {"type": "number"},
        "finished_at": {"type": ["number", "null"]},
        "text": {"type": "string"},
        "duration_ms": {"type": "integer"},
        "error": {"type": "string"},
        "kind": {"type": "string"},
        "retryable": {"type": "boolean"},
    },
    "required": ["job_id", "status"],
}

_JOB_ID_PARAM = {
    "name": "job_id", "in": "path", "required": True,
    "schema": {"type": "string"},
}


def _prompt_body(config: PoolConfig) -> dict:
    return {
        "required": True,
        "content": {"application/json": {"schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "minLength": 1},
                "timeout_sec": {"type": "number", "default": config.default_timeout_sec},
            },
            "required": ["prompt"],
        }}},
    }


def openapi_spec(config: PoolConfig) -> dict:
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "claude-pool",
            "version": VERSION,
            "description": SUMMARY + "\n\nConstraints:\n"
                           + "\n".join(f"- {c}" for c in CONSTRAINTS),
        },
        "servers": [{"url": f"http://{config.host}:{config.port}"}],
        "paths": {
            "/generate": {
                "post": {
                    "summary": "Run one prompt against a pre-warmed worker",
                    "requestBody": _prompt_body(config),
                    "responses": _generate_responses(),
                }
            },
            "/jobs": {
                "post": {
                    "summary": "Submit a prompt to run in the background",
                    "requestBody": _prompt_body(config),
                    "responses": {
                        "202": {
                            "description": "Job accepted; poll GET /jobs/{job_id}",
                            "headers": {"Location": {"schema": {"type": "string"}}},
                            "content": {"application/json": {"schema": _JOB_SCHEMA}},
                        },
                        "400": {"description": "Malformed request body", **_JSON_ERROR},
                        "403": {"description": "Host header is not a loopback literal",
                                **_JSON_ERROR},
                    },
                },
                "get": {
                    "summary": "List known jobs, newest first",
                    "responses": {"200": {
                        "description": "Jobs",
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "properties": {"jobs": {"type": "array",
                                                    "items": _JOB_SCHEMA}},
                        }}},
                    }},
                },
            },
            "/jobs/{job_id}": {
                "get": {
                    "summary": "Poll one job (always 200; read `status`)",
                    "parameters": [_JOB_ID_PARAM],
                    "responses": {
                        "200": {"description": "Job state",
                                "content": {"application/json": {"schema": _JOB_SCHEMA}}},
                        "404": {"description": "No such job", **_JSON_ERROR},
                    },
                },
                "delete": {
                    "summary": "Cancel a running job, or forget a finished one",
                    "parameters": [_JOB_ID_PARAM],
                    "responses": {
                        "200": {"description": "Job after cancellation",
                                "content": {"application/json": {"schema": _JOB_SCHEMA}}},
                        "404": {"description": "No such job", **_JSON_ERROR},
                    },
                },
            },
            "/health": {
                "get": {
                    "summary": "Pool state and worker liveness",
                    "responses": {"200": {
                        "description": "Pool stats",
                        "content": {"application/json": {"schema": _HEALTH_SCHEMA}},
                    }},
                }
            },
            "/": {"get": {"summary": "This API's self-description as JSON",
                          "responses": {"200": {"description": "API info"}}}},
            "/docs": {"get": {"summary": "Human-readable docs",
                              "responses": {"200": {"description": "HTML page"}}}},
            "/openapi.json": {"get": {"summary": "This document",
                                      "responses": {"200": {"description": "OpenAPI 3.1"}}}},
        },
    }


def _failure_table() -> str:
    rows = "".join(
        "<tr>"
        f"<td><code>{html.escape(f['kind'])}</code></td>"
        f"<td>{f['status']}</td>"
        f"<td>{'yes' if f['retryable'] else 'no'}</td>"
        f"<td>{html.escape(f['meaning'])}</td>"
        "</tr>"
        for f in FAILURE_KINDS
    )
    return (
        "<table><thead><tr><th>kind</th><th>HTTP</th><th>Retryable</th>"
        f"<th>Meaning</th></tr></thead><tbody>{rows}</tbody></table>"
    )


def render_html(config: PoolConfig) -> str:
    """A self-contained docs page — no CDN, so it works on an offline box."""
    info = api_info(config)
    base = html.escape(info["base_url"])
    endpoints = "".join(
        f"<tr><td><code>{html.escape(k)}</code></td><td>{html.escape(v)}</td></tr>"
        for k, v in info["endpoints"].items()
    )
    constraints = "".join(f"<li>{html.escape(c)}</li>" for c in CONSTRAINTS)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>claude-pool {html.escape(VERSION)}</title>
<style>
 :root {{ color-scheme: light dark; }}
 body {{ font: 15px/1.6 ui-sans-serif, system-ui, sans-serif; max-width: 62rem;
        margin: 2rem auto; padding: 0 1.25rem; }}
 h1 {{ margin-bottom: .25rem; }}
 h1 small {{ font-weight: 400; opacity: .6; font-size: .55em; }}
 h2 {{ margin-top: 2rem; font-size: 1.1rem; }}
 table {{ border-collapse: collapse; width: 100%; margin: .75rem 0 1.5rem; }}
 th, td {{ text-align: left; padding: .4rem .6rem; border-bottom: 1px solid #8884;
           vertical-align: top; }}
 code, pre {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
 pre {{ background: #8881; padding: .8rem 1rem; border-radius: 6px; overflow-x: auto; }}
 .warn {{ border-left: 3px solid #d97706; padding: .5rem .9rem; background: #d9770615; }}
</style></head><body>
<h1>claude-pool <small>{html.escape(VERSION)}</small></h1>
<p>{html.escape(SUMMARY)}</p>
<p class="warn"><strong>This spends the machine owner's Claude subscription quota.</strong>
   Check with them before issuing bulk requests.</p>

<h2>Endpoints</h2>
<table><thead><tr><th>Endpoint</th><th>Description</th></tr></thead>
<tbody>{endpoints}</tbody></table>

<h2>Example</h2>
<pre>{html.escape(info["example"]["curl"])}
&rarr; {{"text": "PONG", "duration_ms": 1078}}</pre>
<pre>{html.escape(info["example"]["python"])}</pre>

<h3>Background jobs</h3>
<p><code>POST /generate</code> holds the connection open for the whole completion, which
   can be minutes. Submit to <code>/jobs</code> instead to get an id back immediately and
   poll for the result. Same worker lifecycle — only who waits changes.</p>
<pre>{html.escape(info["example"]["background"])}</pre>

<h2>Failures</h2>
<p>The daemon classifies failures but never retries on your behalf — retrying spends
   quota, so that call is yours.</p>
{_failure_table()}

<h2>Constraints</h2>
<ul>{constraints}</ul>

<h2>This daemon</h2>
<table><tbody>
<tr><td>Base URL</td><td><code>{base}</code></td></tr>
<tr><td>Model</td><td><code>{html.escape(config.model)}</code></td></tr>
<tr><td>Workers</td><td>min {config.min_workers} / max {config.max_workers}</td></tr>
<tr><td>Default timeout</td><td>{config.default_timeout_sec}s</td></tr>
</tbody></table>
<p><a href="/openapi.json">openapi.json</a> &middot; <a href="/health">health</a></p>
</body></html>"""
