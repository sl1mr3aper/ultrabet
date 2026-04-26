"""In-memory cache store с TTL и тэгами.

Дополнение к api/cache.py: общая утилитарная реализация для любых нужд.
Потокобезопасная (asyncio.Lock).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class CacheEntry:
    value: Any
    expires_at: float  # monotonic time
    tags: frozenset[str]


class InMemoryCache:
    def __init__(self, *, default_ttl: float = 60.0) -> None:
        self._default_ttl = default_ttl
        self._store: dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if entry.expires_at < time.monotonic():
                self._store.pop(key, None)
                return None
            return entry.value

    async def set(
        self,
        key: str,
        value: Any,
        *,
        ttl: float | None = None,
        tags: list[str] | None = None,
    ) -> None:
        async with self._lock:
            ttl_val = ttl if ttl is not None else self._default_ttl
            self._store[key] = CacheEntry(
                value=value,
                expires_at=time.monotonic() + ttl_val,
                tags=frozenset(tags or []),
            )

    async def delete(self, key: str) -> bool:
        async with self._lock:
            return self._store.pop(key, None) is not None

    async def invalidate_tag(self, tag: str) -> int:
        """Удаляет все ключи, помеченные тэгом. Возвращает число удалённых."""
        async with self._lock:
            keys_to_delete = [k for k, e in self._store.items() if tag in e.tags]
            for k in keys_to_delete:
                del self._store[k]
            return len(keys_to_delete)

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()

    async def size(self) -> int:
        async with self._lock:
            return len(self._store)

    async def prune_expired(self) -> int:
        now = time.monotonic()
        async with self._lock:
            to_del = [k for k, e in self._store.items() if e.expires_at < now]
            for k in to_del:
                del self._store[k]
            return len(to_del)

    async def keys(self) -> list[str]:
        async with self._lock:
            return list(self._store.keys())

    async def get_or_set(
        self,
        key: str,
        *,
        factory,
        ttl: float | None = None,
        tags: list[str] | None = None,
    ) -> Any:
        """Если key есть — вернёт. Иначе вызовет factory() и закеширует."""
        cached = await self.get(key)
        if cached is not None:
            return cached
        fresh = factory()
        if asyncio.iscoroutine(fresh):
            fresh = await fresh
        await self.set(key, fresh, ttl=ttl, tags=tags)
        return fresh


__all__ = ["CacheEntry", "InMemoryCache"]
