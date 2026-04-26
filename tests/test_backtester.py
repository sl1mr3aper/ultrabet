"""Тесты Backtester."""

from __future__ import annotations

from datetime import datetime

from services.backtester import (
    Backtester,
    HistoricalGame,
    Pick,
    flat_stake,
    kelly_stake,
    percent_stake,
)


def _game(gid=1, date_str="2024-01-01"):
    return HistoricalGame(
        game_id=gid,
        home_team="A",
        away_team="B",
        league="L",
        starts_at=datetime.fromisoformat(date_str),
        home_score=1,
        away_score=0,
    )


def _pick(market="home", prob=0.55, odds=2.0):
    return Pick(
        game_id=1,
        market=market,
        probability=prob,
        odds=odds,
        fair_odds=1 / prob,
        value_percent=(prob * odds - 1) * 100,
    )


def _all(picks):
    return picks


def test_empty_backtest():
    bt = Backtester(strategy=_all, stake_fn=flat_stake(10), initial_bankroll=1000)
    r = bt.report()
    assert r.bets_placed == 0
    assert r.profit == 0


def test_winning_bet():
    bt = Backtester(strategy=_all, stake_fn=flat_stake(10), initial_bankroll=1000)
    bt.process(_game(), [_pick()], {"home": True})
    assert bt.bankroll == 1010  # -10 + 20
    r = bt.report()
    assert r.bets_won == 1
    assert r.profit == 10


def test_losing_bet():
    bt = Backtester(strategy=_all, stake_fn=flat_stake(10), initial_bankroll=1000)
    bt.process(_game(), [_pick()], {"home": False})
    assert bt.bankroll == 990
    r = bt.report()
    assert r.bets_lost == 1
    assert r.profit == -10


def test_mixed_bets_roi():
    bt = Backtester(strategy=_all, stake_fn=flat_stake(10), initial_bankroll=1000)
    bt.process(_game(gid=1), [_pick(odds=2.0)], {"home": True})  # +10
    bt.process(_game(gid=2), [_pick(odds=2.0)], {"home": False})  # -10
    r = bt.report()
    assert r.bets_placed == 2
    assert r.profit == 0
    assert r.roi_pct == 0


def test_percent_stake():
    bt = Backtester(strategy=_all, stake_fn=percent_stake(10), initial_bankroll=1000)
    bt.process(_game(), [_pick()], {"home": True})
    # 100 stake, win at 2.0 → +100
    assert bt.bankroll == 1100


def test_kelly_stake():
    bt = Backtester(strategy=_all, stake_fn=kelly_stake(), initial_bankroll=1000)
    bt.process(_game(), [_pick(prob=0.6, odds=2.0)], {"home": True})
    # Kelly: (0.6*1 - 0.4)/1 = 0.2 → cap 0.1 → stake=100
    assert bt.bankroll == 1100


def test_hit_rate_calculated():
    bt = Backtester(strategy=_all, stake_fn=flat_stake(10), initial_bankroll=1000)
    bt.process(_game(gid=1), [_pick()], {"home": True})
    bt.process(_game(gid=2), [_pick()], {"home": True})
    bt.process(_game(gid=3), [_pick()], {"home": False})
    r = bt.report()
    assert abs(r.hit_rate_pct - 66.6666) < 0.1


def test_max_drawdown():
    bt = Backtester(strategy=_all, stake_fn=flat_stake(100), initial_bankroll=1000)
    bt.process(_game(gid=1), [_pick()], {"home": False})  # -100
    bt.process(_game(gid=2), [_pick()], {"home": False})  # -100
    r = bt.report()
    assert r.max_drawdown > 0


def test_strategy_filter():
    bt = Backtester(
        strategy=lambda picks: [p for p in picks if p.value_percent > 20.0],
        stake_fn=flat_stake(10),
        initial_bankroll=1000,
    )
    # Value = (0.55*2-1)*100 = 10% → filtered out
    bt.process(_game(), [_pick()], {"home": True})
    r = bt.report()
    assert r.bets_placed == 0


def test_stake_not_exceeding_bankroll():
    bt = Backtester(strategy=_all, stake_fn=flat_stake(10000), initial_bankroll=100)
    bt.process(_game(), [_pick()], {"home": True})
    # stake too large, should skip
    r = bt.report()
    assert r.bets_placed == 0


def test_markets_without_result_skipped():
    bt = Backtester(strategy=_all, stake_fn=flat_stake(10), initial_bankroll=1000)
    bt.process(_game(), [_pick(market="home")], {"over_2_5": True})
    r = bt.report()
    assert r.bets_placed == 0
