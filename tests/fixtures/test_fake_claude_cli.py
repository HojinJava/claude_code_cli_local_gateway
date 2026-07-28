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
