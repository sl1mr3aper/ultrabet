"""Дополнительные информационные команды.

- /summary <game_id> — текстовое summary матча из SStats.
- /injuries <game_id> — список травмированных игроков.
- /odds <game_id> — полный набор прематч-коэффициентов (1×2 + тоталы).
- /bookmakers — список букмекеров SStats.
- /standings_for <league_id> — таблица лиги по id.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from api.sstats_client import SStatsClient
from bot.keyboards import main_menu_keyboard
from services.countries import format_country
from services.league_service import LeagueService
from services.odds_parser import OddsParser

router = Router(name="extras")


def _parse_id(message: Message) -> int | None:
    parts = (message.text or "").split()
    if len(parts) < 2:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


@router.message(Command("summary"))
async def summary_cmd(message: Message) -> None:
    gid = _parse_id(message)
    if gid is None:
        await message.answer("Использование: /summary <game_id>")
        return
    sstats: SStatsClient = message.bot["sstats"]  # type: ignore[index]
    text = await sstats.get_text_summary(gid)
    if not text:
        await message.answer("Сводка не найдена.", reply_markup=main_menu_keyboard())
        return
    if len(text) > 4000:
        text = text[:3990] + "…"
    await message.answer(text, reply_markup=main_menu_keyboard())


@router.message(Command("injuries"))
async def injuries_cmd(message: Message) -> None:
    gid = _parse_id(message)
    if gid is None:
        await message.answer("Использование: /injuries <game_id>")
        return
    sstats: SStatsClient = message.bot["sstats"]  # type: ignore[index]
    rows = await sstats.get_injuries(gid)
    if not rows:
        await message.answer("Нет данных о травмах.", reply_markup=main_menu_keyboard())
        return
    lines = ["🚑 *Травмы и пропуски*", ""]
    for row in rows[:30]:
        if not isinstance(row, dict):
            continue
        player = row.get("player") or {}
        team = row.get("team") or {}
        reason = row.get("reason") or row.get("status") or "—"
        lines.append(
            f"• {player.get('name', '?')} ({team.get('name', '?')}) — {reason}"
        )
    await message.answer(
        "\n".join(lines), parse_mode="Markdown", reply_markup=main_menu_keyboard()
    )


@router.message(Command("odds"))
async def odds_cmd(message: Message) -> None:
    gid = _parse_id(message)
    if gid is None:
        await message.answer("Использование: /odds <game_id>")
        return
    sstats: SStatsClient = message.bot["sstats"]  # type: ignore[index]
    raw = await sstats.get_prematch_odds(gid)
    if not raw:
        await message.answer("Коэффициенты не найдены.", reply_markup=main_menu_keyboard())
        return
    parsed = OddsParser().parse(raw)
    if not parsed:
        await message.answer("Не удалось распарсить коэффициенты.")
        return
    lines = ["💰 *Прематч-коэффициенты*", ""]
    for market_key, val in sorted(parsed.items()):
        lines.append(f"• `{market_key}` → {val:.2f}")
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "…"
    await message.answer(
        text, parse_mode="Markdown", reply_markup=main_menu_keyboard()
    )


@router.message(Command("bookmakers"))
async def bookmakers_cmd(message: Message) -> None:
    sstats: SStatsClient = message.bot["sstats"]  # type: ignore[index]
    rows = await sstats.list_bookmakers()
    if not rows:
        await message.answer("Список букмекеров недоступен.")
        return
    lines = [f"🏛 *Букмекеры в базе SStats* (всего {len(rows)})", ""]
    for r in rows[:50]:
        if not isinstance(r, dict):
            continue
        name = r.get("name") or "?"
        bid = r.get("id")
        country = format_country(r.get("country", {}).get("name") if isinstance(r.get("country"), dict) else None)
        lines.append(f"• [{bid}] {country} {name}")
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "…"
    await message.answer(
        text, parse_mode="Markdown", reply_markup=main_menu_keyboard()
    )


@router.message(Command("standings_for"))
async def standings_for_cmd(message: Message) -> None:
    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer("Использование: /standings_for <league_id>")
        return
    try:
        league_id = int(parts[1])
    except ValueError:
        await message.answer("league_id должен быть числом.")
        return
    sstats: SStatsClient = message.bot["sstats"]  # type: ignore[index]
    svc = LeagueService(sstats)
    table = await svc.standings(league_id)
    if not table:
        await message.answer("Турнирная таблица недоступна.")
        return
    rows = table.get("standings") or table.get("rows") or []
    lines = ["📋 *Турнирная таблица*", ""]
    for i, row in enumerate(rows[:30], start=1):
        if not isinstance(row, dict):
            continue
        team = row.get("team") or {}
        name = team.get("name") if isinstance(team, dict) else "?"
        played = row.get("played") or row.get("matches") or 0
        points = row.get("points") or 0
        gd = row.get("goalsDiff") or row.get("gd") or 0
        lines.append(f"{i:>2}. {name} — {points} очк. ({played} м, разница {gd:+d})")
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "…"
    await message.answer(
        text, parse_mode="Markdown", reply_markup=main_menu_keyboard()
    )
