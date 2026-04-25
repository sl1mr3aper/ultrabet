"""Просмотр лиг и таблиц."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from api.sstats_client import SStatsClient
from bot.formatters import format_league_table, format_match_list
from bot.keyboards import league_view_keyboard, leagues_keyboard, main_menu_keyboard
from bot.texts import NO_MATCHES
from config import Settings
from services.countries import format_country

router = Router(name="leagues")


@router.callback_query(F.data == "menu:leagues")
async def menu_leagues(callback: CallbackQuery) -> None:
    if callback.message:
        sstats: SStatsClient = callback.message.bot["sstats"]  # type: ignore[index]
        leagues_raw = await sstats.list_leagues()
        leagues = leagues_raw[:30]
        text = "🏆 *Лиги SStats*\nВыбери, чтобы увидеть матчи и таблицу:"
        await callback.message.edit_text(
            text,
            reply_markup=leagues_keyboard(leagues),
            parse_mode="Markdown",
        )
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
