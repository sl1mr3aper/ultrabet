"""Тесты time_utils."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

from services.time_utils import (
    day_end,
    day_start,
    format_match_time,
    humanize_timedelta,
    is_today,
    is_tomorrow,
    month_start,
    to_local,
    to_utc,
    week_end,
    week_start,
)


def test_utc_to_local():
    dt = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    local = to_local(dt, offset_hours=3)
    assert local.hour == 15


def test_to_utc_from_naive():
    dt = datetime(2024, 1, 1, 12, 0)
    utc = to_utc(dt)
    assert utc.tzinfo is not None


def test_to_utc_from_aware():
    dt = datetime(2024, 1, 1, 15, 0, tzinfo=timezone(timedelta(hours=3)))
    utc = to_utc(dt)
    assert utc.hour == 12


def test_is_today():
    now_utc = datetime.now(UTC)
    assert is_today(now_utc) is True


def test_is_tomorrow():
    tomorrow = datetime.now(UTC) + timedelta(days=1)
    assert is_tomorrow(tomorrow) is True


def test_format_match_time_today():
    local_now = datetime.now(timezone(timedelta(hours=3)))
    dt = local_now.replace(hour=20, minute=30).astimezone(UTC)
    out = format_match_time(dt)
    # либо "сегодня" либо "завтра" — зависит от времени, но точно одна из них
    assert "20:30" in out or "23:30" in out


def test_humanize_now():
    assert humanize_timedelta(timedelta(seconds=0)) == "сейчас"


def test_humanize_future():
    assert "через" in humanize_timedelta(timedelta(hours=2, minutes=30))


def test_humanize_past():
    assert "назад" in humanize_timedelta(timedelta(hours=-3))


def test_humanize_minutes_only():
    assert "5 мин" in humanize_timedelta(timedelta(minutes=5))


def test_humanize_days():
    out = humanize_timedelta(timedelta(days=3))
    assert "3" in out


def test_day_start_end():
    d = date(2024, 1, 15)
    start = day_start(d, offset_hours=3)
    end = day_end(d, offset_hours=3)
    assert start < end


def test_week_start_sunday_date():
    d = date(2024, 1, 7)  # Воскресенье
    assert week_start(d) == date(2024, 1, 1)


def test_week_end():
    d = date(2024, 1, 3)  # Среда
    assert week_end(d) == date(2024, 1, 7)


def test_month_start():
    d = date(2024, 1, 15)
    assert month_start(d) == date(2024, 1, 1)


def test_format_match_time_far_future():
    # 10 дней вперёд → должно быть DD.MM
    future_utc = datetime.now(UTC) + timedelta(days=10)
    out = format_match_time(future_utc)
    assert "." in out
