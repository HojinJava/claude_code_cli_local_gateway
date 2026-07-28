"""Spike: does pre-spawning `claude -p` and feeding it stdin later actually
skip the boot cost, compared to spawning it fresh per request?

Uses the cheapest model and a 1-token prompt to keep real API cost
negligible. Run manually: python scripts/bench_cold_vs_warm.py
"""
from __future__ import annotations

import asyncio
import json
import statistics
import time

CLAUDE_BIN = "claude"
MODEL = "haiku"
PROMPT = "reply with the single word OK"
ITERATIONS = 10

ARGV = [
    CLAUDE_BIN, "-p",
    "--input-format", "text",
    "--output-format", "json",
    "--no-session-persistence",
    "--tools", "",
    "--strict-mcp-config",
    "--safe-mode",
    "--model", MODEL,
]


async def run_cold() -> float:
    """Spawn fresh, immediately feed stdin, measure total wall time."""
    start = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *ARGV,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_data, stderr_data = await proc.communicate(input=PROMPT.encode())
    elapsed = time.monotonic() - start
    if proc.returncode != 0:
        raise RuntimeError(f"cold run failed: {stderr_data.decode(errors='replace')}")
    json.loads(stdout_data)  # sanity check it's parseable
    return elapsed


async def run_prewarmed(prewarm_settle_sec: float = 1.0) -> float:
    """Spawn ahead of time, wait a beat (simulating it sitting idle in a
    pool), THEN start the timer and feed stdin. Measures only the cost
    paid at the moment a request actually arrives."""
    proc = await asyncio.create_subprocess_exec(
        *ARGV,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await asyncio.sleep(prewarm_settle_sec)
    start = time.monotonic()
    stdout_data, stderr_data = await proc.communicate(input=PROMPT.encode())
    elapsed = time.monotonic() - start
    if proc.returncode != 0:
        raise RuntimeError(f"prewarmed run failed: {stderr_data.decode(errors='replace')}")
    json.loads(stdout_data)
    return elapsed


async def main() -> None:
    cold_times = []
    for i in range(ITERATIONS):
        t = await run_cold()
        print(f"cold[{i}] = {t:.3f}s")
        cold_times.append(t)

    warm_times = []
    for i in range(ITERATIONS):
        t = await run_prewarmed()
        print(f"warm[{i}] = {t:.3f}s")
        warm_times.append(t)

    print("\n--- summary ---")
    print(f"cold  mean={statistics.mean(cold_times):.3f}s  median={statistics.median(cold_times):.3f}s")
    print(f"warm  mean={statistics.mean(warm_times):.3f}s  median={statistics.median(warm_times):.3f}s")


if __name__ == "__main__":
    asyncio.run(main())
