"""Репозиторий пользователей."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create(
        self,
        *,
        tg_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        language_code: str | None,
        free_initial: int,
    ) -> tuple[User, bool]:
        user = await self._session.scalar(select(User).where(User.tg_id == tg_id))
        created = False
        if user is None:
            user = User(
                tg_id=tg_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                language_code=language_code or "ru",
                free_predictions_left=free_initial,
            )
            self._session.add(user)
            await self._session.flush()
            created = True
        else:
            updated = False
            if user.username != username:
                user.username = username
                updated = True
            if user.first_name != first_name:
                user.first_name = first_name
                updated = True
            if user.last_name != last_name:
                user.last_name = last_name
                updated = True
            if updated:
                await self._session.flush()
        return user, created

    async def get_by_tg_id(self, tg_id: int) -> User | None:
        return await self._session.scalar(select(User).where(User.tg_id == tg_id))

    async def get_by_id(self, user_id: int) -> User | None:
        return await self._session.get(User, user_id)

    async def list_expired_subscriptions(self) -> list[User]:
        """Пользователи с истекшей подпиской, у которых ещё заполнен план."""
        now = datetime.now(tz=UTC)
        result = await self._session.scalars(
            select(User).where(
                User.subscription_plan.is_not(None),
                User.subscription_until.is_not(None),
                User.subscription_until <= now,
            )
        )
        return list(result)

    async def all_users(self, *, limit: int = 1000, offset: int = 0) -> list[User]:
        result = await self._session.scalars(
            select(User).order_by(User.id.desc()).limit(limit).offset(offset)
        )
        return list(result)

    async def stats(self) -> dict[str, Any]:
        total = await self._session.scalar(select(func.count(User.id)))
        active = await self._session.scalar(
            select(func.count(User.id)).where(
                User.subscription_until.is_not(None),
                User.subscription_until > datetime.now(tz=UTC),
            )
        )
        blocked = await self._session.scalar(
            select(func.count(User.id)).where(User.is_blocked.is_(True))
        )
        last_24h_dt = datetime.now(tz=UTC) - timedelta(hours=24)
        new_today = await self._session.scalar(
            select(func.count(User.id)).where(User.created_at > last_24h_dt)
        )
        return {
            "total": int(total or 0),
            "active_subscriptions": int(active or 0),
            "blocked": int(blocked or 0),
            "new_24h": int(new_today or 0),
        }

    async def consume_quota(self, user: User, *, daily_quota_for_subs: int) -> bool:
        """Списать одну единицу квоты прогноза. True — успех."""
        now = datetime.now(tz=UTC)
        if user.is_blocked:
            return False

        # сброс daily счётчика
        if user.daily_reset_at is None or _make_aware(user.daily_reset_at) <= now:
            user.daily_used = 0
            user.daily_reset_at = now + timedelta(hours=24)

        sub_active = (
            user.subscription_until is not None
            and _make_aware(user.subscription_until) > now
        )
        if sub_active:
            quota = user.subscription_daily_quota or daily_quota_for_subs
            if user.daily_used < quota:
                user.daily_used += 1
                await self._session.flush()
                return True

        if (user.bonus_predictions or 0) > 0:
            user.bonus_predictions -= 1
            await self._session.flush()
            return True
        if (user.free_predictions_left or 0) > 0:
            user.free_predictions_left -= 1
            await self._session.flush()
            return True

        if sub_active:
            return False
        return False

    async def add_bonus(self, user: User, amount: int) -> None:
        if amount <= 0:
            return
        user.bonus_predictions = (user.bonus_predictions or 0) + amount
        await self._session.flush()

    async def set_blocked(self, user: User, blocked: bool) -> None:
        user.is_blocked = blocked
        await self._session.flush()


def _make_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


__all__ = ["UserRepository"]
