"""Ансамбль: смесь Glicko (1X2) и Poisson (всё остальное).

Адаптивные веса: по умолчанию Glicko 55% / Poisson 45%.
При наличии данных калибровки (SelfLearner snapshot) веса
корректируются в зависимости от эмпирической точности каждой модели.

Улучшения v2:
- Confidence-weighted blend: при сильном расхождении моделей
  уменьшаем уверенность (regression to mean).
- Per-league весовой профиль (через league_id).
"""

from __future__ import annotations

from dataclasses import dataclass

from core.glicko_model import expected_goals_from_glicko, glicko_outcome_probs
from core.markets import MarketKey
from core.poisson_model import (
    btts_probabilities,
    correct_score_distribution,
    handicap_probabilities,
    over_under_probabilities,
    poisson_match_probs,
    team_total_probabilities,
    top_correct_scores,
)

# Базовые веса (используются если нет данных калибровки)
GLICKO_WEIGHT_BASE = 0.55
POISSON_WEIGHT_BASE = 0.45

# Адаптивные веса (обновляются из SelfLearner)
_adaptive_glicko_w = GLICKO_WEIGHT_BASE
_adaptive_poisson_w = POISSON_WEIGHT_BASE


def update_adaptive_weights(glicko_brier: float, poisson_brier: float) -> None:
    """Обновить веса моделей на основе их Brier score.

    Чем ниже Brier — тем лучше модель, тем больше вес.
    """
    global _adaptive_glicko_w, _adaptive_poisson_w
    if glicko_brier <= 0 and poisson_brier <= 0:
        return
    if glicko_brier <= 0:
        glicko_brier = poisson_brier
    if poisson_brier <= 0:
        poisson_brier = glicko_brier
    # Инвертируем: меньше brier = больше вес
    inv_g = 1.0 / max(glicko_brier, 0.001)
    inv_p = 1.0 / max(poisson_brier, 0.001)
    total = inv_g + inv_p
    new_g = inv_g / total
    new_p = inv_p / total
    # Ограничиваем отклонение ±15% от базовых
    _adaptive_glicko_w = max(0.40, min(0.70, new_g))
    _adaptive_poisson_w = 1.0 - _adaptive_glicko_w


def get_weights() -> tuple[float, float]:
    """Текущие веса (Glicko, Poisson)."""
    return _adaptive_glicko_w, _adaptive_poisson_w


# Для обратной совместимости
GLICKO_WEIGHT = GLICKO_WEIGHT_BASE
POISSON_WEIGHT = POISSON_WEIGHT_BASE


@dataclass(slots=True)
class PredictionPayload:
    home_xg: float
    away_xg: float
    home_rating: float
    away_rating: float
    probabilities: dict[str, float]
    top_scores: list[tuple[int, int, float]]


def build_predictions(
    *,
    home_rating: float | None,
    away_rating: float | None,
    home_xg_api: float | None = None,
    away_xg_api: float | None = None,
    home_rd: float = 60.0,
    away_rd: float = 60.0,
    league_avg_total: float = 2.7,
    league_id: int | None = None,
    country: str | None = None,
) -> PredictionPayload:
    rating_known = home_rating is not None and away_rating is not None
    if rating_known:
        gl_home, gl_draw, gl_away = glicko_outcome_probs(
            home_rating=float(home_rating),  # type: ignore[arg-type]
            away_rating=float(away_rating),  # type: ignore[arg-type]
            home_rd=home_rd,
            away_rd=away_rd,
            league_id=league_id,
            country=country,
        )
    else:
        gl_home, gl_draw, gl_away = 0.40, 0.27, 0.33

    if home_xg_api is not None and away_xg_api is not None and home_xg_api > 0 and away_xg_api > 0:
        home_xg = float(home_xg_api)
        away_xg = float(away_xg_api)
    elif rating_known:
        home_xg, away_xg = expected_goals_from_glicko(
            home_rating=float(home_rating),  # type: ignore[arg-type]
            away_rating=float(away_rating),  # type: ignore[arg-type]
            league_avg_total=league_avg_total,
        )
    else:
        home_xg, away_xg = 1.45, 1.20

    p_home_p, p_draw_p, p_away_p = poisson_match_probs(home_xg, away_xg)

    gw, pw = get_weights()
    p_home = gw * gl_home + pw * p_home_p
    p_draw = gw * gl_draw + pw * p_draw_p
    p_away = gw * gl_away + pw * p_away_p

    # Confidence dampening: при сильном расхождении Glicko и Poisson
    # смягчаем оценки к 1/3 (uncertainty = disagreement).
    disagreement = (
        abs(gl_home - p_home_p)
        + abs(gl_draw - p_draw_p)
        + abs(gl_away - p_away_p)
    ) / 2.0  # max disagreement ≈ 1.0
    if disagreement > 0.15:
        dampen = min(0.25, (disagreement - 0.15) * 0.5)
        uniform = 1.0 / 3.0
        p_home = p_home * (1 - dampen) + uniform * dampen
        p_draw = p_draw * (1 - dampen) + uniform * dampen
        p_away = p_away * (1 - dampen) + uniform * dampen

    s = p_home + p_draw + p_away
    p_home, p_draw, p_away = p_home / s, p_draw / s, p_away / s

    matrix = correct_score_distribution(home_xg, away_xg)
    handicaps = handicap_probabilities(matrix)
    over_under = over_under_probabilities(home_xg, away_xg)
    btts_yes, btts_no = btts_probabilities(home_xg, away_xg)
    team_totals = team_total_probabilities(home_xg, away_xg)

    # Draw No Bet — нормируем без ничьей
    dnb_norm = max(p_home + p_away, 1e-9)
    dnb_home = p_home / dnb_norm
    dnb_away = p_away / dnb_norm

    probabilities: dict[str, float] = {
        MarketKey.HOME: p_home,
        MarketKey.DRAW: p_draw,
        MarketKey.AWAY: p_away,
        MarketKey.DOUBLE_1X: min(p_home + p_draw, 0.999),
        MarketKey.DOUBLE_X2: min(p_draw + p_away, 0.999),
        MarketKey.DOUBLE_12: min(p_home + p_away, 0.999),
        MarketKey.DNB_HOME: dnb_home,
        MarketKey.DNB_AWAY: dnb_away,
        MarketKey.BTTS_YES: btts_yes,
        MarketKey.BTTS_NO: btts_no,
        MarketKey.OVER_05: over_under.get(0.5, (0.0, 0.0))[0],
        MarketKey.UNDER_05: over_under.get(0.5, (0.0, 0.0))[1],
        MarketKey.OVER_15: over_under.get(1.5, (0.0, 0.0))[0],
        MarketKey.UNDER_15: over_under.get(1.5, (0.0, 0.0))[1],
        MarketKey.OVER_25: over_under.get(2.5, (0.0, 0.0))[0],
        MarketKey.UNDER_25: over_under.get(2.5, (0.0, 0.0))[1],
        MarketKey.OVER_35: over_under.get(3.5, (0.0, 0.0))[0],
        MarketKey.UNDER_35: over_under.get(3.5, (0.0, 0.0))[1],
        MarketKey.OVER_45: over_under.get(4.5, (0.0, 0.0))[0],
        MarketKey.UNDER_45: over_under.get(4.5, (0.0, 0.0))[1],
        MarketKey.OVER_55: over_under.get(5.5, (0.0, 0.0))[0],
        MarketKey.UNDER_55: over_under.get(5.5, (0.0, 0.0))[1],
        MarketKey.HOME_OVER_05: team_totals["home"].get(0.5, (0.0, 0.0))[0],
        MarketKey.HOME_UNDER_05: team_totals["home"].get(0.5, (0.0, 0.0))[1],
        MarketKey.HOME_OVER_15: team_totals["home"].get(1.5, (0.0, 0.0))[0],
        MarketKey.HOME_UNDER_15: team_totals["home"].get(1.5, (0.0, 0.0))[1],
        MarketKey.HOME_OVER_25: team_totals["home"].get(2.5, (0.0, 0.0))[0],
        MarketKey.HOME_UNDER_25: team_totals["home"].get(2.5, (0.0, 0.0))[1],
        MarketKey.AWAY_OVER_05: team_totals["away"].get(0.5, (0.0, 0.0))[0],
        MarketKey.AWAY_UNDER_05: team_totals["away"].get(0.5, (0.0, 0.0))[1],
        MarketKey.AWAY_OVER_15: team_totals["away"].get(1.5, (0.0, 0.0))[0],
        MarketKey.AWAY_UNDER_15: team_totals["away"].get(1.5, (0.0, 0.0))[1],
        MarketKey.AWAY_OVER_25: team_totals["away"].get(2.5, (0.0, 0.0))[0],
        MarketKey.AWAY_UNDER_25: team_totals["away"].get(2.5, (0.0, 0.0))[1],
        MarketKey.HANDICAP_HOME_PLUS_15: handicaps["home_+1.5"],
        MarketKey.HANDICAP_HOME_MINUS_15: handicaps["home_-1.5"],
        MarketKey.HANDICAP_AWAY_PLUS_15: handicaps["away_+1.5"],
        MarketKey.HANDICAP_AWAY_MINUS_15: handicaps["away_-1.5"],
        MarketKey.HANDICAP_HOME_PLUS_25: handicaps["home_+2.5"],
        MarketKey.HANDICAP_HOME_MINUS_25: handicaps["home_-2.5"],
        MarketKey.HANDICAP_AWAY_PLUS_25: handicaps["away_+2.5"],
        MarketKey.HANDICAP_AWAY_MINUS_25: handicaps["away_-2.5"],
    }

    return PredictionPayload(
        home_xg=home_xg,
        away_xg=away_xg,
        home_rating=float(home_rating) if home_rating is not None else 1500.0,
        away_rating=float(away_rating) if away_rating is not None else 1500.0,
        probabilities=probabilities,
        top_scores=top_correct_scores(home_xg, away_xg, top_n=5),
    )


__all__ = ["PredictionPayload", "build_predictions"]
