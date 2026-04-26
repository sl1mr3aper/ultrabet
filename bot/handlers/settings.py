"""Команда /settings — заглушка."""

from __future__ import annotations

from aiogram import Router
from aiogram.types import Message

from bot.keyboards import main_menu_keyboard

router = Router(name="settings")
# [removed: command handler — UI is buttons-only]
async def settings_cmd(message: Message) -> None:
    await message.answer(
        "⚙️ Настройки в разработке. Скоро появятся таймзоны и язык.",
        reply_markup=main_menu_keyboard(),
    )
