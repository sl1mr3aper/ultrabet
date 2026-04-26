"""Тесты i18n."""

from __future__ import annotations

import pytest

from services.i18n import DEFAULT_LANG, SUPPORTED_LANGS, keys_for, missing_for, t


def test_default_lang_is_ru():
    assert DEFAULT_LANG == "ru"


def test_all_supported_langs():
    assert "ru" in SUPPORTED_LANGS
    assert "en" in SUPPORTED_LANGS
    assert "uk" in SUPPORTED_LANGS
    assert "kz" in SUPPORTED_LANGS


@pytest.mark.parametrize("lang", ["ru", "en", "uk", "kz"])
def test_welcome_exists_in_all_langs(lang):
    assert t("welcome", lang) != "welcome"


def test_fallback_to_default():
    # Ключа "nonexistent" нет в en, fallback на DEFAULT, потом на сам ключ
    assert t("nonexistent.key", "en") == "nonexistent.key"


def test_unknown_lang_falls_back_to_default():
    assert t("welcome", "zh") == t("welcome", "ru")


def test_keys_for_each_lang_non_empty():
    for lang in SUPPORTED_LANGS:
        assert len(keys_for(lang)) > 0


def test_keys_for_unknown_lang_empty():
    assert keys_for("zz") == []


def test_missing_for_default_empty():
    assert missing_for(DEFAULT_LANG) == []


def test_value_bet_russian():
    assert "алуй" in t("value.bet", "ru") or "Валуй" in t("value.bet", "ru")


def test_strategy_keys_in_all_langs():
    for lang in SUPPORTED_LANGS:
        for kind in ("conservative", "balanced", "aggressive", "underdog"):
            out = t(f"strategy.{kind}", lang)
            assert isinstance(out, str) and len(out) > 0
