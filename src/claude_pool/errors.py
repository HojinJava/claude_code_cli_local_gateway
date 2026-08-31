"""Classify a failed `claude` run into something a caller can act on.

The CLI reports every failure the same way — a stream-json result line with
`is_error: true`, or a non-zero exit with text on stderr — so without this
step a rate limit, an expired login, and a genuine model error all reach the
caller as one indistinguishable 502. Callers need to tell "retry in a
minute" apart from "stop, a human has to log in again".

Matching is on human-readable message text, so it is deliberately
best-effort: an unrecognised failure falls through to WORKER_FAILED, which
is the same behaviour this module replaced. It never guesses "retryable".
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# The CLI does not report when a limit resets, so a retryable failure that
# carries no wait hint of its own gets this conservative floor instead.
DEFAULT_RETRY_AFTER_SEC = 60

_RATE_LIMIT_PATTERNS = (
    r"rate[ _-]?limit",
    r"too many requests",
    r"\b429\b",
    r"\b529\b",
    r"usage limit",
    r"quota",
    r"overloaded",
    r"\bat capacity\b",
)

_AUTH_PATTERNS = (
    r"not authenticated",
    r"unauthorized",
    r"\b401\b",
    r"\b403\b",
    r"authentication[ _-]?error",
    r"invalid api key",
    r"credit balance",
    r"please run [`/]?login",
    r"/login\b",
    r"log ?in again",
)

# Extracts a wait hint the CLI passed through from the API, e.g.
# "try again in 42 seconds" / "retry after 30s".
_RETRY_AFTER_RE = re.compile(
    r"(?:try again in|retry after|wait)\s+(\d+)\s*(?:s\b|sec|second)", re.IGNORECASE
)


@dataclass(frozen=True)
class Failure:
    """How one failed run should be reported over HTTP."""

    kind: str
    status: int
    retryable: bool
    retry_after_sec: int | None = None


def _matches(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def _retry_after(text: str) -> int:
    match = _RETRY_AFTER_RE.search(text)
    return int(match.group(1)) if match else DEFAULT_RETRY_AFTER_SEC


def classify(text: str) -> Failure:
    """Map a worker's error text to a Failure. Never raises."""
    text = text or ""

    if _matches(text, _RATE_LIMIT_PATTERNS):
        # 429 rather than 502: the request was well-formed and the same
        # request will succeed later, which is exactly what 429 means.
        return Failure(
            kind="rate_limited",
            status=429,
            retryable=True,
            retry_after_sec=_retry_after(text),
        )

    if _matches(text, _AUTH_PATTERNS):
        # Retrying cannot fix this — someone has to re-authenticate the CLI —
        # so it must not be lumped in with the retryable failures.
        return Failure(kind="not_authenticated", status=503, retryable=False)

    return Failure(kind="worker_failed", status=502, retryable=False)
