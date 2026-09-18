"""The ask launcher is exercised in-process with a stubbed client.

Spawning a real daemon here would run the real `claude` CLI, which this
suite never does; the launcher's own logic is argument handling, output and
exit codes.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

ASK = Path(__file__).resolve().parent.parent / "scripts" / "ask.py"


def load_ask():
    spec = importlib.util.spec_from_file_location("claude_pool_ask_script", ASK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StubClient:
    instances: list["StubClient"] = []

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        StubClient.instances.append(self)

    def generate(self, prompt, timeout_sec=None):
        StubClient.last_prompt = prompt
        return f"answer to {prompt}"


def test_prints_the_answer_and_exits_zero(monkeypatch, capsys):
    ask = load_ask()
    StubClient.instances.clear()
    monkeypatch.setattr(ask, "ClaudePoolClient", StubClient)

    code = ask.main(["hello", "world"])

    assert code == 0
    assert capsys.readouterr().out.strip() == "answer to hello world"
    assert StubClient.instances, "the launcher must go through the client"


def test_reports_the_failure_classification_and_exits_nonzero(monkeypatch, capsys):
    ask = load_ask()

    class Failing(StubClient):
        def generate(self, prompt, timeout_sec=None):
            raise ask.ClaudePoolError(
                "Claude AI usage limit reached",
                kind="rate_limited",
                retryable=True,
                retry_after_sec=60,
            )

    monkeypatch.setattr(ask, "ClaudePoolClient", Failing)

    code = ask.main(["hi"])

    assert code == 1
    err = capsys.readouterr().err
    assert "rate_limited" in err
    assert "retryable" in err
    assert "60" in err


def test_without_a_prompt_it_prints_usage_and_exits_two(monkeypatch, capsys):
    ask = load_ask()
    monkeypatch.setattr(ask, "ClaudePoolClient", StubClient)

    code = ask.main([])

    assert code == 2
    assert "usage" in capsys.readouterr().err.lower()


@pytest.mark.skipif(not ASK.exists(), reason="launcher not written yet")
def test_module_documents_how_to_run_it():
    ask = load_ask()
    assert "scripts/ask.py" in (ask.__doc__ or "")
