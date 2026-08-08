import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    jitter_ratio: float = 0.2


DEFAULT_RETRY_POLICY = RetryPolicy()


async def request_with_backoff(
    send: Callable[[], Awaitable[httpx.Response]],
    *,
    policy: RetryPolicy = DEFAULT_RETRY_POLICY,
    reset_header: str | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> httpx.Response:
    """Retry a safe HTTP request with bounded exponential backoff and jitter."""

    if policy.max_attempts < 1:
        raise ValueError("Retry policy must allow at least one attempt")

    for attempt in range(policy.max_attempts):
        try:
            response = await send()
        except (httpx.TimeoutException, httpx.RequestError):
            if attempt + 1 >= policy.max_attempts:
                raise
            await sleep(_backoff_delay(attempt, policy))
            continue

        if (
            response.status_code not in RETRYABLE_STATUS_CODES
            or attempt + 1 >= policy.max_attempts
        ):
            return response

        retry_after = retry_after_seconds(response, reset_header=reset_header)
        if retry_after is not None and retry_after > policy.max_delay_seconds:
            # Long provider windows should be retried by a later scheduled run, not hold a worker.
            return response
        await sleep(
            retry_after
            if retry_after is not None
            else _backoff_delay(attempt, policy)
        )

    raise AssertionError("retry loop did not return")


def retry_after_seconds(
    response: httpx.Response,
    *,
    reset_header: str | None = None,
    now: datetime | None = None,
) -> float | None:
    """Read standard Retry-After or a provider Unix reset timestamp."""

    current = now or datetime.now(timezone.utc)
    raw_retry_after = response.headers.get("Retry-After")
    if raw_retry_after:
        try:
            return max(0.0, float(raw_retry_after))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(raw_retry_after)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                return max(0.0, (retry_at - current).total_seconds())
            except (TypeError, ValueError, OverflowError):
                pass

    raw_reset = response.headers.get(reset_header) if reset_header else None
    if raw_reset:
        try:
            return max(0.0, float(raw_reset) - current.timestamp())
        except ValueError:
            return None
    return None


def _backoff_delay(attempt: int, policy: RetryPolicy) -> float:
    base = min(policy.max_delay_seconds, policy.base_delay_seconds * (2**attempt))
    jitter = base * policy.jitter_ratio
    return max(0.0, base + random.uniform(-jitter, jitter))
