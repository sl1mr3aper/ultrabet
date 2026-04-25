"""Очные встречи (H2H)."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from api.sstats_client import SStatsClient
from bot.keyboards import main_menu_keyboard
from services.h2h_service import H2HService
from services.match_finder import MatchFinder

router = Router(name="h2h")


@router.message(Command("h2h"))
async def h2h_command(message: Message) -> None:
    text = (message.text or "").split(maxsplit=1)
    if len(text) < 2:
        await message.answer(
            "Использование: `/h2h Команда1 - Команда2`",
            parse_mode="Markdown",
        )
        return
    parts = text[1].split(" - ", 1)
    if len(parts) != 2:
        await message.answer("Формат: `/h2h Команда1 - Команда2`", parse_mode="Markdown")
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
    h2h = H2HService(sstats)
    summary = await h2h.fetch(home_id, away_id)
    name_a = teams_a[0].get("name") or "?"
    name_b = teams_b[0].get("name") or "?"
    if summary.total_played == 0:
        await message.answer(
            f"🤷 Очных встреч между *{name_a}* и *{name_b}* в базе нет.",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(),
        )
        return
    lines = [
        f"⚔️ *H2H: {name_a} — {name_b}*",
        f"Сыграно: *{summary.total_played}*",
        f"• {name_a} побед: *{summary.home_wins}* ({summary.home_win_pct:.0f}%)",
        f"• Ничьих: *{summary.draws}* ({summary.draw_pct:.0f}%)",
        f"• {name_b} побед: *{summary.away_wins}* ({summary.away_win_pct:.0f}%)",
        f"• Средний тотал: *{summary.avg_total_goals:.2f}*",
        f"• Обе забивали: *{summary.btts_count}/{summary.total_played}* ({summary.btts_pct:.0f}%)",
        "",
        "Последние матчи:",
    ]
    for m in summary.matches[:8]:
        score = "—:—" if m.home_score is None or m.away_score is None else f"{m.home_score}:{m.away_score}"
        date = (m.date_iso or "")[:10]
        lines.append(f"  {date} • {m.home_name} {score} {m.away_name}")
    await message.answer(
        "\n".join(lines), parse_mode="Markdown", reply_markup=main_menu_keyboard()
    )
