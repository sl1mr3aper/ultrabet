"""Тесты LeaderboardService."""

from __future__ import annotations

from datetime import datetime

from services.analytics import PredictionTick
from services.leaderboard_service import LeaderboardMetric, LeaderboardService
from services.user_stats import UserStatsService


def _tick(won=True, odds=2.0):
    return PredictionTick(
        game_id=1,
        created_at=datetime.utcnow(),
        predicted_market="home",
        predicted_prob=0.55,
        actual_odds=odds,
        fair_odds=1 / 0.55,
        value_percent=10,
        settled=True,
        won=won,
    )


def test_empty():
    lb = LeaderboardService(UserStatsService())
    assert lb.compute(LeaderboardMetric.HIT_RATE) == []


def test_hit_rate_ranking():
    stats = UserStatsService()
    for _ in range(10):
        stats.record(1, _tick(won=True))
    for i in range(10):
        stats.record(2, _tick(won=(i < 5)))
    lb = LeaderboardService(stats)
    board = lb.compute(LeaderboardMetric.HIT_RATE)
    assert board[0].tg_id == 1
    assert board[0].rank == 1
    assert board[1].tg_id == 2


def test_min_settled_filter():
    stats = UserStatsService()
    for _ in range(5):
        stats.record(1, _tick())
    lb = LeaderboardService(stats)
    # user has 5 settled, min is 10 → excluded
    board = lb.compute(LeaderboardMetric.HIT_RATE, min_settled=10)
    assert board == []


def test_roi_ranking():
    stats = UserStatsService()
    for _ in range(10):
        stats.record(1, _tick(won=True, odds=3.0))
    for _ in range(10):
        stats.record(2, _tick(won=True, odds=2.0))
    lb = LeaderboardService(stats)
    board = lb.compute(LeaderboardMetric.ROI)
    assert board[0].tg_id == 1  # больше ROI с odds=3


def test_total_bets_ranking():
    stats = UserStatsService()
    for _ in range(100):
        stats.record(1, _tick())
    for _ in range(10):
        stats.record(2, _tick())
    lb = LeaderboardService(stats)
    board = lb.compute(LeaderboardMetric.TOTAL_BETS, min_settled=0)
    assert board[0].tg_id == 1


def test_rank_for_user():
    stats = UserStatsService()
    for _ in range(10):
        stats.record(1, _tick(won=True))
    for i in range(10):
        stats.record(2, _tick(won=(i < 5)))
    lb = LeaderboardService(stats)
    assert lb.rank_for_user(1, LeaderboardMetric.HIT_RATE) == 1
    assert lb.rank_for_user(2, LeaderboardMetric.HIT_RATE) == 2


def test_rank_for_user_not_present():
    stats = UserStatsService()
    lb = LeaderboardService(stats)
    assert lb.rank_for_user(999, LeaderboardMetric.HIT_RATE) is None


def test_display_name():
    stats = UserStatsService()
    for _ in range(10):
        stats.record(1, _tick())
    lb = LeaderboardService(stats)
    lb.set_name(1, "Bobby")
    board = lb.compute(LeaderboardMetric.HIT_RATE)
    assert board[0].display_name == "Bobby"


def test_best_streak_ranking():
    stats = UserStatsService()
    # User 1 — серия 5, потом loss
    for _ in range(5):
        stats.record(1, _tick(won=True))
    for _ in range(5):
        stats.record(1, _tick(won=False))
    # User 2 — чередование
    for i in range(10):
        stats.record(2, _tick(won=(i % 2 == 0)))
    lb = LeaderboardService(stats)
    board = lb.compute(LeaderboardMetric.BEST_STREAK)
    assert board[0].tg_id == 1
    assert board[0].best_streak == 5
