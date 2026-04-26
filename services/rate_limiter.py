"""Универсальный token-bucket rate limiter для handlers и для внешних вызовов.

Используется:
- для защиты от флуда от одного пользователя (N запросов в минуту).
- для ограничения количества запросов к SStats (X per second).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass


@dataclass(slots=True)
class TokenBucket:
    capacity: int
    refill_per_sec: float
    tokens: float = 0.0
    last_refill: float = 0.0

    def take(self, cost: int = 1) -> bool:
        now = time.monotonic()
        if self.last_refill == 0.0:
            self.last_refill = now
            self.tokens = float(self.capacity)
        elapsed = now - self.last_refill
        self.tokens = min(
            float(self.capacity), self.tokens + elapsed * self.refill_per_sec
        )
        self.last_refill = now
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False


class UserRateLimiter:
    """Управляет отдельным ведром на каждого пользователя."""

    def __init__(self, *, capacity: int = 10, refill_per_sec: float = 0.5) -> None:
        self._buckets: dict[int, TokenBucket] = {}
        self._capacity = capacity
        self._refill = refill_per_sec
        self._lock = asyncio.Lock()

    async def check(self, user_id: int, cost: int = 1) -> bool:
        async with self._lock:
            b = self._buckets.get(user_id)
            if b is None:
                b = TokenBucket(capacity=self._capacity, refill_per_sec=self._refill)
                self._buckets[user_id] = b
            return b.take(cost)

    async def reset(self, user_id: int) -> None:
        async with self._lock:
            self._buckets.pop(user_id, None)

    async def stats(self) -> dict[str, int]:
        async with self._lock:
            return {"users": len(self._buckets)}


class GlobalRateLimiter:
    """Глобальный bucket для внешних API."""

    def __init__(self, *, capacity: int = 100, refill_per_sec: float = 5.0) -> None:
        self._bucket = TokenBucket(capacity=capacity, refill_per_sec=refill_per_sec)
        self._lock = asyncio.Lock()

    async def acquire(self, cost: int = 1) -> bool:
        async with self._lock:
            return self._bucket.take(cost)

    async def wait_and_acquire(self, cost: int = 1, *, max_wait: float = 5.0) -> bool:
        """Блокируется до max_wait секунд, ожидая свободный токен."""
        start = time.monotonic()
        while time.monotonic() - start < max_wait:
            if await self.acquire(cost):
                return True
            await asyncio.sleep(0.05)
        return False


__all__ = ["GlobalRateLimiter", "TokenBucket", "UserRateLimiter"]
