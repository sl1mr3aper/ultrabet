"""Проверки словаря алиасов команд."""

from services.team_aliases import TEAM_ALIASES, expand_aliases


def test_abbreviation_resolves_to_canonical_name() -> None:
    res = expand_aliases("мю")
    assert "Manchester United" in res
    # Исходный запрос всегда первый
    assert res[0].lower() == "мю"


def test_multiple_candidates_for_ambiguous_query() -> None:
    res = expand_aliases("милан")
    assert any("Milan" in r for r in res)


def test_psg_multilingual() -> None:
    res_en = expand_aliases("psg")
    res_ru = expand_aliases("псж")
    assert any("Paris" in r for r in res_en)
    assert any("Paris" in r for r in res_ru)


def test_empty_query_returns_empty() -> None:
    assert expand_aliases("") == []
    assert expand_aliases("   ") == []


def test_unknown_query_returns_only_original() -> None:
    res = expand_aliases("неизвестнаякоманда123")
    assert res == ["неизвестнаякоманда123"]


def test_alias_dict_sanity() -> None:
    # Все значения — список непустых строк
    for key, val in TEAM_ALIASES.items():
        assert isinstance(key, str) and key
        assert isinstance(val, list) and val
        for name in val:
            assert isinstance(name, str) and name.strip()


def test_fluff_stripping() -> None:
    res = expand_aliases("фк зенит")
    assert any("Zenit" in r for r in res)
