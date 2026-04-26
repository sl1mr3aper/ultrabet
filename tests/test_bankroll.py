"""Тесты стейкинг-стратегий."""

from __future__ import annotations

import pytest

from services.bankroll import StakeInput, StakeKind, compute_stake, describe


def test_kelly_positive_ev():
    si = StakeInput(
        bankroll=1000, probability=0.6, odds=2.0, base_percent=1.0, max_fraction=1.0
    )
    st = compute_stake(si, StakeKind.KELLY)
    # Kelly = (1*0.6 - 0.4)/1 = 0.2 → 200
    assert abs(st - 200.0) < 1e-6


def test_kelly_zero_when_no_edge():
    si = StakeInput(bankroll=1000, probability=0.5, odds=2.0)
    st = compute_stake(si, StakeKind.KELLY)
    assert st == 0.0


def test_half_kelly_half_of_kelly():
    si = StakeInput(
        bankroll=1000, probability=0.6, odds=2.0, max_fraction=1.0
    )
    k = compute_stake(si, StakeKind.KELLY)
    hk = compute_stake(si, StakeKind.HALF_KELLY)
    assert abs(hk - k / 2) < 1e-6


def test_flat_returns_base():
    si = StakeInput(bankroll=1000, probability=0.6, odds=2.0, base_percent=2.0)
    st = compute_stake(si, StakeKind.FLAT)
    assert abs(st - 20.0) < 1e-6


def test_percent():
    si = StakeInput(bankroll=500, probability=0.6, odds=2.0, base_percent=1.5)
    st = compute_stake(si, StakeKind.PERCENT)
    assert abs(st - 7.5) < 1e-6


def test_martingale_doubles():
    si_no_loss = StakeInput(bankroll=1000, probability=0.6, odds=2.0, base_percent=1.0, previous_losses=0)
    si_loss3 = StakeInput(bankroll=1000, probability=0.6, odds=2.0, base_percent=1.0, previous_losses=3)
    base = compute_stake(si_no_loss, StakeKind.MARTINGALE)
    after3 = compute_stake(si_loss3, StakeKind.MARTINGALE)
    # 2^3 = 8x base, но капится на max_fraction=10%
    assert after3 >= base
    assert after3 <= si_loss3.bankroll * si_loss3.max_fraction + 1e-6


def test_anti_martingale_doubles_on_wins():
    si = StakeInput(bankroll=1000, probability=0.6, odds=2.0, base_percent=1.0, previous_wins=2)
    st = compute_stake(si, StakeKind.ANTI_MARTINGALE)
    # 2^2 = 4x = 4% of 1000 = 40
    assert abs(st - 40.0) < 1e-6


def test_zero_bankroll():
    si = StakeInput(bankroll=0, probability=0.6, odds=2.0)
    for k in StakeKind:
        assert compute_stake(si, k) == 0.0


def test_max_fraction_caps():
    si = StakeInput(
        bankroll=1000, probability=0.99, odds=10.0, base_percent=1.0, max_fraction=0.10
    )
    st = compute_stake(si, StakeKind.KELLY)
    assert st <= 100.0 + 1e-6


@pytest.mark.parametrize("kind", list(StakeKind))
def test_describe_all(kind):
    assert isinstance(describe(kind), str)
    assert len(describe(kind)) > 10
