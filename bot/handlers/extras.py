"""Дополнительные информационные команды с единым стилем и пагинацией.

- /summary <game_id> — текстовое summary матча из SStats.
- /injuries <game_id> — список травмированных игроков (пагинация).
- /odds <game_id> — полный набор прематч-коэффициентов (пагинация + implied).
- /bookmakers — список букмекеров SStats (пагинация).
- /standings_for <league_id> — таблица лиги по id (пагинация).
"""

from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from api.sstats_client import SStatsClient
from bot.context import services
from bot.keyboards import main_menu_keyboard
from bot.pagination import (
    Page,
    format_paginated,
    pagination_keyboard,
    parse_pagination_callback,
)
from bot.styles import (
    ICON_BOOKMAKER,
    ICON_CHART,
    ICON_INJURY,
    ICON_MONEY,
    header,
    status_info,
    truncate,
)
from services.countries import country_flag, format_country
from services.league_service import LeagueService
from services.odds_parser import OddsParser

router = Router(name="extras")

# user_id → (kind, payload). Нужно для пагинации по кэшу: injuries/odds/standings_for
_EXTRAS_CACHE: dict[tuple[int, str], list[Any]] = {}


def _parse_id(message: Message) -> int | None:
    parts = (message.text or "").split()
    if len(parts) < 2:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def _pag_kb(prefix: str, page: Page) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    pag = pagination_keyboard(prefix, page).inline_keyboard
    for row in pag:
        builder.row(*row)
    return builder


# ── /summary ────────────────────────────────────────────────
# [removed: command handler — UI is buttons-only]
async def summary_cmd(message: Message) -> None:
    gid = _parse_id(message)
    if gid is None:
        await message.answer("Использование: /summary <game_id>")
        return
    sstats: SStatsClient = services.sstats
    text = await sstats.get_text_summary(gid)
    if not text:
        await message.answer(
            status_info("Сводка не найдена."), reply_markup=main_menu_keyboard()
        )
        return
    await message.answer(
        truncate(f"{header('Сводка матча', icon=ICON_CHART)}\n\n{text}"),
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )


# ── /injuries ───────────────────────────────────────────────
INJURIES_PAGE = 8


def _render_injury(idx: int, row: dict[str, Any]) -> str:
    player = row.get("player") or {}
    team = row.get("team") or {}
    reason = row.get("reason") or row.get("status") or "—"
    return f"{idx:>2}. *{player.get('name','?')}* ({team.get('name','?')}) — {reason}"


async def _send_injuries_page(
    target, *, user_id: int, game_id: int, page_index: int
) -> None:
    items = _EXTRAS_CACHE.get((user_id, f"injuries:{game_id}")) or []
    if not items:
        msg = status_info("Нет данных о травмах.")
        if isinstance(target, CallbackQuery):
            if target.message:
                await target.message.answer(msg, reply_markup=main_menu_keyboard())
            await target.answer()
        else:
            await target.answer(msg, reply_markup=main_menu_keyboard())
        return
    page: Page = Page(items=items, page_index=page_index, page_size=INJURIES_PAGE)
    text = format_paginated(
        page,
        render_item=_render_injury,
        header_text=header(f"Травмы и пропуски — матч #{game_id}", icon=ICON_INJURY),
    )
    kb = _pag_kb(f"inj_page:{game_id}", page).as_markup()
    if isinstance(target, CallbackQuery):
        if target.message:
            try:
                await target.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
            except Exception:
                await target.message.answer(text, parse_mode="Markdown", reply_markup=kb)
        await target.answer()
    else:
        await target.answer(text, parse_mode="Markdown", reply_markup=kb)
# [removed: command handler — UI is buttons-only]
async def injuries_cmd(message: Message) -> None:
    gid = _parse_id(message)
    if gid is None:
        await message.answer("Использование: /injuries <game_id>")
        return
    sstats: SStatsClient = services.sstats
    rows = await sstats.get_injuries(gid)
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    if message.from_user:
        _EXTRAS_CACHE[(message.from_user.id, f"injuries:{gid}")] = rows
        await _send_injuries_page(
            message, user_id=message.from_user.id, game_id=gid, page_index=0
        )


@router.callback_query(F.data.startswith("inj_page:"))
async def cb_inj_page(callback: CallbackQuery) -> None:
    if not callback.data or not callback.from_user:
        await callback.answer()
        return
    # prefix = inj_page:<game_id>
    parts = callback.data.split(":", 2)
    if len(parts) < 3:
        await callback.answer()
        return
    try:
        gid = int(parts[1])
    except ValueError:
        await callback.answer()
        return
    idx, _ = parse_pagination_callback(f"x:{parts[2]}", "x")
    await _send_injuries_page(
        callback, user_id=callback.from_user.id, game_id=gid, page_index=idx
    )


# ── /odds ───────────────────────────────────────────────────
ODDS_PAGE = 12


def _render_odds_row(
    idx: int, row: tuple[str, float, tuple[float, str] | None]
) -> str:
    market_key, val, best = row
    implied = 1.0 / val if val > 0 else 0.0
    bk = f" — _{best[1]}_" if best else ""
    return f"{idx:>2}. `{market_key}` → *{val:.2f}*{bk} · implied {implied * 100:.1f}%"


async def _send_odds_page(
    target, *, user_id: int, game_id: int, page_index: int
) -> None:
    items = _EXTRAS_CACHE.get((user_id, f"odds:{game_id}")) or []
    if not items:
        msg = status_info("Коэффициенты не найдены.")
        if isinstance(target, CallbackQuery):
            if target.message:
                await target.message.answer(msg, reply_markup=main_menu_keyboard())
            await target.answer()
        else:
            await target.answer(msg, reply_markup=main_menu_keyboard())
        return
    page: Page = Page(items=items, page_index=page_index, page_size=ODDS_PAGE)
    text = format_paginated(
        page,
        render_item=_render_odds_row,
        header_text=header(f"Прематч-коэфы — матч #{game_id}", icon=ICON_MONEY),
        footer_text="Отсортировано по убыванию коэф. Лучший букмекер — курсивом.",
    )
    kb = _pag_kb(f"odds_page:{game_id}", page).as_markup()
    if isinstance(target, CallbackQuery):
        if target.message:
            try:
                await target.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
            except Exception:
                await target.message.answer(text, parse_mode="Markdown", reply_markup=kb)
        await target.answer()
    else:
        await target.answer(text, parse_mode="Markdown", reply_markup=kb)
# [removed: command handler — UI is buttons-only]
async def odds_cmd(message: Message) -> None:
    gid = _parse_id(message)
    if gid is None:
        await message.answer("Использование: /odds <game_id>")
        return
    sstats: SStatsClient = services.sstats
    raw = await sstats.get_prematch_odds(gid)
    if not raw:
        await message.answer(
            status_info("Коэффициенты не найдены."), reply_markup=main_menu_keyboard()
        )
        return
    parser = OddsParser()
    parsed = parser.parse(raw)
    best = parser.best_per_market(raw)
    rows: list[tuple[str, float, tuple[float, str] | None]] = []
    for market_key, val in sorted(parsed.items(), key=lambda kv: kv[1], reverse=True):
        rows.append((market_key, val, best.get(market_key)))
    if message.from_user:
        _EXTRAS_CACHE[(message.from_user.id, f"odds:{gid}")] = rows
        await _send_odds_page(
            message, user_id=message.from_user.id, game_id=gid, page_index=0
        )


@router.callback_query(F.data.startswith("odds_page:"))
async def cb_odds_page(callback: CallbackQuery) -> None:
    if not callback.data or not callback.from_user:
        await callback.answer()
        return
    parts = callback.data.split(":", 2)
    if len(parts) < 3:
        await callback.answer()
        return
    try:
        gid = int(parts[1])
    except ValueError:
        await callback.answer()
        return
    idx, _ = parse_pagination_callback(f"x:{parts[2]}", "x")
    await _send_odds_page(
        callback, user_id=callback.from_user.id, game_id=gid, page_index=idx
    )


# ── /bookmakers ─────────────────────────────────────────────
BOOKMAKERS_PAGE = 15


def _render_bookmaker(idx: int, r: dict[str, Any]) -> str:
    name = r.get("name") or "?"
    bid = r.get("id")
    country = None
    if isinstance(r.get("country"), dict):
        country = r.get("country", {}).get("name")
    flag = country_flag(country)
    return f"{idx:>2}. {flag} *{name}* (id {bid})"


async def _send_bookmakers_page(
    target, *, user_id: int, page_index: int
) -> None:
    items = _EXTRAS_CACHE.get((user_id, "bookmakers:all")) or []
    if not items:
        msg = status_info("Список букмекеров недоступен.")
        if isinstance(target, CallbackQuery):
            if target.message:
                await target.message.answer(msg, reply_markup=main_menu_keyboard())
            await target.answer()
        else:
            await target.answer(msg, reply_markup=main_menu_keyboard())
        return
    page: Page = Page(items=items, page_index=page_index, page_size=BOOKMAKERS_PAGE)
    text = format_paginated(
        page,
        render_item=_render_bookmaker,
        header_text=header(f"Букмекеры SStats (всего {len(items)})", icon=ICON_BOOKMAKER),
    )
    kb = _pag_kb("book_page", page).as_markup()
    if isinstance(target, CallbackQuery):
        if target.message:
            try:
                await target.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
            except Exception:
                await target.message.answer(text, parse_mode="Markdown", reply_markup=kb)
        await target.answer()
    else:
        await target.answer(text, parse_mode="Markdown", reply_markup=kb)
# [removed: command handler — UI is buttons-only]
async def bookmakers_cmd(message: Message) -> None:
    sstats: SStatsClient = services.sstats
    rows = await sstats.list_bookmakers()
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    if message.from_user:
        _EXTRAS_CACHE[(message.from_user.id, "bookmakers:all")] = rows
        await _send_bookmakers_page(
            message, user_id=message.from_user.id, page_index=0
        )


@router.callback_query(F.data.startswith("book_page:"))
async def cb_book_page(callback: CallbackQuery) -> None:
    if not callback.data or not callback.from_user:
        await callback.answer()
        return
    idx, _ = parse_pagination_callback(callback.data, "book_page")
    await _send_bookmakers_page(
        callback, user_id=callback.from_user.id, page_index=idx
    )


# ── /standings_for ──────────────────────────────────────────
STANDINGS_PAGE = 10


def _render_standing_row(idx: int, row: dict[str, Any]) -> str:
    team = row.get("team") or {}
    name = team.get("name") if isinstance(team, dict) else "?"
    played = row.get("played") or row.get("matches") or 0
    points = row.get("points") or 0
    gd = row.get("goalsDiff") or row.get("gd") or 0
    return f"{idx:>2}. *{name}* — {points} очк. ({played} м, разница {gd:+d})"


async def _send_standings_page(
    target, *, user_id: int, league_id: int, page_index: int
) -> None:
    items = _EXTRAS_CACHE.get((user_id, f"standings:{league_id}")) or []
    if not items:
        msg = status_info("Турнирная таблица недоступна.")
        if isinstance(target, CallbackQuery):
            if target.message:
                await target.message.answer(msg, reply_markup=main_menu_keyboard())
            await target.answer()
        else:
            await target.answer(msg, reply_markup=main_menu_keyboard())
        return
    page: Page = Page(items=items, page_index=page_index, page_size=STANDINGS_PAGE)
    text = format_paginated(
        page,
        render_item=_render_standing_row,
        header_text=header(f"Турнирная таблица лиги #{league_id}", icon=ICON_CHART),
    )
    kb = _pag_kb(f"standings_page:{league_id}", page).as_markup()
    if isinstance(target, CallbackQuery):
        if target.message:
            try:
                await target.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
            except Exception:
                await target.message.answer(text, parse_mode="Markdown", reply_markup=kb)
        await target.answer()
    else:
        await target.answer(text, parse_mode="Markdown", reply_markup=kb)
# [removed: command handler — UI is buttons-only]
async def standings_for_cmd(message: Message) -> None:
    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer("Использование: /standings_for <league_id>")
        return
    try:
        league_id = int(parts[1])
    except ValueError:
        await message.answer("league_id должен быть числом.")
        return
    sstats: SStatsClient = services.sstats
    svc = LeagueService(sstats)
    table = await svc.standings(league_id)
    rows = []
    if table:
        raw = table.get("standings") or table.get("rows") or []
        rows = [r for r in raw if isinstance(r, dict)]
    if message.from_user:
        _EXTRAS_CACHE[(message.from_user.id, f"standings:{league_id}")] = rows
        await _send_standings_page(
            message, user_id=message.from_user.id, league_id=league_id, page_index=0
        )


@router.callback_query(F.data.startswith("standings_page:"))
async def cb_standings_page(callback: CallbackQuery) -> None:
    if not callback.data or not callback.from_user:
        await callback.answer()
        return
    parts = callback.data.split(":", 2)
    if len(parts) < 3:
        await callback.answer()
        return
    try:
        league_id = int(parts[1])
    except ValueError:
        await callback.answer()
        return
    idx, _ = parse_pagination_callback(f"x:{parts[2]}", "x")
    await _send_standings_page(
        callback,
        user_id=callback.from_user.id,
        league_id=league_id,
        page_index=idx,
    )


_ = format_country  # keep import, used elsewhere if needed
