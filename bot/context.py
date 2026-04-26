"""Глобальный реестр сервисов, доступный из handlers.

В aiogram 3.27+ Bot не поддерживает item assignment, поэтому храним
сервисы здесь, а main.py заполняет их при старте.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api.sstats_client import SStatsClient
    from config import Settings
    from services.analytics import AnalyticsService


class _Services:
    settings: Settings | None = None
    sstats: SStatsClient | None = None
    session_factory: object | None = None
    analytics: AnalyticsService | None = None


services = _Services()


__all__ = ["services"]
