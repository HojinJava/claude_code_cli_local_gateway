"""Send one prompt to the pool and print the answer.

    python scripts/ask.py "reply with the single word PONG"

Starts the daemon if none is listening, so it works from a cold machine
where a plain `curl` would only get a refused connection. Failures are
reported with the daemon's own classification (`kind`, `retryable`) so a
caller can tell "retry shortly" from "a human has to log in again".
"""
from __future__ import annotations

import sys

from claude_pool.client import ClaudePoolClient, ClaudePoolError

USAGE = 'usage: python scripts/ask.py "<prompt>"'


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    prompt = " ".join(args).strip()
    if not prompt:
        print(USAGE, file=sys.stderr)
        return 2

    try:
        # Auto-start is the point of this launcher: an idle daemon keeps no
        # workers, and a stopped one keeps no port either.
        print(ClaudePoolClient().generate(prompt))
    except ClaudePoolError as exc:
        detail = f"kind={exc.kind} retryable={exc.retryable}"
        if exc.retry_after_sec is not None:
            detail += f" retry_after_sec={exc.retry_after_sec}"
        print(f"{exc} ({detail})", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
