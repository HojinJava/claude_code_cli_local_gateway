"""Test double for the real `claude` CLI. Mimics the subset of
`claude -p --input-format stream-json --output-format stream-json --verbose`
behavior that Worker depends on: read one stream-json user-message line
from stdin (blocking until EOF), then print a stream-json-shaped sequence
of lines ending in one "type":"result" line. Unknown flags (the real
CLI's flags, e.g. --tools, --safe-mode) are ignored.
"""
from __future__ import annotations

import argparse
import json
import sys
import time


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake-mode", choices=["echo", "error", "crash"], default="echo")
    parser.add_argument("--fake-delay-sec", type=float, default=0.0)
    args, _unknown = parser.parse_known_args()

    raw = sys.stdin.read()

    if args.fake_delay_sec:
        time.sleep(args.fake_delay_sec)

    if args.fake_mode == "crash":
        print("boom", file=sys.stderr)
        sys.exit(1)

    message = json.loads(raw.strip())
    prompt = message["message"]["content"]

    print(json.dumps({"type": "system", "subtype": "init"}))

    if args.fake_mode == "error":
        print(json.dumps({"type": "result", "is_error": True, "result": "simulated error", "duration_ms": 1}))
        return

    print(json.dumps({"type": "result", "is_error": False, "result": prompt, "duration_ms": 1}))


if __name__ == "__main__":
    main()
