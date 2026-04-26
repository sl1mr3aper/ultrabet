"""Feature flags для постепенного развёртывания новых функций.

Поддерживает:
- bool-флаги (on/off),
- процентный rollout (включить для X% пользователей),
- whitelist пользователей,
- blacklist пользователей,
- время экспирации флага.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class FeatureFlag:
    name: str
    enabled: bool = False
    rollout_percent: float = 0.0  # 0..100
    whitelist_users: set[int] = field(default_factory=set)
    blacklist_users: set[int] = field(default_factory=set)
    expires_at: datetime | None = None
    description: str = ""


class FeatureFlagStore:
    def __init__(self) -> None:
        self._flags: dict[str, FeatureFlag] = {}

    def register(self, flag: FeatureFlag) -> None:
        self._flags[flag.name] = flag

    def remove(self, name: str) -> None:
        self._flags.pop(name, None)

    def get(self, name: str) -> FeatureFlag | None:
        return self._flags.get(name)

    def all(self) -> list[FeatureFlag]:
        return list(self._flags.values())

    def is_enabled(self, name: str, *, tg_id: int | None = None) -> bool:
        flag = self._flags.get(name)
        if flag is None:
            return False
        if flag.expires_at is not None and datetime.utcnow() > flag.expires_at:
            return False
        if tg_id is not None and tg_id in flag.blacklist_users:
            return False
        if tg_id is not None and tg_id in flag.whitelist_users:
            return True
        if flag.enabled:
            return True
        if flag.rollout_percent > 0 and tg_id is not None:
            return self._user_in_rollout(tg_id, name, flag.rollout_percent)
        return False

    @staticmethod
    def _user_in_rollout(tg_id: int, flag_name: str, rollout_percent: float) -> bool:
        digest = hashlib.md5(f"{flag_name}:{tg_id}".encode(), usedforsecurity=False).hexdigest()
        bucket = int(digest[:8], 16) % 100
        return bucket < rollout_percent

    def enable(self, name: str) -> None:
        flag = self._flags.get(name)
        if flag is not None:
            flag.enabled = True

    def disable(self, name: str) -> None:
        flag = self._flags.get(name)
        if flag is not None:
            flag.enabled = False

    def set_rollout(self, name: str, percent: float) -> None:
        flag = self._flags.get(name)
        if flag is not None:
            flag.rollout_percent = max(0.0, min(100.0, percent))

    def add_whitelist(self, name: str, tg_id: int) -> None:
        flag = self._flags.get(name)
        if flag is not None:
            flag.whitelist_users.add(tg_id)

    def add_blacklist(self, name: str, tg_id: int) -> None:
        flag = self._flags.get(name)
        if flag is not None:
            flag.blacklist_users.add(tg_id)

    def remove_whitelist(self, name: str, tg_id: int) -> None:
        flag = self._flags.get(name)
        if flag is not None:
            flag.whitelist_users.discard(tg_id)

    def remove_blacklist(self, name: str, tg_id: int) -> None:
        flag = self._flags.get(name)
        if flag is not None:
            flag.blacklist_users.discard(tg_id)


__all__ = ["FeatureFlag", "FeatureFlagStore"]
