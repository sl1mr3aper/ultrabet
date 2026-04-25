"""Daily picks — топ валуйных ставок дня."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from api.sstats_client import SStatsClient
from bot.keyboards import main_menu_keyboard
from config import Settings
from core.markets import label_for
from core.value_calculator import ValueCalculator
from services.daily_picks import DailyPicksGenerator

router = Router(name="dailypicks")


@router.message(Command("dailypicks"))
async def dailypicks_cmd(message: Message) -> None:
    settings: Settings = message.bot["settings"]  # type: ignore[index]
    sstats: SStatsClient = message.bot["sstats"]  # type: ignore[index]
    today = (datetime.now(tz=UTC) + timedelta(hours=settings.timezone_offset)).strftime(
        "%Y-%m-%d"
    )
    await message.answer(f"⏳ Сканирую матчи на {today}, это займёт около минуты…")
    generator = DailyPicksGenerator(
        sstats,
        value_calculator=ValueCalculator(
            min_odds=settings.min_value_odds,
            min_value_percent=settings.min_value_percent,
        ),
    )
    picks = await generator.for_date(
        today, top_n=10, time_zone=settings.timezone_offset
    )
    if not picks:
        await message.answer("Сегодня валуйных вариантов в базе не нашлось.",
                              reply_markup=main_menu_keyboard())
        return
    lines = [f"🏆 *Топ-{len(picks)} валуйных ставок на {today}*", ""]
    for i, p in enumerate(picks, start=1):
        market_label = label_for(p.bet.market_key, home=p.result.home_name, away=p.result.away_name)
        lines.append(
            f"{i}. *{p.result.home_name} — {p.result.away_name}*\n"
            f"   {market_label} | коэф {p.bet.actual_odds:.2f} | +{p.bet.value_percent:.2f}%"
        )
    await message.answer(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
        disable_web_page_preview=True,
    )
