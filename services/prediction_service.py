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
    adjust_for_home_advantage,
    adjust_for_injuries,
    adjust_for_last_games,
    adjust_for_profits,
    adjust_for_standings,
    merge_adjustments,
)
from core.ensemble import PredictionPayload, build_predictions
from core.value_calculator import ValueBet, ValueCalculator
from services.external_odds import (
    ExternalOddsBundle,
    NBBetClient,
    fetch_external_odds,
)
from services.odds_parser import OddsParser
from services.pinnacle_odds import PinnacleOddsClient
from services.self_learner import SelfLearner


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
    is_finished: bool = False
    home_score: int | None = None
    away_score: int | None = None
    status_code: int | None = None
    status_name: str | None = None
    is_live: bool = False
    stale_live: bool = False
    current_minute: int | None = None
    glicko_available: bool = True
    home_team_id: int | None = None
    away_team_id: int | None = None
    league_id: int | None = None
    league_avg_total: float = 2.7
    regulated: dict[str, Any] | None = None


class PredictionService:
    """Полный конвейер: данные API → ансамбль → value bets."""

    def __init__(
        self,
        client: SStatsClient,
        *,
        value_calculator: ValueCalculator,
        odds_parser: OddsParser | None = None,
        self_learner: SelfLearner | None = None,
        nb_bet_client: NBBetClient | None = None,
        pinnacle_client: PinnacleOddsClient | None = None,
        external_odds_enabled: bool = True,
    ) -> None:
        self._client = client
        self._value = value_calculator
        self._odds_parser = odds_parser or OddsParser()
        self._self_learner = self_learner
        self._nb_bet_client = nb_bet_client
        self._pinnacle_client = pinnacle_client or PinnacleOddsClient()
        self._external_odds_enabled = external_odds_enabled

    async def predict(self, game_id: int | str) -> PredictionResult | None:
        bundle = await self._client.get_full_match_data(game_id)
        game: dict[str, Any] | None = bundle.get("game")
        if not game:
            logger.warning("Прогноз: нет данных по матчу {}", game_id)
            return None

        glicko_payload: dict[str, Any] | None = bundle.get("glicko")
        odds_raw = bundle.get("odds") or []
        live_odds_raw = bundle.get("live_odds")
        # Если матч в лайве, к prematch-кфам добавляем live-кф (Pinnacle, etc).
        # Live API возвращает один объект-bookmaker, прематч — список. Объединяем.
        if isinstance(live_odds_raw, dict) and live_odds_raw:
            if isinstance(odds_raw, list):
                odds_raw = [*odds_raw, live_odds_raw]
            else:
                odds_raw = [live_odds_raw]
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
            elif glicko_payload:
                glicko_data = glicko_payload

        home_rating = _safe_float(glicko_data.get("homeRating"))
        away_rating = _safe_float(glicko_data.get("awayRating"))
        home_rd = _safe_float(glicko_data.get("homeRd")) or 60.0
        away_rd = _safe_float(glicko_data.get("awayRd")) or 60.0
        home_xg_api = _safe_float(glicko_data.get("homeXg"))
        away_xg_api = _safe_float(glicko_data.get("awayXg"))
        glicko_available = (
            home_rating is not None
            and away_rating is not None
            and (home_rating > 0 or away_rating > 0)
        )

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
            adjust_for_profits(profits),
            adjust_for_home_advantage(last_games),
        )

        if home_rating is not None:
            home_rating = home_rating + adjustments.home_rating_delta
        if away_rating is not None:
            away_rating = away_rating + adjustments.away_rating_delta
        if home_xg_api is not None:
            home_xg_api = home_xg_api * adjustments.home_xg_factor
        if away_xg_api is not None:
            away_xg_api = away_xg_api * adjustments.away_xg_factor

        # Извлекаем league_id и country для per-league калибровки
        _season = game_obj.get("season") or {}
        _league_obj = _season.get("league") if isinstance(_season, dict) else {}
        if not isinstance(_league_obj, dict):
            _league_obj = {}
        _league_id_raw = _league_obj.get("id")
        _league_id = int(_league_id_raw) if _league_id_raw is not None else None
        _country_obj = _league_obj.get("country") or game_obj.get("country") or {}
        _country_name = (
            _country_obj.get("name")
            if isinstance(_country_obj, dict)
            else str(_country_obj) if _country_obj else None
        )

        # Средний тотал по лиге из MatchResult (надёжный источник, считается фоном)
        # Fallback на season_table SStats, если LeagueAggregateService не привязан.
        from services.league_aggregate_service import DEFAULT_AVG_TOTAL

        _league_avg_total = DEFAULT_AVG_TOTAL
        _league_btts_rate: float | None = None
        _league_n_matches = 0
        try:
            from bot.context import services as _ctx

            _agg_svc = getattr(_ctx, "league_aggregates", None)
            if _agg_svc is not None and _league_id is not None:
                _stats = await _agg_svc.get(_league_id)
                if not _stats.is_default:
                    _league_avg_total = float(_stats.avg_total)
                    _league_btts_rate = float(_stats.btts_rate)
                    _league_n_matches = int(_stats.n_matches)
        except Exception as exc:  # pragma: no cover
            logger.debug("LeagueAggregateService.get failed: {}", exc)

        # Если из БД ещё не подгрузили — пробуем season_table от SStats.
        if _league_n_matches == 0 and season_table and isinstance(season_table, dict):
            _st_rows = (
                season_table.get("standings")
                or season_table.get("rows")
                or []
            )
            if isinstance(_st_rows, list) and _st_rows:
                _goals_sum = 0
                _matches_sum = 0
                for _row in _st_rows:
                    if not isinstance(_row, dict):
                        continue
                    _gf = _row.get("goalsFor") or _row.get("GF") or 0
                    _ga = _row.get("goalsAgainst") or _row.get("GA") or 0
                    _mp = _row.get("matchesPlayed") or _row.get("played") or _row.get("GP") or 0
                    try:
                        _goals_sum += int(_gf) + int(_ga)
                        _matches_sum += int(_mp)
                    except (TypeError, ValueError):
                        continue
                if _matches_sum > 0:
                    _league_avg_total = _goals_sum / _matches_sum

        prediction: PredictionPayload = build_predictions(
            home_rating=home_rating,
            away_rating=away_rating,
            home_xg_api=home_xg_api,
            away_xg_api=away_xg_api,
            home_rd=home_rd,
            away_rd=away_rd,
            league_id=_league_id,
            country=_country_name,
            league_avg_total=_league_avg_total,
        )

        # Внешние агрегаторы (NB-Bet, Flashscore) — best-effort, не блокируем.
        external_bundle: ExternalOddsBundle | None = None
        if self._external_odds_enabled:
            try:
                gid_int = int(game_id) if str(game_id).isdigit() else None
                if gid_int is not None and isinstance(odds_raw, list):
                    external_bundle = await fetch_external_odds(
                        session=self._client.session,
                        game_id=gid_int,
                        sstats_odds_raw=odds_raw,
                        nb_bet_client=self._nb_bet_client,
                    )
            except Exception as exc:
                logger.debug("external odds bundle error: {}", exc)
        if external_bundle and external_bundle.bookmakers:
            if isinstance(odds_raw, list):
                odds_raw = [*odds_raw, *external_bundle.bookmakers]
            else:
                odds_raw = list(external_bundle.bookmakers)

        # Pinnacle public API — основной источник кфов когда SStats пуст.
        if self._external_odds_enabled:
            try:
                _gobj = game_obj if isinstance(game_obj, dict) else {}
                _season = _gobj.get("season") or {}
                _league = _season.get("league") if isinstance(_season, dict) else {}
                _lid = (_league or {}).get("id") if isinstance(_league, dict) else None
                _lname = (_league or {}).get("name") if isinstance(_league, dict) else None
                _hname = home.get("name") if isinstance(home, dict) else None
                _aname = away.get("name") if isinstance(away, dict) else None
                if _hname and _aname:
                    pin_book = await self._pinnacle_client.fetch_odds_for_match(
                        session=self._client.session,
                        home_name=str(_hname),
                        away_name=str(_aname),
                        sstats_league_id=int(_lid) if isinstance(_lid, int) else None,
                        sstats_league_name=str(_lname) if _lname else None,
                    )
                    if pin_book is not None:
                        if isinstance(odds_raw, list):
                            odds_raw = [*odds_raw, pin_book]
                        else:
                            odds_raw = [pin_book]
                        logger.info(
                            "pinnacle: matched odds for {} vs {} (markets={})",
                            _hname, _aname,
                            len(pin_book.get("odds", [])),
                        )
            except Exception as exc:
                logger.debug("pinnacle odds error: {}", exc)

        odds_map = self._odds_parser.parse(odds_raw)
        best = self._odds_parser.best_per_market(odds_raw)

        probabilities = prediction.probabilities
        if self._self_learner is not None:
            try:
                probabilities = {
                    key: self._self_learner.calibrate(prob)
                    for key, prob in prediction.probabilities.items()
                }
            except Exception as exc:  # pragma: no cover - защитный блок
                logger.debug("self-learner calibrate error: {}", exc)
                probabilities = prediction.probabilities

        # P0-2: пер-рыночная изотоническая калибровка из CalibrationSnapshot.
        # Если снимка по рынку нет или sklearn не стоит — graceful passthrough.
        try:
            from bot.context import services as _ctx_services
            _calib = getattr(_ctx_services, "calibration", None)
        except Exception:
            _calib = None
        if _calib is not None:
            calibrated: dict[str, float] = {}
            for key, prob in probabilities.items():
                try:
                    calibrated[key] = await _calib.calibrate(key, prob)
                except Exception:
                    calibrated[key] = prob
            probabilities = calibrated

        # Oracle: матч-специфичные сдвиги (травмы, форма, мотивация,
        # H2H-грузы, расхождение с рынком). Применяется ПОСЛЕ калибровки —
        # калибровка делает вероятности «честными» в среднем по выборке,
        # а Oracle добавляет точечные коррекции под конкретный матч.
        try:
            from services.oracle import Oracle as _Oracle
            _oracle = _Oracle()
            probabilities = _oracle.refine(
                probabilities, bundle=bundle, odds_map=odds_map
            )
        except Exception as exc:  # pragma: no cover
            logger.debug("oracle refine error: {}", exc)

        value_bets = self._value.find_top_value(
            probabilities, odds_map, top_n=15
        )

        # Статус матча и счёт (если сыгран / в лайве)
        status_code = None
        status_name: str | None = None
        is_finished = False
        is_live = False
        current_minute: int | None = None
        home_score = None
        away_score = None
        status_raw = game_obj.get("status") if isinstance(game_obj, dict) else None
        if isinstance(status_raw, int):
            status_code = status_raw
        elif isinstance(status_raw, dict):
            code = status_raw.get("code") or status_raw.get("id")
            if isinstance(code, int):
                status_code = code
            sn = status_raw.get("name")
            if isinstance(sn, str):
                status_name = sn
        if isinstance(game_obj, dict):
            sn = game_obj.get("statusName")
            if isinstance(sn, str) and not status_name:
                status_name = sn
            elapsed = game_obj.get("elapsed")
            if isinstance(elapsed, int) and elapsed >= 0:
                current_minute = elapsed
            else:
                m = game_obj.get("minute")
                if isinstance(m, int) and m >= 0:
                    current_minute = m
        # SStats: 1 = scheduled/Not Started, 2 = pre-match phase (postponed/canceled),
        # 3 = First Half, 4 = Halftime, 5 = Second Half, 6 = Extra Time,
        # 7 = Penalty Shootout, 100+ = Finished. Лайв — только активные стадии.
        ACTIVE_STATUS_CODES = {3, 4, 5, 6, 7, 8, 9}
        ACTIVE_STATUS_NAMES = {
            "first half",
            "halftime",
            "half time",
            "second half",
            "extra time",
            "penalty shootout",
            "live",
            "in progress",
        }
        if status_code is not None:
            is_finished = status_code >= 100
            is_live = status_code in ACTIVE_STATUS_CODES
        if status_name and status_name.strip().lower() in ACTIVE_STATUS_NAMES:
            is_live = True
        if status_name and status_name.strip().lower() in {
            "not started",
            "scheduled",
            "tbd",
            "postponed",
            "cancelled",
            "canceled",
        }:
            is_live = False
        # Не считаем матч лайвом, если его старт ещё в будущем по времени.
        # Также автоматически снимаем «лайв» с матчей, у которых SStats
        # не обновил статус: прошло > 4 часов с момента старта или минута
        # ≥ 95 — матч точно завершён, даже если в JSON ещё видно 'Live'.
        stale_live = False
        if isinstance(game_obj, dict):
            from datetime import UTC as _UTC
            from datetime import datetime as _dt
            iso = game_obj.get("date")
            if isinstance(iso, str):
                try:
                    when = _dt.fromisoformat(iso.replace("Z", "+00:00"))
                    if when.tzinfo is None:
                        when = when.replace(tzinfo=_UTC)
                    now_dt = _dt.now(tz=_UTC)
                    if is_live and when > now_dt:
                        is_live = False
                    elif is_live and (now_dt - when).total_seconds() > 4 * 3600:
                        is_live = False
                        is_finished = True
                        stale_live = True
                except ValueError:
                    pass
        if is_live and current_minute is not None and current_minute >= 95:
            is_live = False
            is_finished = True
            stale_live = True
        # Попробовать достать счёт
        if isinstance(game_obj, dict):
            for k_home, k_away in (
                # SStats: основные итоговые поля.
                ("homeFTResult", "awayFTResult"),
                ("homeResult", "awayResult"),
                ("homeScore", "awayScore"),
                ("homeGoals", "awayGoals"),
                ("homeFT", "awayFT"),
            ):
                hv = game_obj.get(k_home)
                av = game_obj.get(k_away)
                if hv is not None and av is not None:
                    try:
                        home_score, away_score = int(hv), int(av)
                        break
                    except (TypeError, ValueError):
                        continue
            score_obj = game_obj.get("score")
            if home_score is None and isinstance(score_obj, dict):
                hv = score_obj.get("home") or score_obj.get("fullTimeHome")
                av = score_obj.get("away") or score_obj.get("fullTimeAway")
                try:
                    if hv is not None and av is not None:
                        home_score, away_score = int(hv), int(av)
                except (TypeError, ValueError):
                    pass
        # Фоллбэк: если в game_obj счёта нет, но матч уже завершён, попробуем
        # вытащить его из локальной таблицы MatchResult (history_backfill).
        if (
            (is_finished or stale_live)
            and home_score is None
            and away_score is None
        ):
            try:
                from sqlalchemy import select

                from bot.context import services as _ctx_services
                from db.models import MatchResult

                _sf = getattr(_ctx_services, "session_factory", None)
                if _sf is not None:
                    _sess = _sf()
                    try:
                        mr = await _sess.scalar(
                            select(MatchResult).where(
                                MatchResult.game_id == int(
                                    game_obj.get("id") or 0,
                                ),
                            ),
                        )
                        if mr is not None and mr.home_score is not None:
                            home_score = mr.home_score
                            away_score = mr.away_score
                    finally:
                        await _sess.close()
            except Exception as _mr_exc:
                logger.debug("MatchResult fallback failed: {}", _mr_exc)
        if (
            home_score is not None
            and away_score is not None
            and not is_live
        ):
            is_finished = True

        season = game_obj.get("season") or {}
        league = season.get("league") if isinstance(season, dict) else {}
        country_raw: str | None = None
        if isinstance(league, dict):
            c = league.get("country")
            if isinstance(c, dict):
                country_raw = c.get("name")
        league_name = (league or {}).get("name") if isinstance(league, dict) else None
        league_id_val: int | None = None
        if isinstance(league, dict):
            _lid = league.get("id")
            if isinstance(_lid, int):
                league_id_val = _lid

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
            probabilities=probabilities,
            top_scores=prediction.top_scores,
            value_bets=value_bets,
            odds_map=odds_map,
            best_odds=best,
            summary_text=summary_text if isinstance(summary_text, str) else None,
            profits=profits if isinstance(profits, dict) else None,
            injuries=list(injuries_raw) if isinstance(injuries_raw, list) else [],
            accuracy_notes=adjustments.notes,
            is_finished=is_finished,
            home_score=home_score,
            away_score=away_score,
            status_code=status_code,
            status_name=status_name,
            is_live=is_live,
            stale_live=stale_live,
            current_minute=current_minute,
            glicko_available=glicko_available,
            home_team_id=home_team_id if isinstance(home_team_id, int) else None,
            away_team_id=away_team_id if isinstance(away_team_id, int) else None,
            league_id=league_id_val,
            league_avg_total=_league_avg_total,
            extra={
                **({"last_games": last_games} if isinstance(last_games, dict) else {}),
                **(
                    {
                        "league_btts_rate": _league_btts_rate,
                        "league_n_matches": _league_n_matches,
                    }
                    if _league_n_matches > 0
                    else {}
                ),
            },
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
