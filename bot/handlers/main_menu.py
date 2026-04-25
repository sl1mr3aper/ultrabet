"""Обработчики переходов из главного меню."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.formatters import format_balance
from bot.keyboards import (
    back_to_menu,
    cancel_keyboard,
    main_menu_keyboard,
    subscription_plans_keyboard,
)
from bot.states import MatchSearchStates
from bot.texts import (
    ABOUT_HEADER,
    ABOUT_TEXT,
    APP_NAME,
    ASK_MATCH_QUERY,
    HELP_TEXT,
    MAIN_MENU,
    SETTINGS_HEADER,
    SUBSCRIBE_HEADER,
)
from config import Settings
from db.models import User
from services.subscription_service import SUBSCRIPTION_PLANS

router = Router(name="main-menu")


@router.callback_query(F.data == "menu:match")
async def menu_match(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(MatchSearchStates.waiting_for_query)
    if callback.message:
        await callback.message.edit_text(
            ASK_MATCH_QUERY, reply_markup=cancel_keyboard(), parse_mode="Markdown"
        )
    await callback.answer()


@router.callback_query(F.data == "menu:about")
async def menu_about(callback: CallbackQuery, settings: Settings) -> None:
    text = ABOUT_HEADER + "\n\n" + ABOUT_TEXT.format(
        app=APP_NAME, min_value=f"{settings.min_value_percent:.1f}"
    )
    if callback.message:
        await callback.message.edit_text(
            text, reply_markup=back_to_menu(), parse_mode="Markdown"
        )
    await callback.answer()


@router.callback_query(F.data == "menu:settings")
async def menu_settings(callback: CallbackQuery, user: User) -> None:
    parts = [
        SETTINGS_HEADER,
        f"• Часовой пояс: UTC+{user.language_code or 'ru'}",
        f"• Язык: {user.language_code or 'ru'}",
    ]
    if callback.message:
        await callback.message.edit_text(
            "\n".join(parts), reply_markup=back_to_menu(), parse_mode="Markdown"
        )
    await callback.answer()


@router.callback_query(F.data == "menu:balance")
async def menu_balance(callback: CallbackQuery, user: User) -> None:
    text = format_balance(
        free=user.free_predictions_left or 0,
        bonus=user.bonus_predictions or 0,
        plan=user.subscription_plan,
        until=user.subscription_until,
        used=user.daily_used or 0,
        quota=user.subscription_daily_quota or 0,
    )
    if callback.message:
        await callback.message.edit_text(
            text, reply_markup=back_to_menu(), parse_mode="Markdown"
        )
    await callback.answer()


@router.callback_query(F.data == "menu:subscribe")
async def menu_subscribe(callback: CallbackQuery) -> None:
    lines = [SUBSCRIBE_HEADER, ""]
    for plan in SUBSCRIPTION_PLANS.values():
        lines.append(f"• *{plan.title}* — {plan.daily_quota} прогнозов/день")
    lines.append("")
    lines.append("Выбери тариф:")
    if callback.message:
        await callback.message.edit_text(
            "\n".join(lines),
            reply_markup=subscription_plans_keyboard(),
            parse_mode="Markdown",
        )
    await callback.answer()


@router.callback_query(F.data == "menu:home")
async def menu_home(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if callback.message:
        await callback.message.edit_text(
            MAIN_MENU, reply_markup=main_menu_keyboard(), parse_mode="Markdown"
        )
    await callback.answer()


@router.callback_query(F.data == "menu:help_btn")
async def menu_help_btn(callback: CallbackQuery) -> None:
    if callback.message:
        await callback.message.edit_text(
            HELP_TEXT, reply_markup=back_to_menu(), parse_mode="Markdown"
        )
    await callback.answer()
