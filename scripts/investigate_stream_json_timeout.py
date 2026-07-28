"""Investigation: does --input-format stream-json avoid claude -p's ~3s
"no stdin data received, proceeding without it" timeout that plain
--input-format text hits when a pre-warmed worker sits idle before being
fed a prompt?

Uses haiku + a minimal prompt to keep real API cost negligible.
"""
from __future__ import annotations

import asyncio
import json

CLAUDE_BIN = "claude"
MODEL = "haiku"

ARGV = [
    CLAUDE_BIN, "-p",
    "--input-format", "stream-json",
    "--output-format", "stream-json",
    "--verbose",
    "--no-session-persistence",
    "--tools", "",
    "--strict-mcp-config",
    "--safe-mode",
    "--model", MODEL,
]


async def try_delayed_feed(delay_sec: float) -> None:
    print(f"\n=== delay={delay_sec}s ===")
    proc = await asyncio.create_subprocess_exec(
        *ARGV,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await asyncio.sleep(delay_sec)

    message = {
        "type": "user",
        "message": {
            "role": "user",
            "content": "reply with the single word OK",
        },
    }
    payload = (json.dumps(message) + "\n").encode("utf-8")

    try:
        stdout_data, stderr_data = await asyncio.wait_for(
            proc.communicate(input=payload), timeout=30
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        print("TIMED OUT waiting for process to respond")
        return

    print(f"returncode={proc.returncode}")
    print("stdout lines (type field only, plus full 'result' line):")
    for line in stdout_data.decode("utf-8", errors="replace").splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            print("UNPARSEABLE LINE:", line[:300])
            continue
        if obj.get("type") == "result":
            print("RESULT:", json.dumps(obj))
        else:
            print("line type:", obj.get("type"), obj.get("subtype"))
    print("stderr:")
    print(stderr_data.decode("utf-8", errors="replace")[:2000])


async def main() -> None:
    # Delay well past the ~3s threshold observed with plain text mode, and
    # past what a realistic pool idle gap might look like.
    await try_delayed_feed(15.0)


if __name__ == "__main__":
    asyncio.run(main())
