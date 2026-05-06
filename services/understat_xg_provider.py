"""P0-9: загрузчик и провайдер реального xG из Understat для PredictionService.

Архитектура:

- ``UnderstatXgLoader`` — синхронизирует данные understat в локальную БД.
  Запускается как cron / фоновой задачей раз в N часов. Идемпотентна:
  uq-индекс не даёт продублировать одни и те же match_id+team.

- ``UnderstatXgProvider`` — read-side. Читает из БД последние N матчей
  команды и считает её "сглаженный xG_for / xG_against". Применяет
  rate-of-points style EWMA: новые матчи весят больше старых.

- ``estimate_match_xg(home_team, away_team, league_avg_total)`` —
  чистая функция без БД: принимает агрегированные xG-параметры команд
  и league average, возвращает (home_xg_pred, away_xg_pred). Это
  рекомендованный вход для ``ensemble.predict_match_outcome``.

Тестируется in-memory SQLite + замоканный ``UnderstatClient``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from db.models import TeamXgSample
from services.understat_client import (
    SUPPORTED_LEAGUES,
    UnderstatClient,
    UnderstatMatch,
)

# ─── Loader (write-side) ────────────────────────────────────────────────────


@dataclass(slots=True)
class LoaderResult:
    league_slug: str
    season: str
    fetched: int
    inserted: int
    skipped: int


def _parse_understat_dt(raw: str) -> datetime:
    """Understat datetime: ``2026-04-30 18:00:00`` (UTC)."""
    if not raw:
        return datetime.now(tz=UTC)
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return datetime.now(tz=UTC)


class UnderstatXgLoader:
    """Синхронизирует завершённые матчи Understat в ``team_xg_samples``."""

    def __init__(
        self,
        *,
        client: UnderstatClient,
        session_factory: Any,
        source: str = "understat",
    ) -> None:
        self._client = client
        self._session_factory = session_factory
        self._source = source

    async def sync_league(
        self,
        *,
        league_slug: str,
        season: str,
    ) -> LoaderResult:
        if league_slug not in SUPPORTED_LEAGUES:
            raise ValueError(f"unsupported league: {league_slug}")
        matches: list[UnderstatMatch] = await self._client.list_matches(
            league_slug, season
        )
        finished = [m for m in matches if m.is_finished]
        rows = list(self._build_rows(finished, league_slug=league_slug, season=season))
        if not rows:
            return LoaderResult(
                league_slug=league_slug,
                season=season,
                fetched=len(finished),
                inserted=0,
                skipped=0,
            )

        async with self._session_factory() as session:
            engine_url = str(session.bind.url)  # type: ignore[union-attr]
            if engine_url.startswith("postgres") or engine_url.startswith(
                "postgresql"
            ):
                stmt = pg_insert(TeamXgSample).values(rows)
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=["source", "match_id", "team_name"]
                )
            else:
                stmt = sqlite_insert(TeamXgSample).values(rows)
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=["source", "match_id", "team_name"]
                )
            result = await session.execute(stmt)
            await session.commit()
        inserted = int(result.rowcount or 0)
        return LoaderResult(
            league_slug=league_slug,
            season=season,
            fetched=len(finished),
            inserted=inserted,
            skipped=len(rows) - inserted,
        )

    def _build_rows(
        self,
        matches: Iterable[UnderstatMatch],
        *,
        league_slug: str,
        season: str,
    ) -> Iterable[dict[str, Any]]:
        for m in matches:
            if m.home_xg is None or m.away_xg is None:
                continue
            dt = _parse_understat_dt(m.datetime_utc)
            yield {
                "source": self._source,
                "league_slug": league_slug,
                "season": season,
                "match_id": m.match_id,
                "match_datetime": dt,
                "team_name": m.home_team,
                "is_home": True,
                "xg_for": float(m.home_xg),
                "xg_against": float(m.away_xg),
                "goals_for": m.home_goals,
                "goals_against": m.away_goals,
            }
            yield {
                "source": self._source,
                "league_slug": league_slug,
                "season": season,
                "match_id": m.match_id,
                "match_datetime": dt,
                "team_name": m.away_team,
                "is_home": False,
                "xg_for": float(m.away_xg),
                "xg_against": float(m.home_xg),
                "goals_for": m.away_goals,
                "goals_against": m.home_goals,
            }


# ─── Provider (read-side) ───────────────────────────────────────────────────


@dataclass(slots=True)
class TeamXgAverages:
    team_name: str
    n_samples: int
    xg_for_avg: float
    xg_against_avg: float


class UnderstatXgProvider:
    """Читает последние ``last_n`` матчей команды и считает EWMA xG."""

    def __init__(
        self,
        *,
        session_factory: Any,
        last_n: int = 10,
        ewma_alpha: float = 0.65,
    ) -> None:
        self._session_factory = session_factory
        self._last_n = max(1, int(last_n))
        # alpha близко к 1 → больший вес недавним; 0.65 — стандартный
        # компромисс (полупериод ≈ 2 матча).
        self._alpha = max(0.05, min(0.95, float(ewma_alpha)))

    async def get_team_averages(
        self,
        *,
        team_name: str,
        league_slug: str | None = None,
    ) -> TeamXgAverages | None:
        async with self._session_factory() as session:
            stmt = (
                select(
                    TeamXgSample.match_datetime,
                    TeamXgSample.xg_for,
                    TeamXgSample.xg_against,
                )
                .where(TeamXgSample.team_name == team_name)
                .order_by(TeamXgSample.match_datetime.desc())
                .limit(self._last_n)
            )
            if league_slug is not None:
                stmt = stmt.where(TeamXgSample.league_slug == league_slug)
            rows = (await session.execute(stmt)).all()
        if not rows:
            return None
        rows = list(reversed(rows))  # старые → новые для EWMA
        ewma_for = float(rows[0].xg_for)
        ewma_against = float(rows[0].xg_against)
        for r in rows[1:]:
            ewma_for = self._alpha * float(r.xg_for) + (1 - self._alpha) * ewma_for
            ewma_against = (
                self._alpha * float(r.xg_against)
                + (1 - self._alpha) * ewma_against
            )
        return TeamXgAverages(
            team_name=team_name,
            n_samples=len(rows),
            xg_for_avg=ewma_for,
            xg_against_avg=ewma_against,
        )

    async def get_match_xg_estimate(
        self,
        *,
        home_team: str,
        away_team: str,
        league_slug: str | None = None,
        league_avg_total: float = 2.7,
        home_advantage_goals: float = 0.25,
    ) -> tuple[float, float] | None:
        """Базовая модель: home_xG ≈ (home.xg_for_avg + away.xg_against_avg) / 2,
        затем добавляем home advantage.

        Если у одной из команд нет достаточно данных (≥ 3 матчей) — None,
        чтобы вызывающий код отступил на старую логику.
        """
        h_avg = await self.get_team_averages(
            team_name=home_team, league_slug=league_slug
        )
        a_avg = await self.get_team_averages(
            team_name=away_team, league_slug=league_slug
        )
        if h_avg is None or a_avg is None:
            return None
        if h_avg.n_samples < 3 or a_avg.n_samples < 3:
            return None
        # Регрессия к среднему: при малой выборке (3-5 игр) подмешиваем
        # league average. Полностью доверяем при n=10+.
        def _shrink(avg_val: float, n: int, league_baseline: float) -> float:
            credibility = min(1.0, n / 10.0)
            return credibility * avg_val + (1.0 - credibility) * league_baseline

        baseline = league_avg_total / 2.0
        h_for = _shrink(h_avg.xg_for_avg, h_avg.n_samples, baseline)
        h_against = _shrink(h_avg.xg_against_avg, h_avg.n_samples, baseline)
        a_for = _shrink(a_avg.xg_for_avg, a_avg.n_samples, baseline)
        a_against = _shrink(a_avg.xg_against_avg, a_avg.n_samples, baseline)
        # Симметричная оценка: home_xg = avg(home.xg_for, away.xg_against),
        # away_xg = avg(away.xg_for, home.xg_against).
        home_xg = (h_for + a_against) / 2.0 + home_advantage_goals
        away_xg = (a_for + h_against) / 2.0 - home_advantage_goals
        # Ограничиваем разумным интервалом, как и tanh-fallback.
        home_xg = max(0.20, min(home_xg, 5.0))
        away_xg = max(0.20, min(away_xg, 5.0))
        return home_xg, away_xg


# ─── Чистая функция (для удобного тестирования) ────────────────────────────


def estimate_match_xg_from_avgs(
    *,
    home_for: float,
    home_against: float,
    away_for: float,
    away_against: float,
    home_advantage_goals: float = 0.25,
) -> tuple[float, float]:
    """Без БД: симметричная оценка из агрегатов команд."""
    home_xg = (home_for + away_against) / 2.0 + home_advantage_goals
    away_xg = (away_for + home_against) / 2.0 - home_advantage_goals
    return max(0.2, home_xg), max(0.2, away_xg)


__all__ = [
    "LoaderResult",
    "TeamXgAverages",
    "UnderstatXgLoader",
    "UnderstatXgProvider",
    "estimate_match_xg_from_avgs",
]


# Suppress "unused import" warning for `and_`, used for advanced filtering
# in subclasses (kept for forward compatibility).
_ = and_
