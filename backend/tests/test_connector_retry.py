from datetime import datetime, timezone

import httpx
import pytest

from app.integrations.connectors.base import BrokerRateLimitError
from app.integrations.connectors.retry import (
    RetryPolicy,
    request_with_backoff,
    retry_after_seconds,
)
from app.integrations.connectors.trading212 import Trading212Connector


@pytest.mark.asyncio
async def test_safe_request_retries_transient_responses_with_exponential_backoff() -> None:
    responses = [503, 502, 200]
    delays: list[float] = []

    async def send() -> httpx.Response:
        status = responses.pop(0)
        return httpx.Response(status, request=httpx.Request("GET", "https://example.test"))

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    response = await request_with_backoff(
        send,
        policy=RetryPolicy(max_attempts=3, jitter_ratio=0),
        sleep=record_sleep,
    )

    assert response.status_code == 200
    assert delays == [1, 2]


@pytest.mark.asyncio
async def test_safe_request_respects_retry_after_header() -> None:
    attempts = 0
    delays: list[float] = []

    async def send() -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            429 if attempts == 1 else 200,
            headers={"Retry-After": "7"},
            request=httpx.Request("GET", "https://example.test"),
        )

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    response = await request_with_backoff(send, sleep=record_sleep)

    assert response.status_code == 200
    assert delays == [7]


def test_trading212_reset_timestamp_is_converted_to_delay() -> None:
    response = httpx.Response(
        429,
        headers={"x-ratelimit-reset": "1800000030"},
        request=httpx.Request("GET", "https://example.test"),
    )

    assert retry_after_seconds(
        response,
        reset_header="x-ratelimit-reset",
        now=datetime.fromtimestamp(1_800_000_000, tz=timezone.utc),
    ) == 30


@pytest.mark.asyncio
async def test_trading212_exposes_long_rate_limit_without_waiting_in_worker() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "120"}, request=request)

    connector = Trading212Connector(
        {"api_key": "test-key", "api_secret": "test-secret"},
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(BrokerRateLimitError) as caught:
        await connector.validate_credentials()

    assert caught.value.retry_after_seconds == 120
    assert calls == 1
