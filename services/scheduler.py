"""Простой async-планировщик задач.

Аналог APScheduler, но легковесный и без внешних зависимостей. Достаточно
для дейли-дайджестов и live-мониторинга.

Использование:
    sched = Scheduler()
    sched.every(seconds=60, func=live_check)
    sched.daily_at(hour=9, minute=0, func=daily_digest)
    await sched.start()
    ...
    await sched.stop()
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any

from loguru import logger

AsyncFunc = Callable[[], Awaitable[Any]]


@dataclass(slots=True)
class ScheduledJob:
    func: AsyncFunc
    interval_seconds: float | None = None
    daily_time: time | None = None
    name: str = "job"
    next_run: datetime = field(default_factory=datetime.utcnow)
    runs: int = 0
    errors: int = 0


class Scheduler:
    def __init__(self) -> None:
        self._jobs: list[ScheduledJob] = []
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def every(self, *, seconds: float, func: AsyncFunc, name: str = "") -> ScheduledJob:
        job = ScheduledJob(
            func=func,
            interval_seconds=seconds,
            name=name or func.__name__,
            next_run=datetime.utcnow() + timedelta(seconds=seconds),
        )
        self._jobs.append(job)
        return job

    def daily_at(
        self, *, hour: int, minute: int, func: AsyncFunc, name: str = ""
    ) -> ScheduledJob:
        t = time(hour=hour, minute=minute)
        now = datetime.utcnow()
        today_run = datetime.combine(now.date(), t)
        next_run = today_run if today_run > now else today_run + timedelta(days=1)
        job = ScheduledJob(
            func=func,
            daily_time=t,
            name=name or func.__name__,
            next_run=next_run,
        )
        self._jobs.append(job)
        return job

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task
            self._task = None

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            now = datetime.utcnow()
            for job in self._jobs:
                if job.next_run <= now:
                    try:
                        await job.func()
                        job.runs += 1
                    except Exception as exc:
                        job.errors += 1
                        logger.error("Ошибка задачи {}: {}", job.name, exc)
                    # compute next run
                    if job.interval_seconds is not None:
                        job.next_run = datetime.utcnow() + timedelta(
                            seconds=job.interval_seconds
                        )
                    elif job.daily_time is not None:
                        next_date = datetime.utcnow().date() + timedelta(days=1)
                        job.next_run = datetime.combine(next_date, job.daily_time)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=1.0)
            except TimeoutError:
                pass

    @property
    def jobs(self) -> list[ScheduledJob]:
        return list(self._jobs)


__all__ = ["ScheduledJob", "Scheduler"]
