# Final Review Fix Report — claude-pool

Branch: `feature/implement-claude-pool`
Worktree: `D:\develope\claude-pool\.worktrees\implement-claude-pool`

All 7 findings from the final whole-branch review are fixed. Two additional
defects surfaced during independent re-review of this fix wave and were fixed in
the same pass (see "Additional defects" below).

---

## HIGH-1 — Cancelled/disconnected request orphans a live worker subprocess

**Fix.** `WorkerPool.release()` (`src/claude_pool/pool.py`) now unconditionally
`await worker.kill()` as its first statement, before any accounting. Confirmed
`Worker.kill()` is a no-op on an already-exited process (it guards on
`self._proc.returncode is None`) and that behavior is unchanged, so this is safe
on every exit path: success, `WorkerError`, timeout, and cancellation.

`server.py`'s `finally` now runs the release as a detached, pool-tracked task
that is also shielded:

```python
finally:
    await asyncio.shield(pool.release_in_background(worker))
```

so cancelling the handler cannot abandon the release half-done.

**Test.** `tests/test_pool.py::test_release_kills_worker_whose_run_was_cancelled`
starts a real `run()` against the fake CLI (`--fake-delay-sec 5.0`), cancels it,
asserts the subprocess is *still alive* (proving cancellation alone does not kill
it — the actual bug), then asserts `release()` kills it. Verified discriminating:
removing the `kill()` from `release()` fails the test with `assert not True`.

**Important correction to the finding's premise.** The review states aiohttp
cancels the handler on client disconnect. It does not, in this configuration:
aiohttp 3.14.3's `RequestHandler.__init__` has `handler_cancellation: bool = False`
by default, and this project never enables it. Verified empirically against a live
daemon — aborting an in-flight request left `busy: 1` in `/health` with the
handler still running to completion, i.e. no disconnect-driven cancellation and
no orphan.

Handler cancellation *is* still reachable — notably `runner.cleanup()` cancels
outstanding handlers after its grace period during shutdown — so the fix is
correct and load-bearing; it just is not triggered by a plain client disconnect
today. Flagging because the severity rationale in the finding ("still burning the
user's subscription with nowhere to send the answer") overstates the current
exposure.

---

## HIGH-2 — Failed worker spawn silently swallowed, hangs `acquire()` forever

Three-part fix in `src/claude_pool/pool.py`:

1. **Spawn failures never vanish.** New `_try_spawn_and_add_idle_locked()` wraps
   the raising `_spawn_and_add_idle_locked()`: on failure it records
   `_last_spawn_error` and still calls `self._cond.notify()`, so a waiter always
   wakes even though nothing was added to `_idle`. `_grow_by_one()` and
   `release()` both use this non-raising variant. `WorkerPool.start()` keeps the
   raising variant deliberately — a daemon that cannot spawn its first worker
   should fail at startup, loudly, rather than come up broken.

2. **`release()` can never propagate.** Its replenish call goes through
   `_try_spawn_and_add_idle_locked()`, so a spawn failure there cannot escape the
   caller's `finally` and turn an already-computed 200 into a 500.

3. **Bounded wait plus fail-fast in `acquire()`.** `acquire()` wraps the internal
   `_acquire()` in `asyncio.wait_for(..., timeout=config.acquire_timeout_sec)`
   (new `PoolConfig` field, default 60s, env `CLAUDE_POOL_ACQUIRE_TIMEOUT_SEC`)
   and converts a timeout into `PoolUnavailableError`. Additionally, a waiter that
   wakes to an empty `_idle` with a recorded spawn error and no other spawn still
   in flight raises `PoolUnavailableError` immediately rather than sitting out the
   full timeout — so a missing binary surfaces in milliseconds, not 60 seconds.

`server.py` maps `PoolUnavailableError` to **503**.

**Tests.**

- `test_acquire_fails_fast_when_worker_spawn_fails` — pool configured with a
  nonexistent binary; the assertion is wrapped in an outer `asyncio.wait_for` so
  the pre-fix hang is caught rather than hanging the suite. Verified
  discriminating: reverting the notify-on-failure makes it fail with `TimeoutError`.
- `test_acquire_times_out_when_pool_is_exhausted` — max_workers=1 with the single
  worker held, `acquire_timeout_sec=0.3`.
- `test_release_never_propagates_a_failed_replenish` — swaps in a bad binary
  before `release()` and asserts no exception escapes.
- `tests/test_server.py::test_generate_returns_503_when_no_worker_can_be_acquired`.

---

## HIGH-3 — No `WorkerPool.stop()`; daemon shutdown never terminates workers

**Fix.** Added `WorkerPool.stop()`:

- sets `_stopped`, cancels and awaits the scale-down task (now retained as
  `self._scale_down_task` instead of a discarded `ensure_future`),
- drains tracked background tasks (`asyncio.wait` with a 5s budget, then cancel
  plus `gather(return_exceptions=True)`) so in-flight spawns land and their
  workers get killed rather than orphaned mid-exec,
- `notify_all()`s so parked `acquire()` waiters fail fast instead of waiting out
  their timeout,
- kills each idle worker, decrementing `_total` **per worker after the kill**, so
  an interrupted shutdown leaves the count matching what was actually killed.

Fire-and-forget grow tasks are now tracked in a `_background_tasks` set with a
`done_callback` that discards them; `_track()` is shared by `_schedule_grow()`
and `release_in_background()`.

**Busy workers are deliberately not killed** by `stop()` — they belong to
in-flight requests whose `release()` kills them on the way out, and that release
is now tracked so `stop()`'s drain waits for it. Documented in the `stop()`
docstring.

`daemon.py` calls `await pool.stop()` from `run_daemon`'s `finally`, in a nested
`try/finally` so it runs even if `runner.cleanup()` raises. `run_daemon` was also
restructured so `pool.start()` is inside the `try`, meaning a failed startup no
longer leaks the workers that did spawn. The `while True: sleep(3600)` idle loop
was replaced with `_wait_for_shutdown_signal()`, which installs SIGTERM/SIGINT
handlers where supported (no-op on Windows and in non-main threads, both caught)
so the graceful path is actually reachable on POSIX.

**Test.** `tests/test_daemon.py::test_run_daemon_kills_pool_workers_on_shutdown`
patches in a recording `WorkerPool` subclass, waits for `/health`, captures the
live idle workers, cancels `run_daemon`, and asserts every worker is dead.
Verified discriminating: fails with `assert False` against the pre-fix sources.

**Test-teardown leaks (Tasks 7/9 ledger note).** Added a `make_pool` fixture to
`tests/conftest.py` that builds pools and `await pool.stop()`s them at teardown;
`test_pool.py`, `test_server.py`, and `test_integration.py` now use it. Side
effect: the suite's two `PytestUnraisableExceptionWarning` /
`ResourceWarning: unclosed transport` warnings are gone — the run is now clean.

**Note on manual verification.** An end-to-end Ctrl+Break shutdown test against a
real daemon showed 0 surviving workers — but the same result appeared against the
*pre-fix* sources, because on Windows `CTRL_BREAK_EVENT` goes to the whole process
group and hits the worker subprocesses directly. That check therefore proves
nothing about `stop()`, and the in-process test above is the real evidence.

---

## HIGH-4 — `acquire()` hands out dead workers without checking `is_alive()`

**Fix.** `_acquire()` now loops: it pops from `_idle`, returns the worker only if
`worker.is_alive()`, and otherwise discards it (decrement `_total`, `kill()` to
reap) and tries the next one. When `_idle` is exhausted it falls through to the
existing grow-and-wait logic, then re-evaluates from the top.

**Test.** `test_acquire_discards_dead_idle_workers` kills a baseline idle worker
out from under the pool and asserts `acquire()` returns a different, live worker
and that `_total` reflects the discard. Verified discriminating.

---

## HIGH-5 — `CLAUDE_POOL_HOST` can bind the unauthenticated API off-loopback

**Fix.** `PoolConfig.__post_init__` rejects any non-loopback host with a
`ValueError` explaining why. Validation is in `__post_init__` rather than
`from_env()` so it covers programmatic construction too. Loopback is determined by
`ipaddress.ip_address(host).is_loopback` (so the whole `127.0.0.0/8` range and
`::1` are accepted) plus an explicit `localhost` name allowance.

**Tests.** `test_loopback_hosts_are_accepted` (127.0.0.1, 127.0.0.2, localhost,
::1) and `test_non_loopback_host_is_rejected` (0.0.0.0, 192.168.1.5, example.com,
empty string), plus `test_from_env_rejects_non_loopback_host`.

Verified against a real process: `CLAUDE_POOL_HOST=0.0.0.0 python -m
claude_pool.daemon` exits 1 with the ValueError before binding anything.

---

## MED-1 — Client auto-start ignores the client's own host/port

**Fix.** `ClaudePoolClient._start_daemon()` copies `os.environ` and sets
`CLAUDE_POOL_HOST` / `CLAUDE_POOL_PORT` from the client's own attributes before
spawning, so the auto-started daemon binds where the client expects.

**Tests.** `test_auto_start_passes_client_host_and_port_to_daemon` patches
`subprocess.Popen` and asserts the passed env. Also verified end to end with real
processes: `ClaudePoolClient(port=8795)` auto-started a daemon on the non-default
port and completed a generate round trip — this did not work before the fix.

---

## MED-3 — Integration test can't detect crossed responses

**Fix.** `test_concurrent_requests_do_not_bleed_context` now asserts
`[b["text"] for b in bodies] == prompts` (strict, order-sensitive) instead of the
set comparison, with a comment explaining why the set form was non-discriminating.

---

## Additional defects found and fixed in this pass

Independent re-review of the fix wave surfaced two real bugs that the fixes above
would otherwise have left behind. Both are in the same subprocess-lifecycle area
and were fixed here.

**A. `_scale_down_loop` could orphan workers when `stop()` cancels it.** The sweep
decremented `_total` for the entire kill batch under the lock, then killed workers
one at a time outside it. Because `stop()` now cancels that task, a cancellation
landing mid-kill left the remaining workers counted as gone but never signalled.
Fixed to decrement per worker after each kill, matching `stop()`. This bug was
only reachable *because* HIGH-3 introduced cancellation of that task.

**B. Spawn-failure fail-fast could reject a request that would have succeeded.**
With several waiters each triggering their own grow, one transiently failing spawn
could wake a waiter that then raised, even though another in-flight grow was about
to succeed. Added a `_pending_grows` counter (incremented in `_schedule_grow`,
decremented in `_grow_by_one`'s `finally`); a waiter only raises the spawn error
when no grow is still in flight. The decrement is observed correctly by the woken
waiter because nothing between the `notify()` and the `finally` awaits an
incomplete future, so the grow task runs to completion before the loop processes
the waiter's wakeup.

Also hardened during re-review: `_acquire()` checks `_stopped` at the top of its
loop and raises `PoolUnavailableError("pool is shutting down")`; `stop()`
`notify_all()`s so parked waiters actually get that error instead of waiting out
`acquire_timeout_sec`. Covered by `test_stop_wakes_parked_acquire_waiters`, which
uses a 30s acquire timeout so a pass cannot come from the timeout backstop.
Verified discriminating.

### Known remaining gap (deliberately not fixed)

If a `_grow_by_one` task is cancelled while suspended *inside*
`asyncio.create_subprocess_exec` — only possible during `stop()`, and only after
the 5s drain window — the OS process may exist without `Worker._proc` ever being
assigned, leaving it unreachable by `kill()`. Closing this requires reworking
`Worker.start()` to record the process handle under cancellation, which is more
invasive than this pass warrants. The drain window makes it very unlikely.

---

## Files changed

```
src/claude_pool/client.py    | client host/port passthrough (MED-1)
src/claude_pool/config.py    | loopback validation, acquire_timeout_sec (HIGH-5, HIGH-2)
src/claude_pool/daemon.py    | pool.stop() wiring, signal handling (HIGH-3)
src/claude_pool/pool.py      | kill-on-release, spawn-failure handling, stop(),
                             | self-healing acquire (HIGH-1..4 + additional A/B)
src/claude_pool/server.py    | 503 on PoolUnavailableError, shielded release (HIGH-1, HIGH-2)
tests/conftest.py            | make_pool fixture (HIGH-3 teardown leaks)
tests/test_client.py         | MED-1 test
tests/test_config.py         | HIGH-5 tests
tests/test_daemon.py         | HIGH-3 shutdown test
tests/test_integration.py    | MED-3 strict assertion, make_pool
tests/test_pool.py           | HIGH-1/2/3/4 + additional-B tests, make_pool
tests/test_server.py         | 503 test, make_pool
```

`tests/fixtures/fake_claude_cli.py` was **not** modified: the existing
`--fake-delay-sec` flag already provides the "process stays alive until killed"
behavior needed to test HIGH-1, so no new fake mode was warranted.

---

## Full pytest output

```
============================= test session starts =============================
platform win32 -- Python 3.14.3, pytest-9.1.1, pluggy-1.6.0 -- C:\Users\modelic\AppData\Local\Python\pythoncore-3.14-64\python.exe
cachedir: .pytest_cache
rootdir: D:\develope\claude-pool\.worktrees\implement-claude-pool
configfile: pyproject.toml
plugins: anyio-4.13.0, aiohttp-1.1.1, asyncio-1.4.0, cov-5.0.0, mock-3.14.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 50 items

tests/fixtures/test_fake_claude_cli.py::test_echo_mode_returns_message_content_as_result PASSED [  2%]
tests/fixtures/test_fake_claude_cli.py::test_error_mode_sets_is_error_true PASSED [  4%]
tests/fixtures/test_fake_claude_cli.py::test_crash_mode_exits_nonzero PASSED [  6%]
tests/fixtures/test_fake_claude_cli.py::test_ignores_real_cli_flags_it_does_not_know_about PASSED [  8%]
tests/test_client.py::test_client_generate_returns_text PASSED           [ 10%]
tests/test_client.py::test_client_health_reports_stats PASSED            [ 12%]
tests/test_client.py::test_client_raises_on_missing_daemon_when_auto_start_disabled PASSED [ 14%]
tests/test_client.py::test_auto_start_passes_client_host_and_port_to_daemon PASSED [ 16%]
tests/test_config.py::test_defaults PASSED                               [ 18%]
tests/test_config.py::test_from_env_reads_overrides PASSED               [ 20%]
tests/test_config.py::test_loopback_hosts_are_accepted[127.0.0.1] PASSED [ 22%]
tests/test_config.py::test_loopback_hosts_are_accepted[127.0.0.2] PASSED [ 24%]
tests/test_config.py::test_loopback_hosts_are_accepted[localhost] PASSED [ 26%]
tests/test_config.py::test_loopback_hosts_are_accepted[::1] PASSED       [ 28%]
tests/test_config.py::test_non_loopback_host_is_rejected[0.0.0.0] PASSED [ 30%]
tests/test_config.py::test_non_loopback_host_is_rejected[192.168.1.5] PASSED [ 32%]
tests/test_config.py::test_non_loopback_host_is_rejected[example.com] PASSED [ 34%]
tests/test_config.py::test_non_loopback_host_is_rejected[] PASSED        [ 36%]
tests/test_config.py::test_from_env_rejects_non_loopback_host PASSED     [ 38%]
tests/test_daemon.py::test_run_daemon_serves_generate_requests PASSED    [ 40%]
tests/test_daemon.py::test_run_daemon_kills_pool_workers_on_shutdown PASSED [ 42%]
tests/test_integration.py::test_concurrent_requests_do_not_bleed_context PASSED [ 44%]
tests/test_integration.py::test_burst_scales_up_and_idle_scales_back_down PASSED [ 46%]
tests/test_pool.py::test_start_primes_min_workers PASSED                 [ 48%]
tests/test_pool.py::test_acquire_and_release_serves_one_request_then_replenishes PASSED [ 50%]
tests/test_pool.py::test_acquire_beyond_idle_capacity_grows_and_waits PASSED [ 52%]
tests/test_pool.py::test_acquire_never_exceeds_max_workers PASSED        [ 54%]
tests/test_pool.py::test_scale_down_shrinks_idle_workers_back_to_min PASSED [ 56%]
tests/test_pool.py::test_scale_down_loop_kills_only_expired_excess_idle_workers PASSED [ 58%]
tests/test_pool.py::test_release_kills_worker_whose_run_was_cancelled PASSED [ 60%]
tests/test_pool.py::test_acquire_discards_dead_idle_workers PASSED       [ 62%]
tests/test_pool.py::test_acquire_fails_fast_when_worker_spawn_fails PASSED [ 64%]
tests/test_pool.py::test_acquire_times_out_when_pool_is_exhausted PASSED [ 66%]
tests/test_pool.py::test_release_never_propagates_a_failed_replenish PASSED [ 68%]
tests/test_pool.py::test_stop_kills_idle_workers_and_cancels_scale_down_loop PASSED [ 70%]
tests/test_pool.py::test_stop_wakes_parked_acquire_waiters PASSED        [ 72%]
tests/test_server.py::test_generate_returns_text PASSED                  [ 74%]
tests/test_server.py::test_generate_requires_prompt PASSED               [ 76%]
tests/test_server.py::test_generate_rejects_invalid_json PASSED          [ 78%]
tests/test_server.py::test_health_reports_pool_stats PASSED              [ 80%]
tests/test_server.py::test_generate_surfaces_worker_error PASSED         [ 82%]
tests/test_server.py::test_generate_returns_503_when_no_worker_can_be_acquired PASSED [ 84%]
tests/test_server.py::test_generate_rejects_non_dict_json_body PASSED    [ 86%]
tests/test_server.py::test_generate_rejects_non_numeric_timeout_sec PASSED [ 88%]
tests/test_worker.py::test_start_puts_worker_in_idle_state PASSED        [ 90%]
tests/test_worker.py::test_run_returns_parsed_result PASSED              [ 92%]
tests/test_worker.py::test_run_raises_on_error_flagged_result PASSED     [ 94%]
tests/test_worker.py::test_run_raises_worker_error_on_crash PASSED       [ 96%]
tests/test_worker.py::test_run_raises_timeout_and_kills_process PASSED   [ 98%]
tests/test_worker.py::test_build_argv_uses_stream_json_protocol PASSED   [100%]

============================= 50 passed in 9.79s ==============================
```

**50 passed** (was 31 before this pass: +19 new tests), 0 warnings.
The suite was run several additional times end to end to check for flakiness in
the timing-sensitive pool tests — 50 passed every time.

## Commit

`3842a27` — `fix: close worker-lifecycle, pool-availability, and binding gaps from final review`

All source and test changes are in that single commit on
`feature/implement-claude-pool`; a follow-up `docs:` commit only corrects the
commit hash recorded in this file. The repository has no remote configured, so
nothing was pushed and no PR was opened.
