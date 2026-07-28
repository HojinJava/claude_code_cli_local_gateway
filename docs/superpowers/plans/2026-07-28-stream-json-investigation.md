# stream-json Investigation — Fix for the 3s stdin Timeout

## Problem

Task 11's manual smoke test against the real `claude` CLI failed: a pre-warmed
worker sitting idle for more than ~3 seconds before being fed a prompt gets
this error from the CLI itself:

```
Warning: no stdin data received in 3s, proceeding without it. If piping from
a slow command, redirect stdin explicitly: < /dev/null to skip, or wait
longer.
Error: Input must be provided either through stdin or as a prompt argument
when using --print
```

This breaks the core pre-warm premise: the whole point of the pool is to let
workers sit idle for an unpredictable amount of time until a real request
arrives. Task 1's validation spike never caught this because it only tested
a 1.0s simulated idle gap (under the 3s threshold).

## Hypothesis

`--input-format stream-json --output-format stream-json` is designed for
programmatic/SDK-style use (a wrapper process holding a long-lived pipe open,
feeding messages whenever it has one) rather than simple shell piping, and
may not apply the same "assume the user forgot to pipe something" 3s
heuristic that plain `--input-format text` uses.

## Experiment

`scripts/investigate_stream_json_timeout.py`: spawn
`claude -p --input-format stream-json --output-format stream-json --verbose
--no-session-persistence --tools "" --strict-mcp-config --safe-mode --model
haiku`, wait N seconds, then feed one stream-json user message
(`{"type":"user","message":{"role":"user","content":"reply with the single
word OK"}}\n`) via `communicate()`.

(`--verbose` turned out to be a hard requirement: `--print` +
`--output-format=stream-json` refuses to start without it — "Error: When
using --print, --output-format=stream-json requires --verbose".)

## Results

| Delay before feeding stdin | Result |
|---|---|
| 0s | `returncode=0`, `"result":"OK"`, `"is_error":false` |
| 6s | `returncode=0`, `"result":"OK"`, `"is_error":false` |
| 15s | `returncode=0`, `"result":"OK"`, `"is_error":false` |

No timeout, no error, at any delay tested — including 15s, well past the 3s
threshold that broke plain-text mode. **Confirmed: stream-json input mode
does not apply the "no stdin in 3s" heuristic.**

## Output shape difference (important for the fix)

Plain `--output-format json` returns exactly one JSON object on stdout.
stream-json returns **multiple newline-delimited JSON objects** — a
`system`/`init` line, some `system`/`thinking_tokens` and `assistant` lines,
a `rate_limit_event` line, and finally one line with `"type":"result"` that
carries the same fields Worker already parses (`is_error`, `result`,
`duration_ms`). The fix must scan stdout line-by-line and use the `result`
line, not assume the whole stdout blob is one JSON object.

## Required change

`Worker._build_argv()` (`src/claude_pool/worker.py`) and `Worker.run()` need
to change:

1. Command line: replace `--input-format text --output-format json` with
   `--input-format stream-json --output-format stream-json --verbose`.
2. Input encoding: replace `prompt.encode("utf-8")` with a JSON line:
   `json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}) + "\n"`,
   encoded to bytes.
3. Output parsing: split stdout on newlines, `json.loads` each non-empty
   line, find the one with `payload.get("type") == "result"`, and extract
   `result`/`duration_ms`/`is_error` from THAT line (ignore the others).

This is a `Worker`-internal change only — `WorkerPool`, the server, the
daemon, and the client are all unaffected (they only depend on `Worker.run()`
returning `{"text", "duration_ms", "is_error"}`, which is unchanged).

## Recommendation

Revise Task 4 (`Worker`) to use stream-json instead of plain text, add a test
that specifically exercises a delayed feed past 3s against the fake CLI
double (update the fake CLI to also emit a stream-json-shaped multi-line
response), and re-run Task 11's manual smoke test against the real CLI to
confirm the fix holds end-to-end.
