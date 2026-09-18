"""Classification reads structured values only — never the message wording.

`classify` no longer takes the error text at all, which is the point: the
wording travels to the caller in the response body and cannot reach the
verdict. The end-to-end proof that wording is inert lives in test_server.py.
"""
import pytest

from claude_pool.errors import (
    AUTH_ERROR_CODES,
    AUTH_STATUSES,
    DEFAULT_RETRY_AFTER_SEC,
    RATE_LIMIT_STATUSES,
    classify,
)


@pytest.mark.parametrize("status", sorted(RATE_LIMIT_STATUSES))
def test_rate_limit_status_is_retryable_429(status):
    failure = classify(api_error_status=status)
    assert failure.kind == "rate_limited"
    assert failure.status == 429
    assert failure.retryable is True
    # The CLI reports no reset time anywhere in its output (measured), so a
    # conservative floor is all there is to give.
    assert failure.retry_after_sec == DEFAULT_RETRY_AFTER_SEC


@pytest.mark.parametrize("status", sorted(AUTH_STATUSES))
def test_auth_status_is_not_retryable(status):
    failure = classify(api_error_status=status)
    assert failure.kind == "not_authenticated"
    assert failure.status == 503
    assert failure.retryable is False
    assert failure.retry_after_sec is None


@pytest.mark.parametrize("code", sorted(AUTH_ERROR_CODES))
def test_auth_error_code_is_enough_without_a_status(code):
    # Measured: a CLI with no credentials at all fails before it ever reaches
    # the API, so api_error_status is null and only this code identifies it.
    failure = classify(api_error_status=None, api_error_code=code)
    assert failure.kind == "not_authenticated"
    assert failure.status == 503
    assert failure.retryable is False


@pytest.mark.parametrize("status", [None, 500, 400, 404])
def test_anything_else_is_worker_failed(status):
    failure = classify(api_error_status=status)
    assert failure.kind == "worker_failed"
    assert failure.status == 502
    assert failure.retryable is False
    assert failure.retry_after_sec is None


def test_no_structured_values_at_all_is_worker_failed():
    # The WorkerError path: the process died without printing a result line.
    failure = classify()
    assert failure.kind == "worker_failed"
    assert failure.status == 502


def test_an_unknown_error_code_does_not_become_an_auth_failure():
    assert classify(api_error_code="error_during_execution").kind == "worker_failed"


def test_status_wins_over_code():
    # A 429 stays rate_limited even if the CLI also tagged the turn with an
    # auth-ish code; the HTTP status is the more precise of the two.
    assert classify(api_error_status=429, api_error_code="authentication_failed").kind == (
        "rate_limited"
    )


def test_module_carries_no_regex_machinery():
    # The regression this issue exists for: a wording pattern list creeping
    # back in. Checked as a property of the module, not of one case.
    import inspect

    from claude_pool import errors

    source = inspect.getsource(errors)
    for banned in ("import re", "re.search", "re.compile", "re.IGNORECASE"):
        assert banned not in source, banned
