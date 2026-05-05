"""Тесты shrinkage xG к лиге-среднему и baseline-fallback без рейтинга.

Регрессия на бага: модель раньше для матча без Glicko рейтинга и без
xG_api жёстко возвращала home_xg=1.45, away_xg=1.20 — игнорируя
league_avg_total. Это переоценивало голы аутсайдеров в низко-голевых
лигах (Бангладеш, NWSL, Финляндия) → системный LOSS на ИТБ 0.5 и ОЗ.
"""

from __future__ import annotations

from core.ensemble import (
    _league_baseline_xg,
    _shrink_xg_to_league,
    build_predictions,
)


def test_baseline_xg_respects_league_avg_low() -> None:
    h, a = _league_baseline_xg(2.0)
    assert abs(h - 1.20) < 1e-9  # 2.0/2 + 0.20
    assert abs(a - 0.80) < 1e-9  # 2.0/2 - 0.20


def test_baseline_xg_respects_league_avg_high() -> None:
    h, a = _league_baseline_xg(3.4)
    assert abs(h - 1.90) < 1e-9
    assert abs(a - 1.50) < 1e-9


def test_shrinkage_zero_data_strong_pull() -> None:
    """n=0 → α=0.6 → xG сильно тянется к baseline лиги."""
    sh, sa = _shrink_xg_to_league(2.0, 0.5, league_avg_total=2.6, n_league_matches=0)
    base_h, base_a = _league_baseline_xg(2.6)
    expected_h = 0.4 * 2.0 + 0.6 * base_h
    expected_a = 0.4 * 0.5 + 0.6 * base_a
    assert abs(sh - expected_h) < 1e-9
    assert abs(sa - expected_a) < 1e-9


def test_shrinkage_full_data_no_pull() -> None:
    """n>=100 → без усадки, xG не меняется."""
    sh, sa = _shrink_xg_to_league(
        2.0, 0.5, league_avg_total=2.6, n_league_matches=200,
    )
    assert sh == 2.0
    assert sa == 0.5


def test_shrinkage_partial_data() -> None:
    """n=50 → α=0.3."""
    sh, sa = _shrink_xg_to_league(
        2.0, 0.5, league_avg_total=2.6, n_league_matches=50,
    )
    base_h, base_a = _league_baseline_xg(2.6)
    expected_h = 0.7 * 2.0 + 0.3 * base_h
    expected_a = 0.7 * 0.5 + 0.3 * base_a
    assert abs(sh - expected_h) < 1e-6
    assert abs(sa - expected_a) < 1e-6


def test_no_rating_no_xg_api_uses_league_baseline() -> None:
    """Без рейтинга и без xG_api — baseline должен зависеть от лиги.

    Раньше: всегда 1.45/1.20. Теперь: для лиги с avg=2.0 → 1.20/0.80.
    """
    p_low = build_predictions(
        home_rating=None, away_rating=None,
        league_avg_total=2.0, n_league_matches=200,  # без shrinkage
    )
    p_high = build_predictions(
        home_rating=None, away_rating=None,
        league_avg_total=3.4, n_league_matches=200,
    )
    # Низко-голевая лига → меньше xG обеих команд
    assert p_low.home_xg < p_high.home_xg
    assert p_low.away_xg < p_high.away_xg
    # Соотношение примерно 2.0/3.4
    assert p_low.home_xg + p_low.away_xg < p_high.home_xg + p_high.away_xg


def test_shrinkage_cuts_underdog_overestimation_in_short_league() -> None:
    """Главный кейс: аутсайдер в Бангладеше с n=0.

    Без shrinkage: модель даёт away_xg=1.20 (хардкод); P(away≥1) = 70%.
    С shrinkage в лиге с avg=2.2: away_xg усажено к 1.0 → P(away≥1)
    падает, ИТБ 0.5 аутсайдера больше не в топе с 70%.
    """
    p_old = build_predictions(
        home_rating=None, away_rating=None,
        league_avg_total=2.2, n_league_matches=200,  # как было
    )
    p_new = build_predictions(
        home_rating=None, away_rating=None,
        league_avg_total=2.2, n_league_matches=0,  # с shrinkage
    )
    # away_xg должен быть ниже после shrinkage
    assert p_new.away_xg <= p_old.away_xg + 1e-9
