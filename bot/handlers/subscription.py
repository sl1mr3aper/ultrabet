"""Подписки."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards import main_menu_keyboard, subscription_plans_keyboard
from bot.texts import (
    SUBSCRIBE_ACTIVATED,
    SUBSCRIBE_HEADER,
    SUBSCRIBE_PLAN_LINE,
    SUBSCRIBE_REQUEST_SENT,
)
from config import Settings
from db.models import User
from db.repositories.payment_repo import PaymentRepository
from services.referral_service import ReferralService
from services.subscription_service import SUBSCRIPTION_PLANS, SubscriptionService

router = Router(name="subscription")


@router.message(Command("subscribe"))
async def subscribe_command(message: Message) -> None:
    await message.answer(_subscribe_text(), reply_markup=subscription_plans_keyboard(),
                          parse_mode="Markdown")


def _subscribe_text() -> str:
    parts = [SUBSCRIBE_HEADER, ""]
    for plan in SUBSCRIPTION_PLANS.values():
        parts.append(SUBSCRIBE_PLAN_LINE.format(title=plan.title, quota=plan.daily_quota))
    parts.append("")
    parts.append("Выбери тариф:")
    return "\n".join(parts)


@router.callback_query(F.data.startswith("sub:buy:"))
async def buy_plan_cb(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    settings: Settings,
) -> None:
    if not callback.data:
        await callback.answer()
        return
    plan_code = callback.data.rsplit(":", 1)[1]
    plan = SubscriptionService.get_plan(plan_code)
    if plan is None:
        await callback.answer("Неизвестный тариф")
        return

    payments = PaymentRepository(session)
    await payments.create(
        user_id=user.id, plan_code=plan.code, amount=0.0, provider="manual"
    )

    if user.is_admin or user.tg_id in settings.admin_ids:
        sub_service = SubscriptionService(session)
        activated = await sub_service.activate(user, plan.code)
        if activated and user.referred_by_id:
            ref = ReferralService(
                session,
                bonus_signup=settings.referral_bonus_signup,
                bonus_sub_1m=settings.referral_bonus_sub_1m,
                bonus_sub_3m=settings.referral_bonus_sub_3m,
                bonus_sub_12m=settings.referral_bonus_sub_12m,
            )
            await ref.reward_for_subscription(referred=user, plan_code=plan.code)
        until = user.subscription_until.strftime("%d.%m.%Y") if user.subscription_until else "—"
        if callback.message:
            await callback.message.edit_text(
                SUBSCRIBE_ACTIVATED.format(plan=plan.title, until=until, quota=plan.daily_quota),
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard(),
            )
    else:
        if callback.message:
            await callback.message.edit_text(
                SUBSCRIBE_REQUEST_SENT.format(plan=plan.title),
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard(),
            )
        for admin_id in settings.admin_ids:
            try:
                await callback.bot.send_message(
                    admin_id,
                    f"💳 Заявка на подписку *{plan.title}* от {user.display_name()} "
                    f"(tg id={user.tg_id}).\n"
                    f"Команда подтверждения: `/grant {user.tg_id} {plan.code}`",
                    parse_mode="Markdown",
                )
            except Exception:
                pass

    await callback.answer()
