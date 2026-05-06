"""Сервис расчёта и получения агрегатов лиги.

Считаем из `MatchResult` (нашей реплики истории, которую заполняет
``services.history_backfill``) — это значительно надёжнее, чем
``season_table`` от SStats, который для половины лиг приходит пустым.

Используется:
* `PredictionService` — `league_avg_total` подставляется в xG-расчёт
  и в отчёт «Ср. тотал лиги: X.XX».
* `MarketFilter` — `btts_rate` / `over_25_rate` для отсечения рынков с
  плохим ROI.
* админ-панель — сводная таблица «средние показатели лиг».

API синхронный с асинхронными методами: один глобальный singleton с
in-memory кэшем (TTL 6h) и фоновое обновление раз в 6 часов.

Покрытие ВСЕХ лиг — каскадный fallback:
  1) Точный league_id → MatchResult ≥ _MIN_MATCHES.
  2) league_id → MatchResult ≥ _MIN_SOFT_MATCHES (5+) — soft-stats.
  3) Усреднение по стране (country_average) — для новых лиг страны.
  4) Глобальное среднее (по всем посчитанным лигам).
  5) Хардкод DEFAULT_AVG_TOTAL=2.65.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import LeagueAggregate, MatchResult

# Минимум матчей для статистически значимого агрегата.
_MIN_MATCHES = 10
# «Мягкий» минимум — если есть 5+ матчей, считаем агрегат с пометкой
# n_matches и применяем shrinkage в моделях.
_MIN_SOFT_MATCHES = 5
# Сколько последних матчей берём (приоритет свежим сезонам).
_LOOKBACK_MATCHES = 200
_CACHE_TTL_SECONDS = 6 * 3600
# Дефолтные значения, когда лиги нет в кэше / БД (общие футбольные средние).
DEFAULT_AVG_TOTAL = 2.65
DEFAULT_BTTS_RATE = 0.51
DEFAULT_HOME_WIN_RATE = 0.45
DEFAULT_DRAW_RATE = 0.25
DEFAULT_OVER_25_RATE = 0.52


@dataclass(slots=True, frozen=True)
class LeagueStats:
    league_id: int | None
    n_matches: int
    avg_total: float
    avg_home: float
    avg_away: float
    btts_rate: float
    home_win_rate: float
    draw_rate: float
    over_25_rate: float
    is_default: bool = False  # True если данных нет, отдаём дефолт

    @property
    def expected_total(self) -> float:
        """Ожидаемый суммарный xG для лиги (среднее тоталов)."""
        return self.avg_total

    @classmethod
    def default(cls) -> LeagueStats:
        return cls(
            league_id=None,
            n_matches=0,
            avg_total=DEFAULT_AVG_TOTAL,
            avg_home=DEFAULT_AVG_TOTAL / 2 + 0.15,
            avg_away=DEFAULT_AVG_TOTAL / 2 - 0.15,
            btts_rate=DEFAULT_BTTS_RATE,
            home_win_rate=DEFAULT_HOME_WIN_RATE,
            draw_rate=DEFAULT_DRAW_RATE,
            over_25_rate=DEFAULT_OVER_25_RATE,
            is_default=True,
        )


class LeagueAggregateService:
    """Считает агрегаты по лигам и кэширует их.

    Ленивая инициализация: при первом обращении к лиге, если данных нет
    в `LeagueAggregate` или они устарели — пересчитываем из MatchResult.
    Фоновую перепрошивку запускают через ``recompute_all`` раз в 6 часов.
    """

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory
        self._cache: dict[int, tuple[LeagueStats, datetime]] = {}
        # Каскадные fallback'и: страна → глобальное среднее.
        # Заполняются при `recompute_all` и обновляются раз в 6 часов.
        self._country_cache: dict[str, LeagueStats] = {}
        self._global_stats: LeagueStats | None = None

    async def get(self, league_id: int | None, country: str | None = None) -> LeagueStats:
        """Получить агрегат лиги. Каскадный fallback покрывает ВСЕ лиги:
          1) league_id из MatchResult (≥10 матчей);
          2) league_id с soft-stats (5+ матчей, помечен n_matches);
          3) среднее по стране (country_average);
          4) глобальное среднее по всем посчитанным лигам;
          5) DEFAULT_AVG_TOTAL=2.65 как последнее.
        """
        if league_id is None:
            return self._fallback_stats(country=country)
        # In-memory кэш
        cached = self._cache.get(league_id)
        if cached is not None:
            stats, fetched_at = cached
            if (datetime.now(tz=UTC) - fetched_at).total_seconds() < _CACHE_TTL_SECONDS:
                return stats

        session: AsyncSession = self._session_factory()
        try:
            row = await session.scalar(
                select(LeagueAggregate).where(LeagueAggregate.league_id == league_id)
            )
            if row is not None and (row.n_matches or 0) >= _MIN_MATCHES:
                # SQLite часто возвращает naive datetime; нормализуем к UTC.
                _updated_at = row.updated_at
                if _updated_at is not None and _updated_at.tzinfo is None:
                    _updated_at = _updated_at.replace(tzinfo=UTC)
                if _updated_at is not None and (
                    datetime.now(tz=UTC) - _updated_at
                ) < timedelta(seconds=_CACHE_TTL_SECONDS):
                    stats = self._row_to_stats(row)
                    self._cache[league_id] = (stats, datetime.now(tz=UTC))
                    return stats
        finally:
            await session.close()

        # Нет в БД или устарело — считаем заново
        stats = await self._recompute_one(league_id)
        if stats.is_default:
            stats = self._fallback_stats(country=country, league_id=league_id)
        self._cache[league_id] = (stats, datetime.now(tz=UTC))
        return stats

    def _fallback_stats(
        self, *, country: str | None = None, league_id: int | None = None,
    ) -> LeagueStats:
        """Каскадный fallback покрытия: country → global → DEFAULT.

        Используется когда у league_id < _MIN_SOFT_MATCHES сыгранных матчей
        (новая лига). Возвращает стат по стране, если есть; иначе
        глобальное среднее; иначе хардкод 2.65.
        """
        if country:
            cs = self._country_cache.get(country.strip().lower())
            if cs is not None and cs.n_matches >= _MIN_MATCHES:
                # Подменяем league_id в копии — для отчёта.
                return LeagueStats(
                    league_id=league_id,
                    n_matches=cs.n_matches,
                    avg_total=cs.avg_total,
                    avg_home=cs.avg_home,
                    avg_away=cs.avg_away,
                    btts_rate=cs.btts_rate,
                    home_win_rate=cs.home_win_rate,
                    draw_rate=cs.draw_rate,
                    over_25_rate=cs.over_25_rate,
                    is_default=True,  # помечаем как fallback
                )
        if self._global_stats is not None and self._global_stats.n_matches >= _MIN_MATCHES:
            gs = self._global_stats
            return LeagueStats(
                league_id=league_id,
                n_matches=gs.n_matches,
                avg_total=gs.avg_total,
                avg_home=gs.avg_home,
                avg_away=gs.avg_away,
                btts_rate=gs.btts_rate,
                home_win_rate=gs.home_win_rate,
                draw_rate=gs.draw_rate,
                over_25_rate=gs.over_25_rate,
                is_default=True,
            )
        return LeagueStats.default()

    async def _recompute_one(self, league_id: int) -> LeagueStats:
        """Пересчитать один league_id из MatchResult."""
        session: AsyncSession = self._session_factory()
        try:
            rows = (
                await session.scalars(
                    select(MatchResult)
                    .where(
                        MatchResult.league_id == league_id,
                        MatchResult.home_score.is_not(None),
                        MatchResult.away_score.is_not(None),
                    )
                    .order_by(MatchResult.date.desc())
                    .limit(_LOOKBACK_MATCHES)
                )
            ).all()
            if len(rows) < _MIN_SOFT_MATCHES:
                return LeagueStats.default()

            n = len(rows)
            sum_h = sum_a = 0
            btts = home_w = draws = over25 = 0
            for r in rows:
                h, a = int(r.home_score), int(r.away_score)
                sum_h += h
                sum_a += a
                total = h + a
                if h > 0 and a > 0:
                    btts += 1
                if h > a:
                    home_w += 1
                elif h == a:
                    draws += 1
                if total > 2.5:
                    over25 += 1
            avg_h = sum_h / n
            avg_a = sum_a / n
            stats = LeagueStats(
                league_id=league_id,
                n_matches=n,
                avg_total=avg_h + avg_a,
                avg_home=avg_h,
                avg_away=avg_a,
                btts_rate=btts / n,
                home_win_rate=home_w / n,
                draw_rate=draws / n,
                over_25_rate=over25 / n,
            )

            # Сохраняем в БД (upsert)
            existing = await session.scalar(
                select(LeagueAggregate).where(LeagueAggregate.league_id == league_id)
            )
            league_name = rows[0].league_name if rows else None
            country_name = rows[0].country_name if rows else None
            if existing is not None:
                existing.n_matches = n
                existing.avg_total_goals = stats.avg_total
                existing.avg_home_goals = stats.avg_home
                existing.avg_away_goals = stats.avg_away
                existing.btts_rate = stats.btts_rate
                existing.home_win_rate = stats.home_win_rate
                existing.draw_rate = stats.draw_rate
                existing.over_25_rate = stats.over_25_rate
                existing.league_name = league_name or existing.league_name
                existing.country_name = country_name or existing.country_name
                existing.updated_at = datetime.now(tz=UTC)
            else:
                session.add(
                    LeagueAggregate(
                        league_id=league_id,
                        league_name=league_name,
                        country_name=country_name,
                        n_matches=n,
                        avg_total_goals=stats.avg_total,
                        avg_home_goals=stats.avg_home,
                        avg_away_goals=stats.avg_away,
                        btts_rate=stats.btts_rate,
                        home_win_rate=stats.home_win_rate,
                        draw_rate=stats.draw_rate,
                        over_25_rate=stats.over_25_rate,
                    )
                )
            await session.commit()
            return stats
        except Exception as exc:
            logger.exception("LeagueAggregateService._recompute_one failed: {}", exc)
            await session.rollback()
            return LeagueStats.default()
        finally:
            await session.close()

    async def recompute_all(self) -> int:
        """Перерасчёт по всем лигам, у которых есть MatchResult.

        Запускается фоном раз в 6 часов. Возвращает количество
        обновлённых агрегатов.
        """
        session: AsyncSession = self._session_factory()
        try:
            from sqlalchemy import distinct

            league_ids_rows = await session.scalars(
                select(distinct(MatchResult.league_id)).where(
                    MatchResult.league_id.is_not(None),
                    MatchResult.home_score.is_not(None),
                    MatchResult.away_score.is_not(None),
                )
            )
            league_ids = [int(lid) for lid in league_ids_rows.all() if lid is not None]
        finally:
            await session.close()

        updated = 0
        from core.glicko_model import (
            calibrate_home_advantage_from_winrate,
            set_league_home_advantage,
        )
        for lid in league_ids:
            try:
                stats = await self._recompute_one(lid)
                if not stats.is_default:
                    updated += 1
                    # Per-league Glicko home_advantage из реальной home_win_rate.
                    # Только при достаточной выборке (≥30 матчей), иначе шум.
                    if stats.n_matches >= 30:
                        ha = calibrate_home_advantage_from_winrate(stats.home_win_rate)
                        set_league_home_advantage(lid, ha)
            except Exception as exc:  # pragma: no cover
                logger.debug("recompute_all error for league {}: {}", lid, exc)
        # После расчёта всех лиг — обновляем country_cache и global_stats,
        # чтобы _fallback_stats использовал актуальные средние.
        try:
            await self._refresh_country_and_global_caches()
        except Exception as exc:  # pragma: no cover
            logger.debug("refresh country/global caches failed: {}", exc)
        if updated > 0:
            logger.info(
                "LeagueAggregateService: пересчитано {} лиг (per-league Glicko HA откалиброван для лиг с ≥30 матчей)",
                updated,
            )
        return updated

    async def _refresh_country_and_global_caches(self) -> None:
        """Считаем средние «по стране» и «по всему миру» из LeagueAggregate.

        Country cache: для каждой страны — взвешенное (по n_matches)
        среднее по всем её лигам.
        Global cache: то же по всем лигам мира.
        """
        session: AsyncSession = self._session_factory()
        try:
            rows = (
                await session.scalars(
                    select(LeagueAggregate).where(
                        LeagueAggregate.n_matches.is_not(None),
                        LeagueAggregate.n_matches >= _MIN_SOFT_MATCHES,
                    )
                )
            ).all()
            country_buckets: dict[str, list[LeagueAggregate]] = {}
            for row in rows:
                cn = (row.country_name or "").strip().lower()
                if cn:
                    country_buckets.setdefault(cn, []).append(row)
            new_country_cache: dict[str, LeagueStats] = {}
            for cn, bucket in country_buckets.items():
                merged = self._merge_aggregates(bucket)
                if merged is not None:
                    new_country_cache[cn] = merged
            self._country_cache = new_country_cache
            merged_all = self._merge_aggregates(list(rows))
            if merged_all is not None:
                self._global_stats = merged_all
        finally:
            await session.close()

    @staticmethod
    def _merge_aggregates(rows: list[LeagueAggregate]) -> LeagueStats | None:
        """Взвешенное по n_matches усреднение нескольких LeagueAggregate."""
        if not rows:
            return None
        total_n = sum(int(r.n_matches or 0) for r in rows)
        if total_n <= 0:
            return None

        def _w(values: list[tuple[float | None, int]], default: float) -> float:
            num = 0.0
            for v, weight in values:
                num += (float(v) if v is not None else default) * float(weight)
            return num / total_n

        weights = [(r.n_matches or 0) for r in rows]
        avg_total = _w(
            [(r.avg_total_goals, w) for r, w in zip(rows, weights, strict=True)], DEFAULT_AVG_TOTAL
        )
        avg_home = _w(
            [(r.avg_home_goals, w) for r, w in zip(rows, weights, strict=True)],
            DEFAULT_AVG_TOTAL / 2 + 0.15,
        )
        avg_away = _w(
            [(r.avg_away_goals, w) for r, w in zip(rows, weights, strict=True)],
            DEFAULT_AVG_TOTAL / 2 - 0.15,
        )
        btts = _w(
            [(r.btts_rate, w) for r, w in zip(rows, weights, strict=True)], DEFAULT_BTTS_RATE
        )
        hw = _w(
            [(r.home_win_rate, w) for r, w in zip(rows, weights, strict=True)], DEFAULT_HOME_WIN_RATE
        )
        dr = _w([(r.draw_rate, w) for r, w in zip(rows, weights, strict=True)], DEFAULT_DRAW_RATE)
        o25 = _w(
            [(r.over_25_rate, w) for r, w in zip(rows, weights, strict=True)], DEFAULT_OVER_25_RATE
        )
        return LeagueStats(
            league_id=None,
            n_matches=total_n,
            avg_total=avg_total,
            avg_home=avg_home,
            avg_away=avg_away,
            btts_rate=btts,
            home_win_rate=hw,
            draw_rate=dr,
            over_25_rate=o25,
        )

    @staticmethod
    def _row_to_stats(row: LeagueAggregate) -> LeagueStats:
        return LeagueStats(
            league_id=row.league_id,
            n_matches=row.n_matches or 0,
            avg_total=row.avg_total_goals or DEFAULT_AVG_TOTAL,
            avg_home=row.avg_home_goals or (DEFAULT_AVG_TOTAL / 2 + 0.15),
            avg_away=row.avg_away_goals or (DEFAULT_AVG_TOTAL / 2 - 0.15),
            btts_rate=row.btts_rate if row.btts_rate is not None else DEFAULT_BTTS_RATE,
            home_win_rate=(
                row.home_win_rate if row.home_win_rate is not None else DEFAULT_HOME_WIN_RATE
            ),
            draw_rate=row.draw_rate if row.draw_rate is not None else DEFAULT_DRAW_RATE,
            over_25_rate=(
                row.over_25_rate if row.over_25_rate is not None else DEFAULT_OVER_25_RATE
            ),
        )


__all__ = ["DEFAULT_AVG_TOTAL", "LeagueAggregateService", "LeagueStats"]
