"""Центральная шина пользовательских уведомлений.

Типы событий:
- daily_digest: ежедневный дайджест валуйных ставок.
- live_alert: уведомление, если в live-матче возникла валуйная ставка.
- match_reminder: напоминание за 30 минут до старта матча.
- subscription_expiring: подписка скоро кончится.
- referral_reward: бонус за приглашённого.

Реализация простая: подписчики регистрируют callback, а основной код
публикует события. В проде подсовывается реальный Telegram-отправитель;
в тестах — счётчик.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from loguru import logger


class NotificationKind(str, Enum):
    DAILY_DIGEST = "daily_digest"
    LIVE_ALERT = "live_alert"
    MATCH_REMINDER = "match_reminder"
    SUBSCRIPTION_EXPIRING = "subscription_expiring"
    REFERRAL_REWARD = "referral_reward"
    BROADCAST = "broadcast"


@dataclass(slots=True)
class Notification:
    kind: NotificationKind
    target_tg_id: int
    title: str
    body: str
    data: dict[str, Any] = field(default_factory=dict)


Handler = Callable[[Notification], Awaitable[None]]


class NotificationBus:
    """Pub/sub по типам уведомлений."""

    def __init__(self) -> None:
        self._subscribers: dict[NotificationKind, list[Handler]] = defaultdict(list)
        self._delivered: int = 0
        self._failed: int = 0
        self._lock = asyncio.Lock()

    def subscribe(self, kind: NotificationKind, handler: Handler) -> None:
        self._subscribers[kind].append(handler)

    def unsubscribe(self, kind: NotificationKind, handler: Handler) -> None:
        if handler in self._subscribers[kind]:
            self._subscribers[kind].remove(handler)

    async def publish(self, notif: Notification) -> int:
        """Доставляет уведомление всем подписчикам. Возвращает число успешных."""
        subs = list(self._subscribers.get(notif.kind, []))
        if not subs:
            logger.debug("Нет подписчиков для {}", notif.kind)
            return 0
        ok = 0
        for h in subs:
            try:
                await h(notif)
                ok += 1
            except Exception as exc:
                logger.error("Ошибка доставки уведомления: {}", exc)
                async with self._lock:
                    self._failed += 1
        async with self._lock:
            self._delivered += ok
        return ok

    @property
    def delivered(self) -> int:
        return self._delivered

    @property
    def failed(self) -> int:
        return self._failed


__all__ = ["Handler", "Notification", "NotificationBus", "NotificationKind"]
