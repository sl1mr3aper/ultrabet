"""Профиль пользователя — агрегаты по запросам, истории, бонусам."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import PredictionLog, QueryHistory, User


@dataclass(slots=True)
class UserProfile:
    user: User
    total_predictions: int
    last_prediction_at: datetime | None
    total_queries: int
    successful_queries: int


class ProfileService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user: User) -> UserProfile:
        pred_q = select(PredictionLog).where(PredictionLog.user_id == user.id)
        pred_rows = (await self._session.execute(pred_q)).scalars().all()
        last_pred_at = max((p.created_at for p in pred_rows), default=None)
        history_q = select(QueryHistory).where(QueryHistory.user_id == user.id)
        history_rows = (await self._session.execute(history_q)).scalars().all()
        successful = sum(1 for h in history_rows if h.success)
        return UserProfile(
            user=user,
            total_predictions=len(pred_rows),
            last_prediction_at=last_pred_at,
            total_queries=len(history_rows),
            successful_queries=successful,
        )


__all__ = ["ProfileService", "UserProfile"]
