import pytest

from claude_pool.errors import DEFAULT_RETRY_AFTER_SEC, classify


@pytest.mark.parametrize(
    "text",
    [
        "Claude AI usage limit reached",
        "API Error: 429 rate_limit_error",
        "Too many requests, slow down",
        "Error: 529 overloaded_error",
        "your quota has been exhausted",
    ],
)
def test_rate_limit_text_is_retryable_429(text):
    failure = classify(text)
    assert failure.kind == "rate_limited"
    assert failure.status == 429
    assert failure.retryable is True
    assert failure.retry_after_sec == DEFAULT_RETRY_AFTER_SEC


def test_rate_limit_uses_wait_hint_from_the_message_when_present():
    assert classify("rate limit exceeded, try again in 42 seconds").retry_after_sec == 42
    assert classify("429: retry after 7s").retry_after_sec == 7


@pytest.mark.parametrize(
    "text",
    [
        "Invalid API key - please run /login",
        "not authenticated",
        "API Error: 401 unauthorized",
        "Your credit balance is too low",
    ],
)
def test_auth_text_is_not_retryable(text):
    failure = classify(text)
    assert failure.kind == "not_authenticated"
    assert failure.status == 503
    assert failure.retryable is False
    assert failure.retry_after_sec is None


@pytest.mark.parametrize("text", ["boom", "", "something else entirely"])
def test_unrecognised_failure_falls_back_to_502(text):
    failure = classify(text)
    assert failure.kind == "worker_failed"
    assert failure.status == 502
    assert failure.retryable is False
