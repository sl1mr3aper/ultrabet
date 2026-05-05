"""Кэш adjustment_factor'ов для применения в `value_engine`.

Раз в час фоновая задача дёргает `SecondaryPickCalibrator.compute_adjustments()`
и обновляет глобальный кэш. PredictionService читает из него синхронно,
без обращения к БД на каждом запросе.

Это позволяет применять накопленную эмпирику к новым прогнозам без
заметной задержки (микросекунды вместо ms на SELECT).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger


class PickAdjustmentCache:
    """Простой in-memory кэш с TTL и фоновым refresh."""

    def __init__(
        self,
        session_factory: Any,
        *,
        refresh_interval_seconds: int = 3600,
    ) -> None:
        self._session_factory = session_factory
        self._refresh_interval = refresh_interval_seconds
        self._adjustments_any: dict[str, float] = {}
        self._adjustments_main_lost: dict[str, float] = {}
        self._adjustments_main_won: dict[str, float] = {}
        self._updated_at: datetime | None = None
        self._task: asyncio.Task[None] | None = None

    def get_for(
        self, condition: str = "any",
    ) -> dict[str, float]:
        """Получить {market_key: factor} для указанного условия."""
        if condition == "main_lost":
            return dict(self._adjustments_main_lost)
        if condition == "main_won":
            return dict(self._adjustments_main_won)
        return dict(self._adjustments_any)

    @property
    def updated_at(self) -> datetime | None:
        return self._updated_at

    async def refresh_now(self) -> int:
        """Прочитать из таблицы `pick_adjustments` и закэшировать."""
        from services.secondary_pick_calibrator import (
            SecondaryPickCalibrator,
        )

        calib = SecondaryPickCalibrator(self._session_factory)
        any_adj = await calib.get_adjustments(condition="any")
        ml_adj = await calib.get_adjustments(condition="main_lost")
        mw_adj = await calib.get_adjustments(condition="main_won")
        self._adjustments_any = any_adj
        self._adjustments_main_lost = ml_adj
        self._adjustments_main_won = mw_adj
        self._updated_at = datetime.now(tz=UTC)
        return len(any_adj)

    async def start(self) -> None:
        """Запустить фоновый refresh-loop."""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                n = await self.refresh_now()
                if n > 0:
                    logger.info(
                        "PickAdjustmentCache refreshed: {} markets",
                        n,
                    )
            except Exception as exc:
                logger.warning("PickAdjustmentCache refresh failed: {}", exc)
            try:
                await asyncio.sleep(self._refresh_interval)
            except asyncio.CancelledError:
                return

    def is_stale(self, *, max_age_seconds: int = 7200) -> bool:
        if self._updated_at is None:
            return True
        return (datetime.now(tz=UTC) - self._updated_at) > timedelta(
            seconds=max_age_seconds,
        )


__all__ = ["PickAdjustmentCache"]
