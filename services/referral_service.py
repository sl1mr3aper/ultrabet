"""Реферальная система."""

from __future__ import annotations

import secrets
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Referral, User
from services.subscription_service import SUBSCRIPTION_PLANS


def _gen_code() -> str:
    return secrets.token_urlsafe(6)


class ReferralService:
    """Хранит коды, начисляет бонусы за привлечение и за подписки."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        bonus_signup: int = 3,
        bonus_sub_1m: int = 5,
        bonus_sub_3m: int = 15,
        bonus_sub_12m: int = 45,
    ) -> None:
        self._session = session
        self._bonus_signup = bonus_signup
        self._bonus_sub: dict[str, int] = {
            "1m": bonus_sub_1m,
            "3m": bonus_sub_3m,
            "12m": bonus_sub_12m,
        }

    async def ensure_code(self, user: User) -> str:
        if user.referral_code:
            return user.referral_code
        for _ in range(5):
            candidate = _gen_code()
            existing = await self._session.scalar(
                select(User).where(User.referral_code == candidate)
            )
            if existing is None:
                user.referral_code = candidate
                await self._session.flush()
                return candidate
        user.referral_code = _gen_code() + str(user.tg_id)
        await self._session.flush()
        return user.referral_code

    @staticmethod
    def build_link(bot_username: str, code: str) -> str:
        return f"https://t.me/{bot_username}?start=ref_{code}"

    async def find_referrer(self, code: str) -> User | None:
        if not code:
            return None
        return await self._session.scalar(select(User).where(User.referral_code == code))

    async def attach_referral(self, *, referrer: User, referred: User) -> bool:
        if referrer.id == referred.id:
            return False
        if referred.referred_by_id:
            return False
        existing = await self._session.scalar(
            select(Referral).where(
                Referral.referrer_id == referrer.id,
                Referral.referred_id == referred.id,
            )
        )
        if existing is not None:
            return False
        record = Referral(referrer_id=referrer.id, referred_id=referred.id)
        self._session.add(record)
        referred.referred_by_id = referrer.id
        # Бонусы выдаём как бесплатные запросы (отдельной "бонусной" квоты нет)
        referrer.free_predictions_left = (
            (referrer.free_predictions_left or 0) + self._bonus_signup
        )
        referrer.referral_signup_bonus_total = (
            (referrer.referral_signup_bonus_total or 0) + self._bonus_signup
        )
        await self._session.flush()
        logger.info(
            "referral attached: referrer={} (+{}) -> referred={}",
            referrer.tg_id, self._bonus_signup, referred.tg_id,
        )
        return True

    async def reward_for_subscription(
        self, *, referred: User, plan_code: str
    ) -> dict[str, Any] | None:
        if not referred.referred_by_id:
            return None
        bonus = self._bonus_sub.get(plan_code)
        if not bonus:
            return None
        plan = SUBSCRIPTION_PLANS.get(plan_code)
        referrer = await self._session.get(User, referred.referred_by_id)
        if referrer is None:
            return None
        referrer.free_predictions_left = (
            (referrer.free_predictions_left or 0) + bonus
        )
        referrer.referral_sub_bonus_total = (
            (referrer.referral_sub_bonus_total or 0) + bonus
        )
        record = await self._session.scalar(
            select(Referral).where(
                Referral.referrer_id == referrer.id,
                Referral.referred_id == referred.id,
            )
        )
        if record is not None:
            record.subscription_plan = plan_code
        await self._session.flush()
        return {
            "referrer_id": referrer.tg_id,
            "plan": plan_code,
            "plan_title": plan.title if plan else plan_code,
            "bonus": bonus,
        }

    async def stats(self, user: User) -> dict[str, Any]:
        rows = await self._session.scalars(
            select(Referral).where(Referral.referrer_id == user.id)
        )
        rows_list = list(rows)
        paid = sum(1 for r in rows_list if r.subscription_plan)
        return {
            "code": user.referral_code or "",
            "total_referred": len(rows_list),
            "paid_referred": paid,
            "bonus_signup_total": user.referral_signup_bonus_total or 0,
            "bonus_sub_total": user.referral_sub_bonus_total or 0,
            "current_bonus_balance": user.free_predictions_left or 0,
        }


__all__ = ["ReferralService"]
