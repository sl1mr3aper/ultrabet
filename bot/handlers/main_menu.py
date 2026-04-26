"""Обработчики переходов из главного меню."""

from __future__ import annotations

from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.context import services
from bot.keyboards import (
    back_to_menu,
    cancel_keyboard,
    main_menu_keyboard,
    subscription_plans_keyboard,
)
from bot.states import MatchSearchStates
from bot.texts import (
    APP_NAME,
    ASK_MATCH_QUERY,
    HELP_TEXT,
    MAIN_MENU,
    SUBSCRIBE_HEADER,
)
from config import Settings
from db.models import User
from services.subscription_service import SUBSCRIPTION_PLANS

router = Router(name="main-menu")


# ── Языки и часовые пояса для настроек ─────────────────────────
_LANG_FLAGS: dict[str, str] = {
    "ru": "🇷🇺 Русский",
    "en": "🇬🇧 English",
    "uk": "🇺🇦 Українська",
    "kz": "🇰🇿 Қазақша",
}
_TZ_CITIES: dict[int, str] = {
    0: "UTC±0 · Лондон",
    1: "UTC+1 · Берлин",
    2: "UTC+2 · Киев",
    3: "UTC+3 · Москва",
    4: "UTC+4 · Самара",
    5: "UTC+5 · Екатеринбург",
    6: "UTC+6 · Астана",
    7: "UTC+7 · Новосибирск",
    8: "UTC+8 · Иркутск",
}
_STRATEGY_NAMES: dict[str, str] = {
    "balanced": "⚖️ Сбалансированная",
    "conservative": "🛡 Консервативная",
    "aggressive": "🔥 Агрессивная",
    "underdog": "🎲 Андердог",
}


def _lang_label(code: str | None) -> str:
    if not code:
        return _LANG_FLAGS["ru"]
    code = code.lower()[:2]
    return _LANG_FLAGS.get(code, _LANG_FLAGS["ru"])


def _tz_label(offset: int) -> str:
    return _TZ_CITIES.get(offset, f"UTC{offset:+d}")


def _strategy_label(code: str | None) -> str:
    return _STRATEGY_NAMES.get((code or "balanced").lower(), _STRATEGY_NAMES["balanced"])


@router.callback_query(F.data == "menu:match")
async def menu_match(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(MatchSearchStates.waiting_for_query)
    if callback.message:
        await callback.message.edit_text(
            ASK_MATCH_QUERY, reply_markup=cancel_keyboard(), parse_mode="Markdown"
        )
    await callback.answer()


@router.callback_query(F.data == "menu:about")
async def menu_about(callback: CallbackQuery) -> None:
    settings: Settings = services.settings  # type: ignore[assignment]
    text = (
        f"ℹ️ *О боте {APP_NAME}*\n\n"
        "UltraBet — независимый Telegram-бот для футбольных прогнозов.\n"
        "Никакой магии: только математика поверх открытой статистики.\n\n"
        "📊 *Источник данных*\n"
        "SStats.net (OpenAPI v0.9.14) — матчи, xG, рейтинги, травмы, стандинги,\n"
        "коэффициенты букмекеров (pre-match и live).\n\n"
        "🧠 *Модель прогнозов*\n"
        "• *Glicko-2* — динамический рейтинг силы команд и неопределённости\n"
        "• *Double Poisson* — распределение по точным счетам через xG\n"
        "• *Ensemble* — смешивание силы, формы, H2H, травм\n"
        "• *Season-table* и *last-games-stats* — поправки за контекст\n\n"
        "💎 *Валуйные ставки*\n"
        f"Value % = (p × коэф) − 1, фильтр ≥ *{settings.min_value_percent:.1f}%*.\n"
        "Сортировка по убыванию валуйности. Показываем fair-коэф (1 / p)\n"
        "и реальный коэф букмекера.\n\n"
        "🎯 *Стратегии*\n"
        "7 пресетов (от консервативного до Kelly / Martingale) — выбираются\n"
        "в разделе настроек и применяются к расчёту стейка.\n\n"
        "🌐 *Языки*: русский, английский, украинский, казахский.\n"
        "📅 *Часовые пояса*: от UTC±0 до UTC+8.\n"
        "🔁 *Кеш и ретраи*: смарт-TTL, circuit breaker, token-bucket лимиты.\n\n"
        "🤝 *Команда*: UltraBet Labs, 2025.\n"
        "📖 Документация: в /help."
    )
    if callback.message:
        await callback.message.edit_text(
            text, reply_markup=back_to_menu(), parse_mode="Markdown"
        )
    await callback.answer()


@router.callback_query(F.data == "menu:settings")
async def menu_settings(callback: CallbackQuery, user: User) -> None:
    settings: Settings = services.settings  # type: ignore[assignment]
    strategy_code = getattr(user, "strategy", None) or "balanced"
    notif_on = bool(getattr(user, "notifications_enabled", True))
    text = (
        "⚙️ *Настройки*\n\n"
        f"🌐 Язык: *{_lang_label(user.language_code)}*\n"
        f"🕒 Часовой пояс: *{_tz_label(settings.timezone_offset)}*\n"
        f"🎯 Стратегия ставок: *{_strategy_label(strategy_code)}*\n"
        f"🔔 Уведомления: *{'включены' if notif_on else 'выключены'}*\n\n"
        "Доступные команды:\n"
        "`/strategy` — выбрать пресет стратегии\n"
        "`/bankroll` — калькулятор стейка (Kelly / Flat / Martingale)\n"
        "`/notify on|off` — уведомления о матчах и новых value-ставках\n"
        "`/tz <N>` — смена часового пояса (UTC+N)\n"
        "`/lang ru|en|uk|kz` — язык интерфейса"
    )
    if callback.message:
        await callback.message.edit_text(
            text, reply_markup=back_to_menu(), parse_mode="Markdown"
        )
    await callback.answer()


@router.callback_query(F.data == "menu:subscribe")
async def menu_subscribe(callback: CallbackQuery, user: User) -> None:
    # Объединяем сюда бывший раздел «Мой баланс»
    free = user.free_predictions_left or 0
    bonus = user.bonus_predictions or 0
    plan = user.subscription_plan
    until = user.subscription_until
    used = user.daily_used or 0
    quota = user.subscription_daily_quota or 0

    if plan and until:
        until_dt = until if isinstance(until, datetime) else datetime.fromisoformat(str(until))
        if until_dt.tzinfo is None:
            until_dt = until_dt.replace(tzinfo=UTC)
        days_left = max(0, (until_dt - datetime.now(tz=UTC)).days)
        status_line = (
            f"✨ *Активная подписка:* `{plan}`\n"
            f"⏳ Осталось: *{days_left} дн.* (до {until_dt.strftime('%d.%m.%Y')})\n"
            f"📊 Использовано сегодня: *{used}/{quota}*"
        )
    else:
        status_line = (
            "🆓 *Тариф:* бесплатный\n"
            f"Осталось прогнозов: *{free}* (бонусных: *{bonus}*)"
        )

    lines = [
        "💎 *Подписка UltraBet*",
        "",
        status_line,
        "",
        SUBSCRIBE_HEADER.split("\n\n", 1)[1] if "\n\n" in SUBSCRIBE_HEADER else "",
        "",
        "*Тарифы (оплата Telegram Stars ⭐):*",
    ]
    for plan_obj in SUBSCRIPTION_PLANS.values():
        price = getattr(plan_obj, "stars_price", None) or getattr(plan_obj, "price", 0)
        lines.append(
            f"• *{plan_obj.title}* — {plan_obj.daily_quota} прогнозов/день · {price} ⭐"
        )
    lines.append("")
    lines.append("Выбери тариф ниже 👇")
    text = "\n".join([ln for ln in lines if ln is not None])
    if callback.message:
        await callback.message.edit_text(
            text,
            reply_markup=subscription_plans_keyboard(),
            parse_mode="Markdown",
        )
    await callback.answer()


@router.callback_query(F.data == "menu:standings")
async def menu_standings_redirect(callback: CallbackQuery) -> None:
    """Раздел удалён — редирект в подписку + короткое сообщение."""
    await callback.answer(
        "Раздел «Турнирные таблицы» отключён. Используй разделы матчей и лиг.",
        show_alert=True,
    )


@router.callback_query(F.data == "menu:balance")
async def menu_balance_redirect(
    callback: CallbackQuery, user: User, state: FSMContext
) -> None:
    """Раздел удалён — информация перенесена в «Подписка»."""
    await menu_subscribe(callback, user)


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


@router.callback_query(F.data == "menu_main")
async def menu_main_alias(callback: CallbackQuery, state: FSMContext) -> None:
    """Алиас для пагинации: возвращает в главное меню."""
    await state.clear()
    if callback.message:
        await callback.message.edit_text(
            MAIN_MENU, reply_markup=main_menu_keyboard(), parse_mode="Markdown"
        )
    await callback.answer()


@router.callback_query(F.data == "noop")
async def callback_noop(callback: CallbackQuery) -> None:
    """Заглушка для индикатора страниц."""
    await callback.answer()
