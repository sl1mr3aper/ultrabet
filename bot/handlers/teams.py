"""Профиль команды."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.context import services
from bot.formatters import format_match_list
from bot.keyboards import main_menu_keyboard
from config import Settings
from services.countries import format_country
from services.team_service import TeamService

router = Router(name="teams")


@router.message(Command("team"))
async def team_command(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /team Название_команды")
        return
    sstats = services.sstats
    settings: Settings = services.settings
    service = TeamService(sstats)
    found = await service.search(parts[1])
    if not found:
        await message.answer("Команда не найдена.")
        return
    profile = await service.profile(int(found[0].get("id") or 0))
    if not profile:
        await message.answer("Профиль команды недоступен.")
        return
    lines = [
        f"⚽ *{profile.name}*",
        f"Страна: {format_country(profile.country)}",
        f"Лига: {profile.league or '—'}",
    ]
    if profile.glicko_rating:
        lines.append(f"Glicko-2: *{profile.glicko_rating:.0f}*")
    lines.append("")
    lines.append("Последние матчи:")
    if profile.last_games:
        lines.append(format_match_list(
            profile.last_games[:5], header="", tz_offset=settings.timezone_offset
        ))
    else:
        lines.append("— нет данных")
    lines.append("")
    lines.append("Ближайшие матчи:")
    if profile.upcoming:
        lines.append(format_match_list(
            profile.upcoming[:5], header="", tz_offset=settings.timezone_offset
        ))
    else:
        lines.append("— нет данных")
    await message.answer(
        "\n".join(lines), parse_mode="Markdown", reply_markup=main_menu_keyboard()
    )
