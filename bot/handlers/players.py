"""Профили игроков."""

from __future__ import annotations

from aiogram import Router
from aiogram.types import Message

from bot.context import services
from bot.keyboards import main_menu_keyboard
from services.countries import format_country
from services.player_service import PlayerService

router = Router(name="players")
# [removed: command handler — UI is buttons-only]
async def player_command(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /player Имя_игрока")
        return
    sstats = services.sstats
    service = PlayerService(sstats)
    found = await service.find(parts[1])
    if not found:
        await message.answer("Игрок не найден.")
        return
    profile = await service.profile(int(found[0].get("id") or 0))
    if not profile:
        await message.answer("Профиль игрока недоступен.")
        return
    lines = [
        f"🧑‍💼 *{profile.name}*",
        f"Позиция: {profile.position or '—'}",
        f"Гражданство: {format_country(profile.nationality)}",
        f"Возраст: {profile.age or '—'}",
        f"Команда: {profile.team_name or '—'}",
    ]
    if profile.events:
        lines.append("")
        lines.append("*Последние события:*")
        for ev in profile.events[:8]:
            ev_type = ev.get("type") or ev.get("name") or "?"
            game = ev.get("game") or {}
            home = (game.get("homeTeam") or {}).get("name") if isinstance(game, dict) else None
            away = (game.get("awayTeam") or {}).get("name") if isinstance(game, dict) else None
            lines.append(f"• {ev_type} • {home or '?'} — {away or '?'}")
    await message.answer(
        "\n".join(lines), parse_mode="Markdown", reply_markup=main_menu_keyboard()
    )
