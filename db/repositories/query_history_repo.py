"""Репозиторий истории запросов."""

from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import QueryHistory


class QueryHistoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        *,
        user_id: int,
        query_text: str,
        matched_game_id: int | None,
        success: bool,
    ) -> None:
        record = QueryHistory(
            user_id=user_id,
            query_text=query_text[:255],
            matched_game_id=matched_game_id,
            success=success,
        )
        self._session.add(record)
        await self._session.flush()

    async def list_for_user(
        self, user_id: int, *, limit: int = 20
    ) -> list[QueryHistory]:
        result = await self._session.scalars(
            select(QueryHistory)
            .where(QueryHistory.user_id == user_id)
            .order_by(desc(QueryHistory.created_at))
            .limit(limit)
        )
        return list(result)


__all__ = ["QueryHistoryRepository"]
