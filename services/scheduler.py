"""Лёгкий scheduler без внешних зависимостей.

Запускает заданные корутины с заданным интервалом. Используется для будущих
фич типа daily-picks-broadcast, ежечасной инвалидации кеша и т.п.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from loguru import logger


@dataclass(slots=True)
class ScheduledJob:
    name: str
    interval_seconds: float
    coro_factory: Callable[[], Awaitable[None]]
    run_at_startup: bool = False
    _task: asyncio.Task[None] | None = None


class Scheduler:
    """Запускает повторяющиеся задачи в фоне."""

    def __init__(self) -> None:
        self._jobs: list[ScheduledJob] = []
        self._stopping = asyncio.Event()

    def add_job(
        self,
        name: str,
        interval_seconds: float,
        coro_factory: Callable[[], Awaitable[None]],
        *,
        run_at_startup: bool = False,
    ) -> None:
        self._jobs.append(
            ScheduledJob(
                name=name,
                interval_seconds=interval_seconds,
                coro_factory=coro_factory,
                run_at_startup=run_at_startup,
            )
        )

    async def start(self) -> None:
        for job in self._jobs:
            job._task = asyncio.create_task(self._loop(job), name=f"job:{job.name}")

    async def stop(self) -> None:
        self._stopping.set()
        for job in self._jobs:
            if job._task and not job._task.done():
                job._task.cancel()
        await asyncio.gather(
            *[job._task for job in self._jobs if job._task],
            return_exceptions=True,
        )

    async def _loop(self, job: ScheduledJob) -> None:
        try:
            if job.run_at_startup:
                await self._run_one(job)
            while not self._stopping.is_set():
                try:
                    await asyncio.wait_for(
                        self._stopping.wait(), timeout=job.interval_seconds
                    )
                    break  # выход — был выставлен flag
                except TimeoutError:
                    pass
                await self._run_one(job)
        except asyncio.CancelledError:
            return

    async def _run_one(self, job: ScheduledJob) -> None:
        try:
            await job.coro_factory()
        except Exception as exc:
            logger.exception("scheduled job '{}' failed: {}", job.name, exc)


__all__ = ["ScheduledJob", "Scheduler"]
