"""Словарь популярных алиасов футбольных команд: RU ↔ EN ↔ сокращения.

Используется в многоэтапном поиске: пользовательский ввод
(`мю`, `псж`, `барса`, `реалы`, `цска`, `спартак`) разворачивается в набор
кандидатных запросов к SStats, чтобы не полагаться только на fuzzy по
«сырому» имени.
"""

from __future__ import annotations

# key — нормализованный пользовательский ввод (lowercase, без спецсимволов)
# value — список альтернативных запросов, которые передадим в SStats API
# Приоритет: сперва полные английские названия, затем локализованные и
# сокращения; если ничего не найдётся — клиент сам сделает fuzzy.
TEAM_ALIASES: dict[str, list[str]] = {
    # ——— Испания ———
    "мадрид": ["Real Madrid", "Atletico Madrid", "Rayo Vallecano"],
    "реал": ["Real Madrid"],
    "реалы": ["Real Madrid"],
    "real": ["Real Madrid"],
    "атлетико": ["Atletico Madrid"],
    "атлетик": ["Athletic Bilbao"],
    "бильбао": ["Athletic Bilbao"],
    "барса": ["Barcelona"],
    "барселона": ["Barcelona"],
    "барс": ["Barcelona"],
    "севилья": ["Sevilla"],
    "валенсия": ["Valencia"],
    "бетис": ["Real Betis"],
    "хетафе": ["Getafe"],
    "вильярреал": ["Villarreal"],
    "сосьедад": ["Real Sociedad"],
    "реал сосьедад": ["Real Sociedad"],
    "жирона": ["Girona"],
    "майорка": ["Mallorca"],
    "мальорка": ["Mallorca"],
    "кадис": ["Cadiz"],
    "алавес": ["Alaves"],
    "осасуна": ["Osasuna"],
    "леганес": ["Leganes"],
    "лас пальмас": ["Las Palmas"],
    "эспаньол": ["Espanyol"],
    "сельта": ["Celta Vigo"],
    "вальядолид": ["Valladolid"],
    "райо": ["Rayo Vallecano"],

    # ——— Англия ———
    "мю": ["Manchester United"],
    "манюнайтед": ["Manchester United"],
    "юнайтед": ["Manchester United"],
    "манчестер юнайтед": ["Manchester United"],
    "манч": ["Manchester United", "Manchester City"],
    "мс": ["Manchester City"],
    "манчестер сити": ["Manchester City"],
    "ман сити": ["Manchester City"],
    "сити": ["Manchester City"],
    "арсенал": ["Arsenal"],
    "челси": ["Chelsea"],
    "ливерпуль": ["Liverpool"],
    "тоттенхэм": ["Tottenham Hotspur"],
    "тоттенхем": ["Tottenham Hotspur"],
    "шпоры": ["Tottenham Hotspur"],
    "ньюкасл": ["Newcastle United"],
    "ньюкастл": ["Newcastle United"],
    "вест хэм": ["West Ham United"],
    "вест хем": ["West Ham United"],
    "астон вилла": ["Aston Villa"],
    "вилла": ["Aston Villa"],
    "брайтон": ["Brighton & Hove Albion", "Brighton"],
    "вулвз": ["Wolverhampton Wanderers"],
    "вулверхэмптон": ["Wolverhampton Wanderers"],
    "эвертон": ["Everton"],
    "форест": ["Nottingham Forest"],
    "ноттингем": ["Nottingham Forest"],
    "фулхэм": ["Fulham"],
    "борнмут": ["Bournemouth"],
    "брентфорд": ["Brentford"],
    "кристал пэлас": ["Crystal Palace"],
    "пэлас": ["Crystal Palace"],
    "лестер": ["Leicester City"],
    "ипсвич": ["Ipswich Town"],
    "саутгемптон": ["Southampton"],
    "лидс": ["Leeds United"],
    "бернли": ["Burnley"],
    "шеффилд юнайтед": ["Sheffield United"],
    "шеффилд": ["Sheffield United", "Sheffield Wednesday"],

    # ——— Италия ———
    "ювентус": ["Juventus"],
    "юве": ["Juventus"],
    "милан": ["AC Milan", "Inter Milan"],
    "ас милан": ["AC Milan"],
    "ac milan": ["AC Milan"],
    "интер": ["Inter Milan", "Inter"],
    "интернационале": ["Inter Milan"],
    "рома": ["Roma", "AS Roma"],
    "лацио": ["Lazio"],
    "наполи": ["Napoli"],
    "аталанта": ["Atalanta"],
    "фиорентина": ["Fiorentina"],
    "торино": ["Torino"],
    "болонья": ["Bologna"],
    "удинезе": ["Udinese"],
    "сассуоло": ["Sassuolo"],
    "верона": ["Hellas Verona", "Verona"],
    "эмполи": ["Empoli"],
    "кальяри": ["Cagliari"],
    "дженоа": ["Genoa"],
    "лечче": ["Lecce"],
    "монца": ["Monza"],
    "парма": ["Parma"],
    "венеция": ["Venezia"],

    # ——— Германия ———
    "бавария": ["Bayern Munich", "Bayern"],
    "баварцы": ["Bayern Munich"],
    "баер": ["Bayer Leverkusen"],
    "байер": ["Bayer Leverkusen"],
    "леверкузен": ["Bayer Leverkusen"],
    "бавария мюнхен": ["Bayern Munich"],
    "дортмунд": ["Borussia Dortmund"],
    "боруссия": ["Borussia Dortmund", "Borussia Monchengladbach"],
    "боруссия дортмунд": ["Borussia Dortmund"],
    "боруссия менхенгладбах": ["Borussia Monchengladbach"],
    "гладбах": ["Borussia Monchengladbach"],
    "лейпциг": ["RB Leipzig"],
    "рб лейпциг": ["RB Leipzig"],
    "айнтрахт": ["Eintracht Frankfurt"],
    "франкфурт": ["Eintracht Frankfurt"],
    "штутгарт": ["Stuttgart", "VfB Stuttgart"],
    "хоффенхайм": ["Hoffenheim"],
    "вольфсбург": ["Wolfsburg"],
    "унион": ["Union Berlin"],
    "унион берлин": ["Union Berlin"],
    "герта": ["Hertha Berlin"],
    "вердер": ["Werder Bremen"],
    "бремен": ["Werder Bremen"],
    "майнц": ["Mainz"],
    "фрайбург": ["Freiburg"],
    "бохум": ["Bochum"],
    "аугсбург": ["Augsburg"],
    "шальке": ["Schalke 04", "Schalke"],
    "гамбург": ["Hamburger SV", "Hamburg"],

    # ——— Франция ———
    "псж": ["Paris Saint-Germain", "PSG"],
    "парижане": ["Paris Saint-Germain"],
    "париж сен-жермен": ["Paris Saint-Germain"],
    "paris": ["Paris Saint-Germain"],
    "psg": ["Paris Saint-Germain"],
    "марсель": ["Marseille"],
    "лион": ["Lyon", "Olympique Lyonnais"],
    "монако": ["Monaco"],
    "лилль": ["Lille"],
    "ренн": ["Rennes"],
    "ницца": ["Nice"],
    "нант": ["Nantes"],
    "страсбур": ["Strasbourg"],
    "брест": ["Brest"],
    "тулуза": ["Toulouse"],
    "анже": ["Angers"],
    "ланс": ["Lens"],
    "ренн фк": ["Rennes"],
    "оверни": ["Clermont"],

    # ——— Нидерланды / Португалия / Шотландия / Турция / Бельгия ———
    "аякс": ["Ajax"],
    "псв": ["PSV Eindhoven"],
    "psv": ["PSV Eindhoven"],
    "фейеноорд": ["Feyenoord"],
    "эйндховен": ["PSV Eindhoven"],
    "бенфика": ["Benfica"],
    "порту": ["Porto", "FC Porto"],
    "спортинг": ["Sporting CP"],
    "спортинг лиссабон": ["Sporting CP"],
    "брага": ["Braga"],
    "селтик": ["Celtic"],
    "рейнджерс": ["Rangers"],
    "галатасарай": ["Galatasaray"],
    "фенербахче": ["Fenerbahce"],
    "бешикташ": ["Besiktas"],
    "трабзонспор": ["Trabzonspor"],
    "брюгге": ["Club Brugge"],
    "андерлехт": ["Anderlecht"],

    # ——— Россия ———
    "зенит": ["Zenit Saint Petersburg", "Zenit"],
    "спартак": ["Spartak Moscow", "Spartak"],
    "цска": ["CSKA Moscow"],
    "cska": ["CSKA Moscow"],
    "локомотив": ["Lokomotiv Moscow"],
    "локо": ["Lokomotiv Moscow"],
    "динамо": ["Dynamo Moscow"],
    "динамо москва": ["Dynamo Moscow"],
    "краснодар": ["Krasnodar"],
    "ростов": ["FK Rostov", "Rostov"],
    "рубин": ["Rubin Kazan"],
    "ахмат": ["Akhmat Grozny"],
    "химки": ["Khimki"],
    "сочи": ["Sochi"],
    "оренбург": ["Orenburg"],
    "пари нн": ["Pari Nizhny Novgorod"],
    "нижний": ["Pari Nizhny Novgorod"],
    "урал": ["Ural Yekaterinburg"],
    "факел": ["Fakel Voronezh"],
    "крылья советов": ["Krylia Sovetov"],

    # ——— Украина ———
    "динамо киев": ["Dynamo Kyiv", "Dynamo Kiev"],
    "шахтер": ["Shakhtar Donetsk"],
    "шахтёр": ["Shakhtar Donetsk"],

    # ——— Сборные / общее ———
    "англия": ["England"],
    "франция": ["France"],
    "испания": ["Spain"],
    "германия": ["Germany"],
    "италия": ["Italy"],
    "португалия": ["Portugal"],
    "нидерланды": ["Netherlands"],
    "бразилия": ["Brazil"],
    "аргентина": ["Argentina"],
    "россия": ["Russia"],
    "хорватия": ["Croatia"],
    "бельгия": ["Belgium"],
    "польша": ["Poland"],
    "турция": ["Turkey"],
    "украина": ["Ukraine"],
}


def expand_aliases(query: str) -> list[str]:
    """Раскрывает пользовательский ввод в набор кандидатных запросов.

    Всегда включает исходный запрос первым элементом. Пустые/дубли отсекаем.
    """
    q = (query or "").strip().lower()
    if not q:
        return []
    seen: set[str] = set()
    ordered: list[str] = []

    def _push(s: str) -> None:
        key = s.strip().lower()
        if not key or key in seen:
            return
        seen.add(key)
        ordered.append(s.strip())

    _push(query.strip())
    variants = TEAM_ALIASES.get(q)
    if variants:
        for v in variants:
            _push(v)
    # Попробовать снять префикс/суффикс «фк», «fc», «club», «football»
    for cleaned in _strip_fluff(q):
        if cleaned != q:
            _push(cleaned)
            for v in TEAM_ALIASES.get(cleaned, []) or []:
                _push(v)
    return ordered


_FLUFF = ("фк ", "fc ", "club ", "football ", "the ")
_FLUFF_SUFFIX = (" фк", " fc", " club", " cf", " sc", " afc")


def _strip_fluff(q: str) -> list[str]:
    out: list[str] = []
    for p in _FLUFF:
        if q.startswith(p):
            out.append(q[len(p):].strip())
    for s in _FLUFF_SUFFIX:
        if q.endswith(s):
            out.append(q[: -len(s)].strip())
    return out


__all__ = ["TEAM_ALIASES", "expand_aliases"]
