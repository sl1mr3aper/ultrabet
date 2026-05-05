"""Личная история прогнозов пользователя — отдельный раздел.

Сценарий:
- `/history` или кнопка `menu:history` открывает раздел.
- Внутри — собственное подменю (без кнопок главного меню).
- Показываем только последние 10 прогнозов (без листания).
- Полная история / срез за месяц — отдельные xlsx-отчёты по кнопкам.
- Авто-обновление: фоновый `SelfLearner.evaluate_pending()` сверяет
  каждый прогноз с фактом матча, на странице сразу видно ✅ / ❌ / ⏳.
"""
from __future__ import annotations

from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from bot.context import services
from bot.keyboards import main_menu_keyboard
from bot.texts import MAIN_MENU
from db.models import User
from services.history_report import (
    HistoryRow,
    collect_history,
    filter_by_period,
    render_xlsx,
)

router = Router(name="history")


VIEW_LIMIT = 10


def _hit_badge(hit: bool | None) -> str:
    if hit is True:
        return "✅"
    if hit is False:
        return "❌"
    return "⏳"


def _md_safe(text: str) -> str:
    """Минимальное экранирование Markdown V1."""
    return (
        str(text)
        .replace("*", "")
        .replace("_", "")
        .replace("`", "")
        .replace("[", "(")
        .replace("]", ")")
    )


def _summary_line(rows: list[HistoryRow]) -> str:
    """Сводка по *всей* истории (а не только по выводу на экране)."""
    hits = sum(1 for r in rows if r.hit is True)
    misses = sum(1 for r in rows if r.hit is False)
    pending = sum(1 for r in rows if r.hit is None)
    resolved = hits + misses
    hit_rate = (hits / resolved * 100.0) if resolved else 0.0
    total_profit = sum(r.profit for r in rows)
    roi = (total_profit / resolved * 100.0) if resolved else 0.0
    sign = "+" if total_profit >= 0 else ""
    parts = [f"📊 *Итого*: ✅ {hits} · ❌ {misses} · ⏳ {pending}"]
    if resolved:
        parts.append(f"точность *{hit_rate:.1f}%*")
        parts.append(
            f"прибыль *{sign}{total_profit:.2f}* у.е.  ·  "
            f"доходность *{roi:.1f}%*"
        )
    return "  ·  ".join(parts)


def _history_keyboard() -> InlineKeyboardMarkup:
    """Подменю истории: отчёты + навигация."""
    from bot.texts import Buttons
    rows = [
        [
            InlineKeyboardButton(
                text="📅 Отчёт за месяц", callback_data="hist:report:month",
            ),
            InlineKeyboardButton(
                text="📈 Отчёт за всё время", callback_data="hist:report:all",
            ),
        ],
        [
            InlineKeyboardButton(text=Buttons.BACK, callback_data="nav:back"),
            InlineKeyboardButton(text=Buttons.MAIN_MENU, callback_data="menu:home"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _format_view(rows: list[HistoryRow]) -> str:
    if not rows:
        return (
            "📋 *История прогнозов*\n\n"
            "Пока пусто. Запроси свой первый прогноз через главное меню."
        )

    visible = rows[:VIEW_LIMIT]
    lines: list[str] = [
        "📋 *История прогнозов*",
        f"_(всего записей: {len(rows)}, без дублей · "
        f"показаны последние {len(visible)})_",
        "",
    ]
    for idx, r in enumerate(visible, start=1):
        date_h = r.created_at.strftime("%d.%m %H:%M")
        teams = f"{_md_safe(r.home)} — {_md_safe(r.away)}"
        # Счёт в скобках, если матч уже прошёл
        if r.home_score is not None and r.away_score is not None:
            teams += f" ({r.home_score}:{r.away_score})"
        head = f"{idx}. {_hit_badge(r.hit)} {date_h} · {teams}"
        meta_bits: list[str] = []
        if r.market_label:
            meta_bits.append(_md_safe(r.market_label))
        if r.fair_odd is not None:
            meta_bits.append(f"кф {r.fair_odd:.2f}")
        if r.hit is True:
            meta_bits.append(f"P/L *+{r.profit:.2f}*")
        elif r.hit is False:
            meta_bits.append(f"P/L *{r.profit:.2f}*")
        sub = "  ·  ".join(meta_bits)
        lines.append(head + (f"\n     {sub}" if sub else ""))
    lines.append("")
    lines.append(_summary_line(rows))
    lines.append("")
    lines.append(
        "_Полная история и аналитика — кнопками отчётов ниже (xlsx)._"
    )
    return "\n".join(lines)


async def _send_history_view(
    message: Message,
    session: AsyncSession,
    user: User,
    *,
    edit: bool,
) -> None:
    # Резолв pending прогнозов делает фоновый цикл (раз в 10 мин) —
    # синхронно во время открытия истории его НЕ зовём, иначе при
    # rate-limit источника пользователь ждёт минуту и видит «не
    # работает». Если хочется ускорить отображение свежих результатов,
    # можно дёрнуть резолвер фоном (без await), не блокируя UI.
    resolver = getattr(services, "predictions_resolver", None)
    if resolver is not None:
        import asyncio as _asyncio
        try:
            # Сохраняем ссылку на task и навешиваем «глушилку» исключений,
            # чтобы он не утёк и любой сбой источника не уронил event-loop.
            _bg = _asyncio.create_task(
                resolver.resolve_pending(max_games=50)
            )
            _bg.add_done_callback(lambda t: t.exception())
        except Exception:
            pass
    rows = await collect_history(session, user.id)
    text = _format_view(rows)
    kb = _history_keyboard()
    if edit:
        try:
            await message.edit_text(
                text, parse_mode="Markdown", reply_markup=kb,
            )
            return
        except Exception:
            pass
    await message.answer(text, parse_mode="Markdown", reply_markup=kb)


@router.message(Command("history"))
async def history_command(
    message: Message, user: User, session: AsyncSession,
) -> None:
    await _send_history_view(message, session, user, edit=False)


@router.callback_query(F.data == "menu:history")
async def history_callback(
    callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext,
) -> None:
    from bot.navigation import nav_push
    await nav_push(state, "menu:home")
    try:
        await callback.answer()
    except Exception:
        pass
    if callback.message:
        await _send_history_view(callback.message, session, user, edit=True)


@router.callback_query(F.data == "hist:exit")
async def history_exit(callback: CallbackQuery) -> None:
    try:
        await callback.answer()
    except Exception:
        pass
    if callback.message:
        try:
            await callback.message.edit_text(
                MAIN_MENU,
                reply_markup=main_menu_keyboard(),
                parse_mode="Markdown",
            )
        except Exception:
            await callback.message.answer(
                MAIN_MENU,
                reply_markup=main_menu_keyboard(),
                parse_mode="Markdown",
            )


@router.callback_query(F.data.startswith("hist:report:"))
async def history_report(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    if not callback.data:
        await callback.answer()
        return
    period = callback.data.rsplit(":", 1)[1]
    try:
        await callback.answer("Готовлю отчёт…")
    except Exception:
        pass

    rows = await collect_history(session, user.id)
    if not rows:
        if callback.message:
            await callback.message.answer(
                "Пока нечего выгружать — нет ни одного сохранённого прогноза.",
            )
        return

    if period == "month":
        rows = filter_by_period(rows, days=30)
        title = "Отчёт за месяц"
        fname = (
            f"history_month_{datetime.now(tz=UTC).strftime('%Y%m%d')}.xlsx"
        )
    else:
        title = "Отчёт за всё время"
        fname = (
            f"history_all_{datetime.now(tz=UTC).strftime('%Y%m%d')}.xlsx"
        )

    if not rows:
        if callback.message:
            await callback.message.answer(
                "За выбранный период прогнозов нет.",
            )
        return

    try:
        data = render_xlsx(rows, title=title)
    except Exception as exc:  # pragma: no cover — отдаём пользователю заглушку
        if callback.message:
            await callback.message.answer(
                f"Не удалось сформировать xlsx: {type(exc).__name__}.",
            )
        return

    if callback.message:
        await callback.message.answer_document(
            BufferedInputFile(data, filename=fname),
            caption=f"📊 {title}",
        )


__all__ = ["router"]
