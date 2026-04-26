"""Переводит ошибки API / сети в понятные пользователю сообщения.

Когда SStats / aiohttp / telegram бросают исключения, handler ловит их через
ErrorMiddleware, но для дружелюбных сообщений мы хотим распознать конкретный
вид ошибки (timeout, rate limit, 404, 500, network) и показать подходящий
текст.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from bot.styles import ICON_FAIL, ICON_WARN, status_error


@dataclass(slots=True)
class TranslatedError:
    kind: str  # "timeout" | "rate_limit" | "not_found" | "server" | "network" | "generic"
    user_message: str
    technical: str
    retryable: bool


def translate(exc: BaseException) -> TranslatedError:
    name = exc.__class__.__name__.lower()
    msg = str(exc)
    low = msg.lower()
    if isinstance(exc, asyncio.TimeoutError) or "timeout" in name:
        return TranslatedError(
            kind="timeout",
            user_message=status_error(
                "API SStats не ответил вовремя. Попробуй ещё раз через минуту."
            ),
            technical=msg,
            retryable=True,
        )
    if "429" in msg or "rate" in low or "too many" in low:
        return TranslatedError(
            kind="rate_limit",
            user_message=(
                f"{ICON_WARN} Ты отправляешь запросы слишком часто. "
                "Дай SStats отдохнуть секунд 10."
            ),
            technical=msg,
            retryable=True,
        )
    if "404" in msg or "not found" in low:
        return TranslatedError(
            kind="not_found",
            user_message=status_error(
                "Данные не найдены. Проверь id матча/лиги и попробуй ещё раз."
            ),
            technical=msg,
            retryable=False,
        )
    if any(s in msg for s in ("500", "502", "503", "504")) or "server" in low:
        return TranslatedError(
            kind="server",
            user_message=status_error(
                "API SStats сейчас недоступно. Уже сообщил админам, попробуй позже."
            ),
            technical=msg,
            retryable=True,
        )
    if any(
        s in name
        for s in ("connection", "dns", "clienterror", "socket", "network")
    ):
        return TranslatedError(
            kind="network",
            user_message=status_error(
                "Проблема с соединением. Проверь интернет и попробуй ещё раз."
            ),
            technical=msg,
            retryable=True,
        )
    return TranslatedError(
        kind="generic",
        user_message=f"{ICON_FAIL} Что-то пошло не так. Попробуй /start.",
        technical=msg,
        retryable=False,
    )


__all__ = ["TranslatedError", "translate"]
