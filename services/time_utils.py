"""Утилиты работы со временем: конвертации, человекочитаемые форматы.

Используется во всех местах, где нужно показать "вчера", "через 2 часа" и т.п.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, timezone


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_local(dt: datetime, *, offset_hours: int = 3) -> datetime:
    """Конвертирует UTC → локальное время (по offset)."""
    tz = timezone(timedelta(hours=offset_hours))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(tz)


def to_utc(dt: datetime) -> datetime:
    """Приводит aware/naive → UTC aware."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def format_match_time(dt: datetime, *, offset_hours: int = 3) -> str:
    """Формат 'сегодня 18:30', 'завтра 20:00', 'в пятницу 18:30', 'DD.MM 18:30'."""
    local = to_local(dt, offset_hours=offset_hours)
    now = to_local(datetime.now(UTC), offset_hours=offset_hours)
    time_str = local.strftime("%H:%M")
    d = local.date()
    today = now.date()
    diff = (d - today).days
    if diff == 0:
        return f"сегодня {time_str}"
    if diff == 1:
        return f"завтра {time_str}"
    if diff == -1:
        return f"вчера {time_str}"
    if 0 < diff < 7:
        weekdays = [
            "в понедельник", "во вторник", "в среду", "в четверг",
            "в пятницу", "в субботу", "в воскресенье",
        ]
        return f"{weekdays[local.weekday()]} {time_str}"
    return f"{local.strftime('%d.%m')} {time_str}"


def humanize_timedelta(td: timedelta) -> str:
    """'через 2 ч 30 мин', '3 дня назад'."""
    total = int(td.total_seconds())
    if total == 0:
        return "сейчас"
    past = total < 0
    total = abs(total)
    parts: list[str] = []
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days > 0:
        parts.append(f"{days} {_plural_day(days)}")
    if hours > 0:
        parts.append(f"{hours} ч")
    if minutes > 0 and days == 0:
        parts.append(f"{minutes} мин")
    if not parts:
        parts.append("меньше минуты")
    joined = " ".join(parts)
    return f"{joined} назад" if past else f"через {joined}"


def _plural_day(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "день"
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return "дня"
    return "дней"


def is_today(dt: datetime, *, offset_hours: int = 3) -> bool:
    local = to_local(dt, offset_hours=offset_hours)
    now = to_local(datetime.now(UTC), offset_hours=offset_hours)
    return local.date() == now.date()


def is_tomorrow(dt: datetime, *, offset_hours: int = 3) -> bool:
    local = to_local(dt, offset_hours=offset_hours)
    now = to_local(datetime.now(UTC), offset_hours=offset_hours)
    return local.date() == now.date() + timedelta(days=1)


def day_start(d: date, *, offset_hours: int = 3) -> datetime:
    """Начало суток по локальному времени → UTC."""
    tz = timezone(timedelta(hours=offset_hours))
    return datetime.combine(d, time.min).replace(tzinfo=tz).astimezone(UTC)


def day_end(d: date, *, offset_hours: int = 3) -> datetime:
    tz = timezone(timedelta(hours=offset_hours))
    return datetime.combine(d, time.max).replace(tzinfo=tz).astimezone(UTC)


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def week_end(d: date) -> date:
    return week_start(d) + timedelta(days=6)


def month_start(d: date) -> date:
    return d.replace(day=1)


__all__ = [
    "day_end",
    "day_start",
    "format_match_time",
    "humanize_timedelta",
    "is_today",
    "is_tomorrow",
    "month_start",
    "to_local",
    "to_utc",
    "utc_now",
    "week_end",
    "week_start",
]
