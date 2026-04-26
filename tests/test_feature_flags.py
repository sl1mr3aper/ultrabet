"""Тесты feature flags."""

from __future__ import annotations

from datetime import datetime, timedelta

from services.feature_flags import FeatureFlag, FeatureFlagStore


def test_unknown_flag_disabled():
    s = FeatureFlagStore()
    assert s.is_enabled("nothing") is False


def test_enabled_flag():
    s = FeatureFlagStore()
    s.register(FeatureFlag(name="new_ui", enabled=True))
    assert s.is_enabled("new_ui") is True


def test_disabled_flag():
    s = FeatureFlagStore()
    s.register(FeatureFlag(name="x"))
    assert s.is_enabled("x") is False


def test_whitelist():
    s = FeatureFlagStore()
    s.register(FeatureFlag(name="beta"))
    s.add_whitelist("beta", 42)
    assert s.is_enabled("beta", tg_id=42) is True
    assert s.is_enabled("beta", tg_id=43) is False


def test_blacklist_overrides_enabled():
    s = FeatureFlagStore()
    s.register(FeatureFlag(name="on", enabled=True))
    s.add_blacklist("on", 99)
    assert s.is_enabled("on", tg_id=99) is False
    assert s.is_enabled("on", tg_id=100) is True


def test_expired_flag():
    s = FeatureFlagStore()
    s.register(
        FeatureFlag(
            name="exp",
            enabled=True,
            expires_at=datetime.utcnow() - timedelta(hours=1),
        )
    )
    assert s.is_enabled("exp") is False


def test_rollout_deterministic():
    s = FeatureFlagStore()
    s.register(FeatureFlag(name="roll", rollout_percent=50.0))
    # same user → same result always
    v1 = s.is_enabled("roll", tg_id=1)
    v2 = s.is_enabled("roll", tg_id=1)
    assert v1 == v2


def test_rollout_zero_percent():
    s = FeatureFlagStore()
    s.register(FeatureFlag(name="r", rollout_percent=0.0))
    assert s.is_enabled("r", tg_id=1) is False


def test_rollout_100_percent():
    s = FeatureFlagStore()
    s.register(FeatureFlag(name="r", rollout_percent=100.0))
    assert s.is_enabled("r", tg_id=1) is True


def test_rollout_distribution():
    s = FeatureFlagStore()
    s.register(FeatureFlag(name="p50", rollout_percent=50.0))
    enabled_count = sum(
        1 for tg_id in range(1000) if s.is_enabled("p50", tg_id=tg_id)
    )
    # Should be roughly 500 with some variance
    assert 400 < enabled_count < 600


def test_enable_disable():
    s = FeatureFlagStore()
    s.register(FeatureFlag(name="x"))
    s.enable("x")
    assert s.is_enabled("x") is True
    s.disable("x")
    assert s.is_enabled("x") is False


def test_set_rollout_clamped():
    s = FeatureFlagStore()
    s.register(FeatureFlag(name="x"))
    s.set_rollout("x", 150)
    assert s.get("x").rollout_percent == 100
    s.set_rollout("x", -50)
    assert s.get("x").rollout_percent == 0


def test_remove_flag():
    s = FeatureFlagStore()
    s.register(FeatureFlag(name="x", enabled=True))
    s.remove("x")
    assert s.is_enabled("x") is False


def test_all_flags():
    s = FeatureFlagStore()
    s.register(FeatureFlag(name="a"))
    s.register(FeatureFlag(name="b"))
    assert len(s.all()) == 2


def test_remove_whitelist_blacklist():
    s = FeatureFlagStore()
    s.register(FeatureFlag(name="x"))
    s.add_whitelist("x", 1)
    s.remove_whitelist("x", 1)
    assert 1 not in s.get("x").whitelist_users
    s.add_blacklist("x", 2)
    s.remove_blacklist("x", 2)
    assert 2 not in s.get("x").blacklist_users
