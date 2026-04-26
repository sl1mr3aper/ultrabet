"""Репозиторий отзывов."""

from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Feedback


class FeedbackRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, *, user_id: int | None, text: str) -> Feedback:
        record = Feedback(user_id=user_id, text=text[:4000])
        self._session.add(record)
        await self._session.flush()
        return record

    async def latest(self, *, limit: int = 50) -> list[Feedback]:
        result = await self._session.scalars(
            select(Feedback).order_by(desc(Feedback.created_at)).limit(limit)
        )
        return list(result)


__all__ = ["FeedbackRepository"]
