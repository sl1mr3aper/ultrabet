"""Подборки матчей: сегодня / завтра / live."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from api.sstats_client import SStatsClient
from bot.formatters import format_match_list
from bot.keyboards import matches_keyboard
from bot.texts import LIVE_HEADER, NO_MATCHES, TODAY_HEADER, TOMORROW_HEADER
from config import Settings

router = Router(name="matches")


def _today_str(tz_offset: int) -> str:
    return (datetime.now(tz=UTC) + timedelta(hours=tz_offset)).strftime("%Y-%m-%d")


def _tomorrow_str(tz_offset: int) -> str:
    return (datetime.now(tz=UTC) + timedelta(hours=tz_offset + 24)).strftime("%Y-%m-%d")


@router.message(Command("matches"))
async def matches_command(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    arg = parts[1].strip().lower() if len(parts) > 1 else "today"
    if arg in {"today", "сегодня"}:
        await _send_today(message)
    elif arg in {"tomorrow", "завтра"}:
        await _send_tomorrow(message)
    elif arg in {"live", "лайв", "сейчас"}:
        await _send_live(message)
    else:
        await message.answer("Используй /matches today | tomorrow | live")


@router.callback_query(F.data == "menu:today")
async def today_cb(callback: CallbackQuery) -> None:
    if callback.message:
        await _send_today(callback.message)
    await callback.answer()


@router.callback_query(F.data == "menu:tomorrow")
async def tomorrow_cb(callback: CallbackQuery) -> None:
    if callback.message:
        await _send_tomorrow(callback.message)
    await callback.answer()


@router.callback_query(F.data == "menu:live")
async def live_cb(callback: CallbackQuery) -> None:
    if callback.message:
        await _send_live(callback.message)
    await callback.answer()


async def _send_today(message: Message) -> None:
    settings: Settings = message.bot["settings"]  # type: ignore[index]
    sstats: SStatsClient = message.bot["sstats"]  # type: ignore[index]
    games = await sstats.list_games(
        date=_today_str(settings.timezone_offset),
        limit=50,
        time_zone=settings.timezone_offset,
    )
    header = TODAY_HEADER.format(date=_today_str(settings.timezone_offset))
    text = format_match_list(games, header=header, tz_offset=settings.timezone_offset)
    if not games:
        text = header + "\n" + NO_MATCHES
    await message.answer(text, parse_mode="Markdown",
                          reply_markup=matches_keyboard(games[:15]))


async def _send_tomorrow(message: Message) -> None:
    settings: Settings = message.bot["settings"]  # type: ignore[index]
    sstats: SStatsClient = message.bot["sstats"]  # type: ignore[index]
    games = await sstats.list_games(
        date=_tomorrow_str(settings.timezone_offset),
        limit=50,
        time_zone=settings.timezone_offset,
    )
    header = TOMORROW_HEADER.format(date=_tomorrow_str(settings.timezone_offset))
    text = format_match_list(games, header=header, tz_offset=settings.timezone_offset)
    if not games:
        text = header + "\n" + NO_MATCHES
    await message.answer(text, parse_mode="Markdown",
                          reply_markup=matches_keyboard(games[:15]))


async def _send_live(message: Message) -> None:
    settings: Settings = message.bot["settings"]  # type: ignore[index]
    sstats: SStatsClient = message.bot["sstats"]  # type: ignore[index]
    games = await sstats.list_games(
        live=True, limit=50, time_zone=settings.timezone_offset
    )
    text = format_match_list(games, header=LIVE_HEADER, tz_offset=settings.timezone_offset)
    if not games:
        text = LIVE_HEADER + "\n" + NO_MATCHES
    await message.answer(text, parse_mode="Markdown",
                          reply_markup=matches_keyboard(games[:15]))
