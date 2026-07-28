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
