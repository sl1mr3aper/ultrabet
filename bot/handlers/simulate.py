"""Команда /simulate — Monte-Carlo симуляция матча по xG.

Использование: /simulate <home_xg> <away_xg> [n_runs]
"""

from __future__ import annotations

from aiogram import Router
from aiogram.types import Message

from bot.keyboards import main_menu_keyboard
from bot.styles import ICON_CHART, header
from services.simulation import simulate

router = Router(name="simulate")
# [removed: command handler — UI is buttons-only]
async def simulate_cmd(message: Message) -> None:
    parts = (message.text or "").split()
    if len(parts) < 3:
        await message.answer(
            "Использование: `/simulate <home_xg> <away_xg> [n_runs]`\n"
            "Пример: `/simulate 1.85 1.10 5000`",
            parse_mode="Markdown",
        )
        return
    try:
        h_xg = float(parts[1])
        a_xg = float(parts[2])
    except ValueError:
        await message.answer("xG должны быть числами.")
        return
    n_runs = 5000
    if len(parts) >= 4:
        try:
            n_runs = max(100, min(50000, int(parts[3])))
        except ValueError:
            pass
    result = simulate(h_xg, a_xg, n_runs=n_runs, seed=42)
    lines = [
        header(f"Monte-Carlo симуляция ({n_runs})", icon=ICON_CHART),
        f"xG: *{h_xg:.2f}* vs *{a_xg:.2f}*",
        "",
        f"🏠 Победа хозяев: *{result.home_win_pct:.2f}%*",
        f"🤝 Ничья: *{result.draw_pct:.2f}%*",
        f"✈️ Победа гостей: *{result.away_win_pct:.2f}%*",
        "",
        f"🔢 Средний тотал: *{result.avg_total_goals:.2f}*",
        f"⚽ хозяева в среднем: *{result.avg_home_goals:.2f}*",
        f"⚽ гости в среднем: *{result.avg_away_goals:.2f}*",
        "",
        f"Total > 1.5: *{result.over_1_5_pct:.2f}%*",
        f"Total > 2.5: *{result.over_2_5_pct:.2f}%*",
        f"Total < 2.5: *{result.under_2_5_pct:.2f}%*",
        f"Обе забьют: *{result.btts_pct:.2f}%*",
        "",
        "*Топ-счёта:*",
    ]
    for score, pct in list(result.score_distribution.items())[:5]:
        lines.append(f"  • {score} → {pct:.2f}%")
    await message.answer(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )
