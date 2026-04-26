"""Форматирование сообщений: прогноз, таблицы, профили."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from core.markets import label_for
from services.countries import format_country
from services.prediction_service import PredictionResult


def _emoji_for_prob(prob: float) -> str:
    p = prob * 100.0
    if p >= 78:
        return "🔥🔥"
    if p >= 65:
        return "🔥"
    if p >= 55:
        return "✅"
    if p >= 45:
        return "⚡"
    if p >= 35:
        return "🟡"
    return "❗"


def _human_date(date_iso: str | None, *, tz_offset: int = 3) -> str:
    if not date_iso:
        return "—"
    try:
        dt = datetime.fromisoformat(date_iso.replace("Z", "+00:00"))
    except ValueError:
        return date_iso
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    local = dt.astimezone()
    if tz_offset:
        from datetime import timedelta
        local = dt + timedelta(hours=tz_offset)
    return local.strftime("%d.%m.%Y %H:%M")


def format_prediction(
    result: PredictionResult,
    *,
    top_predictions: int = 15,
    top_value: int = 15,
    free_left: int = 0,
    bonus_left: int = 0,
    tz_offset: int = 3,
    daily_used: int | None = None,
    daily_quota: int | None = None,
) -> str:
    home = result.home_name
    away = result.away_name

    sorted_probs = sorted(result.probabilities.items(), key=lambda kv: kv[1], reverse=True)
    top = sorted_probs[:top_predictions]

    league_country = format_country(result.country_raw, with_flag=True)
    date_h = _human_date(result.date_iso, tz_offset=tz_offset)
    date_now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")

    parts: list[str] = []
    header = "⚽ *ПРОГНОЗ НА МАТЧ*"
    if result.is_finished:
        header = "⚽ *АНАЛИЗ СЫГРАННОГО МАТЧА*"
    parts.append(f"{header}  _(актуально {date_now})_")
    parts.append(f"⚔️ *Команды*: {home} — {away}")
    parts.append(f"📅 *Дата*: {date_h}")
    parts.append(f"🏆 *Лига*: {result.league_name} ({league_country})")

    if result.is_finished and result.home_score is not None and result.away_score is not None:
        parts.append(
            f"✅ *Матч сыгран — итог:* *{result.home_score}:{result.away_score}*  "
            f"({home} — {away})"
        )
    parts.append(
        f"🌟 *Glicko-2*: {result.home_rating:.0f} vs {result.away_rating:.0f}"
    )
    parts.append("")
    parts.append(f"📊 *ТОП-{top_predictions} ПРОГНОЗОВ* _(по вероятности)_")

    for idx, (key, prob) in enumerate(top, start=1):
        label = label_for(key, home=home, away=away)
        line = f"{idx}. {label} — *{prob * 100:.1f}%* {_emoji_for_prob(prob)}"
        parts.append(line)

    parts.append("")
    parts.append("🧮 *ВЕРОЯТНЫЕ ТОЧНЫЕ СЧЕТА*")
    if result.top_scores:
        for h, a, p in result.top_scores[:5]:
            parts.append(f"• {h}:{a} — *{p * 100:.1f}%*")
    else:
        parts.append("— нет данных")

    parts.append("")
    parts.append("🏹 *xG-АНАЛИЗ*")
    parts.append(f"• {home} → *{result.home_xg:.2f}*")
    parts.append(f"• {away} → *{result.away_xg:.2f}*")
    parts.append(f"• Общий тотал → *{result.home_xg + result.away_xg:.2f}*")

    parts.append("")
    parts.append(f"💎 *ТОП-{top_value} ВАЛУЙНЫХ СТАВОК*")
    parts.append("_Фильтр: p ≥ 90%, кф > 1.15 · сортировка по EV_")
    if result.value_bets:
        sorted_value = sorted(
            result.value_bets[:top_value],
            key=lambda b: b.value_percent,
            reverse=True,
        )
        for idx, vb in enumerate(sorted_value, start=1):
            label = label_for(vb.market_key, home=home, away=away)
            value_emoji = (
                "💎" if vb.value_percent >= 15 else
                "🟢" if vb.value_percent >= 8 else
                "✅"
            )
            parts.append(
                f"{idx}. {value_emoji} *{label}*\n"
                f"    p={vb.probability * 100:.1f}% · fair {vb.fair_odds:.2f} · "
                f"кф {vb.actual_odds:.2f} · *+{vb.value_percent:.2f}%*"
            )
    else:
        parts.append("— валуйных ставок под фильтром не найдено")

    if result.accuracy_notes:
        parts.append("")
        parts.append("🧠 *Корректировки точности*")
        for note in result.accuracy_notes[:6]:
            parts.append(f"• {note}")

    if result.injuries:
        parts.append("")
        parts.append(f"🚑 *Травмы и пропуски*: {len(result.injuries)} игроков")

    if result.summary_text:
        parts.append("")
        parts.append("📝 *Краткое резюме SStats*")
        text = result.summary_text.strip()
        parts.append(text[:600] + ("…" if len(text) > 600 else ""))

    parts.append("")
    if daily_quota and daily_quota > 0:
        parts.append(f"💎 Квота подписки: *{daily_used or 0}/{daily_quota}*  •  🆓 Бесплатных: *{free_left}*")
    else:
        parts.append(f"🆓 Бесплатных запросов осталось: *{free_left}*")
    return "\n".join(parts)


def format_match_list(
    matches: Iterable[dict[str, Any]], *, header: str, tz_offset: int = 3
) -> str:
    items = list(matches)
    if not items:
        return header + "\nНет матчей."
    lines = [header]
    for m in items[:30]:
        home = (m.get("homeTeam") or {}).get("name") or "?"
        away = (m.get("awayTeam") or {}).get("name") or "?"
        date_iso = m.get("date") or ""
        date = _human_date(date_iso, tz_offset=tz_offset)
        league = ((m.get("season") or {}).get("league") or {}).get("name") if isinstance(m.get("season"), dict) else None
        country = None
        season = m.get("season") or {}
        if isinstance(season, dict):
            league_obj = season.get("league") or {}
            if isinstance(league_obj, dict):
                c = league_obj.get("country")
                if isinstance(c, dict):
                    country = c.get("name")
        prefix = format_country(country) if country else "🌐"
        lines.append(f"{prefix} *{home}* — *{away}* · {league or '—'} · {date}")
    return "\n".join(lines)


def format_balance(
    *,
    free: int,
    bonus: int,
    plan: str | None,
    until: datetime | None,
    used: int,
    quota: int,
) -> str:
    from bot.texts import NO_SUBSCRIPTION, QUOTA_INFO

    if plan and until:
        until_text = until.strftime("%d.%m.%Y")
        plan_text = f"{plan} (до {until_text})"
    else:
        plan_text = NO_SUBSCRIPTION
        until_text = "—"
    return QUOTA_INFO.format(
        free=free,
        bonus=bonus,
        plan=plan_text,
        until=until_text,
        used=used,
        quota=max(quota, 0),
    )


def format_league_table(table: dict[str, Any] | None) -> str:
    if not table:
        return "Таблица пока недоступна."
    rows: list[dict[str, Any]] = []
    for key in ("standings", "table", "rows", "data"):
        if isinstance(table.get(key), list):
            rows = table[key]
            break
    if not rows:
        return "Таблица пуста."
    out = ["📋 *Турнирная таблица*"]
    for i, row in enumerate(rows[:20], start=1):
        team = (row.get("team") or {}).get("name") if isinstance(row.get("team"), dict) else row.get("team")
        played = row.get("played") or row.get("p") or 0
        points = row.get("points") or row.get("pts") or 0
        out.append(f"{i:2d}. {team or '?'} — {played} И, *{points} очк.*")
    return "\n".join(out)


__all__ = [
    "format_balance",
    "format_league_table",
    "format_match_list",
    "format_prediction",
]
