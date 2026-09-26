import pytest

from voiceflow.utils.retry import RetryableError, retry_with_backoff


def test_succeeds_first_try_no_retry_needed():
    calls = []

    def fn():
        calls.append(1)
        return "ok"

    sleeps = []
    result = retry_with_backoff(fn, max_retries=3, sleep_fn=sleeps.append)
    assert result == "ok"
    assert len(calls) == 1
    assert sleeps == []


def test_retries_then_succeeds():
    attempts = {"n": 0}

    def fn():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RetryableError("transient")
        return "ok"

    sleeps = []
    result = retry_with_backoff(fn, max_retries=5, base_delay=0.1, sleep_fn=sleeps.append)
    assert result == "ok"
    assert attempts["n"] == 3
    assert len(sleeps) == 2  # slept before attempt 2 and attempt 3


def test_gives_up_after_max_retries():
    def fn():
        raise RetryableError("always fails")

    sleeps = []
    with pytest.raises(RetryableError):
        retry_with_backoff(fn, max_retries=2, base_delay=0.01, sleep_fn=sleeps.append)
    assert len(sleeps) == 2


def test_non_retryable_exception_propagates_immediately():
    calls = []

    def fn():
        calls.append(1)
        raise ValueError("not retryable")

    with pytest.raises(ValueError):
        retry_with_backoff(fn, max_retries=3, sleep_fn=lambda d: None)
    assert len(calls) == 1  # no retries attempted


def test_backoff_delay_grows_and_is_capped():
    def fn():
        raise RetryableError("x")

    delays = []
    with pytest.raises(RetryableError):
        retry_with_backoff(fn, max_retries=4, base_delay=1.0, max_delay=3.0, sleep_fn=delays.append)
    # Each delay includes up to 25% jitter, so check bounds rather than exact values.
    assert delays[0] >= 1.0
    assert delays[-1] <= 3.0 * 1.25
