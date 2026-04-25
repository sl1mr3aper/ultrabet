"""Общие обработчики: /start, /help, /menu, отмена, неизвестная команда."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards import main_menu_keyboard
from bot.texts import (
    HELP_TEXT,
    MAIN_MENU,
    UNKNOWN_COMMAND,
    WELCOME,
    WELCOME_REFERRAL_BONUS,
)
from config import Settings
from db.models import User
from db.repositories.user_repo import UserRepository
from services.referral_service import ReferralService

router = Router(name="common")


@router.message(CommandStart(deep_link=True))
async def start_with_deep_link(
    message: Message,
    user: User,
    session: AsyncSession,
    settings: Settings,
) -> None:
    payload = message.text.split(" ", 1)[1] if message.text and " " in message.text else ""
    payload = payload.strip()
    bonus_text = ""
    if payload.startswith("ref_"):
        code = payload[len("ref_"):]
        ref_service = ReferralService(
            session,
            bonus_signup=settings.referral_bonus_signup,
            bonus_sub_1m=settings.referral_bonus_sub_1m,
            bonus_sub_3m=settings.referral_bonus_sub_3m,
            bonus_sub_12m=settings.referral_bonus_sub_12m,
        )
        referrer = await ref_service.find_referrer(code)
        if referrer is not None and referrer.id != user.id:
            attached = await ref_service.attach_referral(referrer=referrer, referred=user)
            if attached:
                bonus_text = WELCOME_REFERRAL_BONUS.format(
                    ref_name=referrer.display_name(),
                    bonus=settings.referral_bonus_signup,
                )
    await _send_welcome(message, user, bonus_text)


@router.message(CommandStart())
async def start_plain(message: Message, user: User) -> None:
    await _send_welcome(message, user, "")


async def _send_welcome(message: Message, user: User, bonus_text: str) -> None:
    name = user.display_name() if user else (message.from_user.first_name if message.from_user else "друг")
    text = WELCOME.format(name=name, app="UltraBet")
    if bonus_text:
        text = text + "\n\n" + bonus_text
    await message.answer(text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")


@router.message(Command("menu"))
async def menu_command(message: Message) -> None:
    await message.answer(MAIN_MENU, reply_markup=main_menu_keyboard(), parse_mode="Markdown")


@router.callback_query(F.data == "menu:home")
async def menu_home_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if callback.message:
        await callback.message.edit_text(
            MAIN_MENU, reply_markup=main_menu_keyboard(), parse_mode="Markdown"
        )
    await callback.answer()


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(HELP_TEXT, parse_mode="Markdown")


@router.callback_query(F.data == "menu:help")
async def help_cb(callback: CallbackQuery) -> None:
    if callback.message:
        await callback.message.edit_text(HELP_TEXT, parse_mode="Markdown",
                                         reply_markup=main_menu_keyboard())
    await callback.answer()


@router.callback_query(F.data == "cancel")
async def cancel_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if callback.message:
        await callback.message.edit_text(
            MAIN_MENU, reply_markup=main_menu_keyboard(), parse_mode="Markdown"
        )
    await callback.answer("Отменено")


@router.message(Command("balance"))
async def balance_command(message: Message, user: User, session: AsyncSession) -> None:
    from bot.formatters import format_balance

    repo = UserRepository(session)
    text = format_balance(
        free=user.free_predictions_left or 0,
        bonus=user.bonus_predictions or 0,
        plan=user.subscription_plan,
        until=user.subscription_until,
        used=user.daily_used or 0,
        quota=user.subscription_daily_quota or 0,
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())


@router.message()
async def unknown_message(message: Message) -> None:
    if message.text and message.text.startswith("/"):
        await message.answer(UNKNOWN_COMMAND)
