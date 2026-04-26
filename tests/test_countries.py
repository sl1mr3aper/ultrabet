"""Тесты словарей стран."""

from __future__ import annotations

from services.countries import country_flag, country_ru, format_country


def test_country_ru_known():
    assert country_ru("England") == "Англия"
    assert country_ru("Spain") == "Испания"
    assert country_ru("Germany") == "Германия"


def test_country_ru_normalizes():
    assert country_ru("UNITED-STATES") == "США"
    assert country_ru("Czech Republic") == "Чехия"


def test_country_ru_unknown_returns_original():
    assert country_ru("Atlantis") == "Atlantis"


def test_country_flag_known():
    assert country_flag("England") == "🏴"
    assert country_flag("Russia") == "🇷🇺"


def test_country_flag_default():
    assert country_flag("Atlantis") == "🌐"


def test_format_country_full():
    text = format_country("Spain", with_flag=True)
    assert "Испания" in text
    assert "🇪🇸" in text


def test_format_country_no_flag():
    assert format_country("Spain", with_flag=False) == "Испания"


def test_format_country_empty():
    assert "Неизвестно" in format_country(None)
