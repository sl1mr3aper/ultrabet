"""Тесты reports."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from services.analytics import PredictionTick
from services.reports import (
    bankroll_stats,
    generate_bankroll_report,
    generate_weekly_summary,
)


def _tick(day_ago, *, won, odds=2.0, market="home"):
    return PredictionTick(
        game_id=1,
        created_at=datetime.now() - timedelta(days=day_ago),
        predicted_market=market,
        predicted_prob=0.55,
        actual_odds=odds,
        fair_odds=1 / 0.55,
        value_percent=10.0,
        settled=True,
        won=won,
    )


def test_empty_bankroll_report():
    out = generate_bankroll_report([])
    assert out == []


def test_bankroll_report_basic():
    ticks = [_tick(3, won=True), _tick(2, won=False), _tick(1, won=True)]
    report = generate_bankroll_report(ticks, start_bankroll=1000.0, stake_per_bet=10.0)
    assert len(report) == 3


def test_bankroll_ends_above_start_when_wins_dominate():
    ticks = [_tick(i, won=True, odds=3.0) for i in range(5)]
    report = generate_bankroll_report(ticks, start_bankroll=1000.0, stake_per_bet=10.0)
    assert report[-1].bankroll_end > 1000.0


def test_bankroll_ends_below_start_when_losses_dominate():
    ticks = [_tick(i, won=False, odds=3.0) for i in range(5)]
    report = generate_bankroll_report(ticks, start_bankroll=1000.0, stake_per_bet=10.0)
    assert report[-1].bankroll_end < 1000.0


def test_bankroll_stats_empty():
    s = bankroll_stats([])
    assert s["max_drawdown"] == 0
    assert s["volatility"] == 0


def test_bankroll_stats_nonempty():
    ticks = [_tick(5, won=True), _tick(4, won=False), _tick(3, won=True), _tick(2, won=False), _tick(1, won=True)]
    report = generate_bankroll_report(ticks, start_bankroll=1000.0, stake_per_bet=10.0)
    s = bankroll_stats(report)
    assert "max_drawdown" in s
    assert "volatility" in s


def test_weekly_summary_empty():
    s = generate_weekly_summary([])
    assert s["total"] == 0
    assert s["hit_rate_pct"] == 0


def test_weekly_summary_counts():
    ticks = [_tick(1, won=True), _tick(2, won=False), _tick(8, won=True)]  # последний вне 7 дней
    s = generate_weekly_summary(ticks, today=date.today())
    assert s["total"] == 2
    assert s["won"] == 1
    assert s["lost"] == 1
