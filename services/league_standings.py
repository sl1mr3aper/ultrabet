"""Сервис: автообновление турнирных таблиц лиг.

Назначение:
- Раз в час фоном тянем стэндинги по всем активным лигам и сохраняем
  в БД (`LeagueStanding`).
- Inline-запросы (открытие вкладки «📋 Турнирная таблица») сначала
  читают из БД (моментально), а если кэш пуст или устарел —
  fallback на источник.
- Кэш используется ещё и в `core.prediction.adjust_for_standings`
  для коррекции вероятностей.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.sstats_client import SStatsClient
from db.models import LeagueStanding, MatchResult


@dataclass(slots=True)
class StandingRow:
    """Одна строка турнирной таблицы — для UI и для коррекции прогнозов."""

    rank: int
    team_id: int
    team_name: str
    played: int
    points: int
    wins: int
    draws: int
    losses: int
    goals_for: int
    goals_against: int
    goal_diff: int


def _as_int(v: Any, default: int = 0) -> int:
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if isinstance(v, str):
        try:
            return int(float(v))
        except ValueError:
            return default
    return default


class LeagueStandingsService:
    """Кэширующий сервис турнирных таблиц.

    - `get_for_league(league_id, force_refresh=False)` → список строк.
      По умолчанию читаем из БД (если запись свежая — ≤ TTL), иначе
      идём в источник и обновляем кэш.
    - `sync_league(league_id)` → обновить таблицу одной лиги (форс).
    - `sync_all(league_ids)` → пробежаться фоном по списку лиг.
    """

    DEFAULT_TTL = timedelta(hours=2)

    def __init__(
        self,
        client: SStatsClient,
        session_factory: Any,
        *,
        ttl: timedelta | None = None,
        concurrency: int = 1,
    ) -> None:
        self._client = client
        self._session_factory = session_factory
        self._ttl = ttl or self.DEFAULT_TTL
        # Concurrency=1 — критично: иначе фоновый цикл standings создаёт пачку
        # одновременных write-транзакций в SQLite и пользовательские запросы
        # (INSERT prediction_logs и т.п.) валятся с «database is locked».
        self._sem = asyncio.Semaphore(max(1, concurrency))

    # ── Публичные ─────────────────────────────────────────

    async def get_for_league(
        self,
        league_id: int,
        *,
        force_refresh: bool = False,
        league_name: str | None = None,
        country_name: str | None = None,
    ) -> list[StandingRow]:
        """Вернуть таблицу лиги. Сначала пробуем кэш, иначе тянем от источника."""
        if not force_refresh:
            cached = await self._read_cached(league_id)
            if cached is not None:
                return cached
        rows = await self._fetch_from_source(int(league_id))
        if rows:
            await self._save(
                league_id=int(league_id),
                rows=rows,
                league_name=league_name,
                country_name=country_name,
                season_uid=None,
            )
        else:
            # Если источник вернул пусто — отдаём то, что осталось в кэше
            # (возможно устаревшее), чтобы UI не пустовал.
            cached = await self._read_cached(league_id, ignore_ttl=True)
            if cached is not None:
                return cached
        return rows

    async def sync_league(
        self,
        league_id: int,
        *,
        league_name: str | None = None,
        country_name: str | None = None,
    ) -> int:
        """Обновить таблицу одной лиги. Возвращает количество строк."""
        async with self._sem:
            try:
                rows = await self._fetch_from_source(int(league_id))
            except Exception as exc:
                logger.debug(
                    "standings: fetch league={} failed: {}", league_id, exc,
                )
                return 0
        if not rows:
            return 0
        await self._save(
            league_id=int(league_id),
            rows=rows,
            league_name=league_name,
            country_name=country_name,
            season_uid=None,
        )
        return len(rows)

    async def sync_all(
        self, leagues: list[dict[str, Any]] | None = None,
    ) -> int:
        """Прогнать обновление по списку лиг. Если список не передан —
        берём топ из источника. Возвращает суммарное количество обновлённых
        строк по всем лигам.
        """
        if not leagues:
            try:
                leagues = await self._client.list_leagues()
            except Exception as exc:
                logger.debug("standings: list_leagues failed: {}", exc)
                return 0
        leagues = leagues or []
        total = 0
        # Слегка ограничим скорость: концуррентность задана семафором.
        async def _one(lg: dict[str, Any]) -> int:
            league_id = lg.get("id")
            if not isinstance(league_id, int):
                return 0
            cobj = lg.get("country") if isinstance(lg.get("country"), dict) else {}
            cname = cobj.get("name") if isinstance(cobj, dict) else None
            return await self.sync_league(
                int(league_id),
                league_name=lg.get("name"),
                country_name=cname,
            )

        # Берём только лиги, у которых есть country и name — отсекает
        # «мусорные» записи источника.
        candidates = [
            lg for lg in leagues
            if isinstance(lg, dict) and lg.get("id") and lg.get("name")
        ]
        # Не более 60 лиг за один проход — мы запускаемся раз в час, и для
        # популярных турниров этого хватит, остальные подтянутся в
        # следующих циклах. Параллелизм отключён (см. семафор=1) —
        # последовательный обход не нагружает SQLite write-lock.
        candidates = candidates[:60]
        if not candidates:
            return 0
        for lg in candidates:
            try:
                added = await _one(lg)
                total += added
            except Exception as exc:
                logger.debug("standings: sync_all item failed: {}", exc)
            # Небольшая пауза, чтобы не долбить источник и оставлять
            # окно для пользовательских запросов в SQLite.
            await asyncio.sleep(0.25)
        if total:
            logger.info(
                "standings: обновлено {} строк по {} лигам",
                total, len(candidates),
            )
        return total

    # ── Внутренние ────────────────────────────────────────

    async def _fetch_from_source(self, league_id: int) -> list[StandingRow]:
        """Тянем турнирную таблицу через `/Games/season-table?year=&league=`.

        Этот эндпоинт стабильно отдаёт данные (в отличие от /Ls/Seasons,
        который часто пуст). Формат: `{"data": {"<teamId>": {...stats...}}}`.
        Имена команд в этом ответе НЕТ — подтягиваем их из локальной
        `match_results` (там игры этих команд уже есть с именами).
        """
        # Пробуем текущий и предыдущий «год» — sstats считает год началом
        # сезона, и для сезона 2024-2025 это 2025 (так показал зонд).
        now = datetime.now(tz=UTC)
        years_to_try = [now.year, now.year - 1, now.year + 1]
        teams_dict: dict[str, Any] = {}
        for year in years_to_try:
            try:
                payload = await self._client.get_season_table_by_league(
                    year=year, league_id=int(league_id),
                )
            except Exception as exc:
                logger.debug(
                    "standings: season-table league={} year={} failed: {}",
                    league_id, year, exc,
                )
                continue
            if isinstance(payload, dict) and payload:
                teams_dict = payload
                break
        if not teams_dict:
            return []

        # Имена команд:
        #  1) сначала из локальной `match_results` (быстро, оффлайн);
        #  2) недостающие добиваем через `Teams/{id}` источника
        #     (с кэшом 1ч). Параллельно для всей пачки.
        team_ids = [int(tid) for tid in teams_dict if str(tid).lstrip("-").isdigit()]
        names = await self._team_names(team_ids)
        missing = [tid for tid in team_ids if tid not in names]
        if missing:
            await self._fill_names_from_source(missing, names)

        out: list[StandingRow] = []
        for tid_str, stats in teams_dict.items():
            if not isinstance(stats, dict):
                continue
            try:
                tid = int(tid_str)
            except (ValueError, TypeError):
                continue
            rank = _as_int(stats.get("rank"), default=99)
            played = _as_int(stats.get("totalGames"), default=0)
            points = _as_int(stats.get("points"), default=0)
            wins = _as_int(stats.get("wins"), default=0)
            draws = _as_int(stats.get("draws"), default=0)
            losses = _as_int(stats.get("loss") or stats.get("losses"), default=0)
            gf = _as_int(
                stats.get("goalsScored") or stats.get("scored"), default=0,
            )
            ga = _as_int(
                stats.get("goalsMissed") or stats.get("missed"), default=0,
            )
            gd_raw = stats.get("scoreDiff")
            gd = _as_int(gd_raw, default=gf - ga)
            name = names.get(tid) or f"Команда #{tid}"
            out.append(StandingRow(
                rank=rank,
                team_id=tid,
                team_name=name,
                played=played,
                points=points,
                wins=wins,
                draws=draws,
                losses=losses,
                goals_for=gf,
                goals_against=ga,
                goal_diff=gd,
            ))
        out.sort(key=lambda r: (r.rank, -r.points))
        return out

    async def _fill_names_from_source(
        self, team_ids: list[int], names: dict[int, str],
    ) -> None:
        """Дотянуть имена команд через `Teams/{id}` источника.

        Имена там стабильны (например `Manchester United`), так что
        можно агрессивно кэшировать. Параллелим запросы через
        `asyncio.gather` с лимитом для дружелюбия к источнику.
        """
        sem = asyncio.Semaphore(8)

        async def _one(tid: int) -> tuple[int, str | None]:
            async with sem:
                try:
                    payload = await self._client.get_team(tid)
                except Exception as exc:
                    logger.debug(
                        "standings: get_team({}) failed: {}", tid, exc,
                    )
                    return tid, None
            if not isinstance(payload, dict):
                return tid, None
            # Источник иногда отдаёт имя в `name`/`title`/вложенном `team.name`.
            for key in ("name", "title", "displayName"):
                v = payload.get(key)
                if isinstance(v, str) and v.strip():
                    return tid, v.strip()
            inner = payload.get("team")
            if isinstance(inner, dict):
                for key in ("name", "title", "displayName"):
                    v = inner.get(key)
                    if isinstance(v, str) and v.strip():
                        return tid, v.strip()
            return tid, None

        try:
            results = await asyncio.gather(
                *(_one(tid) for tid in team_ids),
                return_exceptions=True,
            )
        except Exception as exc:
            logger.debug("standings: fill_names gather failed: {}", exc)
            return
        for r in results:
            if isinstance(r, BaseException):
                continue
            tid, name = r
            if name and tid not in names:
                names[tid] = name

    async def _team_names(self, team_ids: list[int]) -> dict[int, str]:
        """Подтянуть team_id → name из match_results (последняя встреча команды)."""
        if not team_ids:
            return {}
        session: AsyncSession = self._session_factory()
        try:
            # Из match_results: для каждого team_id берём самое свежее
            # имя (home_name если home_id совпал, иначе away_name).
            stmt_home = (
                select(MatchResult.home_id, MatchResult.home_name, MatchResult.date)
                .where(MatchResult.home_id.in_(team_ids))
                .where(MatchResult.home_name.is_not(None))
                .order_by(MatchResult.date.desc())
            )
            stmt_away = (
                select(MatchResult.away_id, MatchResult.away_name, MatchResult.date)
                .where(MatchResult.away_id.in_(team_ids))
                .where(MatchResult.away_name.is_not(None))
                .order_by(MatchResult.date.desc())
            )
            home_rows = (await session.execute(stmt_home)).all()
            away_rows = (await session.execute(stmt_away)).all()
        except Exception as exc:
            logger.debug("standings: team_names lookup failed: {}", exc)
            return {}
        finally:
            await session.close()
        names: dict[int, str] = {}
        # Берём самое свежее имя; .order_by desc → первое попавшееся
        for tid, name, _date in home_rows:
            if tid is not None and tid not in names and name:
                names[int(tid)] = str(name)
        for tid, name, _date in away_rows:
            if tid is not None and tid not in names and name:
                names[int(tid)] = str(name)
        return names

    async def _read_cached(
        self, league_id: int, *, ignore_ttl: bool = False,
    ) -> list[StandingRow] | None:
        session: AsyncSession = self._session_factory()
        try:
            rows = list(
                await session.scalars(
                    select(LeagueStanding)
                    .where(LeagueStanding.league_id == int(league_id))
                    .order_by(LeagueStanding.team_rank.asc())
                )
            )
        finally:
            await session.close()
        if not rows:
            return None
        if not ignore_ttl:
            updated = max(
                (r.updated_at for r in rows if r.updated_at is not None),
                default=None,
            )
            if updated is None:
                return None
            now = datetime.now(tz=UTC)
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=UTC)
            if now - updated > self._ttl:
                return None
            # Если в кэше большинство имён — placeholder вида «Команда #123»
            # (это значит, в момент последнего сохранения у нас ещё не было
            # реальных имён), считаем кэш устаревшим и переидём в источник.
            placeholder = sum(
                1 for r in rows
                if r.team_name and r.team_name.startswith("Команда #")
            )
            if placeholder >= max(1, len(rows) // 2):
                return None
        return [
            StandingRow(
                rank=r.team_rank,
                team_id=r.team_id,
                team_name=r.team_name,
                played=r.played,
                points=r.points,
                wins=r.wins,
                draws=r.draws,
                losses=r.losses,
                goals_for=r.goals_for,
                goals_against=r.goals_against,
                goal_diff=r.goal_diff,
            )
            for r in rows
        ]

    async def _save(
        self,
        *,
        league_id: int,
        rows: list[StandingRow],
        league_name: str | None,
        country_name: str | None,
        season_uid: str | None,
    ) -> None:
        if not rows:
            return
        session: AsyncSession = self._session_factory()
        try:
            # Простая стратегия: удалить и записать заново. Таблица маленькая,
            # это надёжнее, чем bulk upsert с ручным мерджем по ключу.
            await session.execute(
                delete(LeagueStanding).where(
                    LeagueStanding.league_id == int(league_id)
                )
            )
            now = datetime.now(tz=UTC)
            for r in rows:
                session.add(
                    LeagueStanding(
                        league_id=int(league_id),
                        season_uid=season_uid,
                        team_id=int(r.team_id),
                        team_name=r.team_name,
                        team_rank=int(r.rank),
                        played=int(r.played),
                        points=int(r.points),
                        wins=int(r.wins),
                        draws=int(r.draws),
                        losses=int(r.losses),
                        goals_for=int(r.goals_for),
                        goals_against=int(r.goals_against),
                        goal_diff=int(r.goal_diff),
                        country_name=country_name,
                        league_name=league_name,
                        updated_at=now,
                    )
                )
            await session.commit()
        except Exception as exc:
            logger.debug("standings: save league={} failed: {}", league_id, exc)
            await session.rollback()
        finally:
            await session.close()


__all__ = ["LeagueStandingsService", "StandingRow"]
