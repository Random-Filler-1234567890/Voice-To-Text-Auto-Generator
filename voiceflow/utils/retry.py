"""Exponential-backoff retry helper shared by every network-calling provider."""

from __future__ import annotations

import logging
import random
import time
from typing import Callable, TypeVar

logger = logging.getLogger("voiceflow.retry")

T = TypeVar("T")


class RetryableError(Exception):
    """Raise this from inside a retried callable to signal 'try again'.

    Any other exception propagates immediately without retrying - only
    errors explicitly identified as transient (timeouts, 429s, 5xxs)
    should be wrapped in this.
    """


def retry_with_backoff(
    fn: Callable[[], T],
    max_retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> T:
    """Call ``fn()``, retrying on :class:`RetryableError` with jittered backoff.

    ``sleep_fn`` is injectable so tests can run this instantly without real
    delays while still exercising the retry-count/give-up logic.
    """
    attempt = 0
    while True:
        try:
            return fn()
        except RetryableError as exc:
            attempt += 1
            if attempt > max_retries:
                logger.error("Giving up after %d retries: %s", max_retries, exc)
                raise
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay += random.uniform(0, delay * 0.25)
            logger.warning(
                "Retryable error (attempt %d/%d), backing off %.2fs: %s",
                attempt,
                max_retries,
                delay,
                exc,
            )
            sleep_fn(delay)
