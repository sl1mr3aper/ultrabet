"""Репозиторий логов прогнозов."""

from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import PredictionLog


class PredictionLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, log: PredictionLog) -> None:
        self._session.add(log)
        await self._session.flush()

    async def list_for_user(self, user_id: int, *, limit: int = 20) -> list[PredictionLog]:
        result = await self._session.scalars(
            select(PredictionLog)
            .where(PredictionLog.user_id == user_id)
            .order_by(desc(PredictionLog.created_at))
            .limit(limit)
        )
        return list(result)


__all__ = ["PredictionLogRepository"]
