"""Backfill исторических матчей в локальную БД из SStats.

Фоновая задача раз в N часов:
1. Берёт список лиг из `/Leagues`.
2. Для каждой лиги грузит `/Games/list?order=-1&limit=50` (последние сыгранные).
3. Парсит счёт и сохраняет в `MatchResult` (upsert по game_id).

Используется:
- Историческим анализом моделью self-learning.
- Статистикой пользователя по командам.
- Прогнозами: контекстные корректировки при повторяющихся очных встречах.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.sstats_client import SStatsClient
from db.models import MatchResult


class HistoryBackfillService:
    def __init__(self, client: SStatsClient, session_factory: Any) -> None:
        self._client = client
        self._session_factory = session_factory

    async def run_once(self, *, leagues_limit: int = 30, per_league: int = 50) -> int:
        """Однократный проход. Возвращает количество добавленных записей."""
        added = 0
        try:
            leagues = await self._client.list_leagues()
        except Exception as exc:
            logger.warning("HistoryBackfill: не получили лиги: {}", exc)
            return 0
        leagues = [l for l in (leagues or []) if isinstance(l, dict)][:leagues_limit]
        session: AsyncSession = self._session_factory()
        try:
            for lg in leagues:
                lg_id = lg.get("id")
                if not lg_id:
                    continue
                try:
                    games = await self._client.list_games(
                        league_id=int(lg_id),
                        order=-1,
                        limit=per_league,
                    )
                except Exception as exc:
                    logger.debug("backfill league={}: {}", lg_id, exc)
                    continue
                for g in games or []:
                    if not isinstance(g, dict):
                        continue
                    row = await self._upsert_match(session, g, lg)
                    if row:
                        added += 1
            await session.commit()
        finally:
            await session.close()
        logger.info("HistoryBackfill: добавлено/обновлено {} матчей", added)
        return added

    async def _upsert_match(
        self, session: AsyncSession, g: dict[str, Any], league: dict[str, Any]
    ) -> bool:
        gid = g.get("id")
        if not gid:
            return False
        home_score = _extract_score(g, "home")
        away_score = _extract_score(g, "away")
        if home_score is None or away_score is None:
            return False
        existing = await session.scalar(
            select(MatchResult).where(MatchResult.game_id == int(gid))
        )
        home = g.get("homeTeam") or g.get("home") or {}
        away = g.get("awayTeam") or g.get("away") or {}
        country = (league.get("country") or {}) if isinstance(league, dict) else {}
        date_raw = g.get("date") or g.get("startDate") or g.get("dateUTC")
        date_val: datetime | None = None
        if isinstance(date_raw, str):
            try:
                date_val = datetime.fromisoformat(date_raw.replace("Z", "+00:00"))
            except ValueError:
                date_val = None
        if existing is None:
            obj = MatchResult(
                game_id=int(gid),
                date=date_val,
                league_id=int(league.get("id") or 0) or None,
                league_name=str(league.get("name") or "") or None,
                country_name=str(country.get("name") or "") or None,
                home_id=_int_or_none(home.get("id") if isinstance(home, dict) else None),
                away_id=_int_or_none(away.get("id") if isinstance(away, dict) else None),
                home_name=str(home.get("name") or "") if isinstance(home, dict) else None,
                away_name=str(away.get("name") or "") if isinstance(away, dict) else None,
                home_score=home_score,
                away_score=away_score,
                home_xg=_float_or_none(g.get("homeXG")),
                away_xg=_float_or_none(g.get("awayXG")),
                home_rating=_float_or_none(g.get("homeRating")),
                away_rating=_float_or_none(g.get("awayRating")),
                ingested_at=datetime.now(tz=UTC),
            )
            session.add(obj)
            return True
        # update score (в случае исправления) — если отличается
        changed = False
        if existing.home_score != home_score:
            existing.home_score = home_score
            changed = True
        if existing.away_score != away_score:
            existing.away_score = away_score
            changed = True
        return changed


def _extract_score(g: dict[str, Any], side: str) -> int | None:
    # SStats: homeResult / awayResult — итоговый счёт; FTResult / HTResult —
    # 90 мин / 1-й тайм. Основной ключ — `*FTResult`, fallback на `*Result`.
    for key in (
        f"{side}FTResult",
        f"{side}Result",
        f"{side}Score",
        f"{side}Goals",
        f"{side}FT",
        f"{side}_score",
    ):
        v = g.get(key)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                pass
    score_obj = g.get("score")
    if isinstance(score_obj, dict):
        for key in (
            f"{side}",
            f"fullTime{side.capitalize()}",
            f"{side}FT",
        ):
            v = score_obj.get(key)
            if v is not None:
                try:
                    return int(v)
                except (TypeError, ValueError):
                    pass
    return None


def _int_or_none(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _float_or_none(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


__all__ = ["HistoryBackfillService"]
