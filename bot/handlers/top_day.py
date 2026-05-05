"""Топ дня: топ-10 самых ВАЛУЙНЫХ ставок дня по всем матчам.

Что показываем: лучшие value-беты дня, отсортированные по `value_percent`
убыванию. В выборку могут попасть прогнозы с вероятностью 25–35% — если кф
букмекера достаточно высок относительно нашей оценки, ставка валуйна.
Не путать со списком «самых вероятных исходов».

Источники данных:
1. `TopMatchesPrecompute._cache` — ансамбль уже посчитал прогнозы для
   ~50 значимых матчей следующих 24 ч (обновляется каждые 30 мин).
2. Если кэш пуст — синхронно запускаем `precompute_once()`.

Фильтр по дате: оставляем только матчи, чья ISO-дата в локальном
часовом поясе (МСК = UTC+timezone_offset из settings) совпадает с
сегодняшним днём.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from loguru import logger

from bot.context import services
from bot.keyboards import main_menu_keyboard
from bot.navigation import nav_push
from bot.texts import Buttons
from core.markets import label_for
from services.countries import country_flag

router = Router(name="top_day")


def _today_local(tz_offset: int) -> str:
    return (datetime.now(tz=UTC) + timedelta(hours=tz_offset)).strftime(
        "%Y-%m-%d"
    )


def _date_in_local(date_iso: str, tz_offset: int) -> str | None:
    """Возвращает 'YYYY-MM-DD' матча в локальном часовом поясе или None."""
    if not date_iso:
        return None
    try:
        dt = datetime.fromisoformat(date_iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    local = dt.astimezone(UTC) + timedelta(hours=tz_offset)
    return local.strftime("%Y-%m-%d")


def _format_pick(idx: int, vb: Any, result: Any) -> str:
    home = getattr(result, "home_name", "")
    away = getattr(result, "away_name", "")
    league = getattr(result, "league_name", "") or ""
    country_raw = getattr(result, "country_raw", None)
    flag = country_flag(country_raw) or "🏳"
    market_key = getattr(vb, "market_key", "") or ""
    label = label_for(market_key, home=home, away=away)
    odds = float(getattr(vb, "actual_odds", 0.0))
    # Показываем только флаг, команды, лигу, исход и котировку —
    # без «модель X%» и без «честного КФ», чтобы лента была чище.
    return (
        f"{idx}. {flag} *{home}* — *{away}*\n"
        f"     {league}\n"
        f"     {label}  —  котировка *{odds:.2f}*"
    )


def _top_day_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=Buttons.BACK, callback_data="nav:back"),
            InlineKeyboardButton(text=Buttons.MAIN_MENU, callback_data="menu:home"),
        ],
    ])


@router.callback_query(F.data == "menu:top_day")
async def top_day_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return
    settings = services.settings
    tz_offset = getattr(settings, "timezone_offset", 3)
    today = _today_local(tz_offset)

    precompute = services.topmatches_precompute
    if precompute is None:
        await callback.message.edit_text(
            "🚀 *Топ дня*\n\nПодсистема предрасчёта недоступна.",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(),
        )
        return

    # Если кэш пуст — пробуем посчитать первый набор сразу.
    if not precompute._cache:
        import asyncio

        from bot.progress import (
            animate_message,
            cancel_keyboard,
            clear_cancel,
            minimal_loader,
            register_cancel,
        )

        chat_id = callback.message.chat.id
        message_id = callback.message.message_id
        try:
            await callback.message.edit_text(
                minimal_loader(
                    "Топ дня — готовлю прогнозы по матчам сегодня",
                    elapsed_seconds=0.0,
                ),
                parse_mode="Markdown",
                reply_markup=cancel_keyboard(),
            )
        except Exception:
            pass
        animator = asyncio.create_task(
            animate_message(
                callback.message, "Топ дня — готовлю прогнозы по матчам сегодня",
                hint="_это займёт до минуты_",
            )
        )
        work_task = asyncio.create_task(precompute.precompute_once())
        # Регистрируем обе task'и, чтобы cancel:op отменил и расчёт,
        # и анимацию — иначе animator перезапишет экран главного меню.
        register_cancel(chat_id, message_id, work_task, animator)
        try:
            await work_task
        except asyncio.CancelledError:
            # Отмена кнопкой — пользователь уже получил главное меню.
            animator.cancel()
            try:
                await animator
            except (asyncio.CancelledError, Exception):
                pass
            return
        except Exception as exc:
            logger.warning("top_day: precompute failed: {}", exc)
        finally:
            clear_cancel(chat_id, message_id)
            animator.cancel()
            try:
                await animator
            except (asyncio.CancelledError, Exception):
                pass

    # Собираем все value_bets со всех матчей.
    all_bets: list[tuple[Any, Any]] = []
    for entry in precompute._cache.values():
        result = entry.result
        # Фильтр по дате: только матчи, которые сегодня (МСК).
        date_local = _date_in_local(getattr(result, "date_iso", ""), tz_offset)
        if date_local and date_local != today:
            continue
        for vb in getattr(result, "value_bets", None) or []:
            if not getattr(vb, "is_value", False):
                continue
            all_bets.append((vb, result))

    # Сортировка по value_percent убыванию.
    all_bets.sort(
        key=lambda x: float(getattr(x[0], "value_percent", 0.0)),
        reverse=True,
    )

    # По одному прогнозу на матч.
    seen: set[int] = set()
    parts: list[str] = ["🚀 *Топ дня*", ""]
    rendered = 0
    for vb, result in all_bets:
        gid = int(getattr(result, "game_id", 0) or 0)
        if gid in seen:
            continue
        seen.add(gid)
        parts.append(_format_pick(rendered + 1, vb, result))
        rendered += 1
        if rendered >= 10:
            break

    if rendered == 0:
        parts.append(
            "Сегодня пока нет валуй-беты в кэше прогнозов.\n"
            "Прогнозы пересчитываются каждые 30 мин — попробуй позже."
        )
    else:
        parts.append("")
        parts.append(
            "_Сортировка — по валуйности._\n"
            "_Кэш обновляется каждые 30 мин._"
        )

    await nav_push(state, "menu:home")
    text = "\n".join(parts)
    kb = _top_day_keyboard()
    try:
        await callback.message.edit_text(
            text, parse_mode="Markdown", reply_markup=kb
        )
    except Exception:
        await callback.message.answer(
            text, parse_mode="Markdown", reply_markup=kb
        )
