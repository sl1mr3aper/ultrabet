"""Общие обработчики: /start, /help, /menu, отмена, неизвестная команда."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.context import services
from bot.keyboards import home_keyboard
from bot.navigation import nav_clear, nav_pop
from bot.texts import (
    HELP_TEXT,
    MAIN_MENU,
    UNKNOWN_COMMAND,
    WELCOME,
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
    if payload.startswith("ref_"):
        code = payload[len("ref_"):]
        ref_service = ReferralService(
            session,
            bonus_signup=settings.referral_bonus_signup,
        )
        referrer = await ref_service.find_referrer(code)
        if referrer is not None and referrer.id != user.id:
            attached = await ref_service.attach_referral(referrer=referrer, referred=user)
            if attached:
                # Привязка прошла; пригласителю уходит уведомление о бонусе.
                # Приглашённому НЕ показываем «вас пригласил X, он получил +N»
                # — это лишняя для нового пользователя информация.
                try:
                    await message.bot.send_message(
                        referrer.tg_id,
                        f"🎉 К тебе зарегистрировался новый пользователь "
                        f"по реферальной ссылке.\nТы получил "
                        f"*+{settings.referral_bonus_signup}* бесплатных отчётов.",
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass
    await _send_welcome(message, user, "")


@router.message(CommandStart())
async def start_plain(message: Message, user: User) -> None:
    await _send_welcome(message, user, "")


async def _send_welcome(message: Message, user: User, bonus_text: str) -> None:
    name = user.display_name() if user else (message.from_user.first_name if message.from_user else "друг")
    text = WELCOME.format(name=name, app="UltraBet")
    if bonus_text:
        text = text + "\n\n" + bonus_text
    user_id = message.from_user.id if message.from_user else None
    await message.answer(
        text, reply_markup=home_keyboard(user_id), parse_mode="Markdown"
    )
# [removed: command handler — UI is buttons-only]
async def menu_command(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else None
    await message.answer(
        MAIN_MENU, reply_markup=home_keyboard(user_id), parse_mode="Markdown"
    )


async def _dispatch_back_target(
    target: str, callback: CallbackQuery, state: FSMContext,
) -> bool:
    """Отрисовать экран, на который возвращает кнопка «Назад».

    Возвращает True, если обработка произошла. False означает, что
    таргет нераспознан — вызывающий код должен откатиться на главное
    меню.
    """
    # Главное меню — очищаем стек.
    if target == "menu:home":
        await nav_clear(state)
        await state.clear()
        if callback.message:
            try:
                await callback.message.edit_text(
                    MAIN_MENU,
                    reply_markup=home_keyboard(callback.from_user.id if callback.from_user else None),
                    parse_mode="Markdown",
                )
            except Exception:
                await callback.message.answer(
                    MAIN_MENU,
                    reply_markup=home_keyboard(callback.from_user.id if callback.from_user else None),
                    parse_mode="Markdown",
                )
        return True

    # Подборки матчей: сегодня / завтра / live.
    if target in {"menu:today", "menu:tomorrow", "menu:live"}:
        from bot.handlers.matches import _render_matches_page
        kind = target.split(":", 1)[1]
        # Переход вернул пользователя в список — источник для кнопок
        # «Назад» вновь обновляется, чтобы при клике по матчу back
        # снова привёл сюда.
        await state.update_data(prediction_origin=target)
        await _render_matches_page(callback, kind=kind, page_index=0)
        return True

    # Список лиг.
    if target == "menu:leagues":
        from bot.handlers.leagues import _render_leagues_page
        await _render_leagues_page(callback, page_index=0, state=state)
        try:
            await callback.answer()
        except Exception:
            pass
        return True

    # Отфильтрованный список лиг страны: "leagues_page:<idx>[:f|:<query>]".
    # Маркер `f` означает «фильтр в FSM»; legacy `<query>` — URL-quoted.
    if target.startswith("leagues_page:"):
        from urllib.parse import unquote

        from bot.handlers.leagues import _filter_leagues_by_country, _load_leagues, _render_leagues_page
        parts = target.split(":", 2)
        try:
            idx = int(parts[1])
        except (IndexError, ValueError):
            idx = 0
        marker = parts[2] if len(parts) > 2 else ""
        q = ""
        if marker == "f":
            data = await state.get_data()
            q = str(data.get("leagues_filter_q") or "")
        elif marker:
            q = unquote(marker)
        if q:
            all_leagues = await _load_leagues()
            filtered = _filter_leagues_by_country(all_leagues, q)
            if filtered:
                await _render_leagues_page(
                    callback, page_index=idx,
                    leagues_override=filtered, query=q, state=state,
                )
                try:
                    await callback.answer()
                except Exception:
                    pass
                return True
        await _render_leagues_page(callback, page_index=idx, state=state)
        try:
            await callback.answer()
        except Exception:
            pass
        return True

    # История прогнозов.
    if target == "menu:history":
        from bot.handlers.history import _send_history_view
        from db.repositories.user_repo import UserRepository
        if not callback.message:
            return False
        tg_id = callback.from_user.id if callback.from_user else None
        session = services.session_factory()
        try:
            repo = UserRepository(session)
            user: User | None = None
            if tg_id is not None:
                user = await repo.get_by_tg_id(tg_id)
            if user is None:
                return False
            await _send_history_view(callback.message, session, user, edit=True)
            await session.commit()
        finally:
            await session.close()
        try:
            await callback.answer()
        except Exception:
            pass
        return True

    # Топ матчей / Топ дня.
    if target == "menu:top_matches":
        from bot.handlers.topmatches import _render_top
        await _render_top(callback, page_index=0)
        return True
    if target == "menu:top_day":
        # Перенаправляем в хэндлер топ-дня (чище, чем копировать логику).
        from bot.handlers.top_day import top_day_cb
        await top_day_cb(callback, state)
        return True

    # Ближайшие матчи лиги: "lgmatches:<id>[:<page>][:f|:<back_q>]".
    # Маркер `f` или legacy URL-quoted строка → фильтр активен.
    if target.startswith("lgmatches:"):
        parts = target.split(":")
        try:
            league_id = int(parts[1])
        except (IndexError, ValueError):
            return False
        page_idx = 0
        marker_idx = 2
        if len(parts) > 2:
            try:
                page_idx = int(parts[2])
                marker_idx = 3
            except ValueError:
                marker_idx = 2
        from bot.handlers.leagues import _has_filter_marker, _render_league_matches_page
        has_filter = await _has_filter_marker(parts, state, idx=marker_idx)
        suffix = ":f" if has_filter else ""
        await state.update_data(
            prediction_origin=f"lgmatches:{league_id}:{page_idx}{suffix}",
        )
        await _render_league_matches_page(
            callback, league_id=league_id, page_index=page_idx,
            has_filter=has_filter,
        )
        return True

    # Экран выбора лиги: "league:menu:<id>[:f|:<back_q>]".
    if target.startswith("league:menu:"):
        parts = target.split(":")
        try:
            league_id = int(parts[2])
        except (IndexError, ValueError):
            return False
        from bot.handlers.leagues import _has_filter_marker, _render_league_root
        has_filter = await _has_filter_marker(parts, state, idx=3)
        await _render_league_root(
            callback, state, league_id=league_id, has_filter=has_filter,
        )
        return True

    # Турнирная таблица лиги: "league:standings:<id>:<page>[:f|:<back_q>]".
    if target.startswith("league:standings:"):
        parts = target.split(":")
        try:
            league_id = int(parts[2])
            page_idx = int(parts[3]) if len(parts) > 3 else 0
        except (IndexError, ValueError):
            return False
        from bot.handlers.leagues import _has_filter_marker, _render_league_standings
        has_filter = await _has_filter_marker(parts, state, idx=4)
        await _render_league_standings(
            callback, state,
            league_id=league_id, page_idx=page_idx, has_filter=has_filter,
        )
        return True

    # Подборка матчей с конкретной страницей: "matches:<kind>:<page>".
    if target.startswith("matches:"):
        parts = target.split(":")
        if len(parts) >= 3:
            kind = parts[1]
            try:
                page_idx = int(parts[2])
            except ValueError:
                page_idx = 0
            if kind in {"today", "tomorrow", "live"}:
                from bot.handlers.matches import _render_matches_page
                await state.update_data(
                    prediction_origin=f"matches:{kind}:{page_idx}",
                )
                await _render_matches_page(
                    callback, kind=kind, page_index=page_idx,
                )
                return True

    # Топ матчей с конкретной страницей: "top_matches:<page>".
    if target.startswith("top_matches:"):
        parts = target.split(":")
        try:
            page_idx = int(parts[1]) if len(parts) > 1 else 0
        except ValueError:
            page_idx = 0
        from bot.handlers.topmatches import _render_top
        await state.update_data(prediction_origin=f"top_matches:{page_idx}")
        await _render_top(callback, page_index=page_idx)
        return True

    return False


@router.callback_query(F.data == "nav:back")
async def nav_back_cb(callback: CallbackQuery, state: FSMContext) -> None:
    """Кнопка «Назад»: вернуться на предыдущий экран из стека навигации.

    Стек заполняется `nav_push`-ами при входе в подборки, историю, лиги
    и прочие вкладки (а также при открытии карточки матча). Если стек
    пуст или таргет нераспознан — возвращаемся в главное меню.
    """
    entry = await nav_pop(state)
    target = entry.callback_data if entry is not None else "menu:home"
    handled = await _dispatch_back_target(target, callback, state)
    if not handled:
        await nav_clear(state)
        if callback.message:
            try:
                await callback.message.edit_text(
                    MAIN_MENU,
                    reply_markup=home_keyboard(callback.from_user.id if callback.from_user else None),
                    parse_mode="Markdown",
                )
            except Exception:
                await callback.message.answer(
                    MAIN_MENU,
                    reply_markup=home_keyboard(callback.from_user.id if callback.from_user else None),
                    parse_mode="Markdown",
                )
        try:
            await callback.answer()
        except Exception:
            pass


@router.callback_query(F.data == "menu:home")
async def menu_home_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await nav_clear(state)
    await state.clear()
    if callback.message:
        await callback.message.edit_text(
            MAIN_MENU, reply_markup=home_keyboard(callback.from_user.id if callback.from_user else None), parse_mode="Markdown"
        )
    await callback.answer()
# [removed: command handler — UI is buttons-only]
async def help_command(message: Message) -> None:
    await message.answer(HELP_TEXT, parse_mode="Markdown")


@router.callback_query(F.data == "menu:help")
async def help_cb(callback: CallbackQuery) -> None:
    if callback.message:
        await callback.message.edit_text(HELP_TEXT, parse_mode="Markdown",
                                         reply_markup=home_keyboard(callback.from_user.id if callback.from_user else None))
    await callback.answer()


@router.callback_query(F.data == "cancel")
async def cancel_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if callback.message:
        await callback.message.edit_text(
            MAIN_MENU, reply_markup=home_keyboard(callback.from_user.id if callback.from_user else None), parse_mode="Markdown"
        )
    await callback.answer("Отменено")


@router.callback_query(F.data == "cancel:op")
async def cancel_op_cb(callback: CallbackQuery, state: FSMContext) -> None:
    """Останавливает долгую операцию (Топ дня, EV-дня, поиск) и
    возвращает пользователя в главное меню.

    Работает для любых прогресс-баров, которые заранее зарегистрировали
    свою task'у через `bot.progress.register_cancel(chat_id, message_id, task)`.
    Task получает `CancelledError`, хэндлер обязан обработать её корректно
    и не показывать пользователю ошибку.
    """
    from bot.progress import trigger_cancel

    await callback.answer("Отменено")
    if callback.message is None:
        return
    trigger_cancel(callback.message.chat.id, callback.message.message_id)
    await nav_clear(state)
    await state.clear()
    try:
        await callback.message.edit_text(
            MAIN_MENU, reply_markup=home_keyboard(callback.from_user.id if callback.from_user else None), parse_mode="Markdown",
        )
    except Exception:
        pass
# [removed: command handler — UI is buttons-only]
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
    await message.answer(text, parse_mode="Markdown", reply_markup=home_keyboard(message.from_user.id if message.from_user else None))


@router.message(F.text.regexp(r"^/\w+"))
async def unknown_message(message: Message) -> None:
    await message.answer(UNKNOWN_COMMAND)
