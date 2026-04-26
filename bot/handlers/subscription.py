"""Подписки: оплата через Telegram Stars + авто-активация + авто-экспирация."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
    SuccessfulPayment,
)
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from bot.context import services
from bot.keyboards import main_menu_keyboard, subscription_plans_keyboard
from bot.texts import (
    SUBSCRIBE_ACTIVATED,
    SUBSCRIBE_HEADER,
    SUBSCRIBE_PLAN_LINE,
)
from config import Settings
from db.models import User
from db.repositories.payment_repo import PaymentRepository
from db.repositories.user_repo import UserRepository
from services.referral_service import ReferralService
from services.subscription_service import SUBSCRIPTION_PLANS, SubscriptionService

router = Router(name="subscription")


# ── Команды и меню ──────────────────────────────────────────


@router.message(Command("subscribe"))
async def subscribe_command(message: Message) -> None:
    await message.answer(
        _subscribe_text(),
        reply_markup=subscription_plans_keyboard(),
        parse_mode="Markdown",
    )


def _subscribe_text() -> str:
    parts = [SUBSCRIBE_HEADER, ""]
    for plan in SUBSCRIPTION_PLANS.values():
        parts.append(
            SUBSCRIBE_PLAN_LINE.format(title=plan.title, quota=plan.daily_quota)
            + f" · {plan.stars_price} ⭐"
        )
    parts.append("")
    parts.append("Выбери тариф — бот выставит счёт в Telegram Stars ⭐.")
    return "\n".join(parts)


# ── Выставление счёта (invoice) ─────────────────────────────


@router.callback_query(F.data.startswith("sub:buy:"))
async def buy_plan_cb(callback: CallbackQuery) -> None:
    if not callback.data or not callback.message:
        await callback.answer()
        return
    plan_code = callback.data.rsplit(":", 1)[1]
    plan = SubscriptionService.get_plan(plan_code)
    if plan is None:
        await callback.answer("Неизвестный тариф", show_alert=True)
        return
    if plan.stars_price <= 0:
        await callback.answer("Цена не задана", show_alert=True)
        return

    title = f"UltraBet · {plan.title} {plan.badge}"
    description = plan.description or f"Подписка на {plan.title}"
    # currency=XTR => Telegram Stars
    prices = [LabeledPrice(label=plan.title, amount=plan.stars_price)]
    try:
        await callback.bot.send_invoice(
            chat_id=callback.from_user.id,
            title=title,
            description=description,
            payload=f"sub:{plan.code}:{callback.from_user.id}",
            provider_token="",  # Stars: provider_token пустой
            currency="XTR",
            prices=prices,
            start_parameter="ultrabet_sub",
        )
        await callback.answer("Счёт отправлен ⭐")
    except Exception as exc:
        logger.exception("send_invoice failed: {}", exc)
        await callback.answer("Не удалось создать счёт. Попробуй позже.", show_alert=True)


# ── Pre-checkout: всегда подтверждаем ───────────────────────


@router.pre_checkout_query()
async def pre_checkout(pcq: PreCheckoutQuery) -> None:
    try:
        await pcq.answer(ok=True)
    except Exception as exc:
        logger.warning("pre_checkout failed: {}", exc)


# ── Успешная оплата: активация, бейдж, бонусы рефереру ──────


@router.message(F.successful_payment)
async def on_successful_payment(
    message: Message,
    user: User,
    session: AsyncSession,
    settings: Settings,
) -> None:
    payment: SuccessfulPayment | None = message.successful_payment
    if payment is None:
        return
    payload = payment.invoice_payload or ""
    # payload формата sub:<plan_code>:<tg_id>
    parts = payload.split(":")
    if len(parts) < 2 or parts[0] != "sub":
        await message.answer("Платёж получен, но не удалось распознать тариф.")
        return
    plan = SubscriptionService.get_plan(parts[1])
    if plan is None:
        await message.answer("Платёж получен, но тариф не найден. Свяжись с админом.")
        return

    sub_service = SubscriptionService(session)
    activated = await sub_service.activate(user, plan.code)
    if activated is None:
        await message.answer("Не удалось активировать подписку, обратись к админу.")
        return

    # Сохраняем платёж
    payments = PaymentRepository(session)
    await payments.create(
        user_id=user.id,
        plan_code=plan.code,
        amount=float(payment.total_amount or plan.stars_price),
        provider="telegram_stars",
    )

    # Обновляем ярлык пользователя (бейдж)
    if hasattr(user, "badge"):
        user.badge = plan.badge

    # Бонус пригласителю
    if user.referred_by_id:
        ref = ReferralService(
            session,
            bonus_signup=settings.referral_bonus_signup,
            bonus_sub_1m=settings.referral_bonus_sub_1m,
            bonus_sub_3m=settings.referral_bonus_sub_3m,
            bonus_sub_12m=settings.referral_bonus_sub_12m,
        )
        try:
            await ref.reward_for_subscription(referred=user, plan_code=plan.code)
        except Exception as exc:
            logger.warning("referral reward failed: {}", exc)

    await session.flush()

    until_dt = user.subscription_until
    if isinstance(until_dt, datetime) and until_dt.tzinfo is None:
        until_dt = until_dt.replace(tzinfo=UTC)
    until_s = until_dt.strftime("%d.%m.%Y %H:%M") if until_dt else "—"
    await message.answer(
        SUBSCRIBE_ACTIVATED.format(plan=plan.title, until=until_s, quota=plan.daily_quota)
        + f"\n\nЯрлык: {plan.badge}\nСпасибо за поддержку проекта ⭐",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )


# ── Background task: истечение подписок ─────────────────────


async def expire_subscriptions_loop(interval_seconds: int = 3600) -> None:
    """Фоновая проверка экспирации каждые N секунд.

    Снимает плейлейбл у истекших подписок и шлёт сообщение пользователю.
    """
    while True:
        try:
            factory = services.session_factory
            if factory is None:
                await asyncio.sleep(interval_seconds)
                continue
            async with factory() as session:
                repo = UserRepository(session)
                expired = await repo.list_expired_subscriptions()
                for u in expired:
                    u.subscription_plan = None
                    u.subscription_until = None
                    u.subscription_daily_quota = 0
                    if hasattr(u, "badge"):
                        u.badge = ""
                await session.commit()
                # Шлём уведомления
                # (бот для уведомлений должен быть доступен через services, в проде)
                # здесь оставляем лог для отчёта
                if expired:
                    logger.info("Expired subscriptions: {}", len(expired))
        except Exception as exc:
            logger.warning("expire loop failed: {}", exc)
        await asyncio.sleep(interval_seconds)


__all__ = ["expire_subscriptions_loop", "router"]
