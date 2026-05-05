"""Команды для калькуляции размера ставки.

/bankroll <банк> <prob> <odds>   — расчёт Kelly/Flat/Half-Kelly.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.types import Message

from bot.keyboards import main_menu_keyboard
from bot.styles import ICON_MONEY, header
from services.bankroll import StakeInput, StakeKind, compute_stake, describe

router = Router(name="bankroll")
# [removed: command handler — UI is buttons-only]
async def bankroll_cmd(message: Message) -> None:
    parts = (message.text or "").split()
    if len(parts) < 4:
        await message.answer(
            "Использование: `/bankroll <банк> <вероятность%> <коэф>`\n"
            "Пример: `/bankroll 10000 60 2.00` → банк 10000, p=60%, odds=2.00",
            parse_mode="Markdown",
        )
        return
    try:
        bankroll = float(parts[1])
        prob_pct = float(parts[2])
        odds = float(parts[3])
    except ValueError:
        await message.answer("Все три аргумента должны быть числами.")
        return
    if bankroll <= 0 or prob_pct <= 0 or prob_pct >= 100 or odds <= 1:
        await message.answer(
            "Проверь входные данные: банк>0, 0<prob<100%, odds>1."
        )
        return
    probability = prob_pct / 100.0
    si = StakeInput(
        bankroll=bankroll, probability=probability, odds=odds, base_percent=1.0
    )
    lines = [
        header("Размер ставки", icon=ICON_MONEY),
        f"Банк: *{bankroll:.2f}*",
        f"Вероятность модели: *{prob_pct:.1f}%*",
        f"Коэффициент: *{odds:.2f}*",
        f"КФ (1/p): *{1 / probability:.2f}*",
        f"EV: *{(probability * odds - 1) * 100:+.2f}%*",
        "",
        "*Рекомендуемый размер ставки:*",
    ]
    for kind in (StakeKind.FLAT, StakeKind.PERCENT, StakeKind.KELLY):
        stake = compute_stake(si, kind)
        pct_of_bank = (stake / bankroll * 100.0) if bankroll > 0 else 0.0
        lines.append(
            f"• {kind.value}: *{stake:.2f}* (*{pct_of_bank:.2f}%* банка) — "
            f"_{describe(kind)}_"
        )
    lines.append("")
    lines.append(
        "_Келли — математически оптимальная доля банка на 1 ставку."
        " Для меньшего риска пользуйся долей Келли вручную (÷ 2 или ÷ 4)._"
    )
    lines.append(
        "⚠️ Это калькулятор, не совет. Max cap 10% банка для защиты."
    )
    await message.answer(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )
