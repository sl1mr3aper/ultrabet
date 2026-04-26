"""Тесты UserStatsService."""

from __future__ import annotations

from datetime import datetime

from services.analytics import PredictionTick
from services.user_stats import UserStatsService


def _tick(
    *,
    game_id=1,
    market="home",
    prob=0.55,
    odds=2.0,
    settled=False,
    won=None,
):
    return PredictionTick(
        game_id=game_id,
        created_at=datetime.utcnow(),
        predicted_market=market,
        predicted_prob=prob,
        actual_odds=odds,
        fair_odds=1 / prob,
        value_percent=(prob * odds - 1) * 100,
        settled=settled,
        won=won,
    )


def test_empty_user_stats():
    svc = UserStatsService()
    s = svc.compute(123)
    assert s.total_predictions == 0
    assert s.hit_rate_pct == 0


def test_record_and_compute_unsettled():
    svc = UserStatsService()
    svc.record(1, _tick())
    svc.record(1, _tick())
    s = svc.compute(1)
    assert s.total_predictions == 2
    assert s.settled == 0


def test_settle_flow():
    svc = UserStatsService()
    svc.record(1, _tick(game_id=10, market="home"))
    svc.record(1, _tick(game_id=10, market="over_2_5"))
    svc.record(1, _tick(game_id=11, market="home"))
    updated = svc.settle(1, 10, {"home": True, "over_2_5": False})
    assert updated == 2


def test_hit_rate_and_roi():
    svc = UserStatsService()
    svc.record(1, _tick(settled=True, won=True, odds=2.0))
    svc.record(1, _tick(settled=True, won=False, odds=2.0))
    svc.record(1, _tick(settled=True, won=True, odds=2.0))
    s = svc.compute(1)
    assert abs(s.hit_rate_pct - 2 / 3 * 100) < 1e-6
    # ROI: (+1 -1 +1) / 3 = 0.333 * 100 = 33.3%
    assert abs(s.roi_pct - 33.3333) < 1e-2


def test_streaks():
    svc = UserStatsService()
    for won in [True, True, True, False, False, True, True]:
        svc.record(1, _tick(settled=True, won=won))
    s = svc.compute(1)
    assert s.best_streak == 3
    assert s.worst_streak == 2


def test_markets_breakdown():
    svc = UserStatsService()
    svc.record(1, _tick(market="home"))
    svc.record(1, _tick(market="home"))
    svc.record(1, _tick(market="over_2_5"))
    s = svc.compute(1)
    assert s.markets_breakdown["home"] == 2
    assert s.favorite_market == "home"


def test_leaderboard():
    svc = UserStatsService()
    for _ in range(15):
        svc.record(1, _tick(settled=True, won=True))
    for _ in range(5):
        svc.record(2, _tick(settled=True, won=True))
    lb = svc.leaderboard(min_settled=10)
    assert len(lb) == 1
    assert lb[0].tg_id == 1


def test_clear_user():
    svc = UserStatsService()
    svc.record(1, _tick())
    svc.clear_user(1)
    s = svc.compute(1)
    assert s.total_predictions == 0


def test_user_count():
    svc = UserStatsService()
    svc.record(1, _tick())
    svc.record(2, _tick())
    assert svc.user_count() == 2
