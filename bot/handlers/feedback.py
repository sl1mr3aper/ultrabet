"""Отзывы пользователей."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards import cancel_keyboard, main_menu_keyboard
from bot.states import FeedbackStates
from bot.texts import FEEDBACK_PROMPT, FEEDBACK_SAVED
from config import Settings
from db.models import User
from db.repositories.feedback_repo import FeedbackRepository

router = Router(name="feedback")


@router.message(Command("feedback"))
async def feedback_cmd(message: Message, state: FSMContext) -> None:
    await state.set_state(FeedbackStates.waiting_for_text)
    await message.answer(FEEDBACK_PROMPT, reply_markup=cancel_keyboard())


@router.callback_query(F.data == "menu:feedback")
async def feedback_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(FeedbackStates.waiting_for_text)
    if callback.message:
        await callback.message.edit_text(FEEDBACK_PROMPT, reply_markup=cancel_keyboard())
    await callback.answer()


@router.message(FeedbackStates.waiting_for_text)
async def receive_feedback(
    message: Message,
    state: FSMContext,
    user: User,
    session: AsyncSession,
    settings: Settings,
) -> None:
    text = (message.text or "").strip()
    if not text:
        return
    repo = FeedbackRepository(session)
    await repo.add(user_id=user.id if user else None, text=text)
    await state.clear()
    await message.answer(FEEDBACK_SAVED, reply_markup=main_menu_keyboard())
    for admin_id in settings.admin_ids:
        try:
            await message.bot.send_message(
                admin_id,
                f"📨 Отзыв от {user.display_name() if user else 'unknown'}:\n{text[:1000]}",
            )
        except Exception:
            pass
