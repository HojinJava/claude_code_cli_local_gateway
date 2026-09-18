"""Classify a failed `claude` run into something a caller can act on.

A caller has to tell "retry in a minute" apart from "stop, a human has to
log in again" — and getting that wrong is expensive in both directions:
retrying an expired login burns nothing but never succeeds, while giving up
on a limit that clears in a minute throws away a working request.

The verdict is therefore read from the structured fields of the CLI's own
stream-json output, never from the human-readable message. That message is
still passed through to the caller verbatim, but only for a human to read.

Measured against Claude Code 2.1.276 (2026-09-18), see issue #1:

  result line   `api_error_status` carries the HTTP status the Anthropic API
                returned, or null when the CLI failed before reaching it.
                Confirmed 401 against a rejected API key; null on success.
  assistant line `error` carries the CLI's own error code, e.g.
                "authentication_failed", alongside `is_api_error_message`.
                It is the only signal when `api_error_status` is null — which
                is exactly the case of a CLI with no credentials at all.
  NOT usable    `subtype` is "success" even on a failed turn. `stop_reason`
                and `terminal_reason` do not distinguish one API error from
                another.

Unmeasured: the 429/529 values below. Rate limits cannot be provoked on
demand, so they rest on `api_error_status` holding the API's real HTTP
status, which the 401 measurement confirms for one value.

Anything that does not match falls through to WORKER_FAILED. That is the
honest answer: a kind invented from wording would be indistinguishable, to
the caller, from one the daemon actually knows.
"""
from __future__ import annotations

from dataclasses import dataclass

# The CLI reports no reset time anywhere in its output — not on the result
# line, and the `retry_delay_ms` on its own api_retry lines is its internal
# backoff, not the API's Retry-After. So a retryable failure gets this
# conservative floor rather than a number parsed out of a sentence.
DEFAULT_RETRY_AFTER_SEC = 60

# 429 is the API's rate limit; 529 is "overloaded". Both clear on their own.
RATE_LIMIT_STATUSES = frozenset({429, 529})

# 401/403 mean the credentials are the problem. No amount of waiting fixes
# that, so these must never be lumped in with the retryable failures.
AUTH_STATUSES = frozenset({401, 403})

# The CLI's own error code, read off the assistant line. Needed because a CLI
# with no credentials fails before any HTTP status exists (measured).
AUTH_ERROR_CODES = frozenset({"authentication_failed"})


@dataclass(frozen=True)
class Failure:
    """How one failed run should be reported over HTTP."""

    kind: str
    status: int
    retryable: bool
    retry_after_sec: int | None = None


def classify(
    api_error_status: int | None = None,
    api_error_code: str = "",
) -> Failure:
    """Map a failed run's structured values to a Failure. Never raises.

    Called with no arguments for a worker that died without printing a result
    line: there is nothing structured to go on, so it is WORKER_FAILED.
    """
    if api_error_status in RATE_LIMIT_STATUSES:
        # 429 rather than 502: the request was well-formed and the same
        # request will succeed later, which is exactly what 429 means.
        return Failure(
            kind="rate_limited",
            status=429,
            retryable=True,
            retry_after_sec=DEFAULT_RETRY_AFTER_SEC,
        )

    if api_error_status in AUTH_STATUSES or api_error_code in AUTH_ERROR_CODES:
        # Retrying cannot fix this — someone has to re-authenticate the CLI.
        return Failure(kind="not_authenticated", status=503, retryable=False)

    return Failure(kind="worker_failed", status=502, retryable=False)
