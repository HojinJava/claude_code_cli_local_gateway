"""Test double for the real `claude` CLI. Mimics the subset of
`claude -p --input-format stream-json --output-format stream-json --verbose`
behavior that Worker depends on: read one stream-json user-message line
from stdin (blocking until EOF), then print a stream-json-shaped sequence
of lines ending in one "type":"result" line. Unknown flags (the real
CLI's flags, e.g. --tools, --safe-mode) are ignored.

The line shapes below are trimmed copies of result lines measured against
Claude Code 2.1.276 (see errors.py) — in particular a failing run still
reports `subtype: "success"`, carries the API's HTTP status in
`api_error_status`, and exits 1 *while still printing a result line*.
"""
from __future__ import annotations

import argparse
import json
import sys
import time


def _int_or_none(raw: str) -> int | None:
    return None if raw in ("", "null", "none") else int(raw)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake-mode", choices=["echo", "error", "crash"], default="echo")
    parser.add_argument("--fake-delay-sec", type=float, default=0.0)
    # Lets a test drive the server's failure classification with realistic
    # CLI wording (rate limit, expired login, ...). Wording must never change
    # the verdict — only the structured fields below may.
    parser.add_argument("--fake-error-text", default=None)
    # The structured values classification actually reads: the HTTP status the
    # API returned (result line) and the CLI's own error code (assistant line).
    parser.add_argument("--fake-api-error-status", type=_int_or_none, default=None)
    parser.add_argument("--fake-api-error-code", default=None)
    # The real CLI exits 1 on a failed turn but still prints its result line,
    # so `error` mode does too. Override to pin an exit code explicitly.
    parser.add_argument("--fake-exit-code", type=int, default=None)
    args, _unknown = parser.parse_known_args()

    raw = sys.stdin.read()

    if args.fake_delay_sec:
        time.sleep(args.fake_delay_sec)

    if args.fake_mode == "crash":
        print(args.fake_error_text or "boom", file=sys.stderr)
        sys.exit(args.fake_exit_code if args.fake_exit_code is not None else 1)

    message = json.loads(raw.strip())
    prompt = message["message"]["content"]

    print(json.dumps({"type": "system", "subtype": "init"}))

    if args.fake_mode == "error":
        text = args.fake_error_text or "simulated error"
        if args.fake_api_error_code is not None:
            print(json.dumps({
                "type": "assistant",
                "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
                "error": args.fake_api_error_code,
                "is_api_error_message": True,
            }))
        print(json.dumps({
            "type": "result",
            "subtype": "success",
            "is_error": True,
            "api_error_status": args.fake_api_error_status,
            "terminal_reason": "api_error",
            "result": text,
            "duration_ms": 1,
        }))
        sys.exit(args.fake_exit_code if args.fake_exit_code is not None else 1)

    print(json.dumps({
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "api_error_status": None,
        "terminal_reason": "completed",
        "result": prompt,
        "duration_ms": 1,
    }))
    if args.fake_exit_code:
        sys.exit(args.fake_exit_code)


if __name__ == "__main__":
    main()
