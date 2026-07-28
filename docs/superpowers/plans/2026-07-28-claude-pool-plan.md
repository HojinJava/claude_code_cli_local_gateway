# claude-pool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local HTTP daemon that pre-warms `claude -p` worker processes so Python callers can use Claude Code like a local LLM (stdin prompt in, text out) without per-request boot overhead, while guaranteeing every request is fully isolated from every other.

**Architecture:** A single resident asyncio daemon (`claude_pool.daemon`) owns a `WorkerPool` that keeps `min_workers` one-shot `claude -p` processes idle (stdin open, already authenticated/booted) at all times, growing toward `max_workers` when requests queue and shrinking back to `min_workers` after sustained idle. An `aiohttp` HTTP server exposes `POST /generate` and `GET /health` on `127.0.0.1`. A dependency-free `ClaudePoolClient` (stdlib `urllib` only) auto-starts the daemon if it isn't already running and otherwise just calls the HTTP API.

**Tech Stack:** Python 3.11+, `asyncio` subprocess management, `aiohttp` (server only), stdlib `urllib` (client only), `pytest` + `pytest-asyncio` + `pytest-aiohttp` for tests.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-28-claude-pool-design.md` (read before starting; this plan implements it in full, including the min/max autoscaling and model-override-removed corrections).
- Input to the real `claude` CLI is via stdin only, never argv (argv has length limits on Windows) — worker argv never includes the prompt text itself.
- No auth layer anywhere in this system — HTTP server binds only to `127.0.0.1`; every caller on localhost is trusted.
- Every request must be served by a worker that has processed exactly one request in its lifetime (independent tenant guarantee) — a worker is never reused across requests.
- Worker command line is fixed at process spawn time: `-p --input-format text --output-format json --no-session-persistence --tools "" --strict-mcp-config --safe-mode --model <model>`. Never add `--bare` (breaks OAuth/subscription auth) and never add `--dangerously-skip-permissions` (unnecessary once `--tools ""` disables tool use).
- `model` is fixed per daemon instance (`PoolConfig.model`), not overridable per request (see spec's "검토 후 기각한 대안" follow-up and the model-override fix commit).
- Streaming is out of scope for this plan.
- Target platform is Windows (dev machine); all subprocess/process-group code must work under `asyncio`'s default Windows event loop (`ProactorEventLoop`), which is required for `asyncio.create_subprocess_exec` to work at all on Windows.
- Real `claude` CLI invocations cost real API usage. Every task that needs to exercise process-spawning logic uses the fake CLI test double (`tests/fixtures/fake_claude_cli.py`) instead of the real binary. Only the Task 1 spike and a manual smoke test at the end touch the real `claude` binary, and both use the cheapest available model with a minimal prompt.

---

## Task 1: Validation spike — does pre-warming actually save boot time?

This is a go/no-go gate for the entire design. If pre-warming doesn't save meaningful time, the rest of this plan needs to be revisited with the user before continuing.

**Files:**
- Create: `scripts/bench_cold_vs_warm.py`
- Create: `docs/superpowers/plans/2026-07-28-claude-pool-spike-results.md`

**Interfaces:**
- Produces: no code other tasks depend on — this is a standalone throwaway script. Its only output that matters is the recorded findings doc and the go/no-go decision.

- [ ] **Step 1: Write the benchmark script**

```python
# scripts/bench_cold_vs_warm.py
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
```

- [ ] **Step 2: Run it**

Run: `python scripts/bench_cold_vs_warm.py`

This makes 20 real Claude Code calls (10 cold + 10 pre-warmed) using `haiku` and a 1-token prompt — cost should be a few cents at most. Capture the full console output.

- [ ] **Step 3: Record the findings**

Write the raw output and summary into `docs/superpowers/plans/2026-07-28-claude-pool-spike-results.md`, including the mean/median for both candidates and a explicit **GO** or **NO-GO** line.

**Decision rule:** GO if `warm mean` is at least 20% lower than `cold mean` (or saves at least 200ms in absolute terms, whichever is the more meaningful signal given the numbers). NO-GO otherwise.

- If **GO**: continue to Task 2.
- If **NO-GO**: stop here. Do not proceed to Task 2. Report the numbers back to the user — the pre-warmed pool design's core premise doesn't hold, and the architecture needs to be revisited (e.g., the boot cost may be dominated by something that happens on every stdin write regardless of prior process age, such as a per-turn auth handshake).

- [ ] **Step 4: Commit**

```bash
git add scripts/bench_cold_vs_warm.py docs/superpowers/plans/2026-07-28-claude-pool-spike-results.md
git commit -m "spike: validate pre-warm saves boot time vs cold spawn"
```

---

## Task 2: Project scaffolding and config module

**Files:**
- Create: `pyproject.toml`
- Create: `src/claude_pool/__init__.py`
- Create: `src/claude_pool/config.py`
- Test: `tests/test_config.py`
- Create: `tests/fixtures/__init__.py` (empty, makes it an importable package for later tasks)

**Interfaces:**
- Produces: `PoolConfig` dataclass with fields `min_workers: int`, `max_workers: int`, `model: str`, `host: str`, `port: int`, `default_timeout_sec: float`, `idle_timeout_sec: float`, `scale_down_interval_sec: float`, `scratch_dir: Path`, `claude_cmd: list[str]`, and classmethod `PoolConfig.from_env() -> PoolConfig`.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "claude-pool"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "aiohttp>=3.9",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-aiohttp>=1.0",
]

[project.scripts]
claude-pool-daemon = "claude_pool.daemon:main"

[tool.pytest.ini_options]
asyncio_mode = "auto"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 2: Create the package skeleton**

```bash
mkdir -p src/claude_pool tests/fixtures
touch src/claude_pool/__init__.py tests/fixtures/__init__.py tests/__init__.py
```

- [ ] **Step 3: Write the failing test**

```python
# tests/test_config.py
import os
from pathlib import Path

from claude_pool.config import PoolConfig


def test_defaults():
    config = PoolConfig()
    assert config.min_workers == 4
    assert config.max_workers == 30
    assert config.model == "sonnet"
    assert config.host == "127.0.0.1"
    assert config.port == 8756
    assert config.claude_cmd == ["claude"]


def test_from_env_reads_overrides(monkeypatch):
    monkeypatch.setenv("CLAUDE_POOL_MIN_WORKERS", "2")
    monkeypatch.setenv("CLAUDE_POOL_MAX_WORKERS", "8")
    monkeypatch.setenv("CLAUDE_POOL_PORT", "9999")
    monkeypatch.setenv("CLAUDE_POOL_CLAUDE_CMD_JSON", '["python", "fake.py"]')
    config = PoolConfig.from_env()
    assert config.min_workers == 2
    assert config.max_workers == 8
    assert config.port == 9999
    assert config.claude_cmd == ["python", "fake.py"]
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_pool'`

- [ ] **Step 5: Install the package in editable mode**

```bash
pip install -e ".[dev]"
```

- [ ] **Step 6: Write the implementation**

```python
# src/claude_pool/config.py
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PoolConfig:
    min_workers: int = 4
    max_workers: int = 30
    model: str = "sonnet"
    host: str = "127.0.0.1"
    port: int = 8756
    default_timeout_sec: float = 120.0
    idle_timeout_sec: float = 60.0
    scale_down_interval_sec: float = 30.0
    scratch_dir: Path = field(
        default_factory=lambda: Path.home() / ".claude-pool" / "scratch"
    )
    claude_cmd: list[str] = field(default_factory=lambda: ["claude"])

    @classmethod
    def from_env(cls) -> "PoolConfig":
        claude_cmd_json = os.environ.get("CLAUDE_POOL_CLAUDE_CMD_JSON")
        claude_cmd = json.loads(claude_cmd_json) if claude_cmd_json else ["claude"]
        return cls(
            min_workers=int(os.environ.get("CLAUDE_POOL_MIN_WORKERS", 4)),
            max_workers=int(os.environ.get("CLAUDE_POOL_MAX_WORKERS", 30)),
            model=os.environ.get("CLAUDE_POOL_MODEL", "sonnet"),
            host=os.environ.get("CLAUDE_POOL_HOST", "127.0.0.1"),
            port=int(os.environ.get("CLAUDE_POOL_PORT", 8756)),
            default_timeout_sec=float(os.environ.get("CLAUDE_POOL_TIMEOUT_SEC", 120.0)),
            idle_timeout_sec=float(os.environ.get("CLAUDE_POOL_IDLE_TIMEOUT_SEC", 60.0)),
            scale_down_interval_sec=float(
                os.environ.get("CLAUDE_POOL_SCALE_DOWN_INTERVAL_SEC", 30.0)
            ),
            claude_cmd=claude_cmd,
        )
```

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml src/claude_pool tests
git commit -m "feat: add project scaffolding and PoolConfig"
```

---

## Task 3: Fake CLI test double

**Files:**
- Create: `tests/fixtures/fake_claude_cli.py`
- Test: `tests/fixtures/test_fake_claude_cli.py`

**Interfaces:**
- Consumes: nothing (standalone script).
- Produces: a script invocable as `[sys.executable, path_to_this_file, "--fake-mode", "echo"|"error"|"crash", "--fake-delay-sec", "<float>"]` that reads all of stdin, then either prints a JSON object shaped like `claude -p --output-format json`'s real result (`{"is_error": bool, "result": str, "duration_ms": int}`) or exits non-zero (for `crash` mode). All later tasks that need a `claude` stand-in point `PoolConfig.claude_cmd` at `[sys.executable, str(FAKE_CLI_PATH), ...]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/fixtures/test_fake_claude_cli.py
import json
import subprocess
import sys
from pathlib import Path

FAKE_CLI = Path(__file__).parent / "fake_claude_cli.py"


def _run(args, stdin_text):
    return subprocess.run(
        [sys.executable, str(FAKE_CLI), *args],
        input=stdin_text.encode(),
        capture_output=True,
    )


def test_echo_mode_returns_stdin_as_result():
    proc = _run(["--fake-mode", "echo"], "hello world")
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["is_error"] is False
    assert payload["result"] == "hello world"


def test_error_mode_sets_is_error_true():
    proc = _run(["--fake-mode", "error"], "anything")
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["is_error"] is True


def test_crash_mode_exits_nonzero():
    proc = _run(["--fake-mode", "crash"], "anything")
    assert proc.returncode != 0


def test_ignores_real_cli_flags_it_does_not_know_about():
    proc = _run(
        ["--input-format", "text", "--output-format", "json", "--tools", "",
         "--fake-mode", "echo"],
        "still works",
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["result"] == "still works"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/fixtures/test_fake_claude_cli.py -v`
Expected: FAIL — `fake_claude_cli.py` doesn't exist yet.

- [ ] **Step 3: Write the implementation**

```python
# tests/fixtures/fake_claude_cli.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/fixtures/test_fake_claude_cli.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures
git commit -m "test: add fake claude CLI test double"
```

---

## Task 4: Worker

**Files:**
- Create: `src/claude_pool/worker.py`
- Test: `tests/test_worker.py`

**Interfaces:**
- Consumes: `PoolConfig` from Task 2, fake CLI from Task 3 (test-only).
- Produces: `class WorkerState(Enum)` with values `STARTING`, `IDLE`, `BUSY`, `DONE`; `class WorkerError(Exception)`; `class Worker` with `__init__(self, config: PoolConfig)`, `async def start(self) -> None`, `def is_alive(self) -> bool`, `async def run(self, prompt: str, timeout_sec: float) -> dict` (returns `{"text": str, "duration_ms": int, "is_error": bool}`, raises `WorkerError` on non-zero exit or bad JSON, raises `asyncio.TimeoutError` on timeout), `async def kill(self) -> None`, and public attribute `became_idle_at: float` (set by `start()`, a `time.monotonic()` value).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_worker.py
import asyncio
import sys
from pathlib import Path

import pytest

from claude_pool.config import PoolConfig
from claude_pool.worker import Worker, WorkerError, WorkerState

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_claude_cli.py"


def make_config(tmp_path, *fake_args, **overrides):
    defaults = dict(
        scratch_dir=tmp_path,
        claude_cmd=[sys.executable, str(FAKE_CLI), *fake_args],
    )
    defaults.update(overrides)
    return PoolConfig(**defaults)


async def test_start_puts_worker_in_idle_state(tmp_path):
    worker = Worker(make_config(tmp_path, "--fake-mode", "echo"))
    await worker.start()
    try:
        assert worker.state == WorkerState.IDLE
        assert worker.is_alive()
        assert worker.became_idle_at > 0
    finally:
        await worker.kill()


async def test_run_returns_parsed_result(tmp_path):
    worker = Worker(make_config(tmp_path, "--fake-mode", "echo"))
    await worker.start()
    result = await worker.run("hello", timeout_sec=5.0)
    assert result == {"text": "hello", "duration_ms": 1, "is_error": False}
    assert worker.state == WorkerState.DONE
    assert not worker.is_alive()


async def test_run_raises_on_error_flagged_result(tmp_path):
    worker = Worker(make_config(tmp_path, "--fake-mode", "error"))
    await worker.start()
    result = await worker.run("hello", timeout_sec=5.0)
    assert result["is_error"] is True


async def test_run_raises_worker_error_on_crash(tmp_path):
    worker = Worker(make_config(tmp_path, "--fake-mode", "crash"))
    await worker.start()
    with pytest.raises(WorkerError):
        await worker.run("hello", timeout_sec=5.0)


async def test_run_raises_timeout_and_kills_process(tmp_path):
    worker = Worker(make_config(tmp_path, "--fake-delay-sec", "5.0"))
    await worker.start()
    with pytest.raises(asyncio.TimeoutError):
        await worker.run("hello", timeout_sec=0.2)
    assert not worker.is_alive()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_worker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_pool.worker'`

- [ ] **Step 3: Write the implementation**

```python
# src/claude_pool/worker.py
from __future__ import annotations

import asyncio
import json
import time
from enum import Enum

from .config import PoolConfig


class WorkerState(Enum):
    STARTING = "starting"
    IDLE = "idle"
    BUSY = "busy"
    DONE = "done"


class WorkerError(Exception):
    """Raised when a worker process exits non-zero or returns unparsable output."""


class Worker:
    def __init__(self, config: PoolConfig):
        self.config = config
        self.state = WorkerState.STARTING
        self.became_idle_at: float = 0.0
        self._proc: asyncio.subprocess.Process | None = None

    def _build_argv(self) -> list[str]:
        return [
            *self.config.claude_cmd,
            "-p",
            "--input-format", "text",
            "--output-format", "json",
            "--no-session-persistence",
            "--tools", "",
            "--strict-mcp-config",
            "--safe-mode",
            "--model", self.config.model,
        ]

    async def start(self) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            *self._build_argv(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.config.scratch_dir),
        )
        self.state = WorkerState.IDLE
        self.became_idle_at = time.monotonic()

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def run(self, prompt: str, timeout_sec: float) -> dict:
        if self._proc is None:
            raise WorkerError("worker not started")
        self.state = WorkerState.BUSY
        try:
            stdout_data, stderr_data = await asyncio.wait_for(
                self._proc.communicate(input=prompt.encode("utf-8")),
                timeout=timeout_sec,
            )
        except asyncio.TimeoutError:
            await self.kill()
            raise
        finally:
            self.state = WorkerState.DONE

        if self._proc.returncode != 0:
            raise WorkerError(
                f"worker exited with code {self._proc.returncode}: "
                f"{stderr_data.decode('utf-8', errors='replace')}"
            )
        try:
            payload = json.loads(stdout_data.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise WorkerError(f"invalid worker output: {exc}") from exc
        return {
            "text": payload.get("result", ""),
            "duration_ms": payload.get("duration_ms", 0),
            "is_error": bool(payload.get("is_error", False)),
        }

    async def kill(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            self._proc.kill()
            await self._proc.wait()
        self.state = WorkerState.DONE
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_worker.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/claude_pool/worker.py tests/test_worker.py
git commit -m "feat: add Worker — one-shot claude -p process wrapper"
```

---

## Task 5: WorkerPool with min-baseline and manual scale-up/down

**Files:**
- Create: `src/claude_pool/pool.py`
- Test: `tests/test_pool.py`

**Interfaces:**
- Consumes: `Worker`, `WorkerState` from Task 4; `PoolConfig` from Task 2.
- Produces: `class WorkerPool` with `__init__(self, config: PoolConfig)`, `async def start(self) -> None` (primes `min_workers` idle workers and launches the background scale-down loop), `async def acquire(self) -> Worker`, `async def release(self, worker: Worker) -> None`, `def stats(self) -> dict` (returns `{"min_workers": int, "max_workers": int, "total": int, "idle": int, "busy": int}`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pool.py
import asyncio
import sys
from pathlib import Path

from claude_pool.config import PoolConfig
from claude_pool.pool import WorkerPool

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_claude_cli.py"


def make_config(tmp_path, **overrides):
    defaults = dict(
        min_workers=2,
        max_workers=4,
        scratch_dir=tmp_path,
        claude_cmd=[sys.executable, str(FAKE_CLI), "--fake-mode", "echo"],
        idle_timeout_sec=0.2,
        scale_down_interval_sec=0.1,
    )
    defaults.update(overrides)
    return PoolConfig(**defaults)


async def test_start_primes_min_workers(tmp_path):
    pool = WorkerPool(make_config(tmp_path))
    await pool.start()
    stats = pool.stats()
    assert stats["total"] == 2
    assert stats["idle"] == 2
    assert stats["busy"] == 0


async def test_acquire_and_release_serves_one_request_then_replenishes(tmp_path):
    pool = WorkerPool(make_config(tmp_path))
    await pool.start()

    worker = await pool.acquire()
    assert pool.stats()["busy"] == 1
    result = await worker.run("hi", timeout_sec=5.0)
    assert result["text"] == "hi"
    await pool.release(worker)

    stats = pool.stats()
    assert stats["total"] == 2  # replenished back to min_workers
    assert stats["busy"] == 0


async def test_acquire_beyond_idle_capacity_grows_and_waits(tmp_path):
    pool = WorkerPool(make_config(tmp_path, min_workers=1, max_workers=3))
    await pool.start()

    w1 = await pool.acquire()  # consumes the only idle worker, triggers growth
    w2 = await pool.acquire()  # should be satisfied by the grown worker
    assert pool.stats()["total"] <= 3
    assert pool.stats()["busy"] == 2

    await pool.release(w1)
    await pool.release(w2)


async def test_acquire_never_exceeds_max_workers(tmp_path):
    pool = WorkerPool(make_config(tmp_path, min_workers=1, max_workers=2))
    await pool.start()

    acquired = [await pool.acquire(), await pool.acquire()]
    assert pool.stats()["total"] == 2

    # a third acquire must wait — prove it doesn't exceed max by racing
    # it against a short timeout and confirming it hasn't resolved yet
    third = asyncio.ensure_future(pool.acquire())
    await asyncio.sleep(0.1)
    assert not third.done()
    assert pool.stats()["total"] == 2

    await pool.release(acquired[0])
    worker3 = await asyncio.wait_for(third, timeout=5.0)
    await pool.release(worker3)
    await pool.release(acquired[1])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pool.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_pool.pool'`

- [ ] **Step 3: Write the implementation (without scale-down loop yet — that's Task 6)**

```python
# src/claude_pool/pool.py
from __future__ import annotations

import asyncio
import time
from collections import deque

from .config import PoolConfig
from .worker import Worker


class WorkerPool:
    def __init__(self, config: PoolConfig):
        self.config = config
        self._idle: deque[Worker] = deque()
        self._total = 0
        self._cond = asyncio.Condition()

    async def start(self) -> None:
        async with self._cond:
            for _ in range(self.config.min_workers):
                await self._spawn_and_add_idle_locked()

    async def _spawn_and_add_idle_locked(self) -> None:
        """Caller must hold self._cond."""
        worker = Worker(self.config)
        await worker.start()
        self._idle.append(worker)
        self._total += 1
        self._cond.notify()

    async def acquire(self) -> Worker:
        async with self._cond:
            if not self._idle and self._total < self.config.max_workers:
                asyncio.ensure_future(self._grow_by_one())
            while not self._idle:
                await self._cond.wait()
            return self._idle.popleft()

    async def _grow_by_one(self) -> None:
        async with self._cond:
            if self._total >= self.config.max_workers:
                return
            await self._spawn_and_add_idle_locked()

    async def release(self, worker: Worker) -> None:
        async with self._cond:
            self._total -= 1
            if self._total < self.config.min_workers:
                await self._spawn_and_add_idle_locked()

    def stats(self) -> dict:
        busy = self._total - len(self._idle)
        return {
            "min_workers": self.config.min_workers,
            "max_workers": self.config.max_workers,
            "total": self._total,
            "idle": len(self._idle),
            "busy": busy,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pool.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/claude_pool/pool.py tests/test_pool.py
git commit -m "feat: add WorkerPool with min-baseline replenish and scale-up-on-queue"
```

---

## Task 6: Scale-down loop

**Files:**
- Modify: `src/claude_pool/pool.py`
- Test: `tests/test_pool.py` (add cases)

**Interfaces:**
- Consumes: existing `WorkerPool` from Task 5.
- Produces: `async def start(self) -> None` now also launches a background scale-down task; adds no new public methods, but `Worker.became_idle_at` (from Task 4) is now read by the pool.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pool.py`:

```python
async def test_scale_down_shrinks_idle_workers_back_to_min(tmp_path):
    pool = WorkerPool(make_config(tmp_path, min_workers=1, max_workers=3))
    await pool.start()

    w1 = await pool.acquire()  # forces growth to 2 total
    w2 = await pool.acquire()  # forces growth to 3 total (still under max? min=1,max=3 -> ok)
    await pool.release(w1)
    await pool.release(w2)

    # right after release, replenish-to-min may have already run, but the
    # grown extras should still be sitting idle above min_workers
    assert pool.stats()["total"] >= pool.config.min_workers

    # idle_timeout_sec=0.2 and scale_down_interval_sec=0.1 in make_config —
    # wait past both so the sweep has a chance to run and trim excess idle
    await asyncio.sleep(0.6)
    assert pool.stats()["total"] == pool.config.min_workers
    assert pool.stats()["idle"] == pool.config.min_workers
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pool.py -v -k scale_down`
Expected: FAIL — pool never shrinks back below its post-growth total (no scale-down loop yet).

- [ ] **Step 3: Implement the scale-down loop**

```python
# src/claude_pool/pool.py — add imports and methods
```

Add `import time` is already present from Task 5's file if not, add it. Update the file:

```python
    async def start(self) -> None:
        async with self._cond:
            for _ in range(self.config.min_workers):
                await self._spawn_and_add_idle_locked()
        asyncio.ensure_future(self._scale_down_loop())

    async def _scale_down_loop(self) -> None:
        while True:
            await asyncio.sleep(self.config.scale_down_interval_sec)
            async with self._cond:
                now = time.monotonic()
                excess_allowed = max(0, len(self._idle) - self.config.min_workers)
                survivors: deque[Worker] = deque()
                to_kill: list[Worker] = []
                for w in self._idle:
                    if (
                        len(to_kill) < excess_allowed
                        and (now - w.became_idle_at) > self.config.idle_timeout_sec
                    ):
                        to_kill.append(w)
                    else:
                        survivors.append(w)
                self._idle = survivors
                self._total -= len(to_kill)
            for w in to_kill:
                await w.kill()
```

Insert `_scale_down_loop` as a new method on `WorkerPool`, and change `start()` to call it, per the snippet above (the full file now has `start`, `_spawn_and_add_idle_locked`, `acquire`, `_grow_by_one`, `release`, `_scale_down_loop`, `stats`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pool.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/claude_pool/pool.py tests/test_pool.py
git commit -m "feat: shrink idle workers back to min_workers after sustained idle"
```

---

## Task 7: HTTP server

**Files:**
- Create: `src/claude_pool/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `WorkerPool`, `WorkerError` from Tasks 4-6.
- Produces: `def create_app(pool: WorkerPool) -> aiohttp.web.Application`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_server.py
import sys
from pathlib import Path

import pytest

from claude_pool.config import PoolConfig
from claude_pool.pool import WorkerPool
from claude_pool.server import create_app

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_claude_cli.py"


def make_config(tmp_path, **overrides):
    defaults = dict(
        min_workers=1,
        max_workers=2,
        scratch_dir=tmp_path,
        claude_cmd=[sys.executable, str(FAKE_CLI), "--fake-mode", "echo"],
    )
    defaults.update(overrides)
    return PoolConfig(**defaults)


@pytest.fixture
async def client(aiohttp_client, tmp_path):
    pool = WorkerPool(make_config(tmp_path))
    await pool.start()
    app = create_app(pool)
    return await aiohttp_client(app)


async def test_generate_returns_text(client):
    resp = await client.post("/generate", json={"prompt": "hello"})
    assert resp.status == 200
    data = await resp.json()
    assert data["text"] == "hello"
    assert "duration_ms" in data


async def test_generate_requires_prompt(client):
    resp = await client.post("/generate", json={})
    assert resp.status == 400
    data = await resp.json()
    assert "error" in data


async def test_generate_rejects_invalid_json(client):
    resp = await client.post("/generate", data="not json", headers={"Content-Type": "application/json"})
    assert resp.status == 400


async def test_health_reports_pool_stats(client):
    resp = await client.get("/health")
    assert resp.status == 200
    data = await resp.json()
    assert data["min_workers"] == 1
    assert data["max_workers"] == 2
    assert "idle" in data and "busy" in data


async def test_generate_surfaces_worker_error(aiohttp_client, tmp_path):
    pool = WorkerPool(make_config(tmp_path, claude_cmd=[sys.executable, str(FAKE_CLI), "--fake-mode", "crash"]))
    await pool.start()
    app = create_app(pool)
    client = await aiohttp_client(app)
    resp = await client.post("/generate", json={"prompt": "hello"})
    assert resp.status == 502
    data = await resp.json()
    assert "error" in data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_pool.server'`

- [ ] **Step 3: Write the implementation**

```python
# src/claude_pool/server.py
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

    prompt = body.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        return web.json_response({"error": "'prompt' is required"}, status=400)
    timeout_sec = float(body.get("timeout_sec", pool.config.default_timeout_sec))

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_server.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/claude_pool/server.py tests/test_server.py
git commit -m "feat: add aiohttp server exposing /generate and /health"
```

---

## Task 8: Daemon entrypoint

**Files:**
- Create: `src/claude_pool/daemon.py`
- Test: `tests/test_daemon.py`

**Interfaces:**
- Consumes: `PoolConfig`, `WorkerPool`, `create_app` from prior tasks.
- Produces: `async def run_daemon(config: PoolConfig) -> None` (never returns — runs until cancelled) and `def main() -> None` (the `claude-pool-daemon` console-script entrypoint, reads config via `PoolConfig.from_env()`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_daemon.py
import asyncio
import sys
from pathlib import Path

import pytest
from aiohttp import ClientSession

from claude_pool.config import PoolConfig
from claude_pool.daemon import run_daemon

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_claude_cli.py"


async def test_run_daemon_serves_generate_requests(tmp_path, unused_tcp_port):
    config = PoolConfig(
        min_workers=1,
        max_workers=2,
        host="127.0.0.1",
        port=unused_tcp_port,
        scratch_dir=tmp_path,
        claude_cmd=[sys.executable, str(FAKE_CLI), "--fake-mode", "echo"],
    )
    task = asyncio.ensure_future(run_daemon(config))
    try:
        async with ClientSession() as session:
            for _ in range(50):
                try:
                    async with session.get(f"http://127.0.0.1:{config.port}/health") as resp:
                        if resp.status == 200:
                            break
                except Exception:
                    pass
                await asyncio.sleep(0.1)
            else:
                pytest.fail("daemon never became healthy")

            async with session.post(
                f"http://127.0.0.1:{config.port}/generate", json={"prompt": "hi"}
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["text"] == "hi"
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
```

`unused_tcp_port` is provided by `pytest-asyncio`'s companion fixtures via `aiohttp`'s pytest plugin; if it isn't available in this environment, add a small local fixture instead (see Step 3b below).

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_daemon.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_pool.daemon'`

- [ ] **Step 3: Write the implementation**

```python
# src/claude_pool/daemon.py
from __future__ import annotations

import asyncio

from aiohttp import web

from .config import PoolConfig
from .pool import WorkerPool
from .server import create_app


async def run_daemon(config: PoolConfig) -> None:
    config.scratch_dir.mkdir(parents=True, exist_ok=True)
    pool = WorkerPool(config)
    await pool.start()
    app = create_app(pool)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=config.host, port=config.port)
    await site.start()
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await runner.cleanup()


def main() -> None:
    config = PoolConfig.from_env()
    asyncio.run(run_daemon(config))


if __name__ == "__main__":
    main()
```

- [ ] **Step 3b: If `unused_tcp_port` isn't available, add a local fixture**

Add to `tests/conftest.py` (create the file if it doesn't exist):

```python
# tests/conftest.py
import socket

import pytest


@pytest.fixture
def unused_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_daemon.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add src/claude_pool/daemon.py tests/test_daemon.py tests/conftest.py
git commit -m "feat: add daemon entrypoint wiring pool + server together"
```

---

## Task 9: Client library

**Files:**
- Create: `src/claude_pool/client.py`
- Test: `tests/test_client.py`

**Interfaces:**
- Consumes: nothing from earlier tasks at import time (deliberately dependency-free of `aiohttp`/`asyncio` internals — it only needs `daemon.py` to exist as a module path for `python -m claude_pool.daemon`). Tests exercise it against a real running daemon (spawned via Task 8's `run_daemon`, in a background thread, pointed at the fake CLI).
- Produces: `class ClaudePoolError(Exception)`; `class ClaudePoolClient` with `__init__(self, host="127.0.0.1", port=8756, auto_start=True, start_timeout_sec=15.0)`, `def generate(self, prompt: str, timeout_sec: float | None = None) -> str`, `def health(self) -> dict`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_client.py
import asyncio
import json
import sys
import threading
import time
from pathlib import Path

import pytest

from claude_pool.client import ClaudePoolClient, ClaudePoolError
from claude_pool.config import PoolConfig
from claude_pool.daemon import run_daemon

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_claude_cli.py"


def _run_daemon_in_thread(config: PoolConfig) -> None:
    def target():
        asyncio.run(run_daemon(config))
    t = threading.Thread(target=target, daemon=True)
    t.start()


@pytest.fixture
def running_daemon(tmp_path, unused_tcp_port):
    config = PoolConfig(
        min_workers=1,
        max_workers=2,
        port=unused_tcp_port,
        scratch_dir=tmp_path,
        claude_cmd=[sys.executable, str(FAKE_CLI), "--fake-mode", "echo"],
    )
    _run_daemon_in_thread(config)
    deadline = time.monotonic() + 5.0
    client = ClaudePoolClient(port=config.port, auto_start=False)
    while time.monotonic() < deadline:
        try:
            client.health()
            break
        except Exception:
            time.sleep(0.1)
    return config.port


def test_client_generate_returns_text(running_daemon):
    client = ClaudePoolClient(port=running_daemon, auto_start=False)
    text = client.generate("hello there")
    assert text == "hello there"


def test_client_health_reports_stats(running_daemon):
    client = ClaudePoolClient(port=running_daemon, auto_start=False)
    stats = client.health()
    assert stats["min_workers"] == 1


def test_client_raises_on_missing_daemon_when_auto_start_disabled():
    with pytest.raises(Exception):
        ClaudePoolClient(port=1, auto_start=False).health()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_pool.client'`

- [ ] **Step 3: Write the implementation**

```python
# src/claude_pool/client.py
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request


class ClaudePoolError(Exception):
    pass


class ClaudePoolClient:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8756,
        auto_start: bool = True,
        start_timeout_sec: float = 15.0,
    ):
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        if auto_start and not self._is_healthy():
            self._start_daemon()
            self._wait_until_healthy(start_timeout_sec)

    def _is_healthy(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base_url}/health", timeout=1.0):
                return True
        except (urllib.error.URLError, OSError, TimeoutError):
            return False

    def _start_daemon(self) -> None:
        kwargs: dict = dict(
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        if sys.platform == "win32":
            kwargs["creationflags"] = (
                subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            )
        subprocess.Popen([sys.executable, "-m", "claude_pool.daemon"], **kwargs)

    def _wait_until_healthy(self, timeout_sec: float) -> None:
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            if self._is_healthy():
                return
            time.sleep(0.2)
        raise ClaudePoolError("daemon did not become healthy in time")

    def generate(self, prompt: str, timeout_sec: float | None = None) -> str:
        payload: dict = {"prompt": prompt}
        if timeout_sec is not None:
            payload["timeout_sec"] = timeout_sec
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        request_timeout = (timeout_sec or 120.0) + 5.0
        try:
            with urllib.request.urlopen(req, timeout=request_timeout) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read())
            raise ClaudePoolError(body.get("error", "unknown error")) from exc
        return body["text"]

    def health(self) -> dict:
        with urllib.request.urlopen(f"{self.base_url}/health", timeout=5.0) as resp:
            return json.loads(resp.read())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_client.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/claude_pool/client.py tests/test_client.py
git commit -m "feat: add dependency-free ClaudePoolClient with daemon auto-start"
```

---

## Task 10: End-to-end isolation and autoscaling integration test

**Files:**
- Create: `tests/test_integration.py`

**Interfaces:**
- Consumes: everything from Tasks 2-9. No new production code — this task only adds tests that exercise the full stack together.

- [ ] **Step 1: Write the isolation test**

```python
# tests/test_integration.py
import asyncio
import sys
import time
from pathlib import Path

import pytest

from claude_pool.config import PoolConfig
from claude_pool.pool import WorkerPool
from claude_pool.server import create_app

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_claude_cli.py"


async def test_concurrent_requests_do_not_bleed_context(aiohttp_client, tmp_path):
    config = PoolConfig(
        min_workers=2,
        max_workers=4,
        scratch_dir=tmp_path,
        claude_cmd=[sys.executable, str(FAKE_CLI), "--fake-mode", "echo"],
    )
    pool = WorkerPool(config)
    await pool.start()
    app = create_app(pool)
    client = await aiohttp_client(app)

    prompts = [f"unique-prompt-{i}" for i in range(6)]
    responses = await asyncio.gather(
        *[client.post("/generate", json={"prompt": p}) for p in prompts]
    )
    bodies = await asyncio.gather(*[r.json() for r in responses])
    returned_texts = {b["text"] for b in bodies}
    assert returned_texts == set(prompts)


async def test_burst_scales_up_and_idle_scales_back_down(aiohttp_client, tmp_path):
    config = PoolConfig(
        min_workers=1,
        max_workers=4,
        scratch_dir=tmp_path,
        claude_cmd=[sys.executable, str(FAKE_CLI), "--fake-mode", "echo", "--fake-delay-sec", "0.3"],
        idle_timeout_sec=0.2,
        scale_down_interval_sec=0.1,
    )
    pool = WorkerPool(config)
    await pool.start()
    app = create_app(pool)
    client = await aiohttp_client(app)

    burst = [client.post("/generate", json={"prompt": f"p{i}"}) for i in range(4)]
    # give requests a moment to be admitted and trigger growth before they all finish
    await asyncio.sleep(0.15)
    assert pool.stats()["total"] > config.min_workers

    responses = await asyncio.gather(*burst)
    assert all(r.status == 200 for r in responses)

    await asyncio.sleep(0.6)  # past idle_timeout_sec + scale_down_interval_sec
    assert pool.stats()["total"] == config.min_workers
```

- [ ] **Step 2: Run tests to verify they fail (or pass) as a real check**

Run: `pytest tests/test_integration.py -v`
Expected: PASS if Tasks 2-9 are correctly implemented — this task adds no new implementation, so a failure here means a bug in an earlier task, not a missing implementation. Investigate and fix the earlier task's code if either test fails.

- [ ] **Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: verify request isolation and min/max autoscaling end-to-end"
```

---

## Task 11: Manual smoke test against the real `claude` CLI

This task is manual (not automated in CI) because it costs real API usage and depends on the developer's machine having authenticated `claude` CLI access.

**Files:** none created or modified.

- [ ] **Step 1: Start the real daemon**

```bash
python -m claude_pool.daemon
```

(Uses `PoolConfig.from_env()` defaults: `min_workers=4`, `model="sonnet"`, real `claude` binary — no env overrides set.)

- [ ] **Step 2: Check health in another terminal**

```bash
curl http://127.0.0.1:8756/health
```

Expected: JSON with `"idle": 4, "busy": 0, "total": 4` (or close to it, allowing for startup timing).

- [ ] **Step 3: Send a real request**

```bash
curl -X POST http://127.0.0.1:8756/generate -H "Content-Type: application/json" -d "{\"prompt\": \"reply with the single word PONG\"}"
```

Expected: `{"text": "PONG", "duration_ms": <number>}` (allow for minor variation in exact wording since this is a real model call, not a fixed fake).

- [ ] **Step 4: Confirm independent tenancy manually**

Send two requests with contradictory instructions back to back (e.g., one that says "the secret number is 7, remember it" and a second, unrelated one that asks "what secret number did I just tell you?"). Expected: the second response shows no awareness of the first request's "secret number" — proving there's no session bleed between requests.

- [ ] **Step 5: Stop the daemon**

`Ctrl+C` in the terminal running `python -m claude_pool.daemon`.

No commit for this task — it's a verification step, not a code change.

---

## Task 12: Switch Worker + fake CLI to stream-json protocol (fixes the 3s stdin timeout)

Task 11's manual smoke test against the real `claude` CLI found that plain `--input-format text --output-format json` gives up waiting for stdin after ~3 seconds ("Warning: no stdin data received in 3s, proceeding without it" → "Error: Input must be provided either through stdin or as a prompt argument when using --print"). This breaks the pre-warmed pool's core premise: a worker sitting idle for more than ~3s before a real request arrives will have already exited. Investigation (`docs/superpowers/plans/2026-07-28-stream-json-investigation.md`) confirmed `--input-format stream-json --output-format stream-json --verbose` has no such timeout (verified at 0s/6s/15s delays against the real CLI). This task switches `Worker` to that protocol and updates the fake CLI test double to speak it too. `WorkerPool`, the server, the daemon, and the client are unaffected — they only depend on `Worker.run()`'s returned `{"text", "duration_ms", "is_error"}` dict, which is unchanged.

**Files:**
- Modify: `tests/fixtures/fake_claude_cli.py`
- Modify: `tests/fixtures/test_fake_claude_cli.py`
- Modify: `src/claude_pool/worker.py`
- Test: `tests/test_worker.py` (existing tests should keep passing unmodified — this task's new step only adds one test)

**Interfaces:**
- Consumes: nothing new — `Worker`'s public interface (`start()`, `is_alive()`, `run(prompt, timeout_sec) -> dict`, `kill()`, `became_idle_at`) is unchanged.
- Produces: same `Worker` public interface as before; only its internal argv and stdout-parsing change.

- [ ] **Step 1: Update the fake CLI to speak stream-json**

Replace the entire contents of `tests/fixtures/fake_claude_cli.py`:

```python
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
```

- [ ] **Step 2: Update the fake CLI's own tests to send/expect stream-json**

Replace the entire contents of `tests/fixtures/test_fake_claude_cli.py`:

```python
import json
import subprocess
import sys
from pathlib import Path

FAKE_CLI = Path(__file__).parent / "fake_claude_cli.py"


def _user_message(content: str) -> str:
    return json.dumps({"type": "user", "message": {"role": "user", "content": content}})


def _run(args, stdin_text):
    return subprocess.run(
        [sys.executable, str(FAKE_CLI), *args],
        input=stdin_text.encode(),
        capture_output=True,
    )


def _result_line(stdout: bytes) -> dict:
    lines = [json.loads(line) for line in stdout.decode().splitlines() if line.strip()]
    return next(line for line in lines if line["type"] == "result")


def test_echo_mode_returns_message_content_as_result():
    proc = _run(["--fake-mode", "echo"], _user_message("hello world"))
    assert proc.returncode == 0
    result = _result_line(proc.stdout)
    assert result["is_error"] is False
    assert result["result"] == "hello world"


def test_error_mode_sets_is_error_true():
    proc = _run(["--fake-mode", "error"], _user_message("anything"))
    assert proc.returncode == 0
    result = _result_line(proc.stdout)
    assert result["is_error"] is True


def test_crash_mode_exits_nonzero():
    proc = _run(["--fake-mode", "crash"], _user_message("anything"))
    assert proc.returncode != 0


def test_ignores_real_cli_flags_it_does_not_know_about():
    proc = _run(
        ["--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
         "--tools", "", "--fake-mode", "echo"],
        _user_message("still works"),
    )
    assert proc.returncode == 0
    result = _result_line(proc.stdout)
    assert result["result"] == "still works"
```

- [ ] **Step 3: Run the fake CLI's own tests to confirm they pass against the new protocol**

Run: `pytest tests/fixtures/test_fake_claude_cli.py -v`
Expected: PASS (4 passed)

- [ ] **Step 4: Update `Worker` to use stream-json**

In `src/claude_pool/worker.py`, replace `_build_argv` and `run`:

```python
    def _build_argv(self) -> list[str]:
        return [
            *self.config.claude_cmd,
            "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--no-session-persistence",
            "--tools", "",
            "--strict-mcp-config",
            "--safe-mode",
            "--model", self.config.model,
        ]
```

```python
    async def run(self, prompt: str, timeout_sec: float) -> dict:
        if self._proc is None:
            raise WorkerError("worker not started")
        self.state = WorkerState.BUSY
        message = json.dumps({
            "type": "user",
            "message": {"role": "user", "content": prompt},
        }) + "\n"
        try:
            stdout_data, stderr_data = await asyncio.wait_for(
                self._proc.communicate(input=message.encode("utf-8")),
                timeout=timeout_sec,
            )
        except asyncio.TimeoutError:
            await self.kill()
            raise
        finally:
            self.state = WorkerState.DONE

        if self._proc.returncode != 0:
            raise WorkerError(
                f"worker exited with code {self._proc.returncode}: "
                f"{stderr_data.decode('utf-8', errors='replace')}"
            )

        result_line = None
        for line in stdout_data.decode("utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("type") == "result":
                result_line = payload
                break

        if result_line is None:
            raise WorkerError("no 'result' line found in worker stream-json output")

        return {
            "text": result_line.get("result", ""),
            "duration_ms": result_line.get("duration_ms", 0),
            "is_error": bool(result_line.get("is_error", False)),
        }
```

(`import json` is already present at the top of `worker.py` from the original implementation — don't add it twice.)

- [ ] **Step 5: Run Worker's existing tests to confirm they still pass unmodified**

Run: `pytest tests/test_worker.py -v`
Expected: PASS (5 passed) — none of the existing 5 test cases need code changes, since `Worker`'s public interface and the fake CLI's `--fake-mode`/`--fake-delay-sec` flags are unchanged; only the wire protocol between them changed.

- [ ] **Step 6: Add one new test proving the argv now requests stream-json**

Append to `tests/test_worker.py`:

```python
async def test_build_argv_uses_stream_json_protocol(tmp_path):
    worker = Worker(make_config(tmp_path, "--fake-mode", "echo"))
    argv = worker._build_argv()
    assert "--input-format" in argv
    assert argv[argv.index("--input-format") + 1] == "stream-json"
    assert "--output-format" in argv
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in argv
```

- [ ] **Step 7: Run the full test suite to confirm nothing downstream broke**

Run: `pytest -v`
Expected: PASS, same total count as before this task plus the 1 new test (Tasks 5-10's tests all go through `Worker.run()` indirectly via `WorkerPool`/the server/the daemon/the client and the fake CLI — none of them should need changes, since `Worker`'s return shape is unchanged).

- [ ] **Step 8: Commit**

```bash
git add tests/fixtures/fake_claude_cli.py tests/fixtures/test_fake_claude_cli.py src/claude_pool/worker.py tests/test_worker.py
git commit -m "fix: switch worker to stream-json protocol to avoid the 3s stdin timeout"
```

---

## Task 13: Re-run the manual smoke test to confirm the fix

Task 11 failed against the real CLI due to the 3s stdin timeout; Task 12 fixed it. Re-run the same manual verification to confirm the fix holds end-to-end against the real `claude` binary.

**Files:** none created or modified.

- [ ] **Step 1: Start the real daemon**

```bash
python -m claude_pool.daemon
```

- [ ] **Step 2: Check health, then deliberately wait past the old 3s failure point before sending a request**

```bash
curl http://127.0.0.1:8756/health
```

Expected: `"idle": 4, "busy": 0, "total": 4` (or close to it).

Wait at least 10 seconds (well past the ~3s window that broke Task 11) before proceeding to Step 3 — this is the whole point of the re-test.

- [ ] **Step 3: Send a real request after the delay**

```bash
curl -X POST http://127.0.0.1:8756/generate -H "Content-Type: application/json" -d "{\"prompt\": \"reply with the single word PONG\"}"
```

Expected: `{"text": "PONG", "duration_ms": <number>}` — NOT the "no stdin data received" error Task 11 hit.

- [ ] **Step 4: Confirm independent tenancy manually**

Same as Task 11's Step 4: send two requests with contradictory instructions back to back (e.g., "the secret number is 7, remember it" then "what secret number did I just tell you?") and confirm the second response shows no awareness of the first.

- [ ] **Step 5: Stop the daemon**

Kill the daemon process.

No commit for this task — it's a verification step, not a code change.

---

## Plan Self-Review Notes

- **Spec coverage**: independent tenant (Tasks 4-6, verified in Task 10), speed via pre-warming (Task 1 spike gates the whole plan, Tasks 4-6 implement it), concurrency (Task 5's `acquire`/`_grow_by_one`, verified in Task 10), stdin-only input (`Worker.run` in Task 4), no auth / localhost-only (Task 7's server binds via `TCPSite(host="127.0.0.1", ...)` in Task 8), min/max autoscaling (Tasks 5-6), API shape (Task 7), error handling (Task 7's timeout/crash/queue paths), daemon auto-start (Task 9), model-override-removed correction (reflected in `PoolConfig.model` being fixed per instance, no `model` field accepted in `/generate`'s body handling in Task 7).
- **Deferred by design** (per spec's "후속 작업"): global CLAUDE.md discoverability note and README architecture diagram are explicitly out of scope for this plan — they depend on the implementation existing first, exactly as the user requested.
- **Amendment (added after Task 11)**: Task 11's real-CLI smoke test found a genuine plan defect — the mandated plain-text stdin protocol has a ~3s timeout in the real `claude -p` that breaks pre-warmed workers. Tasks 12-13 correct this (switch to stream-json, re-verify against the real CLI) rather than leaving it as a deferred minor, since it's load-bearing for the whole pool design.
