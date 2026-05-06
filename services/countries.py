"""Маппинг названий стран EN → RU + флаги."""

from __future__ import annotations

_EN_TO_RU: dict[str, str] = {
    "world": "Международные",
    "international": "Международные",
    "europe": "Европа",
    "uefa": "УЕФА",
    "south-america": "Южная Америка",
    "north-central-america": "Северная и Центральная Америка",
    "asia": "Азия",
    "africa": "Африка",
    "oceania": "Океания",
    "albania": "Албания",
    "algeria": "Алжир",
    "andorra": "Андорра",
    "angola": "Ангола",
    "argentina": "Аргентина",
    "armenia": "Армения",
    "australia": "Австралия",
    "austria": "Австрия",
    "azerbaijan": "Азербайджан",
    "bahrain": "Бахрейн",
    "bangladesh": "Бангладеш",
    "belarus": "Беларусь",
    "belgium": "Бельгия",
    "bolivia": "Боливия",
    "bosnia": "Босния и Герцеговина",
    "bosnia-and-herzegovina": "Босния и Герцеговина",
    "botswana": "Ботсвана",
    "brazil": "Бразилия",
    "bulgaria": "Болгария",
    "burkina-faso": "Буркина-Фасо",
    "burundi": "Бурунди",
    "cambodia": "Камбоджа",
    "cameroon": "Камерун",
    "canada": "Канада",
    "chile": "Чили",
    "china": "Китай",
    "china-pr": "Китай",
    "colombia": "Колумбия",
    "congo": "Конго",
    "costa-rica": "Коста-Рика",
    "ivory-coast": "Кот-д’Ивуар",
    "croatia": "Хорватия",
    "cuba": "Куба",
    "cyprus": "Кипр",
    "czech-republic": "Чехия",
    "czechia": "Чехия",
    "denmark": "Дания",
    "ecuador": "Эквадор",
    "egypt": "Египет",
    "el-salvador": "Сальвадор",
    "england": "Англия",
    "estonia": "Эстония",
    "ethiopia": "Эфиопия",
    "faroe-islands": "Фарерские острова",
    "finland": "Финляндия",
    "france": "Франция",
    "gabon": "Габон",
    "gambia": "Гамбия",
    "georgia": "Грузия",
    "germany": "Германия",
    "ghana": "Гана",
    "greece": "Греция",
    "guatemala": "Гватемала",
    "honduras": "Гондурас",
    "hong-kong": "Гонконг",
    "hungary": "Венгрия",
    "iceland": "Исландия",
    "india": "Индия",
    "indonesia": "Индонезия",
    "iran": "Иран",
    "iraq": "Ирак",
    "ireland": "Ирландия",
    "israel": "Израиль",
    "italy": "Италия",
    "jamaica": "Ямайка",
    "japan": "Япония",
    "jordan": "Иордания",
    "kazakhstan": "Казахстан",
    "kenya": "Кения",
    "kosovo": "Косово",
    "kuwait": "Кувейт",
    "kyrgyzstan": "Киргизия",
    "latvia": "Латвия",
    "lebanon": "Ливан",
    "libya": "Ливия",
    "liechtenstein": "Лихтенштейн",
    "lithuania": "Литва",
    "luxembourg": "Люксембург",
    "malaysia": "Малайзия",
    "malta": "Мальта",
    "mexico": "Мексика",
    "moldova": "Молдова",
    "monaco": "Монако",
    "mongolia": "Монголия",
    "montenegro": "Черногория",
    "morocco": "Марокко",
    "myanmar": "Мьянма",
    "namibia": "Намибия",
    "nepal": "Непал",
    "netherlands": "Нидерланды",
    "new-zealand": "Новая Зеландия",
    "nicaragua": "Никарагуа",
    "nigeria": "Нигерия",
    "north-korea": "Северная Корея",
    "north-macedonia": "Северная Македония",
    "macedonia": "Северная Македония",
    "northern-ireland": "Северная Ирландия",
    "norway": "Норвегия",
    "oman": "Оман",
    "pakistan": "Пакистан",
    "palestine": "Палестина",
    "panama": "Панама",
    "paraguay": "Парагвай",
    "peru": "Перу",
    "philippines": "Филиппины",
    "poland": "Польша",
    "portugal": "Португалия",
    "qatar": "Катар",
    "romania": "Румыния",
    "russia": "Россия",
    "rwanda": "Руанда",
    "san-marino": "Сан-Марино",
    "saudi-arabia": "Саудовская Аравия",
    "scotland": "Шотландия",
    "senegal": "Сенегал",
    "serbia": "Сербия",
    "singapore": "Сингапур",
    "slovakia": "Словакия",
    "slovenia": "Словения",
    "south-africa": "ЮАР",
    "south-korea": "Южная Корея",
    "korea-republic": "Южная Корея",
    "spain": "Испания",
    "sri-lanka": "Шри-Ланка",
    "sweden": "Швеция",
    "switzerland": "Швейцария",
    "syria": "Сирия",
    "taiwan": "Тайвань",
    "tajikistan": "Таджикистан",
    "tanzania": "Танзания",
    "thailand": "Таиланд",
    "trinidad-and-tobago": "Тринидад и Тобаго",
    "tunisia": "Тунис",
    "turkey": "Турция",
    "turkmenistan": "Туркменистан",
    "uganda": "Уганда",
    "ukraine": "Украина",
    "united-arab-emirates": "ОАЭ",
    "uae": "ОАЭ",
    "united-states": "США",
    "usa": "США",
    "uruguay": "Уругвай",
    "uzbekistan": "Узбекистан",
    "venezuela": "Венесуэла",
    "vietnam": "Вьетнам",
    "wales": "Уэльс",
    "yemen": "Йемен",
    "zambia": "Замбия",
    "zimbabwe": "Зимбабве",
}

_FLAGS: dict[str, str] = {
    "world": "🌍", "international": "🌍", "europe": "🇪🇺", "uefa": "🇪🇺",
    "south-america": "🌎", "north-central-america": "🌎", "asia": "🌏",
    "africa": "🌍", "oceania": "🌏",
    "england": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
    "scotland": "🏴󠁧󠁢󠁳󠁣󠁴󠁿",
    "wales": "🏴󠁧󠁢󠁷󠁬󠁳󠁿",
    "northern-ireland": "🇬🇧",
    "albania": "🇦🇱", "algeria": "🇩🇿", "andorra": "🇦🇩", "angola": "🇦🇴",
    "argentina": "🇦🇷", "armenia": "🇦🇲", "australia": "🇦🇺", "austria": "🇦🇹",
    "azerbaijan": "🇦🇿", "bahrain": "🇧🇭", "bangladesh": "🇧🇩", "belarus": "🇧🇾",
    "belgium": "🇧🇪", "bolivia": "🇧🇴", "bosnia": "🇧🇦", "bosnia-and-herzegovina": "🇧🇦",
    "botswana": "🇧🇼", "brazil": "🇧🇷", "bulgaria": "🇧🇬", "burkina-faso": "🇧🇫",
    "burundi": "🇧🇮", "cambodia": "🇰🇭", "cameroon": "🇨🇲", "canada": "🇨🇦",
    "chile": "🇨🇱", "china": "🇨🇳", "china-pr": "🇨🇳", "colombia": "🇨🇴",
    "congo": "🇨🇬", "costa-rica": "🇨🇷", "ivory-coast": "🇨🇮", "croatia": "🇭🇷",
    "cuba": "🇨🇺", "cyprus": "🇨🇾", "czech-republic": "🇨🇿", "czechia": "🇨🇿",
    "denmark": "🇩🇰", "ecuador": "🇪🇨", "egypt": "🇪🇬", "el-salvador": "🇸🇻",
    "estonia": "🇪🇪", "ethiopia": "🇪🇹", "faroe-islands": "🇫🇴", "finland": "🇫🇮",
    "france": "🇫🇷", "gabon": "🇬🇦", "gambia": "🇬🇲", "georgia": "🇬🇪",
    "germany": "🇩🇪", "ghana": "🇬🇭", "greece": "🇬🇷", "guatemala": "🇬🇹",
    "honduras": "🇭🇳", "hong-kong": "🇭🇰", "hungary": "🇭🇺", "iceland": "🇮🇸",
    "india": "🇮🇳", "indonesia": "🇮🇩", "iran": "🇮🇷", "iraq": "🇮🇶",
    "ireland": "🇮🇪", "israel": "🇮🇱", "italy": "🇮🇹", "jamaica": "🇯🇲",
    "japan": "🇯🇵", "jordan": "🇯🇴", "kazakhstan": "🇰🇿", "kenya": "🇰🇪",
    "kosovo": "🇽🇰", "kuwait": "🇰🇼", "kyrgyzstan": "🇰🇬", "latvia": "🇱🇻",
    "lebanon": "🇱🇧", "libya": "🇱🇾", "liechtenstein": "🇱🇮", "lithuania": "🇱🇹",
    "luxembourg": "🇱🇺", "malaysia": "🇲🇾", "malta": "🇲🇹", "mexico": "🇲🇽",
    "moldova": "🇲🇩", "monaco": "🇲🇨", "mongolia": "🇲🇳", "montenegro": "🇲🇪",
    "morocco": "🇲🇦", "myanmar": "🇲🇲", "namibia": "🇳🇦", "nepal": "🇳🇵",
    "netherlands": "🇳🇱", "new-zealand": "🇳🇿", "nicaragua": "🇳🇮", "nigeria": "🇳🇬",
    "north-korea": "🇰🇵", "north-macedonia": "🇲🇰", "macedonia": "🇲🇰",
    "norway": "🇳🇴", "oman": "🇴🇲", "pakistan": "🇵🇰", "palestine": "🇵🇸",
    "panama": "🇵🇦", "paraguay": "🇵🇾", "peru": "🇵🇪", "philippines": "🇵🇭",
    "poland": "🇵🇱", "portugal": "🇵🇹", "qatar": "🇶🇦", "romania": "🇷🇴",
    "russia": "🇷🇺", "rwanda": "🇷🇼", "san-marino": "🇸🇲", "saudi-arabia": "🇸🇦",
    "senegal": "🇸🇳", "serbia": "🇷🇸", "singapore": "🇸🇬", "slovakia": "🇸🇰",
    "slovenia": "🇸🇮", "south-africa": "🇿🇦", "south-korea": "🇰🇷",
    "korea-republic": "🇰🇷", "spain": "🇪🇸", "sri-lanka": "🇱🇰", "sweden": "🇸🇪",
    "switzerland": "🇨🇭", "syria": "🇸🇾", "taiwan": "🇹🇼", "tajikistan": "🇹🇯",
    "tanzania": "🇹🇿", "thailand": "🇹🇭", "trinidad-and-tobago": "🇹🇹",
    "tunisia": "🇹🇳", "turkey": "🇹🇷", "turkmenistan": "🇹🇲", "uganda": "🇺🇬",
    "ukraine": "🇺🇦", "united-arab-emirates": "🇦🇪", "uae": "🇦🇪",
    "united-states": "🇺🇸", "usa": "🇺🇸", "uruguay": "🇺🇾", "uzbekistan": "🇺🇿",
    "venezuela": "🇻🇪", "vietnam": "🇻🇳", "yemen": "🇾🇪", "zambia": "🇿🇲",
    "zimbabwe": "🇿🇼",
    # Алиасы Соединённого Королевства
    "uk": "🇬🇧", "united-kingdom": "🇬🇧", "great-britain": "🇬🇧", "gb": "🇬🇧",
}


_EN_TO_RU.setdefault("uk", "Великобритания")
_EN_TO_RU.setdefault("united-kingdom", "Великобритания")
_EN_TO_RU.setdefault("great-britain", "Великобритания")
_EN_TO_RU.setdefault("gb", "Великобритания")


def _normalize(name: str | None) -> str:
    if not name:
        return ""
    return name.strip().lower().replace("_", "-").replace(" ", "-")


def country_ru(name: str | None) -> str:
    if not name:
        return ""
    return _EN_TO_RU.get(_normalize(name), name)


def country_flag(name: str | None) -> str:
    if not name:
        return "🌐"
    return _FLAGS.get(_normalize(name), "🌐")


def format_country(name: str | None, *, with_flag: bool = True) -> str:
    if not name:
        return "🌐 Неизвестно"
    ru = country_ru(name)
    if not with_flag:
        return ru
    return f"{country_flag(name)} {ru}"


# ─── Алиасы для fuzzy-поиска ───────────────────────────────────────
# Ключ — канонический англоязычный ID (как в SStats, нижний регистр,
# дефис как разделитель), значение — список дополнительных написаний
# (RU/EN/короткие формы, опечатки, IATA/ISO).
_ALIASES: dict[str, list[str]] = {
    "russia": ["россия", "россии", "рф", "ru", "rus", "российская федерация"],
    "ukraine": ["украина", "укр", "ua", "ukr"],
    "belarus": ["беларусь", "белоруссия", "бел", "by", "blr"],
    "kazakhstan": ["казахстан", "каз", "kz", "kaz"],
    "england": ["англия", "инглэнд", "eng", "gb-eng"],
    "scotland": ["шотландия", "sco", "gb-sct"],
    "wales": ["уэльс", "wal", "gb-wls"],
    "northern-ireland": ["северная ирландия", "nir", "gb-nir", "n.ireland", "n-ireland"],
    "united-kingdom": ["великобритания", "англия и уэльс", "uk", "gb", "gbr"],
    "spain": ["испания", "esp", "es", "la liga", "ла лига"],
    "italy": ["италия", "ита", "ita", "it", "серия а"],
    "germany": ["германия", "ger", "de", "deu", "немцы", "бундеслига"],
    "france": ["франция", "fra", "fr", "ligue 1", "лига 1"],
    "portugal": ["португалия", "por", "pt"],
    "netherlands": ["нидерланды", "голландия", "nld", "ned", "nl", "эредивизие"],
    "belgium": ["бельгия", "bel", "be"],
    "turkey": ["турция", "tur", "tr"],
    "greece": ["греция", "gre", "gr"],
    "poland": ["польша", "pol", "pl"],
    "romania": ["румыния", "rou", "ro"],
    "czech-republic": ["чехия", "cze", "cz"],
    "czechia": ["чехия", "cze", "cz"],
    "austria": ["австрия", "aut", "at"],
    "switzerland": ["швейцария", "sui", "ch", "che"],
    "denmark": ["дания", "den", "dk", "dnk"],
    "sweden": ["швеция", "swe", "se"],
    "norway": ["норвегия", "nor", "no"],
    "finland": ["финляндия", "fin", "fi"],
    "iceland": ["исландия", "isl", "is"],
    "ireland": ["ирландия", "irl", "ie"],
    "serbia": ["сербия", "srb", "rs"],
    "croatia": ["хорватия", "cro", "hr", "hrv"],
    "slovenia": ["словения", "svn", "si"],
    "slovakia": ["словакия", "svk", "sk"],
    "hungary": ["венгрия", "hun", "hu"],
    "bulgaria": ["болгария", "bul", "bg", "bgr"],
    "bosnia-and-herzegovina": ["босния", "босния и герцеговина", "bih", "ba"],
    "bosnia": ["босния", "bih", "ba"],
    "north-macedonia": ["северная македония", "македония", "mkd", "mk"],
    "albania": ["албания", "alb", "al"],
    "kosovo": ["косово", "kos", "xk"],
    "moldova": ["молдова", "молдавия", "mda", "md"],
    "georgia": ["грузия", "geo", "ge"],
    "armenia": ["армения", "arm", "am"],
    "azerbaijan": ["азербайджан", "aze", "az"],
    "cyprus": ["кипр", "cyp", "cy"],
    "malta": ["мальта", "mlt", "mt"],
    "montenegro": ["черногория", "mne", "me"],
    "usa": ["сша", "usa", "us", "америка", "соединённые штаты"],
    "united-states": ["сша", "usa", "us", "америка", "соединённые штаты"],
    "canada": ["канада", "can", "ca"],
    "mexico": ["мексика", "mex", "mx"],
    "brazil": ["бразилия", "bra", "br", "бразилия серия а"],
    "argentina": ["аргентина", "arg", "ar"],
    "chile": ["чили", "chi", "cl", "chl"],
    "colombia": ["колумбия", "col", "co"],
    "peru": ["перу", "per", "pe"],
    "uruguay": ["уругвай", "uru", "uy", "ury"],
    "paraguay": ["парагвай", "par", "py", "pry"],
    "ecuador": ["эквадор", "ecu", "ec"],
    "bolivia": ["боливия", "bol", "bo"],
    "venezuela": ["венесуэла", "ven", "ve"],
    "japan": ["япония", "jpn", "jp", "j-лига"],
    "south-korea": ["южная корея", "корея", "kor", "kr", "k league"],
    "korea-republic": ["южная корея", "корея", "kor", "kr"],
    "north-korea": ["северная корея", "кндр", "prk", "kp"],
    "china": ["китай", "chn", "cn"],
    "china-pr": ["китай", "chn", "cn"],
    "india": ["индия", "ind", "in"],
    "thailand": ["таиланд", "тайланд", "tha", "th"],
    "vietnam": ["вьетнам", "vie", "vn", "vnm"],
    "indonesia": ["индонезия", "idn", "id"],
    "malaysia": ["малайзия", "mys", "my"],
    "singapore": ["сингапур", "sgp", "sg"],
    "philippines": ["филиппины", "phl", "ph"],
    "iran": ["иран", "irn", "ir"],
    "iraq": ["ирак", "irq", "iq"],
    "saudi-arabia": ["саудовская аравия", "ксв", "sau", "sa"],
    "united-arab-emirates": ["оаэ", "объединённые арабские эмираты", "uae", "are", "ae"],
    "uae": ["оаэ", "объединённые арабские эмираты", "uae", "are", "ae"],
    "qatar": ["катар", "qat", "qa"],
    "israel": ["израиль", "isr", "il"],
    "egypt": ["египет", "egy", "eg"],
    "morocco": ["марокко", "mar", "ma"],
    "tunisia": ["тунис", "tun", "tn"],
    "algeria": ["алжир", "dza", "dz"],
    "nigeria": ["нигерия", "nga", "ng"],
    "ghana": ["гана", "gha", "gh"],
    "south-africa": ["юар", "south africa", "zaf", "za"],
    "australia": ["австралия", "aus", "au", "a-league"],
    "new-zealand": ["новая зеландия", "nzl", "nz"],
    "europe": ["европа", "uefa", "уефа"],
    "uefa": ["европа", "uefa", "уефа"],
    "world": ["мир", "fifa", "фифа", "международные", "международный"],
    "international": ["международные", "международный", "сборные"],
    "south-america": ["южная америка", "conmebol", "конмебол"],
    "north-central-america": [
        "северная америка",
        "концакаф",
        "concacaf",
        "центральная америка",
    ],
}


def _translit_ru_to_en(text: str) -> str:
    table = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sh",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
    return "".join(table.get(ch, ch) for ch in text.lower())


def _norm_search(text: str) -> str:
    """Нормализация для сопоставления: lower, без диакритики, без разделителей."""
    try:
        from unidecode import unidecode  # type: ignore
        text = unidecode(text)
    except Exception:
        pass
    text = text.lower().strip()
    for ch in "-_.,:;/()[]{}\"'`":
        text = text.replace(ch, " ")
    return " ".join(text.split())


def country_candidates(name: str | None) -> list[str]:
    """Возвращает ВСЕ варианты строкового представления страны для сопоставления.

    Используется поиском по списку SStats-лиг: собираем канонический id,
    RU-перевод, все алиасы + транслиты.
    """
    if not name:
        return []
    canon = _normalize(name)
    out: list[str] = [canon]
    ru = _EN_TO_RU.get(canon)
    if ru:
        out.append(ru)
    aliases = _ALIASES.get(canon, [])
    out.extend(aliases)
    # Добавим сырое название (например, SStats может прислать 'England')
    out.append(name)
    return out


def fuzzy_country_match(
    query: str,
    *,
    countries: list[str] | None = None,
    top_k: int = 5,
) -> list[tuple[str, float]]:
    """Возвращает список (canonical_id_или_name, score∈[0..1]) — топ совпадений.

    Этапы:
    1. exact (canonical id / RU / alias) → score = 1.0
    2. prefix match (алиас/название начинается на запрос) → 0.95
    3. translit: если запрос на кириллице, превращаем в латиницу и ищем
       exact/prefix по алиасам → 0.9
    4. rapidfuzz по всем вариантам (token_sort_ratio + WRatio) → 0.0..0.85

    `countries` — необязательный список канонических id, если хочется
    ограничить матчинг (например, доступные страны из SStats). Если не
    задано — ищем по всем известным ключам алиасного словаря + _EN_TO_RU.
    """
    q_raw = (query or "").strip()
    if len(q_raw) < 2:
        return []
    q_norm = _norm_search(q_raw)
    q_trans = _norm_search(_translit_ru_to_en(q_raw))

    known: set[str] = set(_EN_TO_RU.keys()) | set(_ALIASES.keys())
    if countries:
        pool = [_normalize(c) for c in countries]
    else:
        pool = sorted(known)

    # Предсобранные «поисковые строки» для каждого канона.
    variants: dict[str, list[str]] = {}
    for canon in pool:
        if not canon:
            continue
        alts = [canon]
        ru = _EN_TO_RU.get(canon)
        if ru:
            alts.append(ru)
        alts.extend(_ALIASES.get(canon, []))
        variants[canon] = [_norm_search(a) for a in alts if a]

    scores: dict[str, float] = {}

    def _bump(canon: str, score: float) -> None:
        if score > scores.get(canon, 0.0):
            scores[canon] = score

    # 1) exact
    for canon, alts in variants.items():
        if q_norm in alts or q_trans in alts:
            _bump(canon, 1.0)
    # 2) prefix
    for canon, alts in variants.items():
        for alt in alts:
            if alt.startswith(q_norm) or (q_trans and alt.startswith(q_trans)):
                _bump(canon, 0.95)
                break
    # 3) substring
    for canon, alts in variants.items():
        for alt in alts:
            if (q_norm and q_norm in alt) or (q_trans and q_trans in alt):
                _bump(canon, 0.9)
                break

    # 4) rapidfuzz
    try:
        from rapidfuzz import fuzz  # type: ignore

        for canon, alts in variants.items():
            best = 0.0
            for alt in alts:
                s = max(
                    fuzz.token_sort_ratio(q_norm, alt) / 100.0,
                    fuzz.WRatio(q_norm, alt) / 100.0,
                    fuzz.partial_ratio(q_norm, alt) / 100.0,
                )
                if q_trans:
                    s = max(
                        s,
                        fuzz.token_sort_ratio(q_trans, alt) / 100.0,
                        fuzz.WRatio(q_trans, alt) / 100.0,
                    )
                if s > best:
                    best = s
            # Приглушаем rapidfuzz-скор, чтобы он не конкурировал с prefix/exact.
            _bump(canon, min(best * 0.85, 0.85))
    except Exception:
        pass

    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return ordered[:top_k]


__all__ = [
    "country_candidates",
    "country_flag",
    "country_ru",
    "format_country",
    "fuzzy_country_match",
]
