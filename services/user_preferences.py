"""Управление пользовательскими настройками (strategy, language, timezone, ...).

Хранит в памяти; в проде можно вынести в DB при желании.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class UserPreferences:
    tg_id: int
    language: str = "ru"
    timezone_offset: int = 3  # UTC+3 по умолчанию
    strategy: str = "balanced"
    default_stake_kind: str = "half_kelly"
    base_percent: float = 1.0
    bankroll: float = 1000.0
    notifications_enabled: bool = True
    value_threshold_pct: float = 5.0
    show_only_value: bool = False
    favorite_leagues: list[int] = field(default_factory=list)
    favorite_teams: list[int] = field(default_factory=list)
    muted_leagues: list[int] = field(default_factory=list)


class PreferenceStore:
    def __init__(self) -> None:
        self._store: dict[int, UserPreferences] = {}

    def get(self, tg_id: int) -> UserPreferences:
        p = self._store.get(tg_id)
        if p is None:
            p = UserPreferences(tg_id=tg_id)
            self._store[tg_id] = p
        return p

    def set_language(self, tg_id: int, lang: str) -> UserPreferences:
        p = self.get(tg_id)
        p.language = lang
        return p

    def set_timezone(self, tg_id: int, offset: int) -> UserPreferences:
        p = self.get(tg_id)
        p.timezone_offset = max(-12, min(14, offset))
        return p

    def set_strategy(self, tg_id: int, strategy: str) -> UserPreferences:
        p = self.get(tg_id)
        p.strategy = strategy
        return p

    def set_stake_kind(self, tg_id: int, kind: str) -> UserPreferences:
        p = self.get(tg_id)
        p.default_stake_kind = kind
        return p

    def set_bankroll(self, tg_id: int, bankroll: float) -> UserPreferences:
        p = self.get(tg_id)
        p.bankroll = max(0.0, bankroll)
        return p

    def toggle_notifications(self, tg_id: int) -> UserPreferences:
        p = self.get(tg_id)
        p.notifications_enabled = not p.notifications_enabled
        return p

    def add_favorite_league(self, tg_id: int, league_id: int) -> UserPreferences:
        p = self.get(tg_id)
        if league_id not in p.favorite_leagues:
            p.favorite_leagues.append(league_id)
        return p

    def remove_favorite_league(self, tg_id: int, league_id: int) -> UserPreferences:
        p = self.get(tg_id)
        if league_id in p.favorite_leagues:
            p.favorite_leagues.remove(league_id)
        return p

    def mute_league(self, tg_id: int, league_id: int) -> UserPreferences:
        p = self.get(tg_id)
        if league_id not in p.muted_leagues:
            p.muted_leagues.append(league_id)
        return p

    def unmute_league(self, tg_id: int, league_id: int) -> UserPreferences:
        p = self.get(tg_id)
        if league_id in p.muted_leagues:
            p.muted_leagues.remove(league_id)
        return p

    def set_value_threshold(self, tg_id: int, pct: float) -> UserPreferences:
        p = self.get(tg_id)
        p.value_threshold_pct = max(0.0, pct)
        return p

    def toggle_show_only_value(self, tg_id: int) -> UserPreferences:
        p = self.get(tg_id)
        p.show_only_value = not p.show_only_value
        return p

    def to_dict(self, tg_id: int) -> dict[str, Any]:
        p = self.get(tg_id)
        return {
            "tg_id": p.tg_id,
            "language": p.language,
            "timezone_offset": p.timezone_offset,
            "strategy": p.strategy,
            "default_stake_kind": p.default_stake_kind,
            "base_percent": p.base_percent,
            "bankroll": p.bankroll,
            "notifications_enabled": p.notifications_enabled,
            "value_threshold_pct": p.value_threshold_pct,
            "show_only_value": p.show_only_value,
            "favorite_leagues": list(p.favorite_leagues),
            "favorite_teams": list(p.favorite_teams),
            "muted_leagues": list(p.muted_leagues),
        }

    def all_users(self) -> list[int]:
        return list(self._store.keys())


__all__ = ["PreferenceStore", "UserPreferences"]
