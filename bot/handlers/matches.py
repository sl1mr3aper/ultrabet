"""Подборки матчей: сегодня / завтра / live с пагинацией."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from api.sstats_client import SStatsClient
from bot.context import services
from bot.navigation import nav_push
from bot.pagination import (
    Page,
    format_paginated,
    pagination_keyboard,
    parse_page_input,
    parse_pagination_callback,
)
from bot.states import MatchesPageStates
from bot.styles import ICON_BALL, ICON_CALENDAR, ICON_FIRE, header
from bot.texts import LIVE_HEADER, NO_MATCHES, TODAY_HEADER, TOMORROW_HEADER, Buttons
from config import Settings
from services.countries import country_flag

router = Router(name="matches")
PAGE_SIZE = 10
# Сколько матчей пытаемся вытянуть на страницу-список. Раньше было 80
# (потолок 8 страниц по 10), теперь до 500 — это покрывает все
# европейские/азиатские/американские лиги одного дня.
LIST_LIMIT = 500


def _match_country(m: dict[str, Any]) -> str | None:
    season = m.get("season") or {}
    if not isinstance(season, dict):
        return None
    league = season.get("league") or {}
    if not isinstance(league, dict):
        return None
    c = league.get("country")
    if isinstance(c, dict):
        return c.get("name")
    return None


def _match_league(m: dict[str, Any]) -> str:
    season = m.get("season") or {}
    if not isinstance(season, dict):
        return ""
    league = season.get("league") or {}
    if not isinstance(league, dict):
        return ""
    return league.get("name") or ""


def _match_date_iso(m: dict[str, Any]) -> str:
    return m.get("date") or ""


def _sort_matches(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Группировка по стране → лиге → времени.

    Страны сортируются алфавитно, внутри страны — по лиге и времени матча.
    """
    return sorted(
        games,
        key=lambda m: (
            (_match_country(m) or "Я").casefold(),
            _match_league(m).casefold(),
            _match_date_iso(m),
        ),
    )


def _today_str(tz_offset: int) -> str:
    return (datetime.now(tz=UTC) + timedelta(hours=tz_offset)).strftime("%Y-%m-%d")


def _tomorrow_str(tz_offset: int) -> str:
    return (datetime.now(tz=UTC) + timedelta(hours=tz_offset + 24)).strftime("%Y-%m-%d")


def _render_match(idx: int, m: dict[str, Any]) -> str:
    home = (m.get("homeTeam") or {}).get("name") or "?"
    away = (m.get("awayTeam") or {}).get("name") or "?"
    season = m.get("season") or {}
    league_name = "?"
    country_name: str | None = None
    if isinstance(season, dict):
        league_obj = season.get("league") or {}
        if isinstance(league_obj, dict):
            league_name = league_obj.get("name") or "?"
            c = league_obj.get("country")
            if isinstance(c, dict):
                country_name = c.get("name")
    flag = country_flag(country_name)
    iso = m.get("date") or ""
    short = ""
    if iso:
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            short = dt.strftime("%d.%m %H:%M")
        except ValueError:
            short = iso[:16]
    return f"{idx:>2}. {flag} *{home}* — *{away}*\n     {league_name} · {short}"


def _matches_keyboard(
    page: Page, prefix: str, extra: str, *, kind: str,
) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for m in page.slice():
        if not isinstance(m, dict):
            continue
        gid = m.get("id") or m.get("gameId")
        if gid is None:
            continue
        home = (m.get("homeTeam") or {}).get("name") or "?"
        away = (m.get("awayTeam") or {}).get("name") or "?"
        flag = country_flag(_match_country(m))
        builder.button(
            text=f"{flag} {home} — {away}"[:64],
            callback_data=f"predict:{gid}",
        )
    builder.adjust(1)
    # Кнопка «перейти к странице» — открывает текстовый ввод.
    builder.row(
        *InlineKeyboardBuilder().button(
            text=f"🔢 Перейти к странице (из {page.total_pages})",
            callback_data=f"matches:goto:{kind}",
        ).as_markup().inline_keyboard[0]
    )
    pag = pagination_keyboard(prefix, page, extra_payload=extra).inline_keyboard
    for row in pag:
        builder.row(*row)
    # Навигация
    builder.row(
        InlineKeyboardButton(text=Buttons.BACK, callback_data="nav:back"),
        InlineKeyboardButton(text=Buttons.MAIN_MENU, callback_data="menu:home"),
    )
    return builder


async def _fetch_matches(
    bot, *, kind: str, settings: Settings
) -> tuple[list[dict[str, Any]], str]:
    sstats: SStatsClient = services.sstats
    if kind == "today":
        return (
            await sstats.list_games(
                date=_today_str(settings.timezone_offset),
                limit=LIST_LIMIT,
                time_zone=settings.timezone_offset,
            ),
            TODAY_HEADER.format(date=_today_str(settings.timezone_offset)),
        )
    if kind == "tomorrow":
        return (
            await sstats.list_games(
                date=_tomorrow_str(settings.timezone_offset),
                limit=LIST_LIMIT,
                time_zone=settings.timezone_offset,
            ),
            TOMORROW_HEADER.format(date=_tomorrow_str(settings.timezone_offset)),
        )
    # Лайв: тянем `Live=true`, но *обязательно* фильтруем на нашей стороне
    # по статусам активных стадий (3=1H, 4=HT, 5=2H, 6=ET, 7=PEN, 8/9=в игре).
    # SStats иногда отдаёт по этому флагу свежезавершённые матчи — их быть
    # не должно. Если ничего активного нет — просто отдаём пустой список,
    # без фоллбэка на «сегодня» (иначе пойдут не-лайв матчи).
    raw = await sstats.list_games(
        live=True, limit=LIST_LIMIT, time_zone=settings.timezone_offset,
    )
    active_codes = {3, 4, 5, 6, 7, 8, 9}
    active_names = {
        "first half",
        "halftime",
        "half time",
        "second half",
        "extra time",
        "penalty shootout",
        "in progress",
        "live",
    }

    def _is_active(g: dict[str, Any]) -> bool:
        st = g.get("status") if isinstance(g, dict) else None
        if isinstance(st, int):
            return st in active_codes
        if isinstance(st, dict):
            code = st.get("code") or st.get("id")
            if isinstance(code, int):
                return code in active_codes
            name = st.get("name") or st.get("text")
            return isinstance(name, str) and name.strip().lower() in active_names
        sn = g.get("statusName") if isinstance(g, dict) else None
        if isinstance(sn, str) and sn.strip().lower() in active_names:
            return True
        # Минута матча > 0 — тоже признак, что игра идёт.
        for k in ("elapsed", "minute"):
            v = g.get(k) if isinstance(g, dict) else None
            if isinstance(v, int) and 1 <= v <= 130:
                return True
        return False

    games_live = [
        g for g in (raw or []) if isinstance(g, dict) and _is_active(g)
    ]
    # Фоллбэк: если по `Live=true` SStats отдал пусто (бывает при сбое флага),
    # тянем расписание на сегодня и сами вычисляем активные сейчас матчи —
    # по статусу или по минуте `> 0`.
    if not games_live:
        today_raw = await sstats.list_games(
            date=_today_str(settings.timezone_offset),
            limit=LIST_LIMIT,
            time_zone=settings.timezone_offset,
        )
        from datetime import UTC as _UTC
        from datetime import datetime as _dt

        now_dt = _dt.now(tz=_UTC)

        def _looks_live(g: dict[str, Any]) -> bool:
            if _is_active(g):
                return True
            iso = g.get("date") or g.get("startDate")
            if not isinstance(iso, str):
                return False
            try:
                when = _dt.fromisoformat(iso.replace("Z", "+00:00"))
                if when.tzinfo is None:
                    when = when.replace(tzinfo=_UTC)
            except ValueError:
                return False
            mins = (now_dt - when).total_seconds() / 60
            return 0 <= mins <= 120

        games_live = [
            g for g in (today_raw or [])
            if isinstance(g, dict) and _looks_live(g)
        ]
    return games_live, LIVE_HEADER


async def _render_matches_page(
    target,  # Message | CallbackQuery
    *,
    kind: str,
    page_index: int,
) -> None:
    bot = target.message.bot if isinstance(target, CallbackQuery) else target.bot
    settings: Settings = services.settings
    games, hdr = await _fetch_matches(bot, kind=kind, settings=settings)
    games = [g for g in (games or []) if isinstance(g, dict)]
    games = _sort_matches(games)
    icon = ICON_FIRE if kind == "live" else ICON_CALENDAR if kind == "today" else ICON_BALL
    # `hdr` уже начинается со смайла из текстов (📅 / 🔥), повторно
    # добавлять иконку через `header()` нельзя — иначе будет дублирование.
    hdr_clean = hdr.replace("*", "").strip()
    for emoji in (ICON_CALENDAR, ICON_FIRE, ICON_BALL, "📅", "🔥", "⚽"):
        if hdr_clean.startswith(emoji):
            hdr_clean = hdr_clean[len(emoji):].strip()
            break
    if not games:
        msg = f"{header(hdr_clean, icon=icon)}\n{NO_MATCHES}"
        if isinstance(target, CallbackQuery):
            if target.message:
                try:
                    await target.message.edit_text(msg, parse_mode="Markdown")
                except Exception:
                    await target.message.answer(msg, parse_mode="Markdown")
            await target.answer()
        else:
            await target.answer(msg, parse_mode="Markdown")
        return
    # Clamp на случай, если index пришёл из старого callback / FSM мимо
    # валидатора. parse_page_input уже отсекает мусор от пользователя,
    # это защита от внутренних ошибок.
    _max_idx = max(0, (len(games) - 1) // PAGE_SIZE)
    page_index = max(0, min(page_index, _max_idx))
    page: Page = Page(items=games, page_index=page_index, page_size=PAGE_SIZE)
    text = format_paginated(
        page,
        render_item=_render_match,
        header_text=header(hdr_clean, icon=icon),
    )
    builder = _matches_keyboard(
        page, prefix=f"matches_page_{kind}", extra="", kind=kind,
    )
    if isinstance(target, CallbackQuery):
        if target.message:
            try:
                await target.message.edit_text(
                    text, parse_mode="Markdown", reply_markup=builder.as_markup()
                )
            except Exception:
                await target.message.answer(
                    text, parse_mode="Markdown", reply_markup=builder.as_markup()
                )
        await target.answer()
    else:
        await target.answer(
            text, parse_mode="Markdown", reply_markup=builder.as_markup()
        )
# [removed: command handler — UI is buttons-only]
async def matches_today(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    arg = parts[1].strip().lower() if len(parts) > 1 else ""
    if arg in {"tomorrow", "завтра"}:
        await _render_matches_page(message, kind="tomorrow", page_index=0)
    elif arg in {"live", "лайв", "сейчас"}:
        await _render_matches_page(message, kind="live", page_index=0)
    else:
        await _render_matches_page(message, kind="today", page_index=0)
# [removed: command handler — UI is buttons-only]
async def matches_tomorrow(message: Message) -> None:
    await _render_matches_page(message, kind="tomorrow", page_index=0)
# [removed: command handler — UI is buttons-only]
async def matches_live(message: Message) -> None:
    await _render_matches_page(message, kind="live", page_index=0)


@router.callback_query(F.data == "menu:today")
async def cb_today(callback: CallbackQuery, state: FSMContext) -> None:
    await nav_push(state, "menu:home")
    # prediction_origin кодирует и страницу — чтобы «Назад» с карточки
    # прогноза вернул не на 1-ю, а на ту же страницу списка.
    await state.update_data(prediction_origin="matches:today:0")
    await _render_matches_page(callback, kind="today", page_index=0)


@router.callback_query(F.data == "menu:tomorrow")
async def cb_tomorrow(callback: CallbackQuery, state: FSMContext) -> None:
    await nav_push(state, "menu:home")
    await state.update_data(prediction_origin="matches:tomorrow:0")
    await _render_matches_page(callback, kind="tomorrow", page_index=0)


@router.callback_query(F.data == "menu:live")
async def cb_live(callback: CallbackQuery, state: FSMContext) -> None:
    await nav_push(state, "menu:home")
    await state.update_data(prediction_origin="matches:live:0")
    await _render_matches_page(callback, kind="live", page_index=0)


@router.callback_query(F.data.startswith("matches_page_today:"))
async def cb_page_today(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.data:
        await callback.answer()
        return
    idx, _ = parse_pagination_callback(callback.data, "matches_page_today")
    await state.update_data(prediction_origin=f"matches:today:{idx}")
    await _render_matches_page(callback, kind="today", page_index=idx)


@router.callback_query(F.data.startswith("matches_page_tomorrow:"))
async def cb_page_tomorrow(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.data:
        await callback.answer()
        return
    idx, _ = parse_pagination_callback(callback.data, "matches_page_tomorrow")
    await state.update_data(prediction_origin=f"matches:tomorrow:{idx}")
    await _render_matches_page(callback, kind="tomorrow", page_index=idx)


@router.callback_query(F.data.startswith("matches_page_live:"))
async def cb_page_live(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.data:
        await callback.answer()
        return
    idx, _ = parse_pagination_callback(callback.data, "matches_page_live")
    await state.update_data(prediction_origin=f"matches:live:{idx}")
    await _render_matches_page(callback, kind="live", page_index=idx)


_KIND_TO_STATE = {
    "today": MatchesPageStates.waiting_for_page_today,
    "tomorrow": MatchesPageStates.waiting_for_page_tomorrow,
    "live": MatchesPageStates.waiting_for_page_live,
}


@router.callback_query(F.data.startswith("matches:goto:"))
async def cb_matches_goto(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.data or not callback.message:
        await callback.answer()
        return
    kind = callback.data.rsplit(":", 1)[1]
    st = _KIND_TO_STATE.get(kind)
    if st is None:
        await callback.answer()
        return

    # Считаем границы один раз и сохраняем в FSM, чтобы при ручном вводе
    # показать пользователю реальный максимум и не дать выйти за него.
    settings: Settings = services.settings
    games, _hdr = await _fetch_matches(callback.bot, kind=kind, settings=settings)
    games = [g for g in (games or []) if isinstance(g, dict)]
    total_pages = max(1, (len(games) + PAGE_SIZE - 1) // PAGE_SIZE)
    await state.set_state(st)
    await state.update_data(total_pages=total_pages, kind=kind)

    await callback.message.answer(
        f"✏️ Отправь *номер страницы* числом — от *1* до *{total_pages}* "
        f"(например `1`).",
        parse_mode="Markdown",
    )
    await callback.answer()


async def _handle_matches_page_input(
    message: Message, state: FSMContext, kind: str,
) -> None:
    data = await state.get_data()
    total_pages = int(data.get("total_pages") or 1)
    idx, error = parse_page_input(message.text or "", total_pages)
    if error:
        await message.answer(error, parse_mode="Markdown")
        return
    if idx is None:  # safety net
        await message.answer(
            f"Введи номер от 1 до *{total_pages}*.", parse_mode="Markdown",
        )
        return
    await state.clear()
    await _render_matches_page(message, kind=kind, page_index=idx)


@router.message(MatchesPageStates.waiting_for_page_today)
async def on_page_today_input(message: Message, state: FSMContext) -> None:
    await _handle_matches_page_input(message, state, "today")


@router.message(MatchesPageStates.waiting_for_page_tomorrow)
async def on_page_tomorrow_input(message: Message, state: FSMContext) -> None:
    await _handle_matches_page_input(message, state, "tomorrow")


@router.message(MatchesPageStates.waiting_for_page_live)
async def on_page_live_input(message: Message, state: FSMContext) -> None:
    await _handle_matches_page_input(message, state, "live")
