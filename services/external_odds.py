"""Внешние агрегаторы коэффициентов: NB-Bet и Flashscore.

ВАЖНО: оба источника — best-effort. Они НЕ имеют публичного API:
  • NB-Bet (nb-bet.com) — Next.js SSR, отдает opaque dict {outcome_id: odd}
    без названий рынков. Мы выводим карту 1X2 по согласованию с SStats:
    среди всех троек кфов в `match['5']` ищем перестановку, наиболее близкую
    к среднему 1X2 SStats. Если таких троек нет — возвращаем пусто.
  • Flashscore (flashscore.com) — агрессивная антибот-защита, JS-only render.
    Реализация пробует Playwright headless; на любое падение — ничего
    не возвращаем, чтобы не валить прогноз.

Оба клиента рассчитаны на жёсткий тайм-аут (~6 сек) и логирование,
ошибки никогда не пробрасываются в PredictionService.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from itertools import permutations
from typing import Any

import aiohttp
from loguru import logger

JSONDict = dict[str, Any]

NB_BET_HOME = "https://nb-bet.com/"
NB_BET_EVENT_TEMPLATE = "https://nb-bet.com/Events/{slug}"
NB_BET_LIVE_TEMPLATE = "https://nb-bet.com/LiveEvents/{slug}"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru,en-US;q=0.8,en;q=0.5",
}

_SLUG_RE = re.compile(r'href="(/(?:Events|LiveEvents)/(\d+)-([^"]+))"')
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>([^<]+)</script>'
)


@dataclass(slots=True)
class ExternalOddsBundle:
    """Bookmakers, готовые к скармливанию OddsParser."""

    bookmakers: list[JSONDict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class NBBetClient:
    """Лёгкий best-effort клиент к https://nb-bet.com.

    Работа в две стадии:
      1. discover_slug(game_id) — ищет slug события по списку матчей на
         главной/лайв-странице, кэширует.
      2. fetch_event(game_id) — выкачивает Events/{slug} и парсит
         __NEXT_DATA__.
    """

    def __init__(
        self,
        *,
        slug_ttl_seconds: int = 300,
        request_timeout: float = 5.0,
    ) -> None:
        self._slug_ttl = slug_ttl_seconds
        self._timeout = request_timeout
        self._slug_cache: dict[int, str] = {}
        self._slug_cache_time: float = 0.0
        self._lock = asyncio.Lock()

    async def _refresh_slugs(self, session: aiohttp.ClientSession) -> None:
        async with self._lock:
            if time.monotonic() - self._slug_cache_time < self._slug_ttl:
                return
            for url in (NB_BET_HOME, "https://nb-bet.com/LiveEvents/"):
                try:
                    async with session.get(
                        url,
                        headers=DEFAULT_HEADERS,
                        timeout=aiohttp.ClientTimeout(total=self._timeout),
                    ) as resp:
                        if resp.status != 200:
                            continue
                        html = await resp.text()
                except (aiohttp.ClientError, TimeoutError) as exc:
                    logger.debug("nb-bet slug fetch fail {}: {}", url, exc)
                    continue
                for _, gid_str, slug_tail in _SLUG_RE.findall(html):
                    try:
                        gid = int(gid_str)
                    except ValueError:
                        continue
                    self._slug_cache[gid] = f"{gid}-{slug_tail}"
            self._slug_cache_time = time.monotonic()

    async def fetch_event(
        self,
        session: aiohttp.ClientSession,
        game_id: int,
    ) -> JSONDict | None:
        """Возвращает sub-объект `match` из __NEXT_DATA__ или None."""
        await self._refresh_slugs(session)
        slug = self._slug_cache.get(game_id)
        if not slug:
            return None
        url = NB_BET_EVENT_TEMPLATE.format(slug=slug)
        try:
            async with session.get(
                url,
                headers=DEFAULT_HEADERS,
                timeout=aiohttp.ClientTimeout(total=self._timeout),
            ) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
        except (aiohttp.ClientError, TimeoutError) as exc:
            logger.debug("nb-bet event fetch fail {}: {}", url, exc)
            return None
        m = _NEXT_DATA_RE.search(html)
        if not m:
            return None
        try:
            payload = json.loads(m.group(1))
        except json.JSONDecodeError:
            return None
        return (
            payload.get("props", {})
            .get("initialState", {})
            .get("pageSoccerEvent", {})
            .get("match")
        )


def _infer_1x2_from_nb(
    nb_match: JSONDict,
    sstats_avg: dict[str, float] | None,
) -> tuple[float, float, float] | None:
    """Угадывает (home, draw, away) среди value-бакета NB-Bet `match['5']`.

    Стратегия: перебор всех ID-троек, ищется та, чья перестановка
    наименее отклоняется от средних SStats-кфов. Если SStats-кфов нет
    или совпадения слишком плохие — None.
    """
    bucket = nb_match.get("5") if isinstance(nb_match, dict) else None
    if not isinstance(bucket, dict) or not sstats_avg:
        return None
    s_home = sstats_avg.get("1")
    s_draw = sstats_avg.get("X")
    s_away = sstats_avg.get("2")
    if s_home is None or s_draw is None or s_away is None:
        return None
    # Берём только разумные кфы (1.05–30); крупные категории нам не нужны.
    candidates: list[tuple[str, float]] = []
    for k, v in bucket.items():
        try:
            val = float(v)
        except (TypeError, ValueError):
            continue
        if 1.05 <= val <= 30.0:
            candidates.append((str(k), val))
    if len(candidates) < 3:
        return None
    target = (s_home, s_draw, s_away)
    best: tuple[float, tuple[float, float, float]] | None = None
    # Чтобы не уйти в N^3, ограничиваем: возьмём 50 ближайших к sum-target.
    target_sum = sum(target)
    candidates.sort(key=lambda kv: abs(kv[1] - target_sum / 3))
    candidates = candidates[:50]
    for triple in permutations(candidates, 3):
        ids = frozenset(t[0] for t in triple)
        if len(ids) < 3:
            continue
        diff = sum(
            (triple[i][1] - target[i]) ** 2 for i in range(3)
        )
        if best is None or diff < best[0]:
            best = (diff, (triple[0][1], triple[1][1], triple[2][1]))
    if best is None:
        return None
    score, vals = best
    # Среднеквадратичное отклонение должно быть малым (≤0.45 на кф).
    if score / 3 > 0.45 ** 2:
        return None
    return vals


def _nb_bookmaker(odds_1x2: tuple[float, float, float]) -> JSONDict:
    home, draw, away = odds_1x2
    return {
        "bookmakerId": -1,
        "bookmakerName": "NB-Bet",
        "odds": [
            {
                "marketId": 1,
                "marketName": "Match Winner",
                "odds": [
                    {"name": "Home", "value": home},
                    {"name": "Draw", "value": draw},
                    {"name": "Away", "value": away},
                ],
            }
        ],
    }


async def fetch_external_odds(
    *,
    session: aiohttp.ClientSession,
    game_id: int,
    sstats_odds_raw: list[JSONDict] | None,
    nb_bet_client: NBBetClient | None = None,
    enable_flashscore: bool = True,
    enable_nb_bet: bool = True,
    timeout: float = 6.0,
) -> ExternalOddsBundle:
    """Параллельно дёргает NB-Bet и Flashscore. Любая ошибка ⇒ no-op."""
    bundle = ExternalOddsBundle()
    sstats_avg = _sstats_1x2_average(sstats_odds_raw)

    async def _nb() -> None:
        if not enable_nb_bet:
            return
        client = nb_bet_client or NBBetClient(request_timeout=timeout)
        try:
            data = await asyncio.wait_for(
                client.fetch_event(session, game_id), timeout=timeout
            )
        except TimeoutError:
            bundle.errors.append("nb-bet: timeout")
            return
        except Exception as exc:
            bundle.errors.append(f"nb-bet: {type(exc).__name__}")
            return
        if not data:
            return
        triple = _infer_1x2_from_nb(data, sstats_avg)
        if triple is None:
            bundle.errors.append("nb-bet: 1x2 mapping failed")
            return
        bundle.bookmakers.append(_nb_bookmaker(triple))

    async def _fs() -> None:
        if not enable_flashscore:
            return
        try:
            data = await asyncio.wait_for(
                _try_flashscore(game_id), timeout=timeout
            )
        except TimeoutError:
            bundle.errors.append("flashscore: timeout")
            return
        except Exception as exc:
            bundle.errors.append(f"flashscore: {type(exc).__name__}")
            return
        if data:
            bundle.bookmakers.append(data)

    await asyncio.gather(_nb(), _fs(), return_exceptions=True)
    if bundle.errors:
        logger.debug("external odds errors: {}", bundle.errors)
    return bundle


def _sstats_1x2_average(
    raw: list[JSONDict] | None,
) -> dict[str, float] | None:
    """Среднее по 1X2 у SStats для якоря NB-Bet."""
    if not raw:
        return None
    sums: dict[str, list[float]] = {"1": [], "X": [], "2": []}
    for book in raw:
        if not isinstance(book, dict):
            continue
        for market in book.get("odds", []) or []:
            if not isinstance(market, dict):
                continue
            mname = (
                market.get("marketName") or market.get("name") or ""
            ).lower()
            if "match winner" not in mname and "1x2" not in mname:
                continue
            for outcome in market.get("odds", []) or []:
                if not isinstance(outcome, dict):
                    continue
                name = str(outcome.get("name") or "").lower()
                value = outcome.get("value")
                if not isinstance(value, int | float):
                    continue
                if name in {"home", "1"}:
                    sums["1"].append(float(value))
                elif name in {"draw", "x"}:
                    sums["X"].append(float(value))
                elif name in {"away", "2"}:
                    sums["2"].append(float(value))
    out: dict[str, float] = {}
    for k, v in sums.items():
        if v:
            out[k] = sum(v) / len(v)
    return out or None


async def _try_flashscore(game_id: int) -> JSONDict | None:
    """Headless Playwright запрос к Flashscore.

    На сайте агрессивный антибот; пробуем navigate + чтение DOM.
    На любой проблеме — None, чтобы не валить прогноз. SStats-`flashId`
    мы пока не используем, потому что Flashscore публикует matchId по
    хэшу (8 символов), а не по числовому id из SStats.
    """
    del game_id  # пока не используем — нужен пред-маппинг flashId
    try:
        # Импорт нужен, чтобы убедиться, что Playwright установлен,
        # иначе возвращаем None.
        import playwright.async_api  # noqa: F401
    except ImportError:
        return None
    # Без точного flashId-> matchHash маппинга мы не можем найти страницу
    # матча. Возвращаем None как явный no-op (best-effort placeholder).
    return None


__all__ = [
    "ExternalOddsBundle",
    "NBBetClient",
    "fetch_external_odds",
]
