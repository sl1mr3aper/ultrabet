"""Тесты text_processor."""

from __future__ import annotations

import pytest

from services.text_processor import (
    best_match,
    fuzzy_score,
    highlight,
    normalize_search,
    pluralize_ru,
    slugify,
    top_matches,
    transliterate,
    truncate,
)


def test_transliterate_basic():
    assert transliterate("Спартак") == "Spartak"
    assert transliterate("москва") == "moskva"


def test_transliterate_preserves_latin():
    assert transliterate("hello") == "hello"


def test_normalize_search_strips_punct():
    assert normalize_search("Hello, World!") == "helloworld"


def test_normalize_search_lowercase():
    assert normalize_search("СПАРТАК") == "спартак"


def test_fuzzy_score_identical():
    assert fuzzy_score("abc", "abc") == 1.0


def test_fuzzy_score_completely_different():
    assert fuzzy_score("abc", "xyz") < 0.5


def test_fuzzy_score_with_translit():
    # "Spartak" vs "Спартак" должно быть похоже
    assert fuzzy_score("Spartak", "Спартак") > 0.7


def test_best_match_above_threshold():
    candidates = ["Real Madrid", "Barcelona", "Juventus"]
    assert best_match("Real", candidates) == "Real Madrid"


def test_best_match_below_threshold_returns_none():
    assert best_match("Pizza", ["Apple", "Banana"], min_score=0.8) is None


def test_best_match_empty_candidates():
    assert best_match("anything", []) is None


def test_top_matches_sorted():
    cands = ["Real Madrid", "Real Sociedad", "Atletico Madrid"]
    results = top_matches("Real", cands, top_n=3)
    assert results[0][0] == "Real Madrid"
    assert results[1][0] == "Real Sociedad"


def test_top_matches_respects_top_n():
    cands = ["a", "ab", "abc", "abcd", "abcde"]
    assert len(top_matches("a", cands, top_n=2)) == 2


def test_highlight_basic():
    out = highlight("I love football", ["football"])
    assert "**football**" in out


def test_highlight_case_insensitive():
    out = highlight("Football is great", ["football"])
    assert "**Football**" in out


def test_highlight_multiple_keywords():
    out = highlight("Goal scored in match", ["Goal", "match"])
    assert "**Goal**" in out
    assert "**match**" in out


def test_slugify():
    assert slugify("Real Madrid!") == "real-madrid"
    assert slugify("Спартак Москва") == "spartak-moskva"


def test_truncate():
    assert truncate("hello", max_length=10) == "hello"
    assert truncate("hello world", max_length=7) == "hello …"


@pytest.mark.parametrize(
    "count,expected",
    [
        (1, "матч"),
        (2, "матча"),
        (5, "матчей"),
        (21, "матч"),
        (22, "матча"),
        (25, "матчей"),
        (11, "матчей"),
        (111, "матчей"),
    ],
)
def test_pluralize_ru(count, expected):
    assert pluralize_ru(count, "матч", "матча", "матчей") == expected
