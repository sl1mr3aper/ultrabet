"""Тесты Glicko-модели."""

from __future__ import annotations

import math

import pytest

from core.glicko_model import expected_goals_from_glicko, glicko_outcome_probs


def _close(a: float, b: float, eps: float = 1e-3) -> bool:
    return math.fabs(a - b) < eps


def test_glicko_probs_sum_to_one():
    p_h, p_d, p_a = glicko_outcome_probs(1500, 1500)
    assert _close(p_h + p_d + p_a, 1.0)


def test_home_advantage_increases_home_prob():
    p_eq = glicko_outcome_probs(1500, 1500)
    p_higher = glicko_outcome_probs(1700, 1500)
    assert p_higher[0] > p_eq[0]


def test_lower_team_has_lower_prob():
    p_h, _, p_a = glicko_outcome_probs(1300, 1700)
    assert p_h < p_a


@pytest.mark.parametrize(
    ("home", "away"), [(1500, 1500), (1700, 1500), (1300, 1700), (2000, 1100)]
)
def test_glicko_probs_in_range(home: float, away: float):
    p_h, p_d, p_a = glicko_outcome_probs(home, away)
    for v in (p_h, p_d, p_a):
        assert 0.0 < v < 1.0


def test_expected_goals_balanced():
    h, a = expected_goals_from_glicko(1500, 1500)
    assert h > a  # home advantage adds 0.25
    assert h + a == pytest.approx(2.7, abs=0.5)


def test_expected_goals_for_strong_home():
    h, a = expected_goals_from_glicko(1900, 1300)
    assert h > a
    assert h > 1.5
