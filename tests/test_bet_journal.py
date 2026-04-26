"""Тесты BetJournal."""

from __future__ import annotations

from services.bet_journal import BetJournal, BetStatus


def _new() -> BetJournal:
    return BetJournal()


def test_add_entry():
    j = _new()
    e = j.add(
        user_id=1,
        event_name="Real vs Barca",
        league="LaLiga",
        market="home",
        bookmaker="bet365",
        stake=10.0,
        odds=2.0,
    )
    assert e.entry_id == 1
    assert e.status is BetStatus.PENDING


def test_settle():
    j = _new()
    e = j.add(user_id=1, event_name="e", league="l", market="home",
              bookmaker="b", stake=10, odds=2)
    j.settle(e.entry_id, BetStatus.WON)
    assert j.get(e.entry_id).status is BetStatus.WON


def test_settle_once():
    j = _new()
    e = j.add(user_id=1, event_name="e", league="l", market="home",
              bookmaker="b", stake=10, odds=2)
    j.settle(e.entry_id, BetStatus.WON)
    r = j.settle(e.entry_id, BetStatus.LOST)
    assert r is None


def test_delete():
    j = _new()
    e = j.add(user_id=1, event_name="e", league="l", market="home",
              bookmaker="b", stake=10, odds=2)
    assert j.delete(e.entry_id) is True
    assert j.get(e.entry_id) is None


def test_filter_by_user():
    j = _new()
    j.add(user_id=1, event_name="a", league="l", market="home", bookmaker="b", stake=1, odds=2)
    j.add(user_id=2, event_name="b", league="l", market="home", bookmaker="b", stake=1, odds=2)
    assert len(j.filter(user_id=1)) == 1


def test_filter_by_status():
    j = _new()
    e = j.add(user_id=1, event_name="e", league="l", market="home", bookmaker="b", stake=1, odds=2)
    j.settle(e.entry_id, BetStatus.WON)
    j.add(user_id=1, event_name="x", league="l", market="home", bookmaker="b", stake=1, odds=2)
    assert len(j.filter(status=BetStatus.WON)) == 1
    assert len(j.filter(status=BetStatus.PENDING)) == 1


def test_filter_by_bookmaker():
    j = _new()
    j.add(user_id=1, event_name="e", league="l", market="home", bookmaker="A", stake=1, odds=2)
    j.add(user_id=1, event_name="e", league="l", market="home", bookmaker="B", stake=1, odds=2)
    assert len(j.filter(bookmaker="A")) == 1


def test_summary_empty():
    j = _new()
    s = j.summary()
    assert s.total_bets == 0
    assert s.roi_pct == 0


def test_summary_roi_positive():
    j = _new()
    e1 = j.add(user_id=1, event_name="e", league="l", market="home", bookmaker="b", stake=10, odds=3.0)
    e2 = j.add(user_id=1, event_name="e", league="l", market="home", bookmaker="b", stake=10, odds=3.0)
    j.settle(e1.entry_id, BetStatus.WON)  # +20
    j.settle(e2.entry_id, BetStatus.LOST)  # -10
    s = j.summary()
    assert s.won == 1
    assert s.lost == 1
    # profit = 20-10 = 10; staked = 20; ROI = 50%
    assert abs(s.total_profit - 10) < 1e-6
    assert abs(s.roi_pct - 50.0) < 1e-6


def test_summary_per_user():
    j = _new()
    e = j.add(user_id=1, event_name="e", league="l", market="home", bookmaker="b", stake=10, odds=2)
    j.settle(e.entry_id, BetStatus.WON)
    j.add(user_id=2, event_name="e", league="l", market="home", bookmaker="b", stake=10, odds=2)
    s1 = j.summary(user_id=1)
    s2 = j.summary(user_id=2)
    assert s1.won == 1
    assert s2.won == 0


def test_tags():
    j = _new()
    j.add(user_id=1, event_name="e", league="l", market="home", bookmaker="b",
          stake=1, odds=2, tags=["risky"])
    j.add(user_id=1, event_name="e", league="l", market="home", bookmaker="b",
          stake=1, odds=2, tags=["safe"])
    assert len(j.filter(tag="risky")) == 1


def test_clear():
    j = _new()
    j.add(user_id=1, event_name="e", league="l", market="home", bookmaker="b", stake=1, odds=2)
    j.clear()
    assert j.all() == []


def test_void_excluded_from_staked():
    j = _new()
    e = j.add(user_id=1, event_name="e", league="l", market="home", bookmaker="b", stake=100, odds=2)
    j.settle(e.entry_id, BetStatus.VOID)
    s = j.summary()
    assert s.total_staked == 0
