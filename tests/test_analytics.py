"""Тесты AnalyticsService."""

from __future__ import annotations

from datetime import datetime

from core.value_calculator import ValueBet
from services.analytics import AnalyticsService
from services.prediction_service import PredictionResult


def _make_result(gid: int = 100) -> PredictionResult:
    return PredictionResult(
        game_id=gid,
        home_name="A",
        away_name="B",
        league_name="L",
        country_raw="X",
        date_iso="2025-01-01T00:00:00Z",
        home_rating=1500,
        away_rating=1500,
        home_xg=1.0,
        away_xg=1.0,
        probabilities={"home": 0.5},
        top_scores=[],
        value_bets=[],
        odds_map={},
        best_odds={},
        summary_text=None,
        injuries=[],
        accuracy_notes=[],
    )


def _make_bet(market: str = "home", value: float = 10.0) -> ValueBet:
    return ValueBet(
        market_key=market,
        probability=0.55,
        actual_odds=2.0,
        fair_odds=1.82,
        value_percent=value,
        is_value=True,
    )


def test_record_prediction():
    svc = AnalyticsService()
    tick = svc.record_prediction(_make_result(), _make_bet())
    assert tick.game_id == 100
    assert tick.predicted_market == "home"
    assert len(svc) == 1


def test_summary_empty():
    svc = AnalyticsService()
    s = svc.summary()
    assert s.total_predictions == 0
    assert s.hit_rate_pct == 0


def test_summary_counts_wins_losses():
    svc = AnalyticsService()
    svc.record_prediction(_make_result(1), _make_bet())
    svc.record_prediction(_make_result(2), _make_bet())
    svc.settle(1, home_score=2, away_score=0, market_resolver=lambda *_: True)
    svc.settle(2, home_score=0, away_score=2, market_resolver=lambda *_: False)
    s = svc.summary()
    assert s.settled == 2
    assert s.won == 1
    assert s.lost == 1
    assert abs(s.hit_rate_pct - 50.0) < 1e-9


def test_roi_positive_when_winning():
    svc = AnalyticsService()
    svc.record_prediction(_make_result(1), _make_bet())
    svc.settle(1, home_score=1, away_score=0, market_resolver=lambda *_: True)
    s = svc.summary()
    # 1 ставка с коэф 2.0, won → профит = 1.0 = 100% ROI
    assert abs(s.roi_pct - 100.0) < 1e-9


def test_streaks():
    svc = AnalyticsService()
    for i in range(1, 6):
        svc.record_prediction(_make_result(i), _make_bet())
    for i, won in enumerate([True, True, False, True, True], start=1):
        result_won = won
        svc.settle(
            i,
            home_score=1,
            away_score=0,
            market_resolver=lambda *_, _w=result_won: _w,
        )
    s = svc.summary()
    assert s.best_streak == 2
    assert s.worst_streak == 1


def test_markets_breakdown():
    svc = AnalyticsService()
    svc.record_prediction(_make_result(1), _make_bet("home"))
    svc.record_prediction(_make_result(2), _make_bet("home"))
    svc.record_prediction(_make_result(3), _make_bet("over_2.5"))
    s = svc.summary()
    assert s.markets_breakdown == {"home": 2, "over_2.5": 1}


def test_by_user_range():
    svc = AnalyticsService()
    svc.record_prediction(_make_result(1), _make_bet(), now=datetime.utcnow())
    assert len(svc.by_user_range(30)) == 1


def test_clear():
    svc = AnalyticsService()
    svc.record_prediction(_make_result(1), _make_bet())
    svc.clear()
    assert len(svc) == 0
