"""Test double for the real `claude` CLI. Mimics only the subset of
`claude -p --output-format json` behavior that Worker depends on: block
reading stdin until EOF, then print one JSON result object. Unknown
flags (the real CLI's flags, e.g. --input-format, --tools) are ignored.
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

    prompt = sys.stdin.read()

    if args.fake_delay_sec:
        time.sleep(args.fake_delay_sec)

    if args.fake_mode == "crash":
        print("boom", file=sys.stderr)
        sys.exit(1)

    if args.fake_mode == "error":
        print(json.dumps({"is_error": True, "result": "simulated error", "duration_ms": 1}))
        return

    print(json.dumps({"is_error": False, "result": prompt.strip(), "duration_ms": 1}))


if __name__ == "__main__":
    main()
