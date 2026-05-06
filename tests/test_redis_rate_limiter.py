"""Тесты RedisSlidingWindowLimiter — без реального Redis (in-process fake)."""

from __future__ import annotations

import asyncio

import pytest

from services.rate_limiter import (
    RedisSlidingWindowLimiter,
    UserRateLimiter,
    make_user_limiter,
)


class _FakeScript:
    """Эмитирует Lua-скрипт sliding-window in-memory."""

    def __init__(self, store: dict[str, list[tuple[int, str]]]) -> None:
        self._store = store

    async def __call__(self, *, keys: list[str], args: list[str]) -> int:
        key = keys[0]
        now_ms, window_ms, limit, _ttl, member = args
        now_i = int(now_ms)
        window_i = int(window_ms)
        limit_i = int(limit)
        bucket = self._store.setdefault(key, [])
        # Удаляем "старые" записи.
        bucket[:] = [(t, m) for t, m in bucket if t > now_i - window_i]
        if len(bucket) >= limit_i:
            return 0
        bucket.append((now_i, member))
        return 1


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, list[tuple[int, str]]] = {}

    def register_script(self, _script: str) -> _FakeScript:
        return _FakeScript(self.store)

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


@pytest.mark.asyncio
async def test_sliding_window_allows_within_capacity() -> None:
    redis = _FakeRedis()
    limiter = RedisSlidingWindowLimiter(redis, capacity=3, window_seconds=10)
    assert await limiter.allow("u1") is True
    assert await limiter.allow("u1") is True
    assert await limiter.allow("u1") is True
    # 4-й запрос должен быть отклонён.
    assert await limiter.allow("u1") is False


@pytest.mark.asyncio
async def test_sliding_window_independent_keys() -> None:
    redis = _FakeRedis()
    limiter = RedisSlidingWindowLimiter(redis, capacity=2, window_seconds=10)
    assert await limiter.allow("a") is True
    assert await limiter.allow("a") is True
    assert await limiter.allow("a") is False
    # Другой ключ — независимый счётчик.
    assert await limiter.allow("b") is True


@pytest.mark.asyncio
async def test_make_user_limiter_uses_inmemory_when_no_redis() -> None:
    lim = make_user_limiter(redis_client=None, capacity=2, refill_per_sec=10.0)
    assert isinstance(lim, UserRateLimiter)
    assert await lim.check(1) is True
    assert await lim.check(1) is True
    # 3-й сразу — должно быть False (refill за миллисекунды не успеет).
    assert await lim.check(1) is False


@pytest.mark.asyncio
async def test_make_user_limiter_with_redis_uses_distributed() -> None:
    redis = _FakeRedis()
    lim = make_user_limiter(
        redis_client=redis, capacity=1, window_seconds=10
    )
    assert await lim.check(42) is True
    assert await lim.check(42) is False
    # reset через delete возвращает счётчик
    await lim.reset(42)
    assert await lim.check(42) is True


@pytest.mark.asyncio
async def test_window_expires_after_time(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = _FakeRedis()
    limiter = RedisSlidingWindowLimiter(
        redis, capacity=1, window_seconds=0.05
    )
    assert await limiter.allow("u") is True
    assert await limiter.allow("u") is False
    # подождём окно и проверим, что разрешено снова.
    await asyncio.sleep(0.07)
    assert await limiter.allow("u") is True
