"""Сервис фоновых уведомлений: напоминания о матчах, push с главными прогнозами.

Пока работает в режиме on-demand из админки. В будущем подключим Celery/APScheduler.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User


@dataclass(slots=True)
class BroadcastResult:
    sent: int
    failed: int
    blocked: int


class NotificationService:
    """Простая шина уведомлений."""

    def __init__(self, bot: Bot, *, throttle: float = 0.05) -> None:
        self._bot = bot
        self._throttle = throttle

    async def broadcast(
        self, session: AsyncSession, text: str, *, only_paid: bool = False
    ) -> BroadcastResult:
        stmt = select(User).where(User.is_blocked.is_(False))
        if only_paid:
            stmt = stmt.where(User.subscription_plan.is_not(None))
        users = (await session.execute(stmt)).scalars().all()
        return await self._send_to_users(users, text)

    async def notify_ids(
        self, ids: Sequence[int], text: str
    ) -> BroadcastResult:
        return await self._send_to_ids(ids, text)

    async def _send_to_users(self, users: Iterable[User], text: str) -> BroadcastResult:
        return await self._send_to_ids([u.tg_id for u in users], text)

    async def _send_to_ids(self, ids: Iterable[int], text: str) -> BroadcastResult:
        sent = failed = blocked = 0
        for tg_id in ids:
            try:
                await self._bot.send_message(tg_id, text, parse_mode="Markdown")
                sent += 1
            except Exception as exc:
                msg = str(exc).lower()
                if "blocked" in msg or "deactivated" in msg:
                    blocked += 1
                else:
                    failed += 1
            await asyncio.sleep(self._throttle)
        return BroadcastResult(sent=sent, failed=failed, blocked=blocked)


__all__ = ["BroadcastResult", "NotificationService"]
