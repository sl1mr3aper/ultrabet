"""Тесты token bucket & rate limiters."""

from __future__ import annotations

import asyncio

import pytest

from services.rate_limiter import GlobalRateLimiter, TokenBucket, UserRateLimiter


def test_bucket_initial_capacity():
    b = TokenBucket(capacity=5, refill_per_sec=1.0)
    # Первый take должен пройти (initial tokens = capacity)
    assert b.take(1) is True


def test_bucket_exhausts():
    b = TokenBucket(capacity=3, refill_per_sec=0.1)
    assert b.take(1) is True
    assert b.take(1) is True
    assert b.take(1) is True
    assert b.take(1) is False  # исчерпали


@pytest.mark.asyncio
async def test_user_rate_limiter_per_user():
    rl = UserRateLimiter(capacity=2, refill_per_sec=0.01)
    assert await rl.check(1) is True
    assert await rl.check(1) is True
    assert await rl.check(1) is False  # user 1 exhausted
    assert await rl.check(2) is True  # user 2 separate
    assert await rl.check(2) is True


@pytest.mark.asyncio
async def test_user_rate_limiter_reset():
    rl = UserRateLimiter(capacity=1, refill_per_sec=0.01)
    await rl.check(1)
    assert await rl.check(1) is False
    await rl.reset(1)
    assert await rl.check(1) is True


@pytest.mark.asyncio
async def test_user_rate_limiter_stats():
    rl = UserRateLimiter()
    await rl.check(1)
    await rl.check(2)
    s = await rl.stats()
    assert s["users"] == 2


@pytest.mark.asyncio
async def test_global_rate_limiter_acquire():
    rl = GlobalRateLimiter(capacity=2, refill_per_sec=0.01)
    assert await rl.acquire() is True
    assert await rl.acquire() is True
    assert await rl.acquire() is False


@pytest.mark.asyncio
async def test_wait_and_acquire_succeeds_after_refill():
    rl = GlobalRateLimiter(capacity=1, refill_per_sec=50.0)
    assert await rl.acquire() is True
    assert await rl.acquire() is False
    # После небольшой паузы должен рефильнуться
    ok = await rl.wait_and_acquire(max_wait=0.2)
    assert ok is True


@pytest.mark.asyncio
async def test_wait_and_acquire_fails():
    rl = GlobalRateLimiter(capacity=1, refill_per_sec=0.001)
    await rl.acquire()
    ok = await rl.wait_and_acquire(max_wait=0.05)
    assert ok is False


@pytest.mark.asyncio
async def test_concurrent_access_no_race():
    rl = UserRateLimiter(capacity=100, refill_per_sec=0.01)

    async def many():
        results = []
        for _ in range(50):
            results.append(await rl.check(1))
        return results

    res1, res2 = await asyncio.gather(many(), many())
    total_true = sum(1 for r in res1 + res2 if r)
    assert total_true <= 100
