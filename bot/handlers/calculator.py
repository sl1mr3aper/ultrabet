"""Калькулятор Kelly + flat-стратегия для пользователя."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.keyboards import main_menu_keyboard
from core.bankroll import break_even_probability, recommend_stake

router = Router(name="calculator")


@router.message(Command("calc", "calculator", "kelly"))
async def calc_command(message: Message) -> None:
    parts = (message.text or "").split()
    if len(parts) < 4:
        await message.answer(
            "Использование: /calc <банкролл> <вероятность(0-1)> <коэффициент>\n"
            "Пример: `/calc 10000 0.55 2.10`",
            parse_mode="Markdown",
        )
        return
    try:
        bankroll = float(parts[1])
        prob = float(parts[2])
        odds = float(parts[3])
    except ValueError:
        await message.answer("Не удалось распарсить числа. Используй точку для дробных.")
        return
    if not (0 < prob < 1) or odds <= 1.0 or bankroll <= 0:
        await message.answer("Параметры вне допустимого диапазона.")
        return
    rec = recommend_stake(prob, odds)
    be = break_even_probability(odds)
    lines = [
        "🧮 *Калькулятор Kelly*",
        f"Банкролл: {bankroll:.2f}",
        f"Вероятность: {prob*100:.1f}%",
        f"Коэф: {odds:.2f}",
        f"Безубыточный порог: {be*100:.1f}%",
        f"EV: *{rec.expected_value_pct:+.2f}%*",
        "",
        f"Full Kelly:   {rec.full_kelly_fraction*100:.2f}% ({rec.stake_full(bankroll):.2f})",
        f"Half Kelly:   {rec.half_kelly_fraction*100:.2f}% ({rec.stake_half(bankroll):.2f})",
        f"Quarter K.:   {rec.quarter_kelly_fraction*100:.2f}% ({rec.stake_quarter(bankroll):.2f})",
        f"Flat 2%:       {rec.flat_fraction*100:.2f}% ({rec.stake_flat(bankroll):.2f})",
    ]
    await message.answer(
        "\n".join(lines), parse_mode="Markdown", reply_markup=main_menu_keyboard()
    )
