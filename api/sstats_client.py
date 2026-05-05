"""Async-клиент для SStats.net API.

Покрывает все публичные эндпоинты OpenAPI v0.9.14:
Account, Leagues, Games, Odds, Teams, Players, Seasons, Ls.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from typing import Any

import aiohttp
from loguru import logger

from api.cache import APICache
from api.exceptions import (
    APIConnectionError,
    APIInvalidDataError,
    APINotFoundError,
    APIRateLimitError,
    APITimeoutError,
)

JSONDict = dict[str, Any]


class SStatsClient:
    """Async клиент SStats.net.

    Все запросы — GET, кроме /Games/query (POST). Ответы упакованы в
    `{status, data, message, errors}` — клиент возвращает поле ``data``
    (список или dict) для удобства потребителей.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        api_key: str | None = None,
        base_url: str = "https://api.sstats.net",
        timeout: float = 30.0,
        max_retries: int = 3,
        rate_limit_per_second: float = 5.0,
        cache: APICache | None = None,
    ) -> None:
        self._session = session
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._max_retries = max_retries
        self._base_interval = 1.0 / max(rate_limit_per_second, 0.1)
        self._min_interval = self._base_interval
        self._last_request_at = 0.0
        self._semaphore = asyncio.Semaphore(8)
        self._lock = asyncio.Lock()
        self._cache = cache or APICache()
        # Глобальный бэкофф: при 429 все запросы ждут вместе.
        self._rate_limit_until = 0.0  # monotonic timestamp
        # Период «остывания» после 429: пока он не истёк, держим
        # увеличенный min_interval. После истечения возвращаемся к базе,
        # чтобы не тормозить запросы навечно.
        self._cooldown_until = 0.0

    @property
    def cache(self) -> APICache:
        return self._cache

    @property
    def session(self) -> aiohttp.ClientSession:
        """HTTP-сессия (для внешних источников кфов и т.п.)."""
        return self._session

    # ── Internal helpers ────────────────────────────────────

    async def _throttle(self) -> None:
        # Глобальный бэкофф: если были 429, ждём до указанного момента.
        now = time.monotonic()
        global_wait = self._rate_limit_until - now
        if global_wait > 0:
            await asyncio.sleep(global_wait)
        async with self._lock:
            now = time.monotonic()
            # По окончании «периода остывания» после 429 возвращаем
            # базовый интервал — иначе после одного лимита клиент остался
            # бы медленным навсегда.
            if self._min_interval > self._base_interval and now >= self._cooldown_until:
                self._min_interval = self._base_interval
            wait = self._min_interval - (now - self._last_request_at)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_at = time.monotonic()

    def _prepare_params(self, params: Mapping[str, Any] | None) -> dict[str, Any]:
        clean: dict[str, Any] = {}
        if params:
            for key, value in params.items():
                if value is None:
                    continue
                if isinstance(value, bool):
                    clean[key] = "true" if value else "false"
                elif isinstance(value, list | tuple | set):
                    rendered = ",".join(str(v) for v in value if v is not None)
                    if rendered:
                        clean[key] = rendered
                else:
                    clean[key] = value
        if self._api_key:
            clean.setdefault("apikey", self._api_key)
        return clean

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any | None = None,
        cache_key: str | None = None,
        cache_ttl: float | None = None,
    ) -> Any:
        if cache_key and cache_ttl:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                return cached

        url = f"{self._base_url}/{path.lstrip('/')}"
        prepared = self._prepare_params(params)
        attempt = 0
        last_exc: Exception | None = None
        while attempt <= self._max_retries:
            attempt += 1
            await self._throttle()
            try:
                async with self._semaphore, self._session.request(
                    method,
                    url,
                    params=prepared if method == "GET" else None,
                    json=json_body if method != "GET" else None,
                    timeout=self._timeout,
                ) as resp:
                    if resp.status == 404:
                        raise APINotFoundError(f"{method} {path} → 404")
                    if resp.status == 429:
                        # По просьбе: при rate-limit даём SStats отдохнуть
                        # не меньше 10 секунд. Retry-After от сервера
                        # принимается, если он больше, иначе — 10с пола.
                        _hdr = resp.headers.get("Retry-After", "10") or "10"
                        try:
                            retry_after = float(_hdr)
                        except ValueError:
                            retry_after = 10.0
                        retry_after = max(retry_after, 10.0)
                        resume_at = time.monotonic() + retry_after
                        # Глобальный бэкофф: все параллельные запросы увидят
                        # это и подождут вместе, а не задолбят API ещё раз.
                        self._rate_limit_until = max(
                            self._rate_limit_until, resume_at,
                        )
                        # На время остывания держим интервал между
                        # запросами >=1.5с (дольше, чем до срабатывания
                        # лимита), чтобы сразу не схватить 429 ещё раз.
                        self._min_interval = max(
                            self._min_interval, self._base_interval * 3, 1.5,
                        )
                        self._cooldown_until = resume_at + 30.0
                        logger.warning(
                            "SStats 429 at {} attempt={}; global pause {:.1f}s",
                            path, attempt, retry_after,
                        )
                        await asyncio.sleep(retry_after)
                        continue
                    if resp.status >= 500:
                        backoff = min(2 ** attempt, 30)
                        logger.warning(
                            "SStats {} {} → {}; retry in {}s",
                            method, path, resp.status, backoff,
                        )
                        await asyncio.sleep(backoff)
                        continue
                    if resp.status >= 400:
                        text = await resp.text()
                        raise APIInvalidDataError(
                            f"{method} {path} → HTTP {resp.status}: {text[:200]}"
                        )
                    try:
                        payload = await resp.json(content_type=None)
                    except Exception as exc:
                        raise APIInvalidDataError(
                            f"Невалидный JSON от {path}: {exc}"
                        ) from exc

                if isinstance(payload, dict) and "data" in payload:
                    status = payload.get("status")
                    if isinstance(status, str) and status.lower() not in {"ok", "success"}:
                        message = payload.get("message") or "unknown error"
                        raise APIInvalidDataError(f"{path}: API status={status}, message={message}")
                    data = payload.get("data")
                else:
                    data = payload

                if cache_key and cache_ttl and data is not None:
                    await self._cache.set(cache_key, data, cache_ttl)
                return data
            except APINotFoundError:
                raise
            except APIRateLimitError as exc:
                last_exc = exc
                await asyncio.sleep(exc.retry_after)
                continue
            except TimeoutError:
                last_exc = APITimeoutError(f"Timeout: {method} {path}")
                logger.warning("SStats timeout {} {} attempt={}", method, path, attempt)
                await asyncio.sleep(min(2 ** attempt, 15))
            except aiohttp.ClientError as exc:
                last_exc = APIConnectionError(f"Connection error: {exc}")
                logger.warning("SStats network error {} {}: {}", method, path, exc)
                await asyncio.sleep(min(2 ** attempt, 15))
        if last_exc is None:
            last_exc = APIConnectionError(f"Failed after {self._max_retries} retries: {path}")
        raise last_exc

    async def _get(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        cache_key: str | None = None,
        cache_ttl: float | None = None,
    ) -> Any:
        return await self._request(
            "GET", path, params=params, cache_key=cache_key, cache_ttl=cache_ttl
        )

    # ── Account ─────────────────────────────────────────────

    async def get_account_info(self) -> JSONDict | None:
        try:
            data = await self._get("/Account/Info")
        except (APIInvalidDataError, APINotFoundError) as exc:
            logger.debug("Account info недоступен: {}", exc)
            return None
        return data if isinstance(data, dict) else None

    # ── Leagues ─────────────────────────────────────────────

    async def list_leagues(self, cache_ttl: float = 86400) -> list[JSONDict]:
        data = await self._get(
            "/Leagues",
            cache_key="leagues:all",
            cache_ttl=cache_ttl,
        )
        return list(data) if isinstance(data, list) else []

    # ── Games ───────────────────────────────────────────────

    async def list_games(
        self,
        *,
        ids: list[int] | None = None,
        flash_ids: list[str] | None = None,
        league_id: int | None = None,
        season_uid: str | None = None,
        year: int | None = None,
        date: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        status: int | None = None,
        home_team: int | list[int] | None = None,
        away_team: int | list[int] | None = None,
        team: int | list[int] | None = None,
        both_teams: list[int] | None = None,
        ended: bool | None = None,
        live: bool | None = None,
        upcoming: bool | None = None,
        today: bool | None = None,
        offset: int = 0,
        limit: int = 100,
        order: int = -1,
        time_zone: int = 3,
        cache_ttl: float | None = 600.0,
    ) -> list[JSONDict]:
        params: dict[str, Any] = {
            "Id": ids,
            "FlashId": flash_ids,
            "LeagueId": league_id,
            "SeasonUid": season_uid,
            "Year": year,
            "Date": date,
            "From": date_from,
            "To": date_to,
            "Status": status,
            "HomeTeam": home_team,
            "AwayTeam": away_team,
            "Team": team,
            "BothTeams": both_teams,
            "Ended": ended,
            "Live": live,
            "Upcoming": upcoming,
            "Today": today,
            "Offset": offset,
            "Limit": min(max(limit, 1), 1000),
            "Order": order,
            "TimeZone": time_zone,
        }
        # Для live-запросов не держим кэш долго — данные быстро
        # устаревают (счёт, статус). Для «сегодня/завтра/лиги» 10 минут
        # экономят десятки лишних запросов к SStats на пагинации/кликах
        # — расписание матчей в течение дня практически не меняется.
        effective_ttl = cache_ttl
        if live is True and effective_ttl is not None and effective_ttl > 30.0:
            effective_ttl = 30.0
        cache_key = None
        if effective_ttl:
            cache_key = "games:list:" + ",".join(
                f"{k}={params[k]}" for k in sorted(params) if params[k] is not None
            )
        data = await self._get(
            "/Games/list", params=params, cache_key=cache_key, cache_ttl=effective_ttl
        )
        return list(data) if isinstance(data, list) else []

    async def get_game(self, game_id: int | str, *, cache_ttl: float = 300) -> JSONDict | None:
        try:
            data = await self._get(
                f"/Games/{game_id}",
                cache_key=f"game:{game_id}",
                cache_ttl=cache_ttl,
            )
        except APINotFoundError:
            return None
        return data if isinstance(data, dict) else None

    async def get_glicko(self, game_id: int | str, *, cache_ttl: float = 600) -> JSONDict | None:
        try:
            data = await self._get(
                f"/Games/glicko/{game_id}",
                cache_key=f"glicko:{game_id}",
                cache_ttl=cache_ttl,
            )
        except APINotFoundError:
            return None
        return data if isinstance(data, dict) else None

    async def query_games(
        self,
        body: Mapping[str, Any],
        *,
        time_zone: int = 3,
    ) -> list[JSONDict]:
        data = await self._request(
            "POST",
            "/Games/query",
            params={"timeZone": time_zone},
            json_body=dict(body),
        )
        return list(data) if isinstance(data, list) else []

    async def get_season_table(self, season_uid: str) -> JSONDict | None:
        try:
            data = await self._get(
                "/Games/season-table",
                params={"seasonUid": season_uid},
                cache_key=f"season-table:{season_uid}",
                cache_ttl=1800,
            )
        except APINotFoundError:
            return None
        return data if isinstance(data, dict) else None

    async def get_season_table_by_league(
        self,
        *,
        year: int,
        league_id: int,
        cache_ttl: float = 3600,
    ) -> JSONDict | None:
        """Турнирная таблица лиги за конкретный сезон-год.

        Эндпоинт `/Games/season-table` принимает `year`/`league` (а не
        `seasonUid`) и возвращает `{"<teamId>": {...stats...}}`. Это
        стабильный путь получить standings; через /Ls/Seasons часто
        приходит пустой список.
        """
        try:
            data = await self._get(
                "/Games/season-table",
                params={"year": int(year), "league": int(league_id)},
                cache_key=f"season-table-league:{year}:{league_id}",
                cache_ttl=cache_ttl,
            )
        except APINotFoundError:
            return None
        return data if isinstance(data, dict) else None

    async def get_last_games_stats(
        self,
        team_id: int,
        *,
        league_id: int | None = None,
        limit: int = 10,
    ) -> JSONDict | None:
        params = {"teamId": team_id, "leagueId": league_id, "limit": limit}
        try:
            data = await self._get(
                "/Games/last-games-stats",
                params=params,
                cache_key=f"last-stats:{team_id}:{league_id}:{limit}",
                cache_ttl=900,
            )
        except APINotFoundError:
            return None
        return data if isinstance(data, dict) else None

    async def get_text_summary(self, game_id: int | str) -> str | None:
        try:
            data = await self._get(
                "/Games/text-summary",
                params={"gameId": game_id},
                cache_key=f"summary:{game_id}",
                cache_ttl=900,
            )
        except APINotFoundError:
            return None
        if isinstance(data, str):
            return data
        if isinstance(data, dict):
            return data.get("text") or data.get("summary")
        return None

    async def get_profits(
        self,
        game_id: int,
        *,
        this_league: bool = True,
        home_away: bool = False,
        same_games: bool = False,
        bookie_id: int | None = None,
        limit: int = 25,
    ) -> JSONDict | None:
        params = {
            "gameId": game_id,
            "thisLeague": this_league,
            "homeAway": home_away,
            "sameGames": same_games,
            "bookieId": bookie_id,
            "limit": limit,
        }
        try:
            data = await self._get(
                "/Games/profits",
                params=params,
                cache_key=f"profits:{game_id}:{this_league}:{home_away}:{same_games}:{bookie_id}:{limit}",
                cache_ttl=900,
            )
        except APINotFoundError:
            return None
        return data if isinstance(data, dict) else None

    async def get_injuries(self, game_id: int) -> list[JSONDict]:
        try:
            data = await self._get(
                "/Games/injuries",
                params={"gameId": game_id},
                cache_key=f"injuries:{game_id}",
                cache_ttl=600,
            )
        except APINotFoundError:
            return []
        return list(data) if isinstance(data, list) else []

    # ── Odds ────────────────────────────────────────────────

    async def list_bookmakers(self, *, cache_ttl: float = 86400) -> list[JSONDict]:
        data = await self._get(
            "/Odds/bookmakers", cache_key="bookmakers", cache_ttl=cache_ttl
        )
        return list(data) if isinstance(data, list) else []

    async def get_prematch_markets(self) -> list[JSONDict]:
        data = await self._get(
            "/Odds/prematch-markets",
            cache_key="prematch-markets",
            cache_ttl=86400,
        )
        return list(data) if isinstance(data, list) else []

    async def get_live_markets(self) -> list[JSONDict]:
        data = await self._get(
            "/Odds/live-markets",
            cache_key="live-markets",
            cache_ttl=86400,
        )
        return list(data) if isinstance(data, list) else []

    async def get_prematch_odds(
        self,
        game_id: int | str,
        *,
        bookmaker_ids: list[int] | None = None,
        opening: bool = False,
        cache_ttl: float = 180,
    ) -> list[JSONDict]:
        params = {"bookmakerId": bookmaker_ids, "opening": opening}
        try:
            data = await self._get(
                f"/Odds/{game_id}",
                params=params,
                cache_key=f"odds:{game_id}:{bookmaker_ids}:{opening}",
                cache_ttl=cache_ttl,
            )
        except APINotFoundError:
            return []
        return list(data) if isinstance(data, list) else []

    async def get_live_odds(self, game_id: int | str) -> JSONDict | None:
        try:
            data = await self._get(f"/Odds/live/{game_id}")
        except APINotFoundError:
            return None
        return data if isinstance(data, dict) else None

    async def get_live_changes(self, game_id: int | str) -> list[JSONDict]:
        try:
            data = await self._get(f"/Odds/live-changes/{game_id}")
        except APINotFoundError:
            return []
        return list(data) if isinstance(data, list) else []

    async def get_live_updates_only(self) -> list[JSONDict]:
        data = await self._get("/Odds/live-changes/updates-only")
        return list(data) if isinstance(data, list) else []

    # ── Teams ───────────────────────────────────────────────

    async def search_teams(
        self,
        name: str,
        *,
        country: str | None = None,
        offset: int = 0,
        limit: int = 25,
        cache_ttl: float = 3600,
    ) -> list[JSONDict]:
        params = {"Name": name, "Country": country, "Offset": offset, "Limit": limit}
        data = await self._get(
            "/Teams/list",
            params=params,
            cache_key=f"teams:{name.lower()}:{country}:{offset}:{limit}",
            cache_ttl=cache_ttl,
        )
        return list(data) if isinstance(data, list) else []

    async def get_team(self, team_id: int, *, cache_ttl: float = 3600) -> JSONDict | None:
        try:
            data = await self._get(
                f"/Teams/{team_id}",
                cache_key=f"team:{team_id}",
                cache_ttl=cache_ttl,
            )
        except APINotFoundError:
            return None
        return data if isinstance(data, dict) else None

    # ── Players ─────────────────────────────────────────────

    async def find_players(self, name: str, *, limit: int = 25) -> list[JSONDict]:
        params = {"Name": name, "Limit": limit}
        try:
            data = await self._get(
                "/Players/find",
                params=params,
                cache_key=f"players:{name.lower()}:{limit}",
                cache_ttl=1800,
            )
        except APINotFoundError:
            return []
        return list(data) if isinstance(data, list) else []

    async def get_player(self, player_id: int) -> JSONDict | None:
        try:
            data = await self._get(
                f"/Players/{player_id}",
                cache_key=f"player:{player_id}",
                cache_ttl=3600,
            )
        except APINotFoundError:
            return None
        return data if isinstance(data, dict) else None

    async def get_player_events(self, player_id: int) -> list[JSONDict]:
        try:
            data = await self._get(
                f"/Players/{player_id}/events",
                cache_key=f"player-events:{player_id}",
                cache_ttl=900,
            )
        except APINotFoundError:
            return []
        return list(data) if isinstance(data, list) else []

    # ── Seasons ─────────────────────────────────────────────

    async def get_standings(self, season_uid: str) -> JSONDict | None:
        try:
            data = await self._get(
                "/Seasons/standings",
                params={"uid": season_uid},
                cache_key=f"standings:{season_uid}",
                cache_ttl=3600,
            )
        except APINotFoundError:
            return None
        return data if isinstance(data, dict) else None

    # ── Lightweight (Ls/*) ──────────────────────────────────

    async def ls_list(self, **params: Any) -> list[JSONDict]:
        try:
            data = await self._get("/Ls/List", params=params)
        except APINotFoundError:
            return []
        return list(data) if isinstance(data, list) else []

    async def ls_teams(self, **params: Any) -> list[JSONDict]:
        try:
            data = await self._get("/Ls/Teams", params=params)
        except APINotFoundError:
            return []
        return list(data) if isinstance(data, list) else []

    async def ls_leagues(self, **params: Any) -> list[JSONDict]:
        try:
            data = await self._get(
                "/Ls/Leagues",
                params=params,
                cache_key="ls-leagues",
                cache_ttl=86400,
            )
        except APINotFoundError:
            return []
        return list(data) if isinstance(data, list) else []

    async def ls_seasons(self, **params: Any) -> list[JSONDict]:
        try:
            data = await self._get("/Ls/Seasons", params=params)
        except APINotFoundError:
            return []
        return list(data) if isinstance(data, list) else []

    async def ls_game_info(self, game_id: int | str) -> JSONDict | None:
        try:
            data = await self._get("/Ls/GameInfo", params={"gameId": game_id})
        except APINotFoundError:
            return None
        return data if isinstance(data, dict) else None

    # ── Composite helpers ───────────────────────────────────

    async def get_full_match_data(self, game_id: int | str) -> JSONDict:
        """Параллельно собрать ПОЛНЫЙ пакет данных по матчу для повышения точности.

        Используются все доступные эндпоинты SStats:
          /Games/{id}, /Games/glicko/{id}, /Odds/{id}, /Games/injuries,
          /Games/last-games-stats, /Games/text-summary, /Games/profits,
          /Games/season-table.
        """
        async def _safe(coro_factory, default):  # type: ignore[no-untyped-def]
            try:
                return await coro_factory()
            except Exception as exc:
                logger.debug("partial fetch error: {}", exc)
                return default

        gid_int = int(game_id) if str(game_id).isdigit() else None

        async def _injuries() -> list[JSONDict]:
            return await self.get_injuries(gid_int) if gid_int is not None else []

        async def _last_games() -> JSONDict | None:
            return await self.get_last_games_stats(gid_int) if gid_int is not None else None

        async def _summary() -> str | None:
            return await self.get_text_summary(game_id)

        async def _profits() -> JSONDict | None:
            return (
                await self.get_profits(gid_int, this_league=True, limit=25)
                if gid_int is not None else None
            )

        results = await asyncio.gather(
            _safe(lambda: self.get_game(game_id), None),
            _safe(lambda: self.get_glicko(game_id), None),
            _safe(lambda: self.get_prematch_odds(game_id), []),
            _safe(_injuries, []),
            _safe(_last_games, None),
            _safe(_summary, None),
            _safe(_profits, None),
            _safe(lambda: self.get_live_odds(game_id), None),
        )
        game, glicko, odds, injuries, last_games, summary_text, profits, live_odds = (
            results
        )

        # Подгружаем сезонную таблицу, если есть season uid в game
        season_table: JSONDict | None = None
        try:
            season_uid: str | None = None
            if isinstance(game, dict):
                season = game.get("season") or {}
                if isinstance(season, dict):
                    season_uid = season.get("uid") or season.get("id")
            if season_uid:
                season_table = await self.get_season_table(str(season_uid))
        except Exception as exc:
            logger.debug("season table fetch error: {}", exc)

        return {
            "game": game,
            "glicko": glicko,
            "odds": odds,
            "live_odds": live_odds,
            "injuries": injuries,
            "last_games": last_games,
            "summary": summary_text,
            "profits": profits,
            "season_table": season_table,
        }


__all__ = ["SStatsClient"]
