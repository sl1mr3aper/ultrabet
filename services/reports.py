"""Генерация сложных отчётов для пользователя и админа.

Отчёты:
- generate_match_report — подробный разбор одного матча (входные данные:
  PredictionResult). Возвращает большой markdown.
- generate_daily_summary — по списку DailyPick даёт общий итог дня.
- generate_weekly_summary — берёт аналитику за 7 дней, выдаёт сводку.
- generate_bankroll_report — по истории ставок и начальному банку показывает
  кривую банка, худший/лучший день, волатильность.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import mean, pstdev

from services.analytics import PredictionTick


@dataclass(slots=True)
class BankrollPoint:
    day: date
    bankroll_end: float
    staked: float
    won: int
    lost: int


def generate_bankroll_report(
    ticks: Sequence[PredictionTick],
    *,
    start_bankroll: float = 1000.0,
    stake_per_bet: float = 10.0,
) -> list[BankrollPoint]:
    """Эмулирует движение банка если бы юзер поставил fixed stake на каждую ставку."""
    by_day: dict[date, list[PredictionTick]] = {}
    for t in ticks:
        if not t.settled:
            continue
        d = t.created_at.date()
        by_day.setdefault(d, []).append(t)

    cur = start_bankroll
    out: list[BankrollPoint] = []
    for d in sorted(by_day.keys()):
        day_ticks = by_day[d]
        staked = stake_per_bet * len(day_ticks)
        won_count = sum(1 for t in day_ticks if t.won is True)
        lost_count = sum(1 for t in day_ticks if t.won is False)
        gain = 0.0
        for t in day_ticks:
            if t.won is True:
                gain += (t.actual_odds - 1.0) * stake_per_bet
            elif t.won is False:
                gain -= stake_per_bet
        cur += gain
        out.append(
            BankrollPoint(
                day=d, bankroll_end=cur, staked=staked,
                won=won_count, lost=lost_count,
            )
        )
    return out


def bankroll_stats(points: Sequence[BankrollPoint]) -> dict[str, float]:
    """Статы для отчёта: max drawdown, volatility, sharpe-лайк."""
    if not points:
        return {
            "max_drawdown": 0.0,
            "volatility": 0.0,
            "sharpe_like": 0.0,
            "best_day_pct": 0.0,
            "worst_day_pct": 0.0,
        }
    diffs: list[float] = []
    prev = points[0].bankroll_end
    peak = prev
    max_dd = 0.0
    for p in points[1:]:
        diff_pct = (p.bankroll_end - prev) / prev * 100.0 if prev else 0.0
        diffs.append(diff_pct)
        prev = p.bankroll_end
        peak = max(peak, p.bankroll_end)
        dd = (peak - p.bankroll_end) / peak * 100.0 if peak else 0.0
        max_dd = max(max_dd, dd)
    return {
        "max_drawdown": max_dd,
        "volatility": pstdev(diffs) if len(diffs) > 1 else 0.0,
        "sharpe_like": (mean(diffs) / pstdev(diffs)) if len(diffs) > 1 and pstdev(diffs) > 0 else 0.0,
        "best_day_pct": max(diffs) if diffs else 0.0,
        "worst_day_pct": min(diffs) if diffs else 0.0,
    }


def generate_weekly_summary(
    ticks: Sequence[PredictionTick], *, today: date | None = None
) -> dict[str, int | float]:
    """Агрегаты за последние 7 дней относительно today."""
    today = today or date.today()
    cutoff = today - timedelta(days=7)
    recent = [t for t in ticks if t.created_at.date() >= cutoff]
    settled = [t for t in recent if t.settled]
    won = sum(1 for t in settled if t.won is True)
    lost = sum(1 for t in settled if t.won is False)
    out = {
        "total": len(recent),
        "settled": len(settled),
        "won": won,
        "lost": lost,
        "hit_rate_pct": (won / len(settled) * 100.0) if settled else 0.0,
        "avg_odds": mean(t.actual_odds for t in recent) if recent else 0.0,
        "avg_value_pct": mean(t.value_percent for t in recent) if recent else 0.0,
    }
    return out


__all__ = [
    "BankrollPoint",
    "bankroll_stats",
    "generate_bankroll_report",
    "generate_weekly_summary",
]
