"""Daily picks — топ EV-ставок дня (с пагинацией)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from api.sstats_client import SStatsClient
from bot.context import services
from bot.pagination import (
    Page,
    format_paginated,
    pagination_keyboard,
    parse_pagination_callback,
)
from bot.styles import ICON_TROPHY, header
from config import Settings
from core.markets import label_for
from core.value_calculator import ValueCalculator
from services.daily_picks import DailyPick, DailyPicksGenerator

router = Router(name="dailypicks")
PAGE_SIZE = 5
TOP_LIMIT = 30


def _emoji_for(value_pct: float) -> str:
    if value_pct >= 15:
        return "💎"
    if value_pct >= 8:
        return "🟢"
    return "✅"


def _render_pick(idx: int, p: DailyPick) -> str:
    market_label = label_for(
        p.bet.market_key, home=p.result.home_name, away=p.result.away_name
    )
    return (
        f"{idx:>2}. {_emoji_for(p.bet.value_percent)} "
        f"*{p.result.home_name} — {p.result.away_name}*\n"
        f"     {market_label}\n"
        f"     модель {p.bet.probability * 100:.1f}% · "
        f"кф *{p.bet.fair_odds:.2f}* · "
        f"EV *+{p.bet.value_percent:.2f}%*"
    )


def _build_keyboard(page: Page) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for p in page.slice():
        if not isinstance(p, DailyPick):
            continue
        gid = p.result.game_id
        if gid is None:
            continue
        builder.button(
            text=f"{p.result.home_name} — {p.result.away_name}"[:64],
            callback_data=f"predict:{gid}",
        )
    builder.adjust(1)
    pag = pagination_keyboard("dailypicks_page", page).inline_keyboard
    for row in pag:
        builder.row(*row)
    from aiogram.types import InlineKeyboardButton

    from bot.texts import Buttons
    builder.row(
        InlineKeyboardButton(text=Buttons.BACK, callback_data="nav:back"),
        InlineKeyboardButton(text=Buttons.MAIN_MENU, callback_data="menu:home"),
    )
    return builder


async def _render(
    target,
    *,
    page_index: int,
) -> None:
    bot = target.message.bot if isinstance(target, CallbackQuery) else target.bot
    settings: Settings = services.settings
    sstats: SStatsClient = services.sstats
    today = (
        datetime.now(tz=UTC) + timedelta(hours=settings.timezone_offset)
    ).strftime("%Y-%m-%d")
    import asyncio

    from bot.progress import (
        animate_message,
        cancel_keyboard,
        clear_cancel,
        minimal_loader,
        register_cancel,
    )

    # Показываем бегущий прогресс-бар на первой странице — генерация
    # прогнозов на день тянет SStats и может занять до минуты.
    loading_msg = None
    animator = None
    if page_index == 0:
        initial = minimal_loader(
            f"Сканирую матчи на {today}", elapsed_seconds=0,
        )
        if isinstance(target, CallbackQuery) and target.message:
            try:
                await target.message.edit_text(
                    initial, parse_mode="Markdown",
                    reply_markup=cancel_keyboard(),
                )
                loading_msg = target.message
            except Exception:
                loading_msg = await target.message.answer(
                    initial, parse_mode="Markdown",
                    reply_markup=cancel_keyboard(),
                )
        elif isinstance(target, Message):
            loading_msg = await target.answer(
                initial, parse_mode="Markdown",
                reply_markup=cancel_keyboard(),
            )
        if loading_msg is not None:
            animator = asyncio.create_task(
                animate_message(
                    loading_msg, f"Сканирую матчи на {today}",
                    hint="_это займёт около минуты_",
                )
            )

    generator = DailyPicksGenerator(
        sstats,
        value_calculator=ValueCalculator(
            min_odds=settings.min_value_odds,
            min_value_percent=settings.min_value_percent,
            min_probability=settings.min_value_probability,
        ),
    )
    work_task = asyncio.create_task(
        generator.for_date(
            today, top_n=TOP_LIMIT, time_zone=settings.timezone_offset,
        )
    )
    if loading_msg is not None:
        # Регистрируем обе task'и — расчёт и анимацию. Cancel отменит сразу
        # обе, чтобы animator не перезаписал главное меню.
        if animator is not None:
            register_cancel(
                loading_msg.chat.id, loading_msg.message_id,
                work_task, animator,
            )
        else:
            register_cancel(
                loading_msg.chat.id, loading_msg.message_id, work_task,
            )
    try:
        picks = await work_task
    except asyncio.CancelledError:
        if animator is not None:
            animator.cancel()
            try:
                await animator
            except (asyncio.CancelledError, Exception):
                pass
        return
    finally:
        if loading_msg is not None:
            clear_cancel(loading_msg.chat.id, loading_msg.message_id)
        if animator is not None:
            animator.cancel()
            try:
                await animator
            except (asyncio.CancelledError, Exception):
                pass
    title = header(f"Топ EV-ставок на {today}", icon=ICON_TROPHY)
    if not picks:
        msg = f"{title}\nСегодня EV вариантов не нашлось."
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
    sorted_picks = sorted(picks, key=lambda p: p.bet.value_percent, reverse=True)
    page: Page[DailyPick] = Page(
        items=sorted_picks, page_index=page_index, page_size=PAGE_SIZE
    )
    text = format_paginated(
        page,
        render_item=_render_pick,
        header_text=title,
        footer_text="Формат: модель / КФ (1/p) / EV",
    )
    builder = _build_keyboard(page)
    if isinstance(target, CallbackQuery):
        if target.message:
            try:
                await target.message.edit_text(
                    text,
                    parse_mode="Markdown",
                    reply_markup=builder.as_markup(),
                    disable_web_page_preview=True,
                )
            except Exception:
                await target.message.answer(
                    text,
                    parse_mode="Markdown",
                    reply_markup=builder.as_markup(),
                    disable_web_page_preview=True,
                )
        await target.answer()
    else:
        await target.answer(
            text,
            parse_mode="Markdown",
            reply_markup=builder.as_markup(),
            disable_web_page_preview=True,
        )
# [removed: command handler — UI is buttons-only]
async def dailypicks_cmd(message: Message) -> None:
    await _render(message, page_index=0)


@router.callback_query(F.data.startswith("dailypicks_page:"))
async def cb_dailypicks_page(callback: CallbackQuery) -> None:
    if not callback.data:
        await callback.answer()
        return
    idx, _ = parse_pagination_callback(callback.data, "dailypicks_page")
    await _render(callback, page_index=idx)
