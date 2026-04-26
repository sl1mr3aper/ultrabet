"""Тесты retry_async."""

from __future__ import annotations

import asyncio

import pytest

from services.retry import RetryPolicy, retry_async


@pytest.mark.asyncio
async def test_success_first_try():
    calls = [0]

    async def f():
        calls[0] += 1
        return "ok"

    r = await retry_async(f)
    assert r == "ok"
    assert calls[0] == 1


@pytest.mark.asyncio
async def test_retries_on_timeout():
    calls = [0]

    async def f():
        calls[0] += 1
        if calls[0] < 3:
            raise TimeoutError("timed out")
        return "ok"

    policy = RetryPolicy(max_attempts=5, initial_delay=0.001, multiplier=1.1)
    r = await retry_async(f, policy=policy)
    assert r == "ok"
    assert calls[0] == 3


@pytest.mark.asyncio
async def test_gives_up_after_max_attempts():
    calls = [0]

    async def f():
        calls[0] += 1
        raise TimeoutError("always fail")

    policy = RetryPolicy(max_attempts=3, initial_delay=0.001)
    with pytest.raises(TimeoutError):
        await retry_async(f, policy=policy)
    assert calls[0] == 3


@pytest.mark.asyncio
async def test_non_retryable_raised_immediately():
    calls = [0]

    async def f():
        calls[0] += 1
        raise ValueError("won't retry")

    policy = RetryPolicy(max_attempts=5, initial_delay=0.001)
    with pytest.raises(ValueError):
        await retry_async(f, policy=policy)
    assert calls[0] == 1


@pytest.mark.asyncio
async def test_on_retry_callback_invoked():
    calls = [0]
    notified = []

    async def f():
        calls[0] += 1
        if calls[0] < 2:
            raise TimeoutError
        return "ok"

    async def on_retry(attempt, exc, delay):
        notified.append((attempt, type(exc).__name__, delay >= 0))

    await retry_async(
        f,
        policy=RetryPolicy(max_attempts=3, initial_delay=0.001),
        on_retry=on_retry,
    )
    assert len(notified) == 1
    assert notified[0][1] == "TimeoutError"


def test_policy_compute_delay_increases():
    p = RetryPolicy(initial_delay=1.0, multiplier=2.0, max_delay=100.0, jitter_ratio=0.0)
    assert p.compute_delay(1) == 1.0
    assert p.compute_delay(2) == 2.0
    assert p.compute_delay(3) == 4.0


def test_policy_respects_max_delay():
    p = RetryPolicy(initial_delay=1.0, multiplier=10.0, max_delay=5.0, jitter_ratio=0.0)
    assert p.compute_delay(5) == 5.0


@pytest.mark.asyncio
async def test_sync_on_retry_ok():
    calls = [0]
    notified = []

    async def f():
        calls[0] += 1
        if calls[0] < 2:
            raise TimeoutError
        return "ok"

    def on_retry(attempt, exc, delay):
        notified.append(attempt)

    await retry_async(
        f,
        policy=RetryPolicy(max_attempts=3, initial_delay=0.001),
        on_retry=on_retry,
    )
    assert notified == [1]


@pytest.mark.asyncio
async def test_cancellation_not_retried():
    async def f():
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await retry_async(f, policy=RetryPolicy(max_attempts=3))
