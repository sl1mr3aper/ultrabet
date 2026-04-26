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

    def _reset_daily_if_needed(self, user: User, now: datetime) -> None:
        if user.daily_reset_at is None or _make_aware(user.daily_reset_at) <= now:
            user.daily_used = 0
            user.daily_reset_at = now + timedelta(hours=24)

    def _is_subscription_active(self, user: User, now: datetime) -> bool:
        return (
            user.subscription_until is not None
            and _make_aware(user.subscription_until) > now
        )

    async def check_quota(
        self, user: User, *, subscription_daily_limit: int
    ) -> tuple[bool, str]:
        """Проверяем без списания, что пользователь может запросить прогноз.

        Возврат: (allowed, source), где source ∈ {"sub", "free", ""}.
        """
        now = datetime.now(tz=UTC)
        if user.is_blocked:
            return False, ""
        self._reset_daily_if_needed(user, now)
        sub_active = self._is_subscription_active(user, now)
        if sub_active:
            quota = min(
                user.subscription_daily_quota or subscription_daily_limit,
                subscription_daily_limit,
            )
            if user.daily_used < quota:
                await self._session.flush()
                return True, "sub"
            # Подписка активна, но квота исчерпана — не разрешаем тратить фри
            await self._session.flush()
            return False, ""
        if (user.free_predictions_left or 0) > 0:
            await self._session.flush()
            return True, "free"
        await self._session.flush()
        return False, ""

    async def commit_quota(
        self, user: User, *, subscription_daily_limit: int
    ) -> str:
        """Списать одну единицу квоты после успешного отчёта.

        Приоритет: подписка → free (подписка сохраняет фри до экспирации).
        Возвращает источник списания или "" если ничего не списано.
        """
        now = datetime.now(tz=UTC)
        self._reset_daily_if_needed(user, now)
        sub_active = self._is_subscription_active(user, now)
        if sub_active:
            quota = min(
                user.subscription_daily_quota or subscription_daily_limit,
                subscription_daily_limit,
            )
            if user.daily_used < quota:
                user.daily_used += 1
                await self._session.flush()
                return "sub"
            return ""
        if (user.free_predictions_left or 0) > 0:
            user.free_predictions_left -= 1
            await self._session.flush()
            return "free"
        return ""

    # Обратная совместимость: синхронный ``consume_quota`` использовался старыми
    # хендлерами; теперь просто делает check+commit атомарно.
    async def consume_quota(
        self,
        user: User,
        *,
        daily_quota_for_subs: int = 40,
        subscription_daily_limit: int | None = None,
    ) -> bool:
        limit = subscription_daily_limit or daily_quota_for_subs or 40
        ok, _ = await self.check_quota(user, subscription_daily_limit=limit)
        if not ok:
            return False
        return bool(await self.commit_quota(user, subscription_daily_limit=limit))

    async def add_bonus(self, user: User, amount: int) -> None:
        """Deprecated: bonus predictions removed from product.

        Оставлен как no-op для обратной совместимости с рефер-сервисом.
        """
        return

    async def set_blocked(self, user: User, blocked: bool) -> None:
        user.is_blocked = blocked
        await self._session.flush()


def _make_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


__all__ = ["UserRepository"]
