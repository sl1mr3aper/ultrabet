"""Подборки матчей: сегодня / завтра / live с пагинацией."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

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
from bot.styles import ICON_BALL, ICON_CALENDAR, ICON_FIRE, header
from bot.texts import LIVE_HEADER, NO_MATCHES, TODAY_HEADER, TOMORROW_HEADER
from config import Settings
from services.countries import country_flag

router = Router(name="matches")
PAGE_SIZE = 10


def _today_str(tz_offset: int) -> str:
    return (datetime.now(tz=UTC) + timedelta(hours=tz_offset)).strftime("%Y-%m-%d")


def _tomorrow_str(tz_offset: int) -> str:
    return (datetime.now(tz=UTC) + timedelta(hours=tz_offset + 24)).strftime("%Y-%m-%d")


def _render_match(idx: int, m: dict[str, Any]) -> str:
    home = (m.get("homeTeam") or {}).get("name") or "?"
    away = (m.get("awayTeam") or {}).get("name") or "?"
    season = m.get("season") or {}
    league_name = "?"
    country_name: str | None = None
    if isinstance(season, dict):
        league_obj = season.get("league") or {}
        if isinstance(league_obj, dict):
            league_name = league_obj.get("name") or "?"
            c = league_obj.get("country")
            if isinstance(c, dict):
                country_name = c.get("name")
    flag = country_flag(country_name)
    iso = m.get("date") or ""
    short = ""
    if iso:
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            short = dt.strftime("%d.%m %H:%M")
        except ValueError:
            short = iso[:16]
    return f"{idx:>2}. {flag} *{home}* — *{away}*\n     {league_name} · {short}"


def _matches_keyboard(page: Page, prefix: str, extra: str) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for m in page.slice():
        if not isinstance(m, dict):
            continue
        gid = m.get("id") or m.get("gameId")
        if gid is None:
            continue
        home = (m.get("homeTeam") or {}).get("name") or "?"
        away = (m.get("awayTeam") or {}).get("name") or "?"
        builder.button(
            text=f"{home} — {away}"[:64],
            callback_data=f"predict:{gid}",
        )
    builder.adjust(1)
    pag = pagination_keyboard(prefix, page, extra_payload=extra).inline_keyboard
    for row in pag:
        builder.row(*row)
    return builder


async def _fetch_matches(
    bot, *, kind: str, settings: Settings
) -> tuple[list[dict[str, Any]], str]:
    sstats: SStatsClient = services.sstats
    if kind == "today":
        return (
            await sstats.list_games(
                date=_today_str(settings.timezone_offset),
                limit=80,
                time_zone=settings.timezone_offset,
            ),
            TODAY_HEADER.format(date=_today_str(settings.timezone_offset)),
        )
    if kind == "tomorrow":
        return (
            await sstats.list_games(
                date=_tomorrow_str(settings.timezone_offset),
                limit=80,
                time_zone=settings.timezone_offset,
            ),
            TOMORROW_HEADER.format(date=_tomorrow_str(settings.timezone_offset)),
        )
    return (
        await sstats.list_games(
            live=True, limit=80, time_zone=settings.timezone_offset
        ),
        LIVE_HEADER,
    )


async def _render_matches_page(
    target,  # Message | CallbackQuery
    *,
    kind: str,
    page_index: int,
) -> None:
    bot = target.message.bot if isinstance(target, CallbackQuery) else target.bot
    settings: Settings = services.settings
    games, hdr = await _fetch_matches(bot, kind=kind, settings=settings)
    games = [g for g in (games or []) if isinstance(g, dict)]
    icon = ICON_FIRE if kind == "live" else ICON_CALENDAR if kind == "today" else ICON_BALL
    if not games:
        msg = f"{header(hdr.replace('*',''), icon=icon)}\n{NO_MATCHES}"
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
    page: Page = Page(items=games, page_index=page_index, page_size=PAGE_SIZE)
    text = format_paginated(
        page,
        render_item=_render_match,
        header_text=header(hdr.replace("*", ""), icon=icon),
    )
    builder = _matches_keyboard(page, prefix=f"matches_page_{kind}", extra="")
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


@router.message(Command("matches", "today"))
async def matches_today(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    arg = parts[1].strip().lower() if len(parts) > 1 else ""
    if arg in {"tomorrow", "завтра"}:
        await _render_matches_page(message, kind="tomorrow", page_index=0)
    elif arg in {"live", "лайв", "сейчас"}:
        await _render_matches_page(message, kind="live", page_index=0)
    else:
        await _render_matches_page(message, kind="today", page_index=0)


@router.message(Command("tomorrow"))
async def matches_tomorrow(message: Message) -> None:
    await _render_matches_page(message, kind="tomorrow", page_index=0)


@router.message(Command("live"))
async def matches_live(message: Message) -> None:
    await _render_matches_page(message, kind="live", page_index=0)


@router.callback_query(F.data == "menu:today")
async def cb_today(callback: CallbackQuery) -> None:
    await _render_matches_page(callback, kind="today", page_index=0)


@router.callback_query(F.data == "menu:tomorrow")
async def cb_tomorrow(callback: CallbackQuery) -> None:
    await _render_matches_page(callback, kind="tomorrow", page_index=0)


@router.callback_query(F.data == "menu:live")
async def cb_live(callback: CallbackQuery) -> None:
    await _render_matches_page(callback, kind="live", page_index=0)


@router.callback_query(F.data.startswith("matches_page_today:"))
async def cb_page_today(callback: CallbackQuery) -> None:
    if not callback.data:
        await callback.answer()
        return
    idx, _ = parse_pagination_callback(callback.data, "matches_page_today")
    await _render_matches_page(callback, kind="today", page_index=idx)


@router.callback_query(F.data.startswith("matches_page_tomorrow:"))
async def cb_page_tomorrow(callback: CallbackQuery) -> None:
    if not callback.data:
        await callback.answer()
        return
    idx, _ = parse_pagination_callback(callback.data, "matches_page_tomorrow")
    await _render_matches_page(callback, kind="tomorrow", page_index=idx)


@router.callback_query(F.data.startswith("matches_page_live:"))
async def cb_page_live(callback: CallbackQuery) -> None:
    if not callback.data:
        await callback.answer()
        return
    idx, _ = parse_pagination_callback(callback.data, "matches_page_live")
    await _render_matches_page(callback, kind="live", page_index=idx)
