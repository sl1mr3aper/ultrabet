"""Тесты message_templates."""

from __future__ import annotations

from services.message_templates import TEMPLATES, available_templates, placeholders_in, render


def test_welcome_substitution():
    out = render("welcome", name="Jordan", ref_code="ABC123")
    assert "Jordan" in out
    assert "ABC123" in out


def test_unknown_template():
    out = render("nonexistent_key")
    assert "not found" in out


def test_all_templates_render_without_error():
    for key in TEMPLATES:
        render(key)  # no exception


def test_available_templates_non_empty():
    keys = available_templates()
    assert len(keys) > 0
    assert "welcome" in keys


def test_prediction_header_substitution():
    out = render(
        "prediction_header",
        icon="⚽",
        home="Real",
        away="Barca",
        league="LaLiga",
        date_time="today 20:00",
    )
    assert "Real" in out
    assert "Barca" in out
    assert "LaLiga" in out


def test_value_bet_row():
    out = render(
        "value_bet_row",
        rank=1,
        market_name="П1",
        book="bet365",
        prob=55,
        fair=1.82,
        odds=2.10,
        value=14,
    )
    assert "П1" in out
    assert "bet365" in out
    assert "+14%" in out


def test_subscription_offer():
    out = render(
        "subscription_offer",
        price_day=100, price_week=500, price_month=1500,
        price_quarter=4000, price_year=12000,
        save_month=20, save_quarter=30, save_year=40,
        ref_code="NONE",
    )
    assert "1500" in out


def test_arb_found():
    out = render(
        "arb_found",
        event="A vs B",
        allocation="A: 500, B: 500",
        profit=100,
        profit_pct=10,
    )
    assert "A vs B" in out
    assert "100₽" in out


def test_placeholders_in():
    phs = placeholders_in("welcome")
    assert "name" in phs
    assert "ref_code" in phs
