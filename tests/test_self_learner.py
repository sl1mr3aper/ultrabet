"""Проверки SelfLearner._check_market и базовая калибровка."""

from services.self_learner import LearningSnapshot, SelfLearner, _check_market


def test_check_market_1x2() -> None:
    assert _check_market("home", 2, 1) is True
    assert _check_market("away", 0, 1) is True
    assert _check_market("draw", 1, 1) is True
    assert _check_market("home", 0, 0) is False


def test_check_market_double_chance() -> None:
    assert _check_market("1x", 1, 1) is True
    assert _check_market("12", 1, 1) is False
    assert _check_market("x2", 0, 1) is True


def test_check_market_totals() -> None:
    assert _check_market("over_25", 2, 2) is True
    assert _check_market("over_25", 1, 1) is False
    assert _check_market("under_25", 1, 1) is True


def test_check_market_btts() -> None:
    assert _check_market("btts", 1, 1) is True
    assert _check_market("btts", 2, 0) is False
    assert _check_market("btts_no", 2, 0) is True


def test_check_market_unknown_key() -> None:
    assert _check_market("unknown_market", 1, 0) is None


def test_calibrate_without_snapshot_returns_input() -> None:
    sl = SelfLearner(session_factory=lambda: None)  # type: ignore[arg-type]
    assert sl.calibrate(0.8) == 0.8


def test_calibrate_with_empty_snapshot_returns_input() -> None:
    sl = SelfLearner(session_factory=lambda: None)  # type: ignore[arg-type]
    sl._latest = LearningSnapshot()
    assert sl.calibrate(0.8) == 0.8
