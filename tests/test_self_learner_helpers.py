"""Юнит-тесты для новых helper'ов self_learner."""

from __future__ import annotations

from services.self_learner import (
    LearningSnapshot,
    SelfLearner,
    _market_category,
)


def test_market_category_1x2() -> None:
    assert _market_category("home") == "1x2"
    assert _market_category("X") == "1x2"
    assert _market_category("home_win") == "1x2"


def test_market_category_double_chance() -> None:
    assert _market_category("1X") == "double_chance"
    assert _market_category("X2") == "double_chance"
    assert _market_category("12") == "double_chance"
    assert _market_category("double_chance_x2") == "double_chance"


def test_market_category_total() -> None:
    assert _market_category("over_2.5") == "total"
    assert _market_category("under_25") == "total"
    assert _market_category("O25") == "total"
    assert _market_category("U35") == "total"


def test_market_category_btts() -> None:
    assert _market_category("btts") == "btts"
    assert _market_category("btts_no") == "btts"
    assert _market_category("both_yes") == "btts"


def test_market_category_handicap() -> None:
    assert _market_category("AH_H+1.5") == "handicap"
    assert _market_category("handicap_home_-1.5") == "handicap"


def test_market_category_individual_total() -> None:
    assert _market_category("HT_O15") == "individual_total"
    assert _market_category("AT_U05") == "individual_total"
    assert _market_category("home_over_2.5") == "individual_total"


def test_market_category_dnb() -> None:
    assert _market_category("dnb_home") == "dnb"


def test_market_category_other() -> None:
    assert _market_category("") == "other"
    assert _market_category("xyz_unknown") == "other"


def test_calibrate_with_low_count_trusts_model_more() -> None:
    """При count<30 trust меньше — модель имеет больший вес.

    Это anti-overfit: эмпирика на 5 матчах не должна сдвигать модельную
    вероятность на 40% — это шум. С новой логикой при count=5 trust=0.067,
    то есть 93% веса остаётся у модели.
    """
    sl = SelfLearner(session_factory=lambda: None)  # type: ignore[arg-type]

    # Бин с count=5, hits=0, empirical=0.0
    from services.self_learner import CalibrationBin

    snap = LearningSnapshot(
        calibration=[CalibrationBin(0.5, 0.6, count=5, hits=0)],
    )
    sl._latest = snap
    p = sl.calibrate(0.55)
    # При старой логике (trust=0.4): 0.6*0.55 + 0.4*0.0 = 0.33 — слишком сильный сдвиг
    # При новой (trust=0.4*5/30 = 0.067): 0.933*0.55 + 0.067*0 ≈ 0.513
    assert 0.50 < p < 0.55, f"Calibrate должна быть около 0.51, вышло {p}"


def test_calibrate_with_high_count_trusts_empirics() -> None:
    """При count≥30 trust=0.4 — обычная балансировка."""
    sl = SelfLearner(session_factory=lambda: None)  # type: ignore[arg-type]

    from services.self_learner import CalibrationBin

    snap = LearningSnapshot(
        calibration=[CalibrationBin(0.5, 0.6, count=100, hits=40)],
    )
    sl._latest = snap
    p = sl.calibrate(0.55)
    # 0.6*0.55 + 0.4*0.40 = 0.49
    assert 0.485 < p < 0.495, f"Ожидали ~0.49, вышло {p}"
