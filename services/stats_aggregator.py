"""Агрегатор глобальной статистики приложения."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Feedback,
    PaymentLog,
    PredictionLog,
    QueryHistory,
    Referral,
    User,
)


@dataclass(slots=True)
class GlobalStats:
    total_users: int
    blocked_users: int
    paid_users: int
    total_predictions: int
    total_queries: int
    successful_queries: int
    total_referrals: int
    total_feedback: int
    total_payments: int

    @property
    def query_success_rate(self) -> float:
        if not self.total_queries:
            return 0.0
        return self.successful_queries / self.total_queries * 100.0

    @property
    def conversion_pct(self) -> float:
        if not self.total_users:
            return 0.0
        return self.paid_users / self.total_users * 100.0


class StatsAggregator:
    """Считает глобальные показатели для админки."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def collect(self) -> GlobalStats:
        total_users = await self._scalar(select(func.count(User.id)))
        blocked_users = await self._scalar(
            select(func.count(User.id)).where(User.is_blocked.is_(True))
        )
        paid_users = await self._scalar(
            select(func.count(User.id)).where(User.subscription_plan.is_not(None))
        )
        total_predictions = await self._scalar(select(func.count(PredictionLog.id)))
        total_queries = await self._scalar(select(func.count(QueryHistory.id)))
        successful_queries = await self._scalar(
            select(func.count(QueryHistory.id)).where(QueryHistory.success.is_(True))
        )
        total_referrals = await self._scalar(select(func.count(Referral.id)))
        total_feedback = await self._scalar(select(func.count(Feedback.id)))
        total_payments = await self._scalar(select(func.count(PaymentLog.id)))
        return GlobalStats(
            total_users=total_users,
            blocked_users=blocked_users,
            paid_users=paid_users,
            total_predictions=total_predictions,
            total_queries=total_queries,
            successful_queries=successful_queries,
            total_referrals=total_referrals,
            total_feedback=total_feedback,
            total_payments=total_payments,
        )

    async def _scalar(self, stmt) -> int:
        return int((await self._session.scalar(stmt)) or 0)


__all__ = ["GlobalStats", "StatsAggregator"]
