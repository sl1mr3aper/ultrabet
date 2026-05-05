"""Единый стайл-гайд оформления сообщений бота.

Все handler'ы должны использовать функции отсюда, а не вручную клеить
строки. Это даёт одинаковый вид всех экранов.
"""

from __future__ import annotations

# ── Базовая палитра / разделители ─────────────────────────────────────
# По просьбе пользователя декоративные линии-разделители убраны
# из всех заголовков: вместо полосок просто пустая строка.
DIVIDER = ""
DIVIDER_THIN = ""
BULLET = "•"
ARROW = "➤"

# ── Семантические эмодзи ──────────────────────────────────────────────
ICON_OK = "✅"
ICON_FAIL = "❌"
ICON_WARN = "⚠️"
ICON_INFO = "ℹ️"
ICON_LOADING = "⏳"
ICON_FIRE = "🔥"
ICON_TROPHY = "🏆"
ICON_SHIELD = "🛡️"
ICON_TARGET = "🎯"
ICON_BALL = "⚽"
ICON_STAR = "⭐"
ICON_CROWN = "👑"
ICON_BACK = "◀️"
ICON_FORWARD = "▶️"
ICON_HOME = "🏠"
ICON_PROFILE = "👤"
ICON_CALENDAR = "📅"
ICON_GLOBE = "🌍"
ICON_CHART = "📊"
ICON_MONEY = "💰"
ICON_GIFT = "🎁"
ICON_DOC = "📄"
ICON_BELL = "🔔"
ICON_INJURY = "🚑"
ICON_TREND_UP = "📈"
ICON_TREND_DOWN = "📉"
ICON_SWORDS = "⚔️"
ICON_TEAM = "🧑‍🤝‍🧑"
ICON_PLAYER = "⚽"
ICON_BOOK = "📖"
ICON_BOOKMAKER = "🎰"


def header(title: str, *, icon: str = ICON_BALL) -> str:
    """Главный заголовок экрана (без декоративных полосок)."""
    return f"{icon} *{title}*\n"


def subheader(title: str, *, icon: str = "") -> str:
    """Под-заголовок секции (пустая строка как разделитель)."""
    prefix = f"{icon} " if icon else ""
    return f"\n{prefix}*{title}*\n"


def section(text: str) -> str:
    """Секционный блок."""
    return f"\n{text}"


def kv(key: str, value: str) -> str:
    """Пара «ключ: значение» — единый формат."""
    return f"{BULLET} *{key}:* {value}"


def list_item(index: int, text: str) -> str:
    return f"{index:>2}. {text}"


def bullet(text: str) -> str:
    return f"{BULLET} {text}"


def status_loading(text: str = "Загружаю данные…") -> str:
    return f"{ICON_LOADING} {text}"


def status_error(text: str) -> str:
    return f"{ICON_FAIL} {text}"


def status_ok(text: str) -> str:
    return f"{ICON_OK} {text}"


def status_info(text: str) -> str:
    return f"{ICON_INFO} {text}"


def percent(value: float, *, decimals: int = 1) -> str:
    return f"{value * 100:.{decimals}f}%"


def emoji_for_probability(prob: float) -> str:
    if prob >= 0.85:
        return f"{ICON_FIRE}{ICON_FIRE}"
    if prob >= 0.70:
        return ICON_FIRE
    if prob >= 0.55:
        return ICON_OK
    if prob >= 0.45:
        return "⚡"
    if prob >= 0.35:
        return "🟡"
    return "🔻"


def emoji_for_value(value_pct: float) -> str:
    if value_pct >= 15:
        return "💎"
    if value_pct >= 8:
        return "🟢"
    if value_pct >= 3:
        return "✅"
    return "·"


def truncate(text: str, *, limit: int = 4000) -> str:
    """Обрезка для лимита Telegram (4096 в Markdown 4000 безопасно)."""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def escape_md(text: str) -> str:
    """Экранирование Markdown-V1."""
    if not text:
        return ""
    for ch in ("_", "*", "`", "["):
        text = text.replace(ch, "\\" + ch)
    return text


__all__ = [
    "ARROW",
    "BULLET",
    "DIVIDER",
    "DIVIDER_THIN",
    "ICON_BACK",
    "ICON_BALL",
    "ICON_BELL",
    "ICON_BOOK",
    "ICON_BOOKMAKER",
    "ICON_CALENDAR",
    "ICON_CHART",
    "ICON_CROWN",
    "ICON_DOC",
    "ICON_FAIL",
    "ICON_FIRE",
    "ICON_FORWARD",
    "ICON_GIFT",
    "ICON_GLOBE",
    "ICON_HOME",
    "ICON_INFO",
    "ICON_INJURY",
    "ICON_LOADING",
    "ICON_MONEY",
    "ICON_OK",
    "ICON_PLAYER",
    "ICON_PROFILE",
    "ICON_SHIELD",
    "ICON_STAR",
    "ICON_SWORDS",
    "ICON_TARGET",
    "ICON_TEAM",
    "ICON_TREND_DOWN",
    "ICON_TREND_UP",
    "ICON_TROPHY",
    "ICON_WARN",
    "bullet",
    "emoji_for_probability",
    "emoji_for_value",
    "escape_md",
    "header",
    "kv",
    "list_item",
    "percent",
    "section",
    "status_error",
    "status_info",
    "status_loading",
    "status_ok",
    "subheader",
    "truncate",
]
