"""Топ матчей дня по значимости — с пагинацией."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.pagination import (
    Page,
    format_paginated,
    pagination_keyboard,
    parse_pagination_callback,
)
from bot.styles import ICON_STAR, header
from config import Settings
from services.countries import country_flag
from services.top_matches import RankedMatch, TopMatchesService

router = Router(name="topmatches")
PAGE_SIZE = 8
TOP_LIMIT = 50  # сколько вообще попадает в выборку дня


def _render_match(idx: int, m: RankedMatch) -> str:
    flag = country_flag(m.country)
    return (
        f"{idx:>2}. {flag} *{m.home_name}* — *{m.away_name}*\n"
        f"     {m.league_name or '—'} · score *{m.score:.2f}*"
    )


def _build_keyboard(page: Page) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for m in page.slice():
        if not isinstance(m, RankedMatch):
            continue
        builder.button(
            text=f"{m.home_name} — {m.away_name}"[:64],
            callback_data=f"predict:{m.game_id}",
        )
    builder.adjust(1)
    pag = pagination_keyboard("topmatches_page", page).inline_keyboard
    for row in pag:
        builder.row(*row)
    return builder


async def _render_top(
    target,  # Message | CallbackQuery
    *,
    page_index: int,
) -> None:
    bot = target.message.bot if isinstance(target, CallbackQuery) else target.bot
    settings: Settings = bot["settings"]  # type: ignore[index]
    sstats = bot["sstats"]  # type: ignore[index]
    today = (
        datetime.now(tz=UTC) + timedelta(hours=settings.timezone_offset)
    ).strftime("%Y-%m-%d")
    service = TopMatchesService(sstats)
    top = await service.top_for_day(
        today, time_zone=settings.timezone_offset, limit=TOP_LIMIT
    )
    title = header(f"Топ матчей дня ({today})", icon=ICON_STAR)
    if not top:
        msg = f"{title}\nНа сегодня значимых матчей не найдено."
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
    page: Page[RankedMatch] = Page(items=top, page_index=page_index, page_size=PAGE_SIZE)
    text = format_paginated(
        page,
        render_item=_render_match,
        header_text=title,
        footer_text="Нажми кнопку с матчем — будет полный прогноз.",
    )
    builder = _build_keyboard(page)
    if isinstance(target, CallbackQuery):
        if target.message:
            try:
                await target.message.edit_text(
                    text, parse_mode="Markdown", reply_markup=builder.as_markup()
                )
            except Exception:
                await target.message.answer(
                    text, parse_mode="Markdown", reply_markup=builder.as_markup()
                )
        await target.answer()
    else:
        await target.answer(
            text, parse_mode="Markdown", reply_markup=builder.as_markup()
        )


@router.message(Command("top", "topmatches"))
async def top_command(message: Message) -> None:
    await _render_top(message, page_index=0)


@router.callback_query(F.data.startswith("topmatches_page:"))
async def cb_topmatches_page(callback: CallbackQuery) -> None:
    if not callback.data:
        await callback.answer()
        return
    idx, _ = parse_pagination_callback(callback.data, "topmatches_page")
    await _render_top(callback, page_index=idx)
