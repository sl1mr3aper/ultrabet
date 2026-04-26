"""Поиск матчей по названиям команд."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from api.sstats_client import SStatsClient
from services.text_processor import (
    fuzzy_score,
    normalize_search,
    transliterate,
)


@dataclass(slots=True)
class MatchCandidate:
    game_id: int
    home_id: int
    home_name: str
    away_id: int
    away_name: str
    league_name: str
    league_country: str | None
    date_iso: str
    status: int | None
    raw: dict[str, Any]


def _parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, int):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                try:
                    dt = datetime.strptime(value.split(".")[0].replace("Z", ""), fmt.replace("Z", ""))
                    return dt.replace(tzinfo=UTC)
                except ValueError:
                    continue
    return None


def _candidate_from_raw(raw: dict[str, Any]) -> MatchCandidate | None:
    home = raw.get("homeTeam") or {}
    away = raw.get("awayTeam") or {}
    season = raw.get("season") or {}
    league = season.get("league") if isinstance(season, dict) else {}
    league_name = (league or {}).get("name") if isinstance(league, dict) else None
    country = None
    if isinstance(league, dict):
        c = league.get("country")
        if isinstance(c, dict):
            country = c.get("name")
    try:
        return MatchCandidate(
            game_id=int(raw.get("id")),
            home_id=int(home.get("id")) if home.get("id") is not None else 0,
            home_name=str(home.get("name") or "?"),
            away_id=int(away.get("id")) if away.get("id") is not None else 0,
            away_name=str(away.get("name") or "?"),
            league_name=str(league_name or "—"),
            league_country=country,
            date_iso=str(raw.get("date") or ""),
            status=raw.get("status") if isinstance(raw.get("status"), int) else None,
            raw=raw,
        )
    except (TypeError, ValueError) as exc:
        logger.debug("can't build candidate: {}", exc)
        return None


class MatchFinder:
    """Поиск матча двух команд по их именам и идентификаторам."""

    def __init__(self, client: SStatsClient) -> None:
        self._client = client

    async def search_teams(self, query: str, *, limit: int = 25) -> list[dict[str, Any]]:
        """Многоэтапный поиск команд с fuzzy-ранжированием.

        Шаги:
        1) прямой запрос через SStats ``/Teams/list?Name=<query>``;
        2) если пусто — пробуем транслитерацию кириллица↔латиница;
        3) если пусто — пытаемся по каждому слову отдельно;
        4) клиентский fuzzy-ре-ранкинг по normalize_search() + fuzzy_score().
        """
        q = (query or "").strip()
        if not q:
            return []

        tried: set[str] = set()
        pool: list[dict[str, Any]] = []

        async def _try(name: str) -> list[dict[str, Any]]:
            key = name.strip().lower()
            if not key or key in tried:
                return []
            tried.add(key)
            try:
                return await self._client.search_teams(name, limit=limit)
            except Exception as exc:
                logger.debug("search_teams('{}') failed: {}", name, exc)
                return []

        pool += await _try(q)
        if not pool:
            pool += await _try(transliterate(q))
        if not pool:
            words = [w for w in q.split() if len(w) >= 2]
            for w in words:
                pool += await _try(w)
                if len(pool) >= limit:
                    break
                pool += await _try(transliterate(w))
                if len(pool) >= limit:
                    break

        # удалить дубликаты по id
        unique: dict[int, dict[str, Any]] = {}
        for t in pool:
            tid = t.get("id")
            if tid is None:
                continue
            unique[int(tid)] = t
        teams = list(unique.values())
        if not teams:
            return []

        # клиентский fuzzy-скоринг: normalized query vs team name/country
        nq = normalize_search(q)
        nq_lat = normalize_search(transliterate(q))

        def _team_score(t: dict[str, Any]) -> float:
            name = str(t.get("name") or "")
            nt = normalize_search(name)
            score = max(
                fuzzy_score(nq, nt),
                fuzzy_score(nq_lat, nt),
            )
            # префикс-буст
            if nt.startswith(nq) or nt.startswith(nq_lat):
                score += 0.15
            # exact match буст
            if nt in (nq, nq_lat):
                score += 0.35
            return min(1.0, score)

        teams.sort(key=_team_score, reverse=True)
        return teams[:limit]

    async def find_match_for_teams(
        self,
        home_team_id: int,
        away_team_id: int,
    ) -> MatchCandidate | None:
        """Найти матч между двумя командами с приоритетом:

        1) Матч сегодня (в рамках ±36 часов от «сейчас»).
        2) Ближайший будущий матч.
        3) Самый свежий сыгранный матч в прошлом (со счётом).
        """
        now = datetime.now(tz=UTC)

        def _pair_ok(cand: MatchCandidate) -> bool:
            pair = {cand.home_id, cand.away_id}
            return pair == {home_team_id, away_team_id}

        # Собираем все доступные матчи в обоих направлениях (limit большой,
        # чтобы иметь выбор для последующего ранжирования).
        all_raw: list[dict[str, Any]] = []
        for kwargs in (
            {"both_teams": [home_team_id, away_team_id], "upcoming": True, "limit": 20, "order": 1},
            {"both_teams": [home_team_id, away_team_id], "live": True, "limit": 10},
            {"both_teams": [home_team_id, away_team_id], "limit": 40, "order": -1},
        ):
            try:
                part = await self._client.list_games(**kwargs)  # type: ignore[arg-type]
            except Exception as exc:
                logger.debug("list_games {} failed: {}", kwargs, exc)
                part = []
            if isinstance(part, list):
                all_raw.extend(part)

        # Дедуп по id
        seen: set[int] = set()
        cands: list[MatchCandidate] = []
        for raw in all_raw:
            cand = _candidate_from_raw(raw)
            if cand is None or cand.game_id in seen:
                continue
            seen.add(cand.game_id)
            if not _pair_ok(cand):
                continue
            cands.append(cand)

        if not cands:
            return None

        def _when(cand: MatchCandidate) -> datetime | None:
            return _parse_date(cand.date_iso)

        # 1) Матч сегодня (или в ближайшие ~36ч) — самый близкий к now
        today_window = [
            c for c in cands
            if (_when(c) is not None and abs((_when(c) - now).total_seconds()) <= 36 * 3600)
        ]
        if today_window:
            today_window.sort(
                key=lambda c: abs(((_when(c) or now) - now).total_seconds())
            )
            return today_window[0]

        # 2) Ближайший в будущем
        future = [c for c in cands if (_when(c) is not None and _when(c) > now)]
        if future:
            future.sort(key=lambda c: (_when(c) or now))
            return future[0]

        # 3) Самый свежий в прошлом
        past = [c for c in cands if (_when(c) is not None and _when(c) <= now)]
        if past:
            past.sort(key=lambda c: (_when(c) or now), reverse=True)
            return past[0]

        # Фолбек — есть кандидаты, но без разбираемой даты: вернём первый
        return cands[0]


__all__ = ["MatchCandidate", "MatchFinder", "_candidate_from_raw", "_parse_date"]
