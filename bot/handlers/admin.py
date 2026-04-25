"""Админ-панель."""

from __future__ import annotations

from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards import main_menu_keyboard
from bot.texts import ADMIN_NOT_ALLOWED, ADMIN_PANEL
from config import Settings
from db.models import User
from db.repositories.user_repo import UserRepository
from services.referral_service import ReferralService
from services.subscription_service import SUBSCRIPTION_PLANS, SubscriptionService

router = Router(name="admin")


def _is_admin(user: User | None, settings: Settings) -> bool:
    if user is None:
        return False
    if user.is_admin:
        return True
    return user.tg_id in (settings.admin_ids or [])


@router.message(Command("admin"))
async def admin_panel(
    message: Message, user: User, session: AsyncSession, settings: Settings
) -> None:
    if not _is_admin(user, settings):
        await message.answer(ADMIN_NOT_ALLOWED)
        return
    repo = UserRepository(session)
    stats = await repo.stats()
    text = ADMIN_PANEL.format(
        total=stats["total"],
        subs=stats["active_subscriptions"],
        blocked=stats["blocked"],
        new=stats["new_24h"],
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())


@router.message(Command("grant"))
async def grant_subscription(
    message: Message, user: User, session: AsyncSession, settings: Settings
) -> None:
    if not _is_admin(user, settings):
        await message.answer(ADMIN_NOT_ALLOWED)
        return
    parts = (message.text or "").split()
    if len(parts) != 3:
        await message.answer("Использование: /grant <tg_id> <plan_code>")
        return
    try:
        target_tg_id = int(parts[1])
    except ValueError:
        await message.answer("tg_id должен быть числом.")
        return
    plan_code = parts[2]
    if plan_code not in SUBSCRIPTION_PLANS:
        await message.answer(f"Неизвестный тариф {plan_code}. Доступные: "
                              + ", ".join(SUBSCRIPTION_PLANS))
        return
    repo = UserRepository(session)
    target = await repo.get_by_tg_id(target_tg_id)
    if target is None:
        await message.answer("Пользователь не найден.")
        return
    sub = SubscriptionService(session)
    plan = await sub.activate(target, plan_code)
    if plan is None:
        await message.answer("Не удалось активировать.")
        return
    if target.referred_by_id:
        ref = ReferralService(
            session,
            bonus_signup=settings.referral_bonus_signup,
            bonus_sub_1m=settings.referral_bonus_sub_1m,
            bonus_sub_3m=settings.referral_bonus_sub_3m,
            bonus_sub_12m=settings.referral_bonus_sub_12m,
        )
        await ref.reward_for_subscription(referred=target, plan_code=plan_code)
    await session.flush()
    await message.answer(
        f"✅ Подписка *{plan.title}* активирована для tg_id={target_tg_id}",
        parse_mode="Markdown",
    )
    try:
        await message.bot.send_message(
            target_tg_id,
            f"🎉 Тебе подключена подписка *{plan.title}*. Дневная квота — *{plan.daily_quota}*.",
            parse_mode="Markdown",
        )
    except Exception as exc:
        logger.debug("can't notify {}: {}", target_tg_id, exc)


@router.message(Command("ban"))
async def ban_user(
    message: Message, user: User, session: AsyncSession, settings: Settings
) -> None:
    if not _is_admin(user, settings):
        return
    parts = (message.text or "").split()
    if len(parts) != 2:
        return
    try:
        tg_id = int(parts[1])
    except ValueError:
        return
    repo = UserRepository(session)
    target = await repo.get_by_tg_id(tg_id)
    if target:
        await repo.set_blocked(target, True)
        await message.answer(f"Заблокирован {tg_id}")


@router.message(Command("unban"))
async def unban_user(
    message: Message, user: User, session: AsyncSession, settings: Settings
) -> None:
    if not _is_admin(user, settings):
        return
    parts = (message.text or "").split()
    if len(parts) != 2:
        return
    try:
        tg_id = int(parts[1])
    except ValueError:
        return
    repo = UserRepository(session)
    target = await repo.get_by_tg_id(tg_id)
    if target:
        await repo.set_blocked(target, False)
        await message.answer(f"Разблокирован {tg_id}")


@router.message(Command("broadcast"), F.from_user)
async def broadcast(
    message: Message, user: User, session: AsyncSession, settings: Settings
) -> None:
    if not _is_admin(user, settings):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /broadcast Текст рассылки")
        return
    text = parts[1]
    repo = UserRepository(session)
    users = await repo.all_users(limit=10000)
    sent = 0
    failed = 0
    for u in users:
        try:
            await message.bot.send_message(u.tg_id, text)
            sent += 1
        except Exception:
            failed += 1
    await message.answer(f"📨 Отправлено: {sent}, ошибок: {failed}")


def _now() -> datetime:
    return datetime.now(tz=UTC)
