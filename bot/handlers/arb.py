"""Команды /arb2 и /arb3 — поиск арбов по заданным коэфам."""

from __future__ import annotations

from aiogram import Router
from aiogram.types import Message

from bot.keyboards import main_menu_keyboard
from bot.styles import ICON_CHART, header
from services.arbitrage import ArbCheck, find_arb_2way, find_arb_3way, optimal_stakes

router = Router(name="arb")


def _render_arb(result: ArbCheck, total: float = 1000.0) -> str:
    lines = [header("Арбитраж", icon=ICON_CHART)]
    if not result.is_arb:
        lines.append("🚫 Арба нет.")
        lines.append(f"Сумма implied = {result.margin:.4f}")
        return "\n".join(lines)
    lines.append(f"✅ АРБ НАЙДЕН! Прибыль *{result.profit_percent:.2f}%*")
    lines.append(f"Сумма implied = {result.margin:.4f} (< 1)")
    lines.append("")
    lines.append(f"На банк *{total:.0f}*:")
    stakes = optimal_stakes(total, result)
    for key, val in stakes.items():
        book = result.bookmaker_per_outcome.get(key, "?")
        lines.append(f"  • {key} ({book}): *{val:.2f}*")
    return "\n".join(lines)
# [removed: command handler — UI is buttons-only]
async def arb2_cmd(message: Message) -> None:
    parts = (message.text or "").split()
    if len(parts) < 3:
        await message.answer(
            "Использование: `/arb2 <odd_a> <odd_b>` (2-way арб)",
            parse_mode="Markdown",
        )
        return
    try:
        a = float(parts[1])
        b = float(parts[2])
    except ValueError:
        await message.answer("Коэффициенты должны быть числами.")
        return
    result = find_arb_2way(a, b)
    await message.answer(
        _render_arb(result),
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )
# [removed: command handler — UI is buttons-only]
async def arb3_cmd(message: Message) -> None:
    parts = (message.text or "").split()
    if len(parts) < 4:
        await message.answer(
            "Использование: `/arb3 <home> <draw> <away>` (3-way 1x2 арб)",
            parse_mode="Markdown",
        )
        return
    try:
        h = float(parts[1])
        d = float(parts[2])
        a = float(parts[3])
    except ValueError:
        await message.answer("Все три коэф должны быть числами.")
        return
    result = find_arb_3way(h, d, a)
    await message.answer(
        _render_arb(result),
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )
