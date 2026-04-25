"""Просмотр лиг и таблиц."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from api.sstats_client import SStatsClient
from bot.formatters import format_league_table, format_match_list
from bot.keyboards import league_view_keyboard, main_menu_keyboard
from bot.pagination import (
    Page,
    format_paginated,
    pagination_keyboard,
    parse_pagination_callback,
)
from bot.styles import (
    ICON_TROPHY,
    bullet,
    header,
)
from bot.texts import NO_MATCHES
from config import Settings
from services.countries import country_flag, format_country

router = Router(name="leagues")
LEAGUES_PAGE_SIZE = 8


def _leagues_keyboard_paginated(page: Page) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for league in page.slice():
        if not isinstance(league, dict):
            continue
        league_id = league.get("id")
        name = league.get("name") or "?"
        country = (league.get("country") or {}) if isinstance(league.get("country"), dict) else {}
        flag = country_flag(country.get("name") if isinstance(country, dict) else None)
        builder.button(
            text=f"{flag} {name}"[:60],
            callback_data=f"league:{league_id}",
        )
    builder.adjust(1)
    return builder


async def _render_leagues_page(message_or_cb, page_index: int) -> None:
    bot = (message_or_cb.message.bot if hasattr(message_or_cb, "message") else message_or_cb.bot)
    sstats: SStatsClient = bot["sstats"]  # type: ignore[index]
    leagues_raw = await sstats.list_leagues()
    leagues = [l for l in (leagues_raw or []) if isinstance(l, dict) and l.get("id")]
    page: Page = Page(items=leagues, page_index=page_index, page_size=LEAGUES_PAGE_SIZE)
    text = format_paginated(
        page,
        render_item=lambda i, l: bullet(
            f"{country_flag((l.get('country') or {}).get('name'))} {l.get('name') or '?'}"
        ),
        header_text=header("Лиги SStats", icon=ICON_TROPHY),
        footer_text="Нажми кнопку с лигой ниже, чтобы открыть.",
    )
    builder = _leagues_keyboard_paginated(page)
    pag_kb = pagination_keyboard("leagues_page", page).inline_keyboard
    for row in pag_kb:
        builder.row(*row)
    target = message_or_cb.message if hasattr(message_or_cb, "message") else message_or_cb
    if hasattr(target, "edit_text"):
        try:
            await target.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
        except Exception:
            await target.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    else:
        await target.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    if hasattr(message_or_cb, "answer") and not isinstance(message_or_cb, Message):
        await message_or_cb.answer()


@router.callback_query(F.data == "menu:leagues")
async def menu_leagues(callback: CallbackQuery) -> None:
    if callback.message:
        await _render_leagues_page(callback, page_index=0)
    else:
        await callback.answer()


@router.callback_query(F.data.startswith("leagues_page:"))
async def leagues_page_cb(callback: CallbackQuery) -> None:
    if not callback.data or not callback.message:
        await callback.answer()
        return
    idx, _ = parse_pagination_callback(callback.data, "leagues_page")
    await _render_leagues_page(callback, page_index=idx)
    await callback.answer()


@router.callback_query(F.data.startswith("league:matches:"))
async def league_matches(callback: CallbackQuery) -> None:
    if not callback.data or not callback.message:
        await callback.answer()
        return
    league_id = int(callback.data.rsplit(":", 1)[1])
    settings: Settings = callback.message.bot["settings"]  # type: ignore[index]
    sstats: SStatsClient = callback.message.bot["sstats"]  # type: ignore[index]
    games = await sstats.list_games(
        league_id=league_id, upcoming=True, limit=20, time_zone=settings.timezone_offset
    )
    header = "📅 *Ближайшие матчи лиги*"
    text = format_match_list(games, header=header, tz_offset=settings.timezone_offset)
    if not games:
        text = header + "\n" + NO_MATCHES
    await callback.message.edit_text(
        text, parse_mode="Markdown", reply_markup=league_view_keyboard(league_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("league:table:"))
async def league_table(callback: CallbackQuery) -> None:
    if not callback.data or not callback.message:
        await callback.answer()
        return
    league_id = int(callback.data.rsplit(":", 1)[1])
    sstats: SStatsClient = callback.message.bot["sstats"]  # type: ignore[index]
    seasons = await sstats.ls_seasons(leagueId=league_id, limit=1)
    season_uid = seasons[0].get("uid") if seasons else None
    text = "Таблица недоступна." if not season_uid else format_league_table(
        await sstats.get_standings(str(season_uid))
    )
    await callback.message.edit_text(
        text, parse_mode="Markdown", reply_markup=league_view_keyboard(league_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("league:"))
async def league_root(callback: CallbackQuery) -> None:
    if not callback.data or not callback.message:
        await callback.answer()
        return
    parts = callback.data.split(":")
    if parts[1] in {"matches", "table"}:
        return
    try:
        league_id = int(parts[1])
    except ValueError:
        await callback.answer()
        return
    sstats: SStatsClient = callback.message.bot["sstats"]  # type: ignore[index]
    leagues = await sstats.list_leagues()
    league = next((l for l in leagues if l.get("id") == league_id), None)
    if not league:
        await callback.message.edit_text("Лига не найдена.", reply_markup=main_menu_keyboard())
        await callback.answer()
        return
    name = league.get("name") or "?"
    country = (league.get("country") or {}).get("name") if isinstance(league.get("country"), dict) else None
    text = f"🏆 *{name}* — {format_country(country)}"
    await callback.message.edit_text(
        text, parse_mode="Markdown", reply_markup=league_view_keyboard(league_id)
    )
    await callback.answer()


@router.message(Command("standings"))
async def standings_command(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /standings Название_лиги")
        return
    sstats: SStatsClient = message.bot["sstats"]  # type: ignore[index]
    needle = parts[1].lower().strip()
    leagues = await sstats.list_leagues()
    matched = [l for l in leagues if needle in (l.get("name") or "").lower()]
    if not matched:
        await message.answer("Лига не найдена. Попробуй точнее.")
        return
    league = matched[0]
    seasons = await sstats.ls_seasons(leagueId=league.get("id"), limit=1)
    season_uid = seasons[0].get("uid") if seasons else None
    if not season_uid:
        await message.answer("Активный сезон не найден.")
        return
    table = await sstats.get_standings(str(season_uid))
    await message.answer(format_league_table(table), parse_mode="Markdown")


@router.message(Command("league"))
async def league_command(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /league Название")
        return
    sstats: SStatsClient = message.bot["sstats"]  # type: ignore[index]
    settings: Settings = message.bot["settings"]  # type: ignore[index]
    needle = parts[1].lower().strip()
    leagues = await sstats.list_leagues()
    matched = [l for l in leagues if needle in (l.get("name") or "").lower()]
    if not matched:
        await message.answer("Лига не найдена.")
        return
    league = matched[0]
    games = await sstats.list_games(
        league_id=league.get("id"), upcoming=True, limit=15,
        time_zone=settings.timezone_offset,
    )
    header = f"🏆 *{league.get('name')}* — ближайшие матчи"
    text = format_match_list(games, header=header, tz_offset=settings.timezone_offset)
    await message.answer(text, parse_mode="Markdown")
