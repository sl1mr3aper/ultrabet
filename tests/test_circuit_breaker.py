"""Тесты Circuit Breaker."""

from __future__ import annotations

import asyncio

import pytest

from services.circuit_breaker import CircuitBreaker, State


@pytest.mark.asyncio
async def test_initial_state_closed():
    cb = CircuitBreaker()
    assert cb.state == State.CLOSED


@pytest.mark.asyncio
async def test_allow_closed():
    cb = CircuitBreaker()
    assert await cb.allow() is True


@pytest.mark.asyncio
async def test_opens_after_threshold_failures():
    cb = CircuitBreaker(failure_threshold=3, reset_timeout=60.0)
    for _ in range(3):
        await cb.check_and_record(False)
    assert cb.state == State.OPEN


@pytest.mark.asyncio
async def test_open_blocks():
    cb = CircuitBreaker(failure_threshold=1, reset_timeout=60.0)
    await cb.check_and_record(False)
    assert await cb.allow() is False


@pytest.mark.asyncio
async def test_half_open_after_reset():
    cb = CircuitBreaker(failure_threshold=1, reset_timeout=0.05)
    await cb.check_and_record(False)
    assert cb.state == State.OPEN
    await asyncio.sleep(0.1)
    assert await cb.allow() is True
    assert cb.state == State.HALF_OPEN


@pytest.mark.asyncio
async def test_half_open_success_closes():
    cb = CircuitBreaker(failure_threshold=1, reset_timeout=0.05)
    await cb.check_and_record(False)
    await asyncio.sleep(0.1)
    await cb.allow()  # half open, allow one
    await cb.check_and_record(True)
    assert cb.state == State.CLOSED


@pytest.mark.asyncio
async def test_half_open_failure_reopens():
    cb = CircuitBreaker(failure_threshold=1, reset_timeout=0.05)
    await cb.check_and_record(False)
    await asyncio.sleep(0.1)
    await cb.allow()
    await cb.check_and_record(False)
    assert cb.state == State.OPEN


@pytest.mark.asyncio
async def test_stats_tracked():
    cb = CircuitBreaker(failure_threshold=3)
    await cb.check_and_record(True)
    await cb.check_and_record(True)
    await cb.check_and_record(False)
    assert cb.stats.total_successes == 2
    assert cb.stats.total_failures == 1
    assert cb.stats.total_calls == 3


@pytest.mark.asyncio
async def test_success_resets_failure_count_in_closed():
    cb = CircuitBreaker(failure_threshold=3)
    await cb.check_and_record(False)
    await cb.check_and_record(False)
    await cb.check_and_record(True)  # reset!
    await cb.check_and_record(False)
    await cb.check_and_record(False)
    assert cb.state == State.CLOSED  # not opened
