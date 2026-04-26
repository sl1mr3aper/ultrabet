"""Очные встречи (H2H) с пагинацией по предыдущим матчам."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from api.sstats_client import SStatsClient
from bot.pagination import (
    Page,
    format_paginated,
    pagination_keyboard,
    parse_pagination_callback,
)
from bot.styles import ICON_SWORDS, header
from services.h2h_service import H2HMatch, H2HService, H2HSummary
from services.match_finder import MatchFinder

router = Router(name="h2h")
PAGE_SIZE = 5

# Примитивный in-memory кэш последних H2H summary per user — чтобы при пагинации
# не делать повторных тяжёлых запросов. Ключ: user_id → (home, away, summary).
_H2H_CACHE: dict[int, tuple[str, str, H2HSummary]] = {}


def _render_match(idx: int, m: H2HMatch) -> str:
    score = (
        "—:—"
        if m.home_score is None or m.away_score is None
        else f"{m.home_score}:{m.away_score}"
    )
    date = (m.date_iso or "")[:10]
    return f"{idx:>2}. {date} • {m.home_name} *{score}* {m.away_name}"


def _summary_header(name_a: str, name_b: str, summary: H2HSummary) -> str:
    lines = [
        header(f"H2H: {name_a} — {name_b}", icon=ICON_SWORDS),
        f"Сыграно: *{summary.total_played}*",
        f"• {name_a} побед: *{summary.home_wins}* ({summary.home_win_pct:.0f}%)",
        f"• Ничьих: *{summary.draws}* ({summary.draw_pct:.0f}%)",
        f"• {name_b} побед: *{summary.away_wins}* ({summary.away_win_pct:.0f}%)",
        f"• Средний тотал: *{summary.avg_total_goals:.2f}*",
        f"• Обе забивали: *{summary.btts_count}/{summary.total_played}* "
        f"({summary.btts_pct:.0f}%)",
    ]
    return "\n".join(lines)


async def _send_page(
    target,  # Message | CallbackQuery
    *,
    name_a: str,
    name_b: str,
    summary: H2HSummary,
    page_index: int,
) -> None:
    page: Page[H2HMatch] = Page(
        items=summary.matches, page_index=page_index, page_size=PAGE_SIZE
    )
    text = format_paginated(
        page,
        render_item=_render_match,
        header_text=_summary_header(name_a, name_b, summary),
        footer_text="Прошлые личные встречи (свежие сверху)",
    )
    builder = InlineKeyboardBuilder()
    pag = pagination_keyboard("h2h_page", page).inline_keyboard
    for row in pag:
        builder.row(*row)
    kb = builder.as_markup()
    if isinstance(target, CallbackQuery):
        if target.message:
            try:
                await target.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
            except Exception:
                await target.message.answer(text, parse_mode="Markdown", reply_markup=kb)
        await target.answer()
    else:
        await target.answer(text, parse_mode="Markdown", reply_markup=kb)


@router.message(Command("h2h"))
async def h2h_command(message: Message) -> None:
    text = (message.text or "").split(maxsplit=1)
    if len(text) < 2:
        await message.answer(
            "Использование: `/h2h Команда1 - Команда2`", parse_mode="Markdown"
        )
        return
    parts = text[1].split(" - ", 1)
    if len(parts) != 2:
        await message.answer(
            "Формат: `/h2h Команда1 - Команда2`", parse_mode="Markdown"
        )
        return
    a, b = parts[0].strip(), parts[1].strip()
    sstats: SStatsClient = message.bot["sstats"]  # type: ignore[index]
    finder = MatchFinder(sstats)
    teams_a = await finder.search_teams(a, limit=1)
    teams_b = await finder.search_teams(b, limit=1)
    if not teams_a or not teams_b:
        await message.answer("Команда не найдена.")
        return
    home_id = int(teams_a[0].get("id") or 0)
    away_id = int(teams_b[0].get("id") or 0)
    svc = H2HService(sstats)
    summary = await svc.fetch(home_id, away_id)
    name_a = str(teams_a[0].get("name") or "?")
    name_b = str(teams_b[0].get("name") or "?")
    if summary.total_played == 0:
        await message.answer(
            f"🤷 Очных встреч между *{name_a}* и *{name_b}* в базе нет.",
            parse_mode="Markdown",
        )
        return
    if message.from_user:
        _H2H_CACHE[message.from_user.id] = (name_a, name_b, summary)
    await _send_page(
        message, name_a=name_a, name_b=name_b, summary=summary, page_index=0
    )


@router.callback_query(F.data.startswith("h2h_page:"))
async def cb_h2h_page(callback: CallbackQuery) -> None:
    if not callback.data or not callback.from_user:
        await callback.answer()
        return
    entry = _H2H_CACHE.get(callback.from_user.id)
    if not entry:
        await callback.answer("Сессия истекла, отправь /h2h заново", show_alert=True)
        return
    idx, _ = parse_pagination_callback(callback.data, "h2h_page")
    name_a, name_b, summary = entry
    await _send_page(
        callback, name_a=name_a, name_b=name_b, summary=summary, page_index=idx
    )
