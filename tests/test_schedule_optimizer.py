"""Тесты ScheduleOptimizer."""

from __future__ import annotations

from datetime import datetime, timedelta

from services.schedule_optimizer import ScheduleOptimizer


def test_plan_returns_positive_ttls():
    opt = ScheduleOptimizer(daily_budget=100)
    plan = opt.plan(active_leagues=5, upcoming_matches=30, live_matches=3)
    assert plan.leagues_ttl_hours > 0
    assert plan.live_odds_ttl_seconds > 0


def test_plan_scales_under_budget():
    opt = ScheduleOptimizer(daily_budget=10)
    plan = opt.plan(active_leagues=20, upcoming_matches=100, live_matches=10)
    # Должен сильно увеличить TTL при ограниченном бюджете
    assert plan.games_list_ttl_minutes > 5.0
    assert plan.live_odds_ttl_seconds > 15.0


def test_plan_no_scale_at_high_budget():
    opt = ScheduleOptimizer(daily_budget=100_000)
    plan = opt.plan(active_leagues=3, upcoming_matches=10, live_matches=2)
    # Никакого масштабирования — всё умещается в бюджет
    assert plan.games_list_ttl_minutes == 5.0


def test_recommend_poll_interval_no_live():
    opt = ScheduleOptimizer(daily_budget=100)
    interval = opt.recommend_live_poll_interval(live_matches=0, daily_budget_used_so_far=50)
    assert interval >= 10


def test_recommend_poll_interval_budget_exhausted():
    opt = ScheduleOptimizer(daily_budget=100)
    interval = opt.recommend_live_poll_interval(live_matches=5, daily_budget_used_so_far=100)
    assert interval >= 60


def test_should_refresh_stale():
    opt = ScheduleOptimizer()
    old = datetime.utcnow() - timedelta(hours=2)
    assert opt.should_refresh(last_refresh=old, ttl=timedelta(hours=1)) is True


def test_should_refresh_fresh():
    opt = ScheduleOptimizer()
    recent = datetime.utcnow() - timedelta(minutes=5)
    assert opt.should_refresh(last_refresh=recent, ttl=timedelta(hours=1)) is False


def test_safety_margin_respected():
    opt = ScheduleOptimizer(daily_budget=100)
    plan = opt.plan()
    assert plan.safety_margin_percent == 20.0
