"""Inline-клавиатуры бота."""

from __future__ import annotations

from collections.abc import Iterable

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.texts import Buttons
from services.countries import format_country
from services.subscription_service import SUBSCRIPTION_PLANS


# ── Главное меню ─────────────────────────────────────────────
def main_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=Buttons.MATCH, callback_data="menu:match")
    builder.button(text=Buttons.TODAY, callback_data="menu:today")
    builder.button(text=Buttons.TOMORROW, callback_data="menu:tomorrow")
    builder.button(text=Buttons.LIVE, callback_data="menu:live")
    builder.button(text=Buttons.LEAGUES, callback_data="menu:leagues")
    builder.button(text=Buttons.STANDINGS, callback_data="menu:standings")
    builder.button(text=Buttons.BALANCE, callback_data="menu:balance")
    builder.button(text=Buttons.SUBSCRIPTION, callback_data="menu:subscribe")
    builder.button(text=Buttons.REFERRAL, callback_data="menu:referral")
    builder.button(text=Buttons.SETTINGS, callback_data="menu:settings")
    builder.button(text=Buttons.ABOUT, callback_data="menu:about")
    builder.button(text=Buttons.HELP, callback_data="menu:help")
    builder.adjust(1, 2, 2, 2, 2, 2, 1)
    return builder.as_markup()


def back_to_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=Buttons.BACK, callback_data="menu:home")
    return builder.as_markup()


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
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for t in teams:
        team_id = t.get("id")
        name = t.get("name") or "?"
        country = t.get("country") or {}
        cname = country.get("name") if isinstance(country, dict) else None
        label = f"{format_country(cname, with_flag=True)} • {name}" if cname else name
        if team_id is None:
            continue
        builder.button(text=label[:64], callback_data=f"{callback_prefix}:{team_id}")
    builder.button(text=Buttons.CANCEL, callback_data="cancel")
    builder.adjust(1)
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
    builder.button(text=Buttons.CANCEL, callback_data="cancel")
    builder.adjust(2)
    return builder.as_markup()


# ── Подписки ─────────────────────────────────────────────────
def subscription_plans_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for plan in SUBSCRIPTION_PLANS.values():
        builder.button(
            text=f"💎 {plan.title} ({plan.daily_quota}/день)",
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
    builder.button(text="📈 Best odds", callback_data=f"predict:best:{game_id}")
    builder.button(text="🧮 Все рынки", callback_data=f"predict:all:{game_id}")
    builder.button(text=Buttons.BACK, callback_data="menu:home")
    builder.adjust(2, 1, 1)
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


def league_view_keyboard(league_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 Матчи", callback_data=f"league:matches:{league_id}")
    builder.button(text="📋 Таблица", callback_data=f"league:table:{league_id}")
    builder.button(text=Buttons.BACK, callback_data="menu:leagues")
    builder.adjust(2, 1)
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
    "prediction_actions_keyboard",
    "share_referral_keyboard",
    "subscription_plans_keyboard",
    "teams_keyboard",
    "url_button",
]
