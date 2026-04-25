"""Middlewares: DB-сессии, throttling, идентификация пользователя, ошибки."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update
from loguru import logger
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.texts import ERROR_GENERIC, RATE_LIMITED
from db.models import User
from db.repositories.user_repo import UserRepository


class DbSessionMiddleware(BaseMiddleware):
    """Открывает AsyncSession для каждого update и кладёт в data['session']."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        super().__init__()
        self._factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self._factory() as session:
            data["session"] = session
            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise


class UserMiddleware(BaseMiddleware):
    """Создаёт/получает User из Telegram-апдейта и кладёт в data['user']."""

    def __init__(self, *, free_initial: int) -> None:
        super().__init__()
        self._free_initial = free_initial

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = _extract_tg_user(event)
        if tg_user is None:
            return await handler(event, data)
        session = data.get("session")
        if session is None:
            return await handler(event, data)
        repo = UserRepository(session)
        user, _ = await repo.get_or_create(
            tg_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            last_name=tg_user.last_name,
            language_code=tg_user.language_code,
            free_initial=self._free_initial,
        )
        data["user"] = user
        return await handler(event, data)


class ThrottlingMiddleware(BaseMiddleware):
    """Простой in-memory rate-limit (per user)."""

    def __init__(self, *, rate: float = 0.5) -> None:
        super().__init__()
        self._min_interval = rate
        self._last_seen: dict[int, float] = defaultdict(float)
        self._lock = asyncio.Lock()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = _extract_tg_user(event)
        if tg_user is None:
            return await handler(event, data)
        async with self._lock:
            now = time.monotonic()
            last = self._last_seen.get(tg_user.id, 0.0)
            if now - last < self._min_interval:
                await _send_temp(event, RATE_LIMITED)
                return None
            self._last_seen[tg_user.id] = now
        return await handler(event, data)


class ErrorMiddleware(BaseMiddleware):
    """Глобальный перехват исключений."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except Exception as exc:
            logger.exception("Handler failed: {}", exc)
            await _send_temp(event, ERROR_GENERIC)
            return None


class BlockedGuardMiddleware(BaseMiddleware):
    """Не пропускает заблокированных пользователей."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("user")
        if user is not None and user.is_blocked:
            await _send_temp(event, "🚫 Доступ ограничен.")
            return None
        return await handler(event, data)


def _extract_tg_user(event: TelegramObject) -> Any:
    if isinstance(event, Update):
        if event.message:
            return event.message.from_user
        if event.callback_query:
            return event.callback_query.from_user
        if event.edited_message:
            return event.edited_message.from_user
        return None
    if isinstance(event, Message):
        return event.from_user
    if isinstance(event, CallbackQuery):
        return event.from_user
    return getattr(event, "from_user", None)


async def _send_temp(event: TelegramObject, text: str) -> None:
    try:
        if isinstance(event, Message):
            await event.answer(text)
        elif isinstance(event, CallbackQuery):
            await event.answer(text, show_alert=False)
        elif isinstance(event, Update):
            if event.message:
                await event.message.answer(text)
            elif event.callback_query:
                await event.callback_query.answer(text, show_alert=False)
    except Exception:
        pass


__all__ = [
    "BlockedGuardMiddleware",
    "DbSessionMiddleware",
    "ErrorMiddleware",
    "ThrottlingMiddleware",
    "UserMiddleware",
]
