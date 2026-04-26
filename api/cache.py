"""Простой in-memory TTL кэш для ответов API."""

from __future__ import annotations

import asyncio
import time
from typing import Any


class APICache:
    """In-memory TTL-кэш по ключам."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at < time.monotonic():
                self._store.pop(key, None)
                return None
            return value

    async def set(self, key: str, value: Any, ttl: float) -> None:
        async with self._lock:
            self._store[key] = (time.monotonic() + max(ttl, 0.0), value)

    async def invalidate(self, prefix: str | None = None) -> None:
        async with self._lock:
            if prefix is None:
                self._store.clear()
                return
            keys = [k for k in self._store if k.startswith(prefix)]
            for k in keys:
                self._store.pop(k, None)

    async def size(self) -> int:
        async with self._lock:
            return len(self._store)


__all__ = ["APICache"]
