"""Реферальная программа."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards import share_referral_keyboard
from bot.texts import REFERRAL_HEADER
from config import Settings
from db.models import User
from services.referral_service import ReferralService

router = Router(name="referral")
# [removed: command handler — UI is buttons-only]
async def referral_command(
    message: Message, user: User, session: AsyncSession, settings: Settings
) -> None:
    await _send_referral(message, user, session, settings)


@router.callback_query(F.data == "menu:referral")
async def referral_cb(
    callback: CallbackQuery, user: User, session: AsyncSession, settings: Settings
) -> None:
    if callback.message:
        await _send_referral(callback.message, user, session, settings, edit=True)
    await callback.answer()


async def _send_referral(
    message: Message,
    user: User,
    session: AsyncSession,
    settings: Settings,
    *,
    edit: bool = False,
) -> None:
    from services.subscription_service import SUBSCRIPTION_PLANS

    service = ReferralService(
        session,
        bonus_signup=settings.referral_bonus_signup,
    )
    code = await service.ensure_code(user)
    link = service.build_link(settings.bot_username, code)
    stats = await service.stats(user)
    # Бонусы за каждый тариф собираем динамически из плана.
    plans_lines = [
        f"• {p.title} → +{p.referrer_bonus}"
        for p in SUBSCRIPTION_PLANS.values()
        if p.referrer_bonus > 0
    ]
    plans_block = "\n".join(plans_lines)
    text = REFERRAL_HEADER.format(
        signup=settings.referral_bonus_signup,
        plans_block=plans_block,
        link=link,
        total=stats["total_referred"],
        paid=stats["paid_referred"],
        signup_total=stats["bonus_signup_total"],
        sub_total=stats["bonus_sub_total"],
        balance=stats["current_bonus_balance"],
    )
    keyboard = share_referral_keyboard(link)
    if edit:
        await message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard,
                                disable_web_page_preview=True)
    else:
        await message.answer(text, parse_mode="Markdown", reply_markup=keyboard,
                              disable_web_page_preview=True)
