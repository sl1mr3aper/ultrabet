"""Утилиты обработки текста: транслит, fuzzy, хайлайт, unidecode.

Используется в 6-этапном поиске команд (services/match_finder.py):
1) сырой запрос, 2) алиасы, 3) транслит, 4) unidecode, 5) по словам,
6) rapidfuzz ранжирование.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

try:  # rapidfuzz — опциональный ускоритель/улучшитель точности
    from rapidfuzz import fuzz as _rf_fuzz
except ImportError:  # pragma: no cover
    _rf_fuzz = None  # type: ignore[assignment]

try:
    from unidecode import unidecode as _unidecode
except ImportError:  # pragma: no cover
    def _unidecode(s: str) -> str:
        return s

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d",
    "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i",
    "й": "y", "к": "k", "л": "l", "м": "m", "н": "n",
    "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch",
    "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "",
    "э": "e", "ю": "yu", "я": "ya",
}

_REVERSE_TRANSLIT = {v: k for k, v in _TRANSLIT.items() if v}


def transliterate(text: str) -> str:
    """Кириллица → латиница."""
    out = []
    for ch in text:
        low = ch.lower()
        if low in _TRANSLIT:
            tr = _TRANSLIT[low]
            if ch.isupper():
                tr = tr.capitalize() if len(tr) > 1 else tr.upper()
            out.append(tr)
        else:
            out.append(ch)
    return "".join(out)


def normalize_search(text: str) -> str:
    """Убирает диакритические знаки, спецсимволы, пробелы. Возвращает lowercase."""
    text = text.lower().strip()
    # Удаляем диакритические знаки через NFD normalization
    nfkd = unicodedata.normalize("NFKD", text)
    out = "".join(c for c in nfkd if not unicodedata.combining(c))
    out = re.sub(r"[^a-zа-я0-9]+", "", out)
    return out


def _ascii_norm(s: str) -> str:
    """Кириллица → латиница → unidecode → normalize_search."""
    return normalize_search(_unidecode(transliterate(s)))


def fuzzy_score(a: str, b: str) -> float:
    """Устойчивый fuzzy-ratio в диапазоне 0..1.

    Комбинируем: прямое сравнение нормализованных строк + ASCII-транслит
    (через unidecode) + rapidfuzz token_sort/partial (если доступно).
    Берём максимум — это делает поиск толерантным к диакритике, сокращениям
    и разному порядку слов.
    """
    a_norm = normalize_search(a)
    b_norm = normalize_search(b)
    direct = SequenceMatcher(a=a_norm, b=b_norm).ratio()
    tr_a = _ascii_norm(a)
    tr_b = _ascii_norm(b)
    tr = SequenceMatcher(a=tr_a, b=tr_b).ratio()
    scores = [direct, tr]
    if _rf_fuzz is not None:
        # Фазовый поиск: устойчив к перестановкам и префиксам
        scores.append(_rf_fuzz.token_sort_ratio(tr_a, tr_b) / 100.0)
        scores.append(_rf_fuzz.partial_ratio(tr_a, tr_b) / 100.0)
        scores.append(_rf_fuzz.WRatio(tr_a, tr_b) / 100.0)
    return max(scores) if scores else 0.0


def best_match(query: str, candidates: list[str], *, min_score: float = 0.4) -> str | None:
    if not candidates:
        return None
    best: tuple[str, float] | None = None
    for cand in candidates:
        score = fuzzy_score(query, cand)
        if best is None or score > best[1]:
            best = (cand, score)
    if best is None or best[1] < min_score:
        return None
    return best[0]


def top_matches(
    query: str,
    candidates: list[str],
    *,
    top_n: int = 5,
    min_score: float = 0.3,
) -> list[tuple[str, float]]:
    scored = [(c, fuzzy_score(query, c)) for c in candidates]
    scored = [(c, s) for c, s in scored if s >= min_score]
    scored.sort(key=lambda cs: cs[1], reverse=True)
    return scored[:top_n]


def highlight(text: str, keywords: list[str]) -> str:
    """Оборачивает каждое вхождение ключевого слова в **жирный** (Markdown)."""
    if not keywords:
        return text
    for kw in keywords:
        if not kw:
            continue
        pattern = re.compile(re.escape(kw), re.IGNORECASE)
        text = pattern.sub(lambda m: f"**{m.group(0)}**", text)
    return text


def slugify(text: str, *, separator: str = "-") -> str:
    """Делает url-safe slug."""
    text = transliterate(text).lower()
    text = re.sub(r"[^a-z0-9]+", separator, text)
    return text.strip(separator)


def truncate(text: str, *, max_length: int = 120, suffix: str = "…") -> str:
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix


def pluralize_ru(count: int, one: str, few: str, many: str) -> str:
    """Русский плюрализатор: 1 матч / 2 матча / 5 матчей."""
    n = abs(count)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return few
    return many


__all__ = [
    "best_match",
    "fuzzy_score",
    "highlight",
    "normalize_search",
    "pluralize_ru",
    "slugify",
    "top_matches",
    "transliterate",
    "truncate",
]
