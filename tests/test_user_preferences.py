"""Тесты PreferenceStore."""

from __future__ import annotations

from services.user_preferences import PreferenceStore


def test_default_prefs():
    s = PreferenceStore()
    p = s.get(1)
    assert p.language == "ru"
    assert p.strategy == "balanced"
    assert p.notifications_enabled is True


def test_set_language():
    s = PreferenceStore()
    s.set_language(1, "en")
    assert s.get(1).language == "en"


def test_timezone_clamped():
    s = PreferenceStore()
    s.set_timezone(1, 99)
    assert s.get(1).timezone_offset == 14
    s.set_timezone(1, -99)
    assert s.get(1).timezone_offset == -12


def test_toggle_notifications():
    s = PreferenceStore()
    s.toggle_notifications(1)
    assert s.get(1).notifications_enabled is False
    s.toggle_notifications(1)
    assert s.get(1).notifications_enabled is True


def test_favorite_leagues():
    s = PreferenceStore()
    s.add_favorite_league(1, 100)
    s.add_favorite_league(1, 200)
    s.add_favorite_league(1, 100)  # duplicate
    assert s.get(1).favorite_leagues == [100, 200]
    s.remove_favorite_league(1, 100)
    assert s.get(1).favorite_leagues == [200]


def test_mute_unmute():
    s = PreferenceStore()
    s.mute_league(1, 50)
    assert 50 in s.get(1).muted_leagues
    s.unmute_league(1, 50)
    assert 50 not in s.get(1).muted_leagues


def test_set_strategy():
    s = PreferenceStore()
    s.set_strategy(1, "aggressive")
    assert s.get(1).strategy == "aggressive"


def test_to_dict_complete():
    s = PreferenceStore()
    d = s.to_dict(1)
    assert set(d.keys()) >= {
        "tg_id", "language", "timezone_offset", "strategy",
        "default_stake_kind", "bankroll", "notifications_enabled",
        "favorite_leagues", "muted_leagues",
    }


def test_all_users():
    s = PreferenceStore()
    s.get(1)
    s.get(2)
    s.get(3)
    assert set(s.all_users()) == {1, 2, 3}


def test_bankroll_non_negative():
    s = PreferenceStore()
    s.set_bankroll(1, -100)
    assert s.get(1).bankroll == 0.0


def test_value_threshold():
    s = PreferenceStore()
    s.set_value_threshold(1, 10.0)
    assert s.get(1).value_threshold_pct == 10.0
    s.set_value_threshold(1, -5)
    assert s.get(1).value_threshold_pct == 0.0


def test_toggle_show_only_value():
    s = PreferenceStore()
    s.toggle_show_only_value(1)
    assert s.get(1).show_only_value is True
