"""Универсальный token-bucket rate limiter для handlers и для внешних вызовов.

Используется:
- для защиты от флуда от одного пользователя (N запросов в минуту).
- для ограничения количества запросов к SStats (X per second).

Дополнительно: ``RedisSlidingWindowLimiter`` — распределённый ограничитель
(нескольких процессов / контейнеров) на Lua-скрипте Redis. Применяется,
когда бот масштабируется горизонтально или нужно общее ведро между
процессом-ботом и worker'ом.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any


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


# ─── Redis-backed sliding window (для горизонтального масштабирования) ────


_REDIS_SLIDING_LUA = """
-- Sliding-window лимитер.
-- KEYS[1] — sorted-set ключ (ZSET с timestamp'ами в качестве score).
-- ARGV[1] — текущий unix-time (мс).
-- ARGV[2] — окно в мс.
-- ARGV[3] — лимит запросов внутри окна.
-- ARGV[4] — TTL ключа в секундах (clean-up).
-- ARGV[5] — уникальный member (например {now}-{rand}).
-- Возвращает 1, если разрешено, иначе 0.
local key = KEYS[1]
local now_ms = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local ttl_s = tonumber(ARGV[4])
local member = ARGV[5]

redis.call('ZREMRANGEBYSCORE', key, 0, now_ms - window_ms)
local count = tonumber(redis.call('ZCARD', key)) or 0
if count >= limit then
    return 0
end
redis.call('ZADD', key, now_ms, member)
redis.call('EXPIRE', key, ttl_s)
return 1
"""


class RedisSlidingWindowLimiter:
    """Распределённый sliding-window лимитер на Redis (Lua).

    Параметры:
    - ``capacity`` — сколько запросов разрешено внутри окна.
    - ``window_seconds`` — длина окна в секундах.

    Использование:

        limiter = RedisSlidingWindowLimiter(redis_client, capacity=20,
                                             window_seconds=60)
        ok = await limiter.allow("user:42")
        if not ok:
            return  # перегрузка

    Если Redis недоступен — `allow()` поднимает исключение клиента; вызывающий
    код должен обернуть в try/except и пойти на fallback (in-memory bucket).
    """

    def __init__(
        self,
        redis_client: Any,
        *,
        capacity: int,
        window_seconds: float,
        key_prefix: str = "rl",
    ) -> None:
        self._redis = redis_client
        self._capacity = int(capacity)
        self._window_ms = int(window_seconds * 1000)
        self._ttl_s = max(int(window_seconds * 2), 60)
        self._prefix = key_prefix.rstrip(":")
        self._script = self._redis.register_script(_REDIS_SLIDING_LUA)

    async def allow(self, key: str, *, cost: int = 1) -> bool:
        """Возвращает True, если все ``cost`` тиков уместились в окно."""
        if cost < 1:
            return True
        now_ms = int(time.time() * 1000)
        full_key = f"{self._prefix}:{key}"
        for i in range(cost):
            member = f"{now_ms}-{i}-{id(self):x}"
            allowed = await self._script(
                keys=[full_key],
                args=[
                    str(now_ms),
                    str(self._window_ms),
                    str(self._capacity),
                    str(self._ttl_s),
                    member,
                ],
            )
            if not int(allowed or 0):
                return False
        return True


def make_user_limiter(
    *,
    redis_client: Any | None = None,
    capacity: int = 20,
    refill_per_sec: float = 0.5,
    window_seconds: float = 60.0,
) -> Any:
    """Фабрика: если Redis есть — distributed; иначе — в памяти процесса.

    Сохраняет общий `check(user_id)` API: возвращает coroutine -> bool.
    """
    if redis_client is None:
        return UserRateLimiter(
            capacity=capacity, refill_per_sec=refill_per_sec
        )

    redis_limiter = RedisSlidingWindowLimiter(
        redis_client,
        capacity=capacity,
        window_seconds=window_seconds,
        key_prefix="rl:user",
    )

    class _UserAdapter:
        async def check(self, user_id: int, cost: int = 1) -> bool:
            return await redis_limiter.allow(str(user_id), cost=cost)

        async def reset(self, user_id: int) -> None:  # для совместимости
            await redis_client.delete(f"rl:user:{user_id}")

        async def stats(self) -> dict[str, int]:
            return {"users": -1}  # точное число не считаем для простоты

    return _UserAdapter()


__all__ = [
    "GlobalRateLimiter",
    "RedisSlidingWindowLimiter",
    "TokenBucket",
    "UserRateLimiter",
    "make_user_limiter",
]
