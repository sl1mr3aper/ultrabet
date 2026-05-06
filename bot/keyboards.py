"""Inline-клавиатуры бота."""

from __future__ import annotations

from collections.abc import Iterable

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.texts import Buttons
from services.countries import format_country
from services.subscription_service import SUBSCRIPTION_PLANS


# ── Главное меню ─────────────────────────────────────────────
def main_menu_keyboard(*, is_admin: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=Buttons.MATCH, callback_data="menu:match")
    # Кнопка «Топ дня» временно скрыта — раздел дорабатывается
    # (см. handler `top_day_cb`, останется доступным по deep-link/admin).
    builder.button(text=Buttons.TODAY, callback_data="menu:today")
    builder.button(text=Buttons.TOMORROW, callback_data="menu:tomorrow")
    builder.button(text=Buttons.LEAGUES, callback_data="menu:leagues")
    builder.button(text=Buttons.SUBSCRIPTION, callback_data="menu:subscribe")
    builder.button(text=Buttons.REFERRAL, callback_data="menu:referral")
    builder.button(text=Buttons.HISTORY, callback_data="menu:history")
    builder.button(text=Buttons.SETTINGS, callback_data="menu:settings")
    builder.button(text=Buttons.ABOUT, callback_data="menu:about")
    builder.button(text=Buttons.HELP, callback_data="menu:help")
    # Админ-кнопки видим только админу (по `admin_ids` в настройках).
    # Массовый анализ и анализ прогнозов — две отдельные точки входа,
    # как просил пользователь.
    if is_admin:
        builder.button(
            text=Buttons.ADMIN_MASS_ANALYSIS,
            callback_data="admin:mass_analysis",
        )
        builder.button(
            text=Buttons.ADMIN_PREDICTION_ANALYSIS,
            callback_data="admin:prediction_analysis",
        )
        builder.button(
            text=Buttons.ADMIN_MODEL_ACCURACY,
            callback_data="admin:model_accuracy",
        )
        builder.adjust(1, 2, 1, 2, 1, 2, 1, 2, 1)
    else:
        builder.adjust(1, 2, 1, 2, 1, 2, 1)
    return builder.as_markup()


def is_admin_user(user_id: int | None, admin_ids: list[int] | None) -> bool:
    """Унифицированная проверка прав администратора.

    Используется в обработчиках для решения, добавлять ли админ-кнопки
    в главное меню. None-id (например, callback без from_user) считаем
    обычным пользователем.
    """
    if user_id is None or not admin_ids:
        return False
    try:
        return int(user_id) in {int(x) for x in admin_ids}
    except (TypeError, ValueError):
        return False


def home_keyboard(user_id: int | None = None) -> InlineKeyboardMarkup:
    """Главное меню с автоопределением админ-статуса по `services.settings`.

    Удобно вызывать из любого хэндлера: не нужно прокидывать `is_admin`
    вручную, статус резолвится по `admin_ids` из конфигурации.
    """
    try:
        from bot.context import services
        admin_ids = getattr(services.settings, "admin_ids", None)
    except Exception:
        admin_ids = None
    is_admin = is_admin_user(user_id, admin_ids if isinstance(admin_ids, list) else None)
    return main_menu_keyboard(is_admin=is_admin)


def back_to_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=Buttons.BACK, callback_data="menu:home")
    return builder.as_markup()


def nav_back_menu_row(builder: InlineKeyboardBuilder) -> None:
    """Добавить строку с кнопками 'Назад' и 'Главное меню' в builder."""
    builder.row(
        InlineKeyboardButton(text=Buttons.BACK, callback_data="nav:back"),
        InlineKeyboardButton(text=Buttons.MAIN_MENU, callback_data="menu:home"),
    )


def cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=Buttons.CANCEL, callback_data="cancel")
    builder.button(text=Buttons.BACK, callback_data="menu:home")
    builder.adjust(2)
    return builder.as_markup()


# ── Команды и страны ─────────────────────────────────────────
def teams_keyboard(
    teams: Iterable[dict],
    *,
    callback_prefix: str,
    page: int = 0,
    page_size: int = 10,
    total: int | None = None,
) -> InlineKeyboardMarkup:
    """Клавиатура выбора команды с пагинацией.

    Параметры:
      teams      — уже срезанная страница (≤ page_size элементов).
      page       — номер текущей страницы (0-based) — для prev/next.
      page_size  — размер страницы (по умолчанию 10).
      total      — общее число команд во всём списке. Если None — пагинация
                   не показывается, ведёт себя как одна страница.
    """
    builder = InlineKeyboardBuilder()
    teams_list = [t for t in teams if t.get("id") is not None]
    for t in teams_list:
        team_id = t.get("id")
        name = t.get("name") or "?"
        country = t.get("country") or {}
        cname = country.get("name") if isinstance(country, dict) else None
        label = (
            f"{format_country(cname, with_flag=True)} • {name}" if cname else name
        )
        builder.button(text=label[:64], callback_data=f"{callback_prefix}:{team_id}")
    rows = [1] * len(teams_list)
    # Кнопки пагинации (← / →) только если есть смысл листать.
    if total is not None and total > page_size:
        last_page = (total - 1) // page_size
        nav_buttons = 0
        if page > 0:
            builder.button(
                text="← Назад",
                callback_data=f"{callback_prefix}_p:{page - 1}",
            )
            nav_buttons += 1
        builder.button(
            text=f"Стр. {page + 1}/{last_page + 1}",
            callback_data="noop",
        )
        nav_buttons += 1
        if page < last_page:
            builder.button(
                text="Вперёд →",
                callback_data=f"{callback_prefix}_p:{page + 1}",
            )
            nav_buttons += 1
        rows.append(nav_buttons)
    builder.button(text=Buttons.CANCEL, callback_data="cancel")
    rows.append(1)
    builder.adjust(*rows)
    return builder.as_markup()


def countries_keyboard(
    countries: Iterable[str], *, callback_prefix: str = "country"
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for c in countries:
        if not c:
            continue
        builder.button(
            text=format_country(c, with_flag=True)[:60],
            callback_data=f"{callback_prefix}:{c[:48]}",
        )
    # Кросс-страновые матчи (Лига Чемпионов и пр.): пользователь
    # должен иметь возможность пропустить фильтрацию по стране.
    builder.button(
        text="🌍 Любая страна / разные страны",
        callback_data=f"{callback_prefix}:__any__",
    )
    builder.button(text=Buttons.CANCEL, callback_data="cancel")
    builder.adjust(2)
    return builder.as_markup()


# ── Подписки ─────────────────────────────────────────────────
def subscription_plans_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for plan in SUBSCRIPTION_PLANS.values():
        builder.button(
            text=f"{plan.badge} {plan.title} · {plan.stars_price} ⭐",
            callback_data=f"sub:buy:{plan.code}",
        )
    builder.button(text=Buttons.BACK, callback_data="menu:home")
    builder.adjust(1)
    return builder.as_markup()


# ── Подборки ─────────────────────────────────────────────────
def matches_keyboard(
    matches: Iterable[dict], *, callback_prefix: str = "predict"
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for m in matches:
        gid = m.get("id") or m.get("gameId")
        home = (m.get("homeTeam") or {}).get("name") or "?"
        away = (m.get("awayTeam") or {}).get("name") or "?"
        if gid is None:
            continue
        builder.button(
            text=f"{home} — {away}"[:64],
            callback_data=f"{callback_prefix}:{gid}",
        )
    builder.button(text=Buttons.BACK, callback_data="menu:home")
    builder.adjust(1)
    return builder.as_markup()


def prediction_actions_keyboard(game_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=Buttons.REFRESH, callback_data=f"predict:refresh:{game_id}")
    builder.button(text="📊 Полный CSV-отчёт", callback_data=f"predict:csv:{game_id}")
    builder.adjust(2)
    builder.row(
        InlineKeyboardButton(text=Buttons.BACK, callback_data="nav:back"),
        InlineKeyboardButton(text=Buttons.MAIN_MENU, callback_data="menu:home"),
    )
    return builder.as_markup()


# ── Лиги/таблицы ─────────────────────────────────────────────
def leagues_keyboard(leagues: Iterable[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for league in leagues:
        league_id = league.get("id")
        name = league.get("name") or "?"
        country = league.get("country") or {}
        cname = country.get("name") if isinstance(country, dict) else None
        label = f"{format_country(cname)} • {name}" if cname else name
        if league_id is None:
            continue
        builder.button(text=label[:64], callback_data=f"league:{league_id}")
    builder.button(text=Buttons.BACK, callback_data="menu:home")
    builder.adjust(1)
    return builder.as_markup()


def league_view_keyboard(
    league_id: int, *, has_filter: bool = False,
) -> InlineKeyboardMarkup:
    """Кнопки под пустой страницей «Ближайшие матчи лиги».

    `has_filter` — флаг «активен фильтр по стране в списке лиг».
    Используется маркер `:f` в callback вместо реального названия
    страны (короткий — обходит 64-байтный лимит callback_data).
    """
    del league_id  # сейчас не используется в callback
    builder = InlineKeyboardBuilder()
    if has_filter:
        builder.button(
            text=Buttons.BACK,
            callback_data="leagues_page:0:f",
        )
    else:
        builder.row(
            InlineKeyboardButton(text=Buttons.BACK, callback_data="nav:back"),
            InlineKeyboardButton(text=Buttons.MAIN_MENU, callback_data="menu:home"),
        )
    builder.adjust(1)
    return builder.as_markup()


# ── Утилиты ──────────────────────────────────────────────────
def url_button(label: str, url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label, url=url)]])


def share_referral_keyboard(link: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📤 Поделиться", url=f"https://t.me/share/url?url={link}")
    builder.button(text=Buttons.BACK, callback_data="menu:home")
    builder.adjust(1)
    return builder.as_markup()


__all__ = [
    "back_to_menu",
    "cancel_keyboard",
    "countries_keyboard",
    "league_view_keyboard",
    "leagues_keyboard",
    "main_menu_keyboard",
    "matches_keyboard",
    "nav_back_menu_row",
    "prediction_actions_keyboard",
    "share_referral_keyboard",
    "subscription_plans_keyboard",
    "teams_keyboard",
    "url_button",
]
