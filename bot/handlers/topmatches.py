"""Топ матчей дня — сортировка по EV при разумной вероятности.

Показываем 20 лучших прогнозов из предрасчёта. Сортировка — по
композитному score из `core.value_engine` (EV × √p), фильтр —
verdict = «брать» (если таких нет, оставляем «осторожно» как
fallback). Пагинация 10 на страницу.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.context import services
from bot.navigation import nav_push
from bot.texts import Buttons
from config import Settings
from core.markets import label_for
from core.value_engine import select_best_pick
from services.countries import country_flag

router = Router(name="topmatches")
PAGE_SIZE = 10
TOP_LIMIT = 20

_VERDICT_ICON = {
    "брать": "🟢",
    "осторожно": "🟡",
    "не брать": "🔴",
}


def _render_match(idx: int, entry: dict) -> str:
    """Форматирование одного матча в списке."""
    flag = country_flag(entry.get("country"))
    home = entry.get("home", "?")
    away = entry.get("away", "?")
    league = entry.get("league", "—")
    prob = entry.get("probability", 0.0) * 100.0
    fair = entry.get("fair_odds") or 0.0
    ev = entry.get("ev_pct", 0.0)
    label = entry.get("market_label", "")
    verdict = entry.get("verdict", "не брать")
    icon = _VERDICT_ICON.get(verdict, "⚪")
    return (
        f"{idx}. {flag} *{home}* — *{away}*\n"
        f"     {league}\n"
        f"     {label} · кф *{fair:.2f}*\n"
        f"     {icon} *{verdict}* · модель *{prob:.1f}%* · "
        f"EV *{ev:+.1f}%*"
    )


def _build_keyboard(
    items: list[dict], page: int, total_pages: int,
) -> InlineKeyboardMarkup:
    """Клавиатура: кнопки матчей + пагинация + навигация."""
    builder = InlineKeyboardBuilder()
    for entry in items:
        gid = entry.get("game_id", 0)
        home = entry.get("home", "?")
        away = entry.get("away", "?")
        builder.button(
            text=f"{home} — {away}"[:64],
            callback_data=f"predict:{gid}",
        )
    builder.adjust(1)
    # Пагинация
    nav_row: list[InlineKeyboardButton] = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(
            text="← Назад", callback_data=f"topmatches_page:{page - 1}",
        ))
    nav_row.append(InlineKeyboardButton(
        text=f"Стр. {page + 1}/{total_pages}", callback_data="noop",
    ))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(
            text="Вперёд →", callback_data=f"topmatches_page:{page + 1}",
        ))
    if nav_row:
        builder.row(*nav_row)
    # Навигация
    builder.row(
        InlineKeyboardButton(text=Buttons.BACK, callback_data="nav:back"),
        InlineKeyboardButton(text=Buttons.MAIN_MENU, callback_data="menu:home"),
    )
    return builder.as_markup()


def _collect_top_bets() -> list[dict]:
    """Собрать топ прогнозов из кэша предрасчёта, сортировка по EV."""
    precompute = services.topmatches_precompute
    if precompute is None:
        return []

    settings = services.settings
    tz_offset = getattr(settings, "timezone_offset", 3)
    today = (datetime.now(tz=UTC) + timedelta(hours=tz_offset)).strftime("%Y-%m-%d")

    all_entries: list[dict] = []
    seen_games: set[int] = set()

    for entry in precompute._cache.values():
        result = entry.result
        gid = int(getattr(result, "game_id", 0) or 0)
        if gid in seen_games:
            continue

        # Фильтр по дате
        date_iso = getattr(result, "date_iso", "")
        if date_iso:
            try:
                dt = datetime.fromisoformat(date_iso.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                local = dt.astimezone(UTC) + timedelta(hours=tz_offset)
                if local.strftime("%Y-%m-%d") != today:
                    continue
            except ValueError:
                pass

        # Новая логика: для каждого матча ищем «лучший пик» через
        # `core.value_engine.select_best_pick`, который:
        #   1) считает EV/Kelly/composite/verdict,
        #   2) фильтрует только пики с verdict="брать",
        #   3) при отсутствии «брать» fallback'ится на «осторожно».
        # На уровне ленты:
        #   - в выборку попадают только матчи, где есть пик «брать»,
        #   - сортировка — по composite score (EV × √p).
        probs = getattr(result, "probabilities", None) or {}
        if not probs:
            continue
        home = getattr(result, "home_name", "?")
        away = getattr(result, "away_name", "?")
        league_name = getattr(result, "league_name", "—")
        country_raw = getattr(result, "country_raw", None)
        odds_map = getattr(result, "odds_map", None) or {}

        pick = select_best_pick(
            probs, odds_map, accept_only=True, fallback_to_caution=False,
        )
        if pick is None:
            continue

        all_entries.append({
            "game_id": gid,
            "home": home,
            "away": away,
            "league": league_name,
            "country": country_raw,
            "probability": pick.probability,
            "odds": pick.odds or 0.0,
            "fair_odds": pick.fair_odds,
            "ev_pct": pick.ev_pct,
            "verdict": pick.verdict,
            "composite": pick.composite,
            "market_label": label_for(pick.market_key, home=home, away=away),
        })
        seen_games.add(gid)

    # Сортировка по composite score (+EV И вероятный) — это и есть
    # то, что просит пользователь: «не самый высокий процент, а самый
    # EV, при этом вероятная ставка».
    all_entries.sort(
        key=lambda e: (e.get("composite", 0.0), e.get("ev_pct", 0.0)),
        reverse=True,
    )
    return all_entries[:TOP_LIMIT]


async def _render_top(
    target: CallbackQuery | Message,
    *,
    page_index: int,
) -> None:
    precompute = services.topmatches_precompute
    if precompute is None or not precompute._cache:
        if precompute is not None:
            try:
                await precompute.precompute_once()
            except Exception:
                pass

    top = _collect_top_bets()

    total_pages = max(1, (len(top) + PAGE_SIZE - 1) // PAGE_SIZE)
    page_index = max(0, min(page_index, total_pages - 1))
    start = page_index * PAGE_SIZE
    page_items = top[start:start + PAGE_SIZE]

    settings: Settings = services.settings
    tz_offset = getattr(settings, "timezone_offset", 3)
    today = (datetime.now(tz=UTC) + timedelta(hours=tz_offset)).strftime("%Y-%m-%d")

    parts: list[str] = [f"⭐ *Топ матчей дня ({today})*", ""]
    if not page_items:
        parts.append(
            "Сегодня нет матчей с вердиктом «брать».\n"
            "_Кэш обновляется каждые 30 мин — попробуй позже._"
        )
    else:
        for i, entry in enumerate(page_items, start=start + 1):
            parts.append(_render_match(i, entry))
        parts.append("")
        parts.append(
            f"_Стр. {page_index + 1}/{total_pages} · "
            f"Топ-{len(top)} по EV при разумной вероятности_"
        )

    text = "\n".join(parts)
    kb = _build_keyboard(page_items, page_index, total_pages)

    if isinstance(target, CallbackQuery):
        if target.message:
            try:
                await target.message.edit_text(
                    text, parse_mode="Markdown", reply_markup=kb,
                )
            except Exception:
                await target.message.answer(
                    text, parse_mode="Markdown", reply_markup=kb,
                )
        await target.answer()
    else:
        await target.answer(text, parse_mode="Markdown", reply_markup=kb)


@router.callback_query(F.data == "menu:top_matches")
async def top_matches_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await nav_push(state, "menu:home")
    # prediction_origin кодирует страницу — для возврата с карточки прогноза.
    await state.update_data(prediction_origin="top_matches:0")
    await _render_top(callback, page_index=0)


@router.callback_query(F.data.startswith("topmatches_page:"))
async def cb_topmatches_page(
    callback: CallbackQuery, state: FSMContext,
) -> None:
    if not callback.data:
        await callback.answer()
        return
    try:
        idx = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        idx = 0
    await state.update_data(prediction_origin=f"top_matches:{idx}")
    await _render_top(callback, page_index=idx)
