"""In-memory кэш результатов для пагинации между сообщениями.

Тяжёлые запросы (top-matches на день, daily-picks, h2h) считаются один раз и
переиспользуются при перелистывании страниц. TTL по умолчанию 5 минут.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class _Entry:
    value: Any
    expires_at: float


class CacheStore:
    """Самый простой TTL-кэш на dict без зависимостей."""

    def __init__(self, default_ttl: float = 300.0) -> None:
        self._data: dict[str, _Entry] = {}
        self._default_ttl = default_ttl

    def get(self, key: str) -> Any | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        if entry.expires_at < time.time():
            self._data.pop(key, None)
            return None
        return entry.value

    def set(self, key: str, value: Any, *, ttl: float | None = None) -> None:
        ttl_eff = ttl if ttl is not None else self._default_ttl
        self._data[key] = _Entry(value=value, expires_at=time.time() + ttl_eff)

    def invalidate(self, key: str) -> None:
        self._data.pop(key, None)

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)


__all__ = ["CacheStore"]
