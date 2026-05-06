"""P0-7: маппинг канонических имён команд между источниками данных.

Источники различаются в написании:

  SStats:        "Paris Saint Germain"
  Understat:     "Paris Saint Germain"
  FDC (csv):     "Paris SG"

  SStats:        "Manchester United"
  Understat:     "Manchester United"
  FDC (csv):     "Man United"

Этот модуль предоставляет:

* ``normalize(name)``  — приводит имя к каноническому ключу
  (lowercase, без артиклей, без префиксов FC/AFC/CF, без суффиксов
  "BK"/"FK", удалены диакритики). Используется как ключ во всех
  кросс-источных lookup'ах.

* ``to_understat(sstats_name)`` — возвращает имя команды в стиле
  Understat. Если оно неизвестно — возвращает входное имя как fallback.

* ``to_fdc(sstats_name)``        — возвращает имя в стиле football-data.

База алиасов сейчас зашита в код (топ-50 европейских клубов), при
расширении подключи внешнюю таблицу ``team_name_aliases``.
"""

from __future__ import annotations

import re
import unicodedata

# ── Канонизация ────────────────────────────────────────────────────────────

_PREFIX_RE = re.compile(r"^(fc|afc|cf|ac|cd|sd|us|sc|rc|kv|kf|sk|sl)\b\s*", re.I)
_SUFFIX_RE = re.compile(r"\s*\b(fc|afc|fk|bk|sk|kv|cf|ac|sc|sd|us|rc|cd)$", re.I)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _strip_diacritics(s: str) -> str:
    """Заменяет диакритику ASCII-эквивалентом."""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize(name: str) -> str:
    """Канонический ключ команды.

    Примеры:
        "FC Bayern München"   -> "bayernmunchen"
        "Atlético de Madrid"  -> "atleticodemadrid"
        "Manchester United"   -> "manchesterunited"
        "Man United"          -> "manunited"
        "Paris SG"            -> "parissg"
    """
    if not name:
        return ""
    s = _strip_diacritics(name).lower().strip()
    s = _PREFIX_RE.sub("", s)
    s = _SUFFIX_RE.sub("", s)
    s = _NON_ALNUM.sub("", s)
    return s


# ── Перекрёстные алиасы (sstats canonical key → variant per source) ───────


# Источник истины: имена в SStats (как они приходят с Live API).
# Для каждого мы знаем, как их называют другие источники — если по-другому.
# Если значения нет → сохраняем имя SStats (большинство Latin-только лиг).
_SSTATS_TO_UNDERSTAT: dict[str, str] = {
    # Премьер-Лига
    "manchesterunited": "Manchester United",
    "manchestercity": "Manchester City",
    "tottenham": "Tottenham",
    "tottenhamhotspur": "Tottenham",
    "arsenal": "Arsenal",
    "chelsea": "Chelsea",
    "liverpool": "Liverpool",
    "newcastleunited": "Newcastle United",
    "westhamunited": "West Ham",
    "westham": "West Ham",
    "astonvilla": "Aston Villa",
    "wolverhamptonwanderers": "Wolverhampton Wanderers",
    "wolves": "Wolverhampton Wanderers",
    "brightonhoveal": "Brighton",
    "brightonhovealbion": "Brighton",
    "brighton": "Brighton",
    "crystalpalace": "Crystal Palace",
    "leedsunited": "Leeds",
    "leicestercity": "Leicester",
    "everton": "Everton",
    "fulham": "Fulham",
    "brentford": "Brentford",
    "bournemouth": "Bournemouth",
    "nottinghamforest": "Nottingham Forest",
    # La Liga
    "realmadrid": "Real Madrid",
    "barcelona": "Barcelona",
    "atleticodemadrid": "Atletico Madrid",
    "atleticomadrid": "Atletico Madrid",
    "atletico": "Atletico Madrid",
    "athleticbilbao": "Athletic Club",
    "athleticclub": "Athletic Club",
    "realsociedad": "Real Sociedad",
    "villarreal": "Villarreal",
    "valencia": "Valencia",
    "sevilla": "Sevilla",
    "betis": "Real Betis",
    "realbetis": "Real Betis",
    "celta": "Celta Vigo",
    "celtavigo": "Celta Vigo",
    "espanyol": "Espanyol",
    "girona": "Girona",
    "mallorca": "Mallorca",
    "osasuna": "Osasuna",
    # Bundesliga
    "bayernmunchen": "Bayern Munich",
    "bayernmunich": "Bayern Munich",
    "borussiadortmund": "Borussia Dortmund",
    "rblipzig": "RasenBallsport Leipzig",
    "rasenballsportlipzig": "RasenBallsport Leipzig",
    "bayer04leverkusen": "Bayer Leverkusen",
    "bayerleverkusen": "Bayer Leverkusen",
    "borussiamonchengladbach": "Borussia M.Gladbach",
    "eintrachtfrankfurt": "Eintracht Frankfurt",
    "vflwolfsburg": "Wolfsburg",
    # Serie A
    "interdimilano": "Internazionale",
    "internazionale": "Internazionale",
    "inter": "Internazionale",
    "milan": "Milan",
    "acmilan": "Milan",
    "juventus": "Juventus",
    "napoli": "Napoli",
    "roma": "Roma",
    "lazio": "Lazio",
    "atalanta": "Atalanta",
    "fiorentina": "Fiorentina",
    "torino": "Torino",
    "bologna": "Bologna",
    # Ligue 1
    "parissaintgermain": "Paris Saint Germain",
    "psg": "Paris Saint Germain",
    "olympiquedemarseille": "Marseille",
    "olympiquemarseille": "Marseille",
    "marseille": "Marseille",
    "olympiquelyonnais": "Lyon",
    "lyon": "Lyon",
    "monaco": "Monaco",
    "lille": "Lille",
    "rennes": "Rennes",
    "nice": "Nice",
}


# football-data.co.uk использует более короткие имена (Man United vs Manchester United).
_SSTATS_TO_FDC: dict[str, str] = {
    # Премьер-Лига
    "manchesterunited": "Man United",
    "manchestercity": "Man City",
    "tottenham": "Tottenham",
    "tottenhamhotspur": "Tottenham",
    "arsenal": "Arsenal",
    "chelsea": "Chelsea",
    "liverpool": "Liverpool",
    "newcastleunited": "Newcastle",
    "westhamunited": "West Ham",
    "westham": "West Ham",
    "astonvilla": "Aston Villa",
    "wolverhamptonwanderers": "Wolves",
    "wolves": "Wolves",
    "brightonhoveal": "Brighton",
    "brightonhovealbion": "Brighton",
    "brighton": "Brighton",
    "crystalpalace": "Crystal Palace",
    "leedsunited": "Leeds",
    "leicestercity": "Leicester",
    "everton": "Everton",
    "fulham": "Fulham",
    "brentford": "Brentford",
    "bournemouth": "Bournemouth",
    "nottinghamforest": "Nott'm Forest",
    # La Liga
    "realmadrid": "Real Madrid",
    "barcelona": "Barcelona",
    "atleticodemadrid": "Ath Madrid",
    "atleticomadrid": "Ath Madrid",
    "atletico": "Ath Madrid",
    "athleticbilbao": "Ath Bilbao",
    "athleticclub": "Ath Bilbao",
    "realsociedad": "Sociedad",
    "villarreal": "Villarreal",
    "valencia": "Valencia",
    "sevilla": "Sevilla",
    "betis": "Betis",
    "realbetis": "Betis",
    "celta": "Celta",
    "celtavigo": "Celta",
    "espanyol": "Espanol",
    "girona": "Girona",
    "mallorca": "Mallorca",
    "osasuna": "Osasuna",
    # Bundesliga
    "bayernmunchen": "Bayern Munich",
    "bayernmunich": "Bayern Munich",
    "borussiadortmund": "Dortmund",
    "rblipzig": "RB Leipzig",
    "bayer04leverkusen": "Leverkusen",
    "bayerleverkusen": "Leverkusen",
    "borussiamonchengladbach": "M'gladbach",
    "eintrachtfrankfurt": "Ein Frankfurt",
    "vflwolfsburg": "Wolfsburg",
    # Serie A
    "interdimilano": "Inter",
    "internazionale": "Inter",
    "inter": "Inter",
    "milan": "Milan",
    "acmilan": "Milan",
    "juventus": "Juventus",
    "napoli": "Napoli",
    "roma": "Roma",
    "lazio": "Lazio",
    "atalanta": "Atalanta",
    "fiorentina": "Fiorentina",
    "torino": "Torino",
    "bologna": "Bologna",
    # Ligue 1
    "parissaintgermain": "Paris SG",
    "psg": "Paris SG",
    "olympiquedemarseille": "Marseille",
    "olympiquemarseille": "Marseille",
    "marseille": "Marseille",
    "olympiquelyonnais": "Lyon",
    "lyon": "Lyon",
    "monaco": "Monaco",
    "lille": "Lille",
    "rennes": "Rennes",
    "nice": "Nice",
}


def to_understat(sstats_name: str) -> str:
    """Возвращает имя команды для Understat. Fallback: исходное имя."""
    if not sstats_name:
        return ""
    return _SSTATS_TO_UNDERSTAT.get(normalize(sstats_name), sstats_name)


def to_fdc(sstats_name: str) -> str:
    """Возвращает имя команды для football-data.co.uk. Fallback: исходное."""
    if not sstats_name:
        return ""
    return _SSTATS_TO_FDC.get(normalize(sstats_name), sstats_name)


# ── Лиги ───────────────────────────────────────────────────────────────────

# Маппинг названий лиг (как приходят из SStats) → Understat slug.
_LEAGUE_TO_UNDERSTAT: dict[str, str] = {
    "premier league": "EPL",
    "english premier league": "EPL",
    "la liga": "La_liga",
    "laliga": "La_liga",
    "spanish la liga": "La_liga",
    "primera division": "La_liga",
    "bundesliga": "Bundesliga",
    "german bundesliga": "Bundesliga",
    "serie a": "Serie_A",
    "italian serie a": "Serie_A",
    "ligue 1": "Ligue_1",
    "french ligue 1": "Ligue_1",
    "russian premier league": "RFPL",
    "rpl": "RFPL",
    "premier liga": "RFPL",
}


def league_to_understat_slug(league_name: str) -> str | None:
    """SStats league name → Understat slug (или None)."""
    if not league_name:
        return None
    return _LEAGUE_TO_UNDERSTAT.get(league_name.lower().strip())


# Маппинг лиг → код football-data.co.uk
_LEAGUE_TO_FDC: dict[str, str] = {
    "premier league": "E0",
    "english premier league": "E0",
    "english championship": "E1",
    "championship": "E1",
    "la liga": "SP1",
    "laliga": "SP1",
    "primera division": "SP1",
    "bundesliga": "D1",
    "2. bundesliga": "D2",
    "serie a": "I1",
    "serie b": "I2",
    "ligue 1": "F1",
    "ligue 2": "F2",
    "eredivisie": "N1",
    "primeira liga": "P1",
    "scottish premiership": "SC0",
}


def league_to_fdc_code(league_name: str) -> str | None:
    """SStats league name → FDC код (E0/D1/SP1/...) или None."""
    if not league_name:
        return None
    return _LEAGUE_TO_FDC.get(league_name.lower().strip())


__all__ = [
    "league_to_fdc_code",
    "league_to_understat_slug",
    "normalize",
    "to_fdc",
    "to_understat",
]
