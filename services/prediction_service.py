"""Сервис конечного прогноза по матчу.

Собирает ВСЕ доступные данные через `SStatsClient.get_full_match_data()`
(8 эндпоинтов: game, glicko, odds, injuries, last_games_stats, summary,
profits, season_table) и применяет корректировки точности через
`core.accuracy_boost`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from api.sstats_client import SStatsClient
from core.accuracy_boost import (
    AccuracyAdjustments,
    adjust_for_injuries,
    adjust_for_last_games,
    adjust_for_standings,
    merge_adjustments,
)
from core.ensemble import PredictionPayload, build_predictions
from core.value_calculator import ValueBet, ValueCalculator
from services.odds_parser import OddsParser


@dataclass(slots=True)
class PredictionResult:
    game_id: int
    home_name: str
    away_name: str
    league_name: str
    country_raw: str | None
    date_iso: str
    home_rating: float
    away_rating: float
    home_xg: float
    away_xg: float
    probabilities: dict[str, float]
    top_scores: list[tuple[int, int, float]]
    value_bets: list[ValueBet]
    odds_map: dict[str, float]
    best_odds: dict[str, tuple[float, str]]
    summary_text: str | None = None
    profits: dict[str, Any] | None = None
    injuries: list[dict[str, Any]] = field(default_factory=list)
    accuracy_notes: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


class PredictionService:
    """Полный конвейер: данные API → ансамбль → value bets."""

    def __init__(
        self,
        client: SStatsClient,
        *,
        value_calculator: ValueCalculator,
        odds_parser: OddsParser | None = None,
    ) -> None:
        self._client = client
        self._value = value_calculator
        self._odds_parser = odds_parser or OddsParser()

    async def predict(self, game_id: int | str) -> PredictionResult | None:
        bundle = await self._client.get_full_match_data(game_id)
        game: dict[str, Any] | None = bundle.get("game")
        if not game:
            logger.warning("Прогноз: нет данных по матчу {}", game_id)
            return None

        glicko_payload: dict[str, Any] | None = bundle.get("glicko")
        odds_raw = bundle.get("odds") or []
        injuries_raw = bundle.get("injuries") or []
        last_games = bundle.get("last_games")
        season_table = bundle.get("season_table")
        summary_text = bundle.get("summary")
        profits = bundle.get("profits")

        glicko_data: dict[str, Any] = {}
        if isinstance(glicko_payload, dict):
            inner = glicko_payload.get("glicko")
            if isinstance(inner, dict):
                glicko_data = inner

        home_rating = _safe_float(glicko_data.get("homeRating"))
        away_rating = _safe_float(glicko_data.get("awayRating"))
        home_rd = _safe_float(glicko_data.get("homeRd")) or 60.0
        away_rd = _safe_float(glicko_data.get("awayRd")) or 60.0
        home_xg_api = _safe_float(glicko_data.get("homeXg"))
        away_xg_api = _safe_float(glicko_data.get("awayXg"))

        # --- Извлекаем команды
        game_obj = game.get("game") if isinstance(game.get("game"), dict) else game
        if not isinstance(game_obj, dict):
            game_obj = {}
        home = game_obj.get("homeTeam") or {}
        away = game_obj.get("awayTeam") or {}
        home_team_id = home.get("id") if isinstance(home, dict) else None
        away_team_id = away.get("id") if isinstance(away, dict) else None

        # --- Применяем корректировки точности из всех эндпоинтов
        adjustments: AccuracyAdjustments = merge_adjustments(
            adjust_for_injuries(home_team_id, away_team_id, injuries_raw),
            adjust_for_last_games(last_games),
            adjust_for_standings(home_team_id, away_team_id, season_table),
        )

        if home_rating is not None:
            home_rating = home_rating + adjustments.home_rating_delta
        if away_rating is not None:
            away_rating = away_rating + adjustments.away_rating_delta
        if home_xg_api is not None:
            home_xg_api = home_xg_api * adjustments.home_xg_factor
        if away_xg_api is not None:
            away_xg_api = away_xg_api * adjustments.away_xg_factor

        prediction: PredictionPayload = build_predictions(
            home_rating=home_rating,
            away_rating=away_rating,
            home_xg_api=home_xg_api,
            away_xg_api=away_xg_api,
            home_rd=home_rd,
            away_rd=away_rd,
        )

        odds_map = self._odds_parser.parse(odds_raw)
        best = self._odds_parser.best_per_market(odds_raw)
        value_bets = self._value.find_top_value(
            prediction.probabilities, odds_map, top_n=20
        )

        season = game_obj.get("season") or {}
        league = season.get("league") if isinstance(season, dict) else {}
        country_raw: str | None = None
        if isinstance(league, dict):
            c = league.get("country")
            if isinstance(c, dict):
                country_raw = c.get("name")
        league_name = (league or {}).get("name") if isinstance(league, dict) else None

        return PredictionResult(
            game_id=int(game_obj.get("id") or 0) if isinstance(game_obj, dict) else int(str(game_id)),
            home_name=str(home.get("name") or "?"),
            away_name=str(away.get("name") or "?"),
            league_name=str(league_name or "—"),
            country_raw=country_raw,
            date_iso=str(game_obj.get("date") or ""),
            home_rating=prediction.home_rating,
            away_rating=prediction.away_rating,
            home_xg=prediction.home_xg,
            away_xg=prediction.away_xg,
            probabilities=prediction.probabilities,
            top_scores=prediction.top_scores,
            value_bets=value_bets,
            odds_map=odds_map,
            best_odds=best,
            summary_text=summary_text if isinstance(summary_text, str) else None,
            profits=profits if isinstance(profits, dict) else None,
            injuries=list(injuries_raw) if isinstance(injuries_raw, list) else [],
            accuracy_notes=adjustments.notes,
        )


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


__all__ = ["PredictionResult", "PredictionService"]
