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


def _line_of_type(stdout: bytes, type_: str) -> dict:
    lines = [json.loads(line) for line in stdout.decode().splitlines() if line.strip()]
    return next(line for line in lines if line["type"] == type_)


def _result_line(stdout: bytes) -> dict:
    return _line_of_type(stdout, "result")


def test_echo_mode_returns_message_content_as_result():
    proc = _run(["--fake-mode", "echo"], _user_message("hello world"))
    assert proc.returncode == 0
    result = _result_line(proc.stdout)
    assert result["is_error"] is False
    assert result["result"] == "hello world"


def test_error_mode_sets_is_error_true_and_exits_one_like_the_real_cli():
    # Measured against Claude Code 2.1.276: a failed turn prints a complete
    # result line and *then* exits 1, with nothing on stderr.
    proc = _run(["--fake-mode", "error"], _user_message("anything"))
    assert proc.returncode == 1
    assert proc.stderr == b""
    result = _result_line(proc.stdout)
    assert result["is_error"] is True
    # A failed turn still reports subtype "success" — which is exactly why
    # subtype cannot be used to classify anything.
    assert result["subtype"] == "success"
    assert result["api_error_status"] is None


def test_error_mode_can_carry_the_structured_failure_values():
    proc = _run(
        ["--fake-mode", "error", "--fake-api-error-status", "429",
         "--fake-api-error-code", "rate_limit_error"],
        _user_message("anything"),
    )
    assert _result_line(proc.stdout)["api_error_status"] == 429
    assistant = _line_of_type(proc.stdout, "assistant")
    assert assistant["error"] == "rate_limit_error"
    assert assistant["is_api_error_message"] is True


def test_echo_mode_result_line_carries_a_null_api_error_status():
    result = _result_line(_run(["--fake-mode", "echo"], _user_message("hi")).stdout)
    assert result["api_error_status"] is None
    assert result["terminal_reason"] == "completed"


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
