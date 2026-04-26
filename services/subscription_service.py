"""Управление подписками пользователей."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User


class PlanCode(StrEnum):
    DAY_1 = "1d"
    WEEK_1 = "1w"
    MONTH_1 = "1m"
    MONTH_3 = "3m"
    MONTH_12 = "12m"


@dataclass(frozen=True, slots=True)
class SubscriptionPlan:
    code: str
    title: str
    days: int
    daily_quota: int
    referrer_bonus: int
    stars_price: int = 0
    badge: str = "🎯"
    description: str = ""

    @property
    def price(self) -> int:
        """Совместимость со старым API: цена в Stars."""
        return self.stars_price

    def end_date(self, now: datetime | None = None) -> datetime:
        base = now or datetime.now(tz=UTC)
        return base + timedelta(days=self.days)


_DAILY_QUOTA = 40

SUBSCRIPTION_PLANS: dict[str, SubscriptionPlan] = {
    PlanCode.DAY_1: SubscriptionPlan(
        PlanCode.DAY_1, "1 день", 1, _DAILY_QUOTA, 0,
        stars_price=50, badge="🎟",
        description="Тест-драйв на сутки: до 40 прогнозов.",
    ),
    PlanCode.WEEK_1: SubscriptionPlan(
        PlanCode.WEEK_1, "1 неделя", 7, _DAILY_QUOTA, 2,
        stars_price=250, badge="🎫",
        description="До 40 прогнозов в день + приоритетная очередь.",
    ),
    PlanCode.MONTH_1: SubscriptionPlan(
        PlanCode.MONTH_1, "1 месяц", 30, _DAILY_QUOTA, 5,
        stars_price=900, badge="💎",
        description="До 40 прогнозов в день + live-монитор и дайджест.",
    ),
    PlanCode.MONTH_3: SubscriptionPlan(
        PlanCode.MONTH_3, "3 месяца", 90, _DAILY_QUOTA, 15,
        stars_price=2400, badge="🔥",
        description="До 40 прогнозов в день + расширенная аналитика и экспорт.",
    ),
    PlanCode.MONTH_12: SubscriptionPlan(
        PlanCode.MONTH_12, "12 месяцев", 365, _DAILY_QUOTA, 45,
        stars_price=8400, badge="🌟",
        description="До 40 прогнозов в день без ограничений по функциям.",
    ),
}


class SubscriptionService:
    """Бизнес-логика подписок."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def get_plan(code: str) -> SubscriptionPlan | None:
        return SUBSCRIPTION_PLANS.get(code)

    @staticmethod
    def is_active(user: User, *, now: datetime | None = None) -> bool:
        if not user.subscription_until:
            return False
        moment = now or datetime.now(tz=UTC)
        until = user.subscription_until
        if until.tzinfo is None:
            until = until.replace(tzinfo=UTC)
        return until > moment

    async def activate(self, user: User, plan_code: str) -> SubscriptionPlan | None:
        plan = self.get_plan(plan_code)
        if plan is None:
            return None
        now = datetime.now(tz=UTC)
        if user.subscription_until and self.is_active(user, now=now):
            base = user.subscription_until
            if base.tzinfo is None:
                base = base.replace(tzinfo=UTC)
        else:
            base = now
        user.subscription_plan = plan.code
        user.subscription_until = base + timedelta(days=plan.days)
        user.subscription_daily_quota = plan.daily_quota
        await self._session.flush()
        return plan


__all__ = [
    "SUBSCRIPTION_PLANS",
    "PlanCode",
    "SubscriptionPlan",
    "SubscriptionService",
]
