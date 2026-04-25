"""Тесты Пуассон-модели."""

from __future__ import annotations

import math

import pytest

from core.poisson_model import (
    btts_probabilities,
    correct_score_distribution,
    handicap_probabilities,
    over_under_probabilities,
    poisson_match_probs,
    team_total_probabilities,
    top_correct_scores,
)


def test_correct_score_normalized():
    matrix = correct_score_distribution(1.5, 1.2)
    total = sum(sum(row) for row in matrix)
    assert math.isclose(total, 1.0, abs_tol=1e-3)


def test_match_probs_sum_one():
    p_h, p_d, p_a = poisson_match_probs(1.5, 1.2)
    assert math.isclose(p_h + p_d + p_a, 1.0, abs_tol=1e-6)


def test_higher_xg_means_higher_winprob():
    p_h_a, _, _ = poisson_match_probs(0.8, 1.5)
    p_h_b, _, _ = poisson_match_probs(2.5, 1.5)
    assert p_h_b > p_h_a


def test_overunder_pairs_sum_to_one():
    table = over_under_probabilities(1.5, 1.5)
    for over, under in table.values():
        assert math.isclose(over + under, 1.0, abs_tol=1e-6)


def test_btts_pair_sum_one():
    yes, no = btts_probabilities(1.4, 1.0)
    assert math.isclose(yes + no, 1.0, abs_tol=1e-6)


def test_team_totals_have_keys():
    res = team_total_probabilities(1.4, 1.0)
    assert 1.5 in res["home"]
    assert 0.5 in res["home"]


def test_handicap_in_unit_interval():
    matrix = correct_score_distribution(1.7, 1.0)
    h = handicap_probabilities(matrix)
    for v in h.values():
        assert 0.0 <= v <= 1.0


def test_top_scores_sorted():
    scores = top_correct_scores(1.5, 1.2)
    probs = [s[2] for s in scores]
    assert probs == sorted(probs, reverse=True)


@pytest.mark.parametrize("xg", [0.0, -1.0])
def test_zero_xg_safe(xg: float):
    p_h, p_d, p_a = poisson_match_probs(xg, 1.0)
    assert 0.0 <= p_h <= 1.0
    assert 0.0 <= p_d <= 1.0
    assert 0.0 <= p_a <= 1.0
