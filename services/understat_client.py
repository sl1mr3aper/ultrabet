"""P0-5: парсер understat.com (бесплатный xG для топ-5 лиг + РПЛ).

Understat не имеет публичного REST API. Данные приходят страницами с
JSON, упакованным в JS-переменные вида ``var datesData = JSON.parse('...')``.

Поддерживаемые лиги (URL-slugи Understat):
- EPL          (Английская Премьер-лига)
- La_liga      (Испанская Ла Лига)
- Bundesliga   (Германия)
- Serie_A      (Италия)
- Ligue_1      (Франция)
- RFPL         (РПЛ, есть с сезона 2014/15)

Что отдаёт клиент:
- ``list_matches(league, season)`` — расписание со статусом + xG для
  завершённых матчей.
- ``match_xg(match_id)`` — детальный xG матча (по ударам).
- ``team_form(team, season)`` — последние 10 матчей команды + xG_for/against.

Архитектура:
- aiohttp + общий ``RateLimiter`` (1 req / 2s, чтобы не словить 429).
- Кэш через ``KVCache`` или ``APICache`` (TTL: 24ч для исторических,
  10 мин для текущего сезона).
- Декодирование JS: regex-извлечение содержимого ``JSON.parse('...')``,
  затем ``codecs.decode(..., 'unicode_escape')``.

Тестируется без сети: ``UnderstatParser`` принимает строку HTML и
возвращает чистые dict'ы; HTTP-обвязка тестируется на моках aiohttp.
"""

from __future__ import annotations

import asyncio
import codecs
import json
import re
from dataclasses import dataclass, field
from typing import Any

import aiohttp
from loguru import logger

UNDERSTAT_BASE = "https://understat.com"
SUPPORTED_LEAGUES: tuple[str, ...] = (
    "EPL",
    "La_liga",
    "Bundesliga",
    "Serie_A",
    "Ligue_1",
    "RFPL",
)

# Регулярка ловит конструкцию вида:
#   var datesData = JSON.parse('...');
# где между кавычками — escape-последовательности (\xNN, \uNNNN, \").
_JS_VAR_RE = re.compile(
    r"var\s+(?P<name>\w+)\s*=\s*JSON\.parse\('(?P<payload>.*?)'\)\s*;",
    re.DOTALL,
)


@dataclass(slots=True)
class UnderstatMatch:
    match_id: int
    league: str
    season: str
    datetime_utc: str
    home_team: str
    away_team: str
    home_goals: int | None
    away_goals: int | None
    home_xg: float | None
    away_xg: float | None
    is_finished: bool
    raw: dict[str, Any] = field(default_factory=dict)


def _decode_payload(payload: str) -> Any:
    """JSON.parse('<escaped>') → распакованный dict / list."""
    decoded = codecs.decode(payload, "unicode_escape")
    return json.loads(decoded)


def _extract_js_vars(html: str) -> dict[str, Any]:
    """Возвращает все ``var X = JSON.parse(...)`` страницы как dict."""
    out: dict[str, Any] = {}
    for m in _JS_VAR_RE.finditer(html):
        name = m.group("name")
        try:
            out[name] = _decode_payload(m.group("payload"))
        except (ValueError, json.JSONDecodeError) as exc:
            logger.debug("understat: не распарсил {}: {}", name, exc)
    return out


def parse_league_matches(
    html: str,
    *,
    league: str,
    season: str,
) -> list[UnderstatMatch]:
    """Достаёт ``datesData`` из страницы лиги и приводит к списку матчей."""
    js = _extract_js_vars(html)
    raw = js.get("datesData") or []
    if not isinstance(raw, list):
        return []
    matches: list[UnderstatMatch] = []
    for row in raw:
        try:
            mid = int(row["id"])
            home = row.get("h", {}) or {}
            away = row.get("a", {}) or {}
            goals = row.get("goals") or {}
            xg = row.get("xG") or {}
            is_result = bool(row.get("isResult"))
            home_g_raw = goals.get("h")
            away_g_raw = goals.get("a")
            matches.append(
                UnderstatMatch(
                    match_id=mid,
                    league=league,
                    season=season,
                    datetime_utc=str(row.get("datetime", "")),
                    home_team=str(home.get("title", "")),
                    away_team=str(away.get("title", "")),
                    home_goals=(
                        int(home_g_raw) if home_g_raw not in (None, "") else None
                    ),
                    away_goals=(
                        int(away_g_raw) if away_g_raw not in (None, "") else None
                    ),
                    home_xg=float(xg["h"]) if xg.get("h") not in (None, "") else None,
                    away_xg=float(xg["a"]) if xg.get("a") not in (None, "") else None,
                    is_finished=is_result,
                    raw=row,
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.debug("understat: пропускаю строку: {}", exc)
    return matches


def parse_match_shots(html: str) -> dict[str, list[dict[str, Any]]]:
    """Достаёт ``shotsData`` из страницы матча.

    Возвращает {"h": [...], "a": [...]} с ударами обеих команд.
    """
    js = _extract_js_vars(html)
    shots = js.get("shotsData") or {}
    if not isinstance(shots, dict):
        return {"h": [], "a": []}
    return {"h": list(shots.get("h", [])), "a": list(shots.get("a", []))}


@dataclass(slots=True)
class _RateLimiter:
    """Простой 1-req-per-N-seconds лимитер на asyncio.Lock."""

    min_interval: float
    _last_request: float = 0.0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def acquire(self) -> None:
        async with self._lock:
            now = asyncio.get_running_loop().time()
            wait = self._last_request + self.min_interval - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = asyncio.get_running_loop().time()


class UnderstatClient:
    """Async-клиент для understat.com.

    ``cache`` — любой объект с интерфейсом ``async get(key) -> Any | None``
    и ``async set(key, value, ttl=...)``. Подходит ``api.cache.APICache``
    или ``services.kv_cache.KVCache``.
    """

    DEFAULT_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/123.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        cache: Any | None = None,
        rate_limit_seconds: float = 2.0,
        timeout: float = 15.0,
    ) -> None:
        self._session = session
        self._cache = cache
        self._rate = _RateLimiter(min_interval=rate_limit_seconds)
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def _get_html(self, url: str, *, cache_ttl: int) -> str:
        """Выкачивает страницу с кэшем и rate-limit."""
        if self._cache is not None:
            cached = await self._cache.get(url)
            if isinstance(cached, str):
                return cached
        await self._rate.acquire()
        async with self._session.get(
            url, headers=self.DEFAULT_HEADERS, timeout=self._timeout
        ) as resp:
            resp.raise_for_status()
            html = await resp.text()
        if self._cache is not None and html:
            try:
                await self._cache.set(url, html, ttl=cache_ttl)
            except TypeError:
                # Совместимость с APICache (positional ttl).
                await self._cache.set(url, html, cache_ttl)  # type: ignore[arg-type]
        return html

    async def list_matches(
        self,
        league: str,
        season: str,
        *,
        cache_ttl: int = 600,
    ) -> list[UnderstatMatch]:
        """Получить расписание лиги и xG завершённых матчей."""
        if league not in SUPPORTED_LEAGUES:
            raise ValueError(
                f"Лига {league!r} не поддерживается; "
                f"допустимы: {', '.join(SUPPORTED_LEAGUES)}"
            )
        url = f"{UNDERSTAT_BASE}/league/{league}/{season}"
        html = await self._get_html(url, cache_ttl=cache_ttl)
        return parse_league_matches(html, league=league, season=season)

    async def match_shots(
        self,
        match_id: int,
        *,
        cache_ttl: int = 86_400,
    ) -> dict[str, list[dict[str, Any]]]:
        """Получить полный shotsData (xG по ударам) одного матча."""
        url = f"{UNDERSTAT_BASE}/match/{match_id}"
        html = await self._get_html(url, cache_ttl=cache_ttl)
        return parse_match_shots(html)


__all__ = [
    "SUPPORTED_LEAGUES",
    "UNDERSTAT_BASE",
    "UnderstatClient",
    "UnderstatMatch",
    "parse_league_matches",
    "parse_match_shots",
]
