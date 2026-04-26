"""Тесты Scheduler."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

from services.scheduler import Scheduler


@pytest.mark.asyncio
async def test_add_every_job():
    sched = Scheduler()
    async def noop() -> None:
        pass
    job = sched.every(seconds=10, func=noop)
    assert job.interval_seconds == 10
    assert job.name == "noop"
    assert len(sched.jobs) == 1


@pytest.mark.asyncio
async def test_daily_at_job_schedules_future():
    sched = Scheduler()
    async def noop() -> None:
        pass
    # время ровно минуту назад — должен запланировать на завтра
    past_hour = (datetime.utcnow() - timedelta(hours=1)).hour
    job = sched.daily_at(hour=past_hour, minute=0, func=noop)
    # next_run либо сегодня в будущем, либо завтра
    assert job.next_run > datetime.utcnow() - timedelta(minutes=1)


@pytest.mark.asyncio
async def test_run_executes_due_job():
    sched = Scheduler()
    counter = [0]
    async def tick() -> None:
        counter[0] += 1
    job = sched.every(seconds=0.1, func=tick)
    job.next_run = datetime.utcnow() - timedelta(seconds=1)
    await sched.start()
    await asyncio.sleep(0.2)
    await sched.stop()
    assert counter[0] >= 1


@pytest.mark.asyncio
async def test_error_counted():
    sched = Scheduler()
    async def bad() -> None:
        raise RuntimeError("bad")
    job = sched.every(seconds=0.1, func=bad)
    job.next_run = datetime.utcnow() - timedelta(seconds=1)
    await sched.start()
    await asyncio.sleep(0.2)
    await sched.stop()
    assert job.errors >= 1
    assert job.runs == 0


@pytest.mark.asyncio
async def test_stop_idempotent():
    sched = Scheduler()
    await sched.stop()  # до старта — ОК
    await sched.start()
    await sched.stop()
    await sched.stop()  # повторно
