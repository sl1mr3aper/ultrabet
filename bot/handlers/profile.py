"""Профиль пользователя."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards import main_menu_keyboard
from db.models import User
from services.profile_service import ProfileService

router = Router(name="profile")


@router.message(Command("profile", "history", "me"))
async def profile_command(
    message: Message, user: User, session: AsyncSession
) -> None:
    service = ProfileService(session)
    prof = await service.get(user)
    last_pred = (
        prof.last_prediction_at.strftime("%d.%m.%Y %H:%M")
        if prof.last_prediction_at
        else "—"
    )
    lines = [
        "👤 *Профиль*",
        f"ID: `{user.tg_id}`",
        f"Имя: {user.display_name()}",
        f"Прогнозов сделано: *{prof.total_predictions}*",
        f"Последний прогноз: {last_pred}",
        f"Запросов всего: *{prof.total_queries}*",
        f"Удачных запросов: *{prof.successful_queries}*",
        "",
        f"Подписка: *{user.subscription_plan or 'нет'}*",
        f"Бесплатных: *{user.free_predictions_left or 0}*",
        f"Бонусных: *{user.bonus_predictions or 0}*",
    ]
    await message.answer(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )
