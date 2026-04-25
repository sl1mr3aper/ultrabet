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
        self._min_interval = 1.0 / max(rate_limit_per_second, 0.1)
        self._last_request_at = 0.0
        self._semaphore = asyncio.Semaphore(8)
        self._lock = asyncio.Lock()
        self._cache = cache or APICache()

    @property
    def cache(self) -> APICache:
        return self._cache

    # ── Internal helpers ────────────────────────────────────

    async def _throttle(self) -> None:
        async with self._lock:
            now = time.monotonic()
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
                        retry_after = float(resp.headers.get("Retry-After", "5") or 5)
                        logger.warning(
                            "SStats rate-limit hit at {} attempt={}; sleeping {:.1f}s",
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
        cache_ttl: float | None = None,
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
        cache_key = None
        if cache_ttl:
            cache_key = "games:list:" + ",".join(
                f"{k}={params[k]}" for k in sorted(params) if params[k] is not None
            )
        data = await self._get(
            "/Games/list", params=params, cache_key=cache_key, cache_ttl=cache_ttl
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
        """Параллельно собрать полный пакет данных для прогноза."""
        async def _safe_injuries() -> list[JSONDict]:
            if not str(game_id).isdigit():
                return []
            try:
                return await self.get_injuries(int(game_id))
            except Exception:
                return []

        results = await asyncio.gather(
            self.get_game(game_id),
            self.get_glicko(game_id),
            self.get_prematch_odds(game_id),
            _safe_injuries(),
            return_exceptions=True,
        )
        game, glicko, odds, injuries = results

        def _safe(value: Any, default: Any) -> Any:
            if isinstance(value, Exception):
                logger.debug("partial fetch error: {}", value)
                return default
            return value

        return {
            "game": _safe(game, None),
            "glicko": _safe(glicko, None),
            "odds": _safe(odds, []),
            "injuries": _safe(injuries, []),
        }


__all__ = ["SStatsClient"]
