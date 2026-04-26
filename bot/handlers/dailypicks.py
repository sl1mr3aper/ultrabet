"""Daily picks — топ валуйных ставок дня (с пагинацией)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from api.sstats_client import SStatsClient
from bot.context import services
from bot.pagination import (
    Page,
    format_paginated,
    pagination_keyboard,
    parse_pagination_callback,
)
from bot.styles import ICON_TROPHY, header
from config import Settings
from core.markets import label_for
from core.value_calculator import ValueCalculator
from services.daily_picks import DailyPick, DailyPicksGenerator

router = Router(name="dailypicks")
PAGE_SIZE = 5
TOP_LIMIT = 30


def _emoji_for(value_pct: float) -> str:
    if value_pct >= 15:
        return "💎"
    if value_pct >= 8:
        return "🟢"
    return "✅"


def _render_pick(idx: int, p: DailyPick) -> str:
    market_label = label_for(
        p.bet.market_key, home=p.result.home_name, away=p.result.away_name
    )
    best = p.result.best_odds.get(p.bet.market_key) if p.result.best_odds else None
    book = f" _{best[1]}_" if best else ""
    return (
        f"{idx:>2}. {_emoji_for(p.bet.value_percent)} "
        f"*{p.result.home_name} — {p.result.away_name}*\n"
        f"     {market_label}\n"
        f"     модель {p.bet.probability * 100:.1f}% · "
        f"fair {p.bet.fair_odds:.2f} · "
        f"букмекер{book} {p.bet.actual_odds:.2f} · "
        f"*+{p.bet.value_percent:.2f}%*"
    )


def _build_keyboard(page: Page) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for p in page.slice():
        if not isinstance(p, DailyPick):
            continue
        gid = p.result.game_id
        if gid is None:
            continue
        builder.button(
            text=f"{p.result.home_name} — {p.result.away_name}"[:64],
            callback_data=f"predict:{gid}",
        )
    builder.adjust(1)
    pag = pagination_keyboard("dailypicks_page", page).inline_keyboard
    for row in pag:
        builder.row(*row)
    return builder


async def _render(
    target,
    *,
    page_index: int,
) -> None:
    bot = target.message.bot if isinstance(target, CallbackQuery) else target.bot
    settings: Settings = services.settings
    sstats: SStatsClient = services.sstats
    today = (
        datetime.now(tz=UTC) + timedelta(hours=settings.timezone_offset)
    ).strftime("%Y-%m-%d")
    if isinstance(target, Message) and page_index == 0:
        await target.answer(
            f"⏳ Сканирую матчи на {today}, это займёт около минуты…"
        )
    generator = DailyPicksGenerator(
        sstats,
        value_calculator=ValueCalculator(
            min_odds=settings.min_value_odds,
            min_value_percent=settings.min_value_percent,
        ),
    )
    picks = await generator.for_date(
        today, top_n=TOP_LIMIT, time_zone=settings.timezone_offset
    )
    title = header(f"Топ валуйных ставок на {today}", icon=ICON_TROPHY)
    if not picks:
        msg = f"{title}\nСегодня валуйных вариантов не нашлось."
        if isinstance(target, CallbackQuery):
            if target.message:
                try:
                    await target.message.edit_text(msg, parse_mode="Markdown")
                except Exception:
                    await target.message.answer(msg, parse_mode="Markdown")
            await target.answer()
        else:
            await target.answer(msg, parse_mode="Markdown")
        return
    sorted_picks = sorted(picks, key=lambda p: p.bet.value_percent, reverse=True)
    page: Page[DailyPick] = Page(
        items=sorted_picks, page_index=page_index, page_size=PAGE_SIZE
    )
    text = format_paginated(
        page,
        render_item=_render_pick,
        header_text=title,
        footer_text="Формат: модель / fair-коэф / коэф букмекера = валуйность",
    )
    builder = _build_keyboard(page)
    if isinstance(target, CallbackQuery):
        if target.message:
            try:
                await target.message.edit_text(
                    text,
                    parse_mode="Markdown",
                    reply_markup=builder.as_markup(),
                    disable_web_page_preview=True,
                )
            except Exception:
                await target.message.answer(
                    text,
                    parse_mode="Markdown",
                    reply_markup=builder.as_markup(),
                    disable_web_page_preview=True,
                )
        await target.answer()
    else:
        await target.answer(
            text,
            parse_mode="Markdown",
            reply_markup=builder.as_markup(),
            disable_web_page_preview=True,
        )


@router.message(Command("dailypicks"))
async def dailypicks_cmd(message: Message) -> None:
    await _render(message, page_index=0)


@router.callback_query(F.data.startswith("dailypicks_page:"))
async def cb_dailypicks_page(callback: CallbackQuery) -> None:
    if not callback.data:
        await callback.answer()
        return
    idx, _ = parse_pagination_callback(callback.data, "dailypicks_page")
    await _render(callback, page_index=idx)
