"""Команда /parlay — сборка и анализ экспресса.

Формат: /parlay odd1 odd2 odd3 ... (просто перемножение)
Или:   /parlay p1:o1 p2:o2 p3:o3 — с нашими вероятностями для расчёта EV.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.types import Message

from bot.keyboards import main_menu_keyboard
from bot.styles import ICON_TARGET, header
from services.parlay import ParlayLeg, calculate_parlay, describe_risk

router = Router(name="parlay")
# [removed: command handler — UI is buttons-only]
async def parlay_cmd(message: Message) -> None:
    parts = (message.text or "").split()
    if len(parts) < 3:
        await message.answer(
            "Использование:\n"
            "`/parlay 2.0 1.8 2.5` — просто коэфы\n"
            "`/parlay 0.6:2.0 0.55:1.8` — вероятности:коэфы (для EV)",
            parse_mode="Markdown",
        )
        return
    legs: list[ParlayLeg] = []
    for token in parts[1:]:
        try:
            if ":" in token:
                p_str, o_str = token.split(":", 1)
                prob = float(p_str)
                odds = float(o_str)
            else:
                odds = float(token)
                # implicit prob = fair (1/odds) → value_pct будет 0
                prob = 1.0 / odds if odds > 1.0 else 0.0
        except ValueError:
            await message.answer(f"Не могу распарсить `{token}`.", parse_mode="Markdown")
            return
        legs.append(ParlayLeg(name=token, probability=prob, odds=odds))
    result = calculate_parlay(legs)
    if result is None:
        await message.answer("Некорректные данные. Проверь коэф > 1 и 0 < prob ≤ 1.")
        return
    lines = [
        header(f"Экспресс из {result.leg_count} событий", icon=ICON_TARGET),
        f"Итоговый коэф: *{result.total_odds:.2f}*",
        f"Итоговая вероятность: *{result.combined_probability * 100:.2f}%*",
        f"Fair-коэф: *{result.fair_total_odds:.2f}*",
        f"EV: *{result.value_percent:+.2f}%*",
        f"Риск: *{describe_risk(result)}*",
        "",
    ]
    for leg in legs:
        lines.append(
            f"• `{leg.name}` → prob={leg.probability*100:.1f}%, odds={leg.odds:.2f}"
        )
    await message.answer(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )
