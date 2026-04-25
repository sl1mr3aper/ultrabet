"""Сервис конечного прогноза по матчу."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from api.sstats_client import SStatsClient
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
        glicko_payload: dict[str, Any] | None = bundle.get("glicko")
        odds_raw = bundle.get("odds") or []
        if not game:
            logger.warning("Прогноз: нет данных по матчу {}", game_id)
            return None

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
        value_bets = self._value.find_top_value(prediction.probabilities, odds_map, top_n=20)

        game_obj = game.get("game") if isinstance(game.get("game"), dict) else game
        if not isinstance(game_obj, dict):
            game_obj = {}
        home = game_obj.get("homeTeam") or {}
        away = game_obj.get("awayTeam") or {}
        season = game_obj.get("season") or {}
        league = season.get("league") if isinstance(season, dict) else {}
        country_raw: str | None = None
        if isinstance(league, dict):
            c = league.get("country")
            if isinstance(c, dict):
                country_raw = c.get("name")
        league_name = (league or {}).get("name") if isinstance(league, dict) else None

        summary_text = None
        try:
            summary_text = await self._client.get_text_summary(game_id)
        except Exception as exc:
            logger.debug("summary error: {}", exc)

        profits = None
        try:
            if str(game_id).isdigit():
                profits = await self._client.get_profits(int(game_id), this_league=True, limit=25)
        except Exception as exc:
            logger.debug("profits error: {}", exc)

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
            summary_text=summary_text,
            profits=profits,
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
