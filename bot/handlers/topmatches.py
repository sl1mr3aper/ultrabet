"""Топ матчей дня по значимости."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.keyboards import main_menu_keyboard, matches_keyboard
from config import Settings
from services.countries import format_country
from services.top_matches import TopMatchesService

router = Router(name="topmatches")


@router.message(Command("top"))
async def top_command(message: Message) -> None:
    settings: Settings = message.bot["settings"]  # type: ignore[index]
    sstats = message.bot["sstats"]  # type: ignore[index]
    today = (datetime.now(tz=UTC) + timedelta(hours=settings.timezone_offset)).strftime(
        "%Y-%m-%d"
    )
    service = TopMatchesService(sstats)
    top = await service.top_for_day(today, time_zone=settings.timezone_offset, limit=10)
    if not top:
        await message.answer("На сегодня значимых матчей не найдено.",
                              reply_markup=main_menu_keyboard())
        return
    lines = [f"⭐ *Топ матчей дня* ({today})", ""]
    for i, m in enumerate(top, start=1):
        prefix = format_country(m.country) if m.country else "🌐"
        lines.append(
            f"{i}. {prefix} *{m.home_name}* — *{m.away_name}* · {m.league_name or '—'} "
            f"(score {m.score:.2f})"
        )
    fake_games = [
        {
            "id": m.game_id,
            "homeTeam": {"name": m.home_name},
            "awayTeam": {"name": m.away_name},
        }
        for m in top
    ]
    await message.answer(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=matches_keyboard(fake_games, callback_prefix="predict"),
    )
