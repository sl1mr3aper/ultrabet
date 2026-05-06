"""Бесплатный безлимитный скрапер коэффициентов Pinnacle.

Pinnacle.com предоставляет публичный JSON-эндпоинт `guest.api.arcadia.pinnacle.com`,
без auth и без rate-limit (требуется только X-API-Key, общеизвестный для guest).
Источник стабильный, покрывает все топ-лиги футбола, кфы — самые точные на рынке.

Стратегия:
1. На старте загружаем список лиг для футбола (sport_id=29) — кэш 24ч.
2. По SStats league_id (или названию) находим соответствующий Pinnacle league_id.
3. Тянем `/leagues/{id}/matchups` (список матчей) и `/leagues/{id}/markets/straight`
   (все цены), кэшируем 5 минут.
4. По именам команд (норм. lower / без диакритики / fuzzy) находим matchup.
5. Конвертируем американские цены в десятичные кфы и формируем bookmaker
   формата SStats для скармливания OddsParser.

Все ошибки/таймауты — graceful degrade (None / пустой bundle). Не валит прогноз.
"""

from __future__ import annotations

import asyncio
import time
import unicodedata
from dataclasses import dataclass
from typing import Any

import aiohttp
from loguru import logger

JSONDict = dict[str, Any]

PIN_BASE = "https://guest.api.arcadia.pinnacle.com/0.1"
# Этот ключ вшит в публичную web-страницу pinnacle.com — он same-as-no-auth.
PIN_API_KEY = "CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R"
PIN_HEADERS = {
    "X-API-Key": PIN_API_KEY,
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://www.pinnacle.com/",
}
SOCCER_SPORT_ID = 29

# Маппинг по нашему SStats league_id → Pinnacle league_id (топ-лиги).
# Если на матч пришёл другой league_id — пробуем fuzzy-search по названию.
SSTATS_TO_PIN_LEAGUE: dict[int, int] = {
    140: 2196,    # La Liga
    39: 1980,     # Premier League
    78: 1842,     # Bundesliga
    135: 2436,    # Serie A IT
    61: 2036,     # Ligue 1
    88: 1928,     # Eredivisie  (валидируем lookup-ом если ID не совпал)
    94: 2451,     # Primeira PT (та же история)
    119: 1851,    # MLS (заглушка)
    218: 1792,    # Austria Bundesliga
    2: 1971,      # UEFA Champions League
    3: 1972,      # UEFA Europa League
}


def _amer_to_decimal(american: float) -> float | None:
    if american is None:
        return None
    if american >= 100:
        return round(american / 100.0 + 1.0, 3)
    if american <= -100:
        return round(100.0 / abs(american) + 1.0, 3)
    return None


# Стоп-слова, которые встречаются и в SStats и в Pinnacle, но мешают
# точному matchу. Удаляем их перед сравнением имён.
_STOP_TOKENS = (
    "fc", "sc", "cf", "afc", "ac", "as",  # клубные приставки
    "club", "futbol", "football", "calcio",
    "and", "the", "of",  # стоп-слова
    "hotspur", "albion", "rovers", "wanderers", "athletic", "town",
    "city",  # «Manchester City» оставляет «manchester» — но коллизия с United, см. синонимы
)
# Канонические синонимы команд (двусторонние).
_TEAM_ALIASES: dict[str, list[str]] = {
    # Англия
    "manchesterutd": ["manchesterunited", "manutd", "manunited"],
    "manchestercity": ["mancity"],
    "tottenhamhotspur": ["tottenham", "spurs"],
    "wolverhamptonwanderers": ["wolves", "wolverhampton"],
    "leicestercity": ["leicester"],
    "newcastleunited": ["newcastle"],
    "westhamunited": ["westham"],
    "leedsunited": ["leeds"],
    "brightonhovealbion": ["brighton", "brightonhove"],
    "afcbournemouth": ["bournemouth"],
    "nottinghamforest": ["nottmforest", "nottingham"],
    "crystalpalace": ["palace"],
    "sheffieldunited": ["sheffieldutd"],
    # Испания
    "atleticomadrid": ["atletico", "atletico"],
    "realsociedad": ["realsociedad", "sociedad"],
    "athleticbilbao": ["athletic", "athleticclub"],
    # Италия
    "internazionale": ["inter", "internazionale", "intermilan"],
    "acmilan": ["milan", "acmilan"],
    "asroma": ["roma", "asroma"],
    "juventus": ["juve", "juventus"],
    # Германия
    "bayernmunich": ["bayern", "bayernmunich"],
    "borussiadortmund": ["dortmund", "bvb"],
    "borussiamoenchengladbach": ["gladbach", "borussiamonchengladbach", "monchengladbach"],
    "bayer04leverkusen": ["bayerleverkusen", "leverkusen"],
    # Франция
    "parissaintgermain": ["psg", "paris"],
    "olympiquemarseille": ["marseille", "olmarseille"],
    "olympiquelyonnais": ["lyon", "lyonnais"],
}


def _norm_name(s: str) -> str:
    """Нормализация имени для сравнения: lower → strip diacritics → alnum."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return "".join(c for c in s if c.isalnum())


def _canonical_name(s: str) -> set[str]:
    """Возвращает множество канонических вариантов имени для матчинга:
    - сырое нормализованное;
    - без стоп-слов (fc, hotspur, ...);
    - все алиасы (manunited↔manchesterutd↔manchesterunited).

    Сравнение двух имён = непустое пересечение их канонических множеств.
    """
    n = _norm_name(s)
    if not n:
        return set()
    out = {n}
    # Без стоп-слов.
    cleaned = n
    for tok in _STOP_TOKENS:
        cleaned = cleaned.replace(tok, "")
    if cleaned and cleaned != n:
        out.add(cleaned)
    # Алиасы: как сам ключ, так и все значения.
    for canon, aliases in _TEAM_ALIASES.items():
        if n in (canon, *aliases) or cleaned in (canon, *aliases):
            out.add(canon)
            out.update(aliases)
    return out


def _names_match(a: str, b: str) -> bool:
    """True если имена a и b ссылаются на одну и ту же команду."""
    sa = _canonical_name(a)
    sb = _canonical_name(b)
    if not sa or not sb:
        return False
    if sa & sb:
        return True
    # Дополнительно — substring (для имён типа "Real Madrid CF" / "Real Madrid").
    for x in sa:
        for y in sb:
            if len(x) >= 5 and len(y) >= 5 and (x in y or y in x):
                return True
    return False


@dataclass
class _LeagueCache:
    leagues: list[JSONDict]
    fetched_at: float

    def is_fresh(self, ttl: float = 86400.0) -> bool:
        return time.monotonic() - self.fetched_at < ttl


@dataclass
class _MatchupsCache:
    matchups: list[JSONDict]
    markets: list[JSONDict]
    fetched_at: float

    def is_fresh(self, ttl: float = 300.0) -> bool:
        return time.monotonic() - self.fetched_at < ttl


class PinnacleOddsClient:
    """Best-effort клиент Pinnacle public API."""

    def __init__(
        self,
        *,
        request_timeout: float = 6.0,
        league_ttl: float = 86400.0,
        markets_ttl: float = 300.0,
    ) -> None:
        self._timeout = request_timeout
        self._league_ttl = league_ttl
        self._markets_ttl = markets_ttl
        self._leagues_cache: _LeagueCache | None = None
        self._matchups_cache: dict[int, _MatchupsCache] = {}
        self._lock = asyncio.Lock()

    async def _get_json(
        self, session: aiohttp.ClientSession, url: str
    ) -> Any:
        try:
            async with session.get(
                url,
                headers=PIN_HEADERS,
                timeout=aiohttp.ClientTimeout(total=self._timeout),
            ) as resp:
                if resp.status != 200:
                    logger.debug("pinnacle {} -> HTTP {}", url, resp.status)
                    return None
                return await resp.json()
        except (TimeoutError, aiohttp.ClientError) as exc:
            logger.debug("pinnacle {} fail: {}", url, exc)
            return None

    async def _ensure_leagues(self, session: aiohttp.ClientSession) -> list[JSONDict]:
        if self._leagues_cache and self._leagues_cache.is_fresh(self._league_ttl):
            return self._leagues_cache.leagues
        async with self._lock:
            if self._leagues_cache and self._leagues_cache.is_fresh(self._league_ttl):
                return self._leagues_cache.leagues
            data = await self._get_json(
                session, f"{PIN_BASE}/sports/{SOCCER_SPORT_ID}/leagues"
            )
            leagues = data if isinstance(data, list) else []
            self._leagues_cache = _LeagueCache(leagues=leagues, fetched_at=time.monotonic())
        return leagues

    async def _resolve_pin_league_id(
        self,
        session: aiohttp.ClientSession,
        sstats_league_id: int | None,
        sstats_league_name: str | None = None,
    ) -> int | None:
        if isinstance(sstats_league_id, int) and sstats_league_id in SSTATS_TO_PIN_LEAGUE:
            return SSTATS_TO_PIN_LEAGUE[sstats_league_id]
        if not sstats_league_name:
            return None
        # Fuzzy-search по имени.
        leagues = await self._ensure_leagues(session)
        needle = _norm_name(sstats_league_name)
        for lg in leagues:
            name = _norm_name(str(lg.get("name") or ""))
            if needle and (needle in name or name in needle):
                pin_id = lg.get("id")
                if isinstance(pin_id, int):
                    return pin_id
        return None

    async def _fetch_league_matchups(
        self, session: aiohttp.ClientSession, pin_league_id: int
    ) -> _MatchupsCache | None:
        cached = self._matchups_cache.get(pin_league_id)
        if cached and cached.is_fresh(self._markets_ttl):
            return cached
        matchups_task = self._get_json(
            session, f"{PIN_BASE}/leagues/{pin_league_id}/matchups"
        )
        markets_task = self._get_json(
            session, f"{PIN_BASE}/leagues/{pin_league_id}/markets/straight"
        )
        matchups, markets = await asyncio.gather(matchups_task, markets_task)
        if not isinstance(matchups, list) or not isinstance(markets, list):
            return None
        cached = _MatchupsCache(
            matchups=matchups, markets=markets, fetched_at=time.monotonic()
        )
        self._matchups_cache[pin_league_id] = cached
        return cached

    @staticmethod
    def _find_matchup(
        matchups: list[JSONDict], home: str, away: str
    ) -> JSONDict | None:
        """Находит ОСНОВНОЙ matchup (не специальный prop/handicap-suffix).

        Pinnacle помечает основной матч как `type=='matchup'` с
        `parent is None`. Все props (Bookings, Corners, AH с parent),
        teasers, "(+1)" — это `parent` ссылка на основной matchup.
        """
        if not home or not away:
            return None
        # Берём только полноценные матчи (без parent).
        main_only: list[JSONDict] = [
            m for m in matchups
            if isinstance(m, dict)
            and m.get("type") == "matchup"
            and m.get("parent") is None
        ]
        for m in main_only:
            ps = m.get("participants") or []
            if len(ps) < 2:
                continue
            p_home = str((ps[0] or {}).get("name") or "")
            p_away = str((ps[1] or {}).get("name") or "")
            if not p_home or not p_away:
                continue
            # Имена должны совпасть в "правильном" порядке (home↔home, away↔away).
            if _names_match(p_home, home) and _names_match(p_away, away):
                return m
            # Иногда home/away перепутаны при поиске; принимаем reverse.
            if _names_match(p_home, away) and _names_match(p_away, home):
                return m
        return None

    @staticmethod
    def _build_bookmaker(
        matchup: JSONDict, all_markets: list[JSONDict]
    ) -> JSONDict | None:
        """Конвертирует Pinnacle matchup+markets → SStats bookmaker dict."""
        mu_id = matchup.get("id")
        ps = matchup.get("participants") or []
        if not isinstance(mu_id, int) or len(ps) < 2:
            return None
        p_home_id = ps[0].get("id")
        p_away_id = ps[1].get("id")

        # Markets, относящиеся к этому матчу.
        my_markets = [
            mk for mk in all_markets
            if isinstance(mk, dict) and mk.get("matchupId") == mu_id and mk.get("period") == 0
        ]
        if not my_markets:
            return None

        odds_blocks: list[JSONDict] = []
        # Match Winner (1X2 / moneyline) — только non-alternate.
        ml = next(
            (
                mk for mk in my_markets
                if mk.get("type") == "moneyline" and not mk.get("isAlternate")
            ),
            None,
        )
        if ml is not None:
            home_odd = draw_odd = away_odd = None
            for pr in ml.get("prices", []) or []:
                price = pr.get("price")
                desig = pr.get("designation")
                if not isinstance(price, int | float):
                    continue
                dec = _amer_to_decimal(float(price))
                if dec is None:
                    continue
                if desig == "home":
                    home_odd = dec
                elif desig == "away":
                    away_odd = dec
                elif desig == "draw":
                    draw_odd = dec
            outcomes: list[JSONDict] = []
            if home_odd is not None:
                outcomes.append({"name": "Home", "value": home_odd})
            if draw_odd is not None:
                outcomes.append({"name": "Draw", "value": draw_odd})
            if away_odd is not None:
                outcomes.append({"name": "Away", "value": away_odd})
            if outcomes:
                odds_blocks.append(
                    {
                        "marketId": 1,
                        "marketName": "Match Winner",
                        "odds": outcomes,
                    }
                )

        # Тоталы (Over/Under) — все линии включая alternate (нам нужны 2.5/3.5).
        for mk in my_markets:
            if mk.get("type") != "total":
                continue
            over_odd = under_odd = None
            line_val: float | None = None
            for pr in mk.get("prices", []) or []:
                price = pr.get("price")
                designation = pr.get("designation")
                points = pr.get("points")
                if isinstance(points, int | float) and line_val is None:
                    line_val = float(points)
                if not isinstance(price, int | float):
                    continue
                dec = _amer_to_decimal(float(price))
                if dec is None:
                    continue
                if designation == "over":
                    over_odd = dec
                elif designation == "under":
                    under_odd = dec
            if line_val is None:
                continue
            ou_outcomes: list[JSONDict] = []
            if over_odd is not None:
                ou_outcomes.append({"name": f"Over {line_val}", "value": over_odd})
            if under_odd is not None:
                ou_outcomes.append({"name": f"Under {line_val}", "value": under_odd})
            if ou_outcomes:
                odds_blocks.append(
                    {
                        "marketId": 5,
                        "marketName": "Goals Over/Under",
                        "odds": ou_outcomes,
                    }
                )

        # Team totals — alternate lines тоже.
        for mk in my_markets:
            if mk.get("type") != "team_total":
                continue
            side = mk.get("side")  # "home" / "away"
            over_odd = under_odd = None
            line_val = None
            for pr in mk.get("prices", []) or []:
                price = pr.get("price")
                designation = pr.get("designation")
                points = pr.get("points")
                if isinstance(points, int | float) and line_val is None:
                    line_val = float(points)
                if not isinstance(price, int | float):
                    continue
                dec = _amer_to_decimal(float(price))
                if dec is None:
                    continue
                if designation == "over":
                    over_odd = dec
                elif designation == "under":
                    under_odd = dec
            if line_val is None:
                continue
            tt_outcomes: list[JSONDict] = []
            if over_odd is not None:
                tt_outcomes.append({"name": f"Over {line_val}", "value": over_odd})
            if under_odd is not None:
                tt_outcomes.append({"name": f"Under {line_val}", "value": under_odd})
            if tt_outcomes:
                market_name = (
                    "Home Team Total" if side == "home" else "Away Team Total"
                )
                odds_blocks.append(
                    {
                        "marketId": 7,
                        "marketName": market_name,
                        "odds": tt_outcomes,
                    }
                )

        # Спреды (форы / handicap) — основная и alternate линии.
        for mk in my_markets:
            if mk.get("type") != "spread":
                continue
            home_odd = away_odd = None
            home_pts = away_pts = None
            for pr in mk.get("prices", []) or []:
                price = pr.get("price")
                desig = pr.get("designation")
                points = pr.get("points")
                if not isinstance(price, int | float):
                    continue
                dec = _amer_to_decimal(float(price))
                if dec is None:
                    continue
                if desig == "home":
                    home_odd = dec
                    if isinstance(points, int | float):
                        home_pts = float(points)
                elif desig == "away":
                    away_odd = dec
                    if isinstance(points, int | float):
                        away_pts = float(points)
            ah_outcomes: list[JSONDict] = []
            if home_odd is not None and home_pts is not None:
                ah_outcomes.append(
                    {"name": f"Home {home_pts:+}", "value": home_odd}
                )
            if away_odd is not None and away_pts is not None:
                ah_outcomes.append(
                    {"name": f"Away {away_pts:+}", "value": away_odd}
                )
            if ah_outcomes:
                odds_blocks.append(
                    {
                        "marketId": 4,
                        "marketName": "Asian Handicap",
                        "odds": ah_outcomes,
                    }
                )

        if not odds_blocks:
            return None
        return {
            "bookmakerId": -10,
            "bookmakerName": "Pinnacle",
            "odds": odds_blocks,
        }

    async def fetch_odds_for_match(
        self,
        *,
        session: aiohttp.ClientSession,
        home_name: str,
        away_name: str,
        sstats_league_id: int | None,
        sstats_league_name: str | None = None,
    ) -> JSONDict | None:
        """Найти Pinnacle-bookmaker для матча. Любая ошибка → None."""
        try:
            pin_lg = await self._resolve_pin_league_id(
                session, sstats_league_id, sstats_league_name
            )
            if pin_lg is None:
                return None
            cache = await self._fetch_league_matchups(session, pin_lg)
            if cache is None:
                return None
            mu = self._find_matchup(cache.matchups, home_name, away_name)
            if mu is None:
                return None
            book = self._build_bookmaker(mu, cache.markets)
            if book is None:
                return None
            return book
        except Exception as exc:
            logger.debug("pinnacle fetch_odds_for_match error: {}", exc)
            return None


__all__ = ["PinnacleOddsClient"]
