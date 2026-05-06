"""Тесты форматтеров."""

from __future__ import annotations

from datetime import UTC, datetime

from bot.formatters import (
    _emoji_for_prob,
    _human_date,
    format_balance,
    format_match_list,
    format_prediction,
)
from core.markets import MarketKey
from core.value_calculator import ValueBet
from services.prediction_service import PredictionResult


def _make_result() -> PredictionResult:
    return PredictionResult(
        game_id=1,
        home_name="Real",
        away_name="Barca",
        league_name="La Liga",
        country_raw="Spain",
        date_iso="2025-05-01T20:00:00Z",
        home_rating=1750,
        away_rating=1700,
        home_xg=1.6,
        away_xg=1.3,
        probabilities={
            MarketKey.HOME: 0.45,
            MarketKey.DRAW: 0.27,
            MarketKey.AWAY: 0.28,
            MarketKey.OVER_25: 0.55,
            MarketKey.UNDER_25: 0.45,
            MarketKey.BTTS_YES: 0.62,
            MarketKey.BTTS_NO: 0.38,
            MarketKey.DOUBLE_1X: 0.72,
            MarketKey.DOUBLE_X2: 0.55,
            MarketKey.DOUBLE_12: 0.73,
            MarketKey.OVER_15: 0.78,
            MarketKey.UNDER_15: 0.22,
            MarketKey.OVER_35: 0.30,
            MarketKey.UNDER_35: 0.70,
            MarketKey.HOME_OVER_05: 0.85,
            MarketKey.HOME_OVER_15: 0.55,
            MarketKey.AWAY_OVER_05: 0.78,
            MarketKey.AWAY_OVER_15: 0.42,
        },
        top_scores=[(1, 1, 0.114), (2, 1, 0.098), (1, 0, 0.091)],
        value_bets=[
            ValueBet("1X", 0.72, 1.45, 1.39, 4.4, True),
            ValueBet("BTTS", 0.62, 1.80, 1.61, 11.6, True),
        ],
        odds_map={MarketKey.HOME: 2.10, MarketKey.OVER_25: 1.95},
        best_odds={MarketKey.HOME: (2.15, "Pinnacle")},
    )


def test_format_prediction_contains_titles():
    text = format_prediction(_make_result(), free_left=4, bonus_left=1)
    assert "ПРОГНОЗ НА МАТЧ" in text
    assert "актуально на " in text
    assert "Real" in text and "Barca" in text
    assert "Glicko-2" in text
    assert "ТОП-15 ПРОГНОЗОВ" in text
    # раздел EV-ставок удалён из отчёта
    assert "EV СТАВОК" not in text
    assert "Бесплатных" in text and "*4*" in text


def test_format_prediction_without_glicko():
    result = _make_result()
    result.glicko_available = False
    text = format_prediction(result, free_left=0, bonus_left=0)
    assert "Glicko-2" in text
    assert "данные недоступны" in text


def test_format_prediction_includes_top_pick_block():
    text = format_prediction(_make_result(), free_left=0, bonus_left=0)
    assert "ГЛАВНЫЙ ПРОГНОЗ" in text


def test_format_prediction_hides_odds_shows_fair_hint():
    """В отчёте не должно быть коэффициентов букмекера — только fair-кф
    в подсказке о EV (1/p)."""
    text = format_prediction(_make_result(), free_left=0, bonus_left=0)
    assert "кф *" not in text  # коэффициенты скрыты
    assert "ставка EV, если коэф" in text  # подсказка 1/p


def test_format_prediction_live_mode_compact():
    result = _make_result()
    result.is_live = True
    result.current_minute = 22
    result.home_score = 1
    result.away_score = 0
    text = format_prediction(result, free_left=0, bonus_left=0)
    assert "ЛАЙВЕ" in text
    assert "(22’)" in text
    assert "1:0" in text  # лайв-счёт
    # В лайв-режиме не выводится топ-15 (только главный пик и top-1 счёт)
    assert "ТОП-15 ПРОГНОЗОВ" not in text
    assert "ГЛАВНЫЙ ПРОГНОЗ" in text
    assert "САМЫЙ ВЕРОЯТНЫЙ" in text


def test_format_prediction_filters_above_85():
    result = _make_result()
    # Поднимаем одну из вероятностей выше 85% — её не должно быть в списке.
    result.probabilities[MarketKey.DOUBLE_1X] = 0.92
    text = format_prediction(result, free_left=0, bonus_left=0)
    # 92% не должно появиться в строках с пронумерованными прогнозами
    pred_lines = [
        ln for ln in text.split("\n")
        if ln.lstrip().split(".", 1)[0].isdigit()
    ]
    for ln in pred_lines:
        assert "92.0%" not in ln, f"вероятности >85% должны быть отсечены: {ln!r}"


def test_format_prediction_top_includes_low_probabilities():
    result = _make_result()
    text = format_prediction(result, free_left=0, bonus_left=0)
    # Убеждаемся, что в топе показываются и котировки ниже 85% (у данного
    # фикстур-матча нет ставок ≥85% — должны всё равно попадать в список).
    lines = [ln for ln in text.split("\n") if ln.strip().startswith(("1.", "2.", "3."))]
    assert lines, "должны быть пронумерованные прогнозы"
    # Нет эмодзи в конце строки после процента — чистая ставка
    for ln in lines:
        assert not ln.rstrip().endswith(
            ("🔥🔥", "🔥", "✅", "⚡", "🟡", "❗")
        ), f"unexpected trailing emoji: {ln!r}"


def test_format_balance_no_subscription():
    text = format_balance(
        free=3, bonus=2, plan=None, until=None, used=0, quota=0
    )
    assert "Без подписки" in text


def test_format_balance_with_subscription():
    text = format_balance(
        free=3, bonus=2, plan="1m", until=datetime(2030, 1, 1, tzinfo=UTC),
        used=4, quota=30,
    )
    assert "01.01.2030" in text
    assert "30" in text


def test_format_match_list_empty():
    out = format_match_list([], header="📅 H")
    assert "Нет матчей" in out


def test_emoji_thresholds():
    assert _emoji_for_prob(0.95) == "🔥🔥"
    assert _emoji_for_prob(0.70) == "🔥"
    assert _emoji_for_prob(0.55) == "✅"
    assert _emoji_for_prob(0.46) == "⚡"
    assert _emoji_for_prob(0.40) == "🟡"
    assert _emoji_for_prob(0.30) == "❗"


def test_human_date_iso():
    out = _human_date("2025-05-01T20:00:00Z", tz_offset=3)
    assert "01.05.2025" in out
