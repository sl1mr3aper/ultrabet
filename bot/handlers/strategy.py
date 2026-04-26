"""Команды для выбора стратегий ставок и фильтрации топ-значений."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards import main_menu_keyboard
from bot.styles import ICON_TARGET, header
from services.strategy import STRATEGIES, StrategyKind, describe_strategy

router = Router(name="strategy")


def _strategies_keyboard() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for kind in StrategyKind:
        builder.button(
            text=_label(kind),
            callback_data=f"strategy:{kind.value}",
        )
    builder.adjust(1)
    builder.row()
    return builder


def _label(kind: StrategyKind) -> str:
    return {
        StrategyKind.CONSERVATIVE: "🛡 Консервативная",
        StrategyKind.BALANCED: "⚖️ Сбалансированная",
        StrategyKind.AGGRESSIVE: "🔥 Агрессивная",
        StrategyKind.UNDERDOG: "🎯 На аутсайдеров",
    }[kind]
# [removed: command handler — UI is buttons-only]
async def show_strategies(message: Message) -> None:
    lines = [header("Стратегии ставок", icon=ICON_TARGET), ""]
    for k in StrategyKind:
        lines.append(f"*{_label(k)}*")
        flt = STRATEGIES[k]
        lines.append(
            f"   prob: {flt.min_probability:.0%}–{flt.max_probability:.0%}, "
            f"odds: {flt.min_odds:.2f}–{flt.max_odds:.2f}, "
            f"EV ≥ {flt.min_value_pct:.0f}%"
        )
        lines.append(f"   {describe_strategy(k)}")
        lines.append("")
    kb = _strategies_keyboard().as_markup()
    await message.answer(
        "\n".join(lines), parse_mode="Markdown", reply_markup=kb
    )


@router.callback_query(F.data.startswith("strategy:"))
async def cb_strategy(callback: CallbackQuery) -> None:
    if not callback.data:
        await callback.answer()
        return
    kind_value = callback.data.split(":", 1)[1]
    try:
        kind = StrategyKind(kind_value)
    except ValueError:
        await callback.answer("Неизвестная стратегия")
        return
    text = (
        f"{header(_label(kind), icon=ICON_TARGET)}\n\n"
        f"{describe_strategy(kind)}\n\n"
        f"Стратегия будет применена при следующих /dailypicks.\n"
        f"Параметры:\n"
        f"  • prob: {STRATEGIES[kind].min_probability:.0%} — "
        f"{STRATEGIES[kind].max_probability:.0%}\n"
        f"  • odds: {STRATEGIES[kind].min_odds:.2f} — "
        f"{STRATEGIES[kind].max_odds:.2f}\n"
        f"  • EV ≥ {STRATEGIES[kind].min_value_pct:.0f}%"
    )
    if callback.message:
        try:
            await callback.message.edit_text(
                text, parse_mode="Markdown", reply_markup=main_menu_keyboard()
            )
        except Exception:
            await callback.message.answer(
                text, parse_mode="Markdown", reply_markup=main_menu_keyboard()
            )
    await callback.answer("Выбрано")
