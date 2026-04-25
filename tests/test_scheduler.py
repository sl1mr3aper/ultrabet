"""Тесты планировщика."""

from __future__ import annotations

import asyncio

import pytest

from services.scheduler import Scheduler


@pytest.mark.asyncio
async def test_scheduler_runs_at_startup():
    counter = {"x": 0}

    async def job():
        counter["x"] += 1

    sched = Scheduler()
    sched.add_job("test", interval_seconds=10.0, coro_factory=job, run_at_startup=True)
    await sched.start()
    await asyncio.sleep(0.05)
    await sched.stop()
    assert counter["x"] == 1


@pytest.mark.asyncio
async def test_scheduler_runs_periodically():
    counter = {"x": 0}

    async def job():
        counter["x"] += 1

    sched = Scheduler()
    sched.add_job("test", interval_seconds=0.1, coro_factory=job)
    await sched.start()
    await asyncio.sleep(0.35)
    await sched.stop()
    assert counter["x"] >= 2


@pytest.mark.asyncio
async def test_scheduler_swallows_exceptions():
    async def fail():
        raise RuntimeError("boom")

    sched = Scheduler()
    sched.add_job("fail", interval_seconds=0.05, coro_factory=fail, run_at_startup=True)
    await sched.start()
    await asyncio.sleep(0.15)
    await sched.stop()
