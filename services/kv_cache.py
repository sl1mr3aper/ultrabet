"""P0-9: единый key-value кэш с Redis-бэкендом и in-memory фолбэком.

Если задан `REDIS_URL` в конфиге — используем Redis (aioredis / redis.asyncio).
Иначе — `cachetools.TTLCache` в памяти процесса.

Интерфейс умышленно простой: `get(key)`, `set(key, value, ttl)`, `delete(key)`.
Значения — JSON-сериализуемые.
"""

from __future__ import annotations

import json
from typing import Any

from cachetools import TTLCache
from loguru import logger


class KVCache:
    """Общий интерфейс кэша. Thread-/async-safe для обычного сценария бота."""

    def __init__(
        self,
        *,
        redis_url: str | None = None,
        memory_maxsize: int = 20_000,
        memory_ttl: int = 600,
    ) -> None:
        self._memory: TTLCache = TTLCache(maxsize=memory_maxsize, ttl=memory_ttl)
        self._redis = None
        self._redis_url = redis_url
        if redis_url:
            try:
                import redis.asyncio as aioredis  # type: ignore[import-untyped]
                self._redis = aioredis.from_url(
                    redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                )
                logger.info("KVCache: подключён Redis ({})", redis_url)
            except ImportError:
                logger.warning(
                    "KVCache: redis-py не установлен, работаем на TTLCache"
                )
                self._redis = None
            except Exception as exc:
                logger.warning(
                    "KVCache: не удалось подключиться к Redis: {}. Fallback: memory",
                    exc,
                )
                self._redis = None

    async def get(self, key: str) -> Any | None:
        if self._redis is not None:
            try:
                raw = await self._redis.get(key)
                if raw is None:
                    return None
                try:
                    return json.loads(raw)
                except ValueError:
                    return raw
            except Exception as exc:
                logger.debug("KVCache.get: redis error: {}", exc)
        return self._memory.get(key)

    async def set(
        self, key: str, value: Any, *, ttl: int | None = None
    ) -> None:
        if self._redis is not None:
            try:
                payload = json.dumps(value)
                if ttl:
                    await self._redis.setex(key, ttl, payload)
                else:
                    await self._redis.set(key, payload)
                return
            except Exception as exc:
                logger.debug("KVCache.set: redis error: {}", exc)
        self._memory[key] = value

    async def delete(self, key: str) -> None:
        if self._redis is not None:
            try:
                await self._redis.delete(key)
            except Exception as exc:
                logger.debug("KVCache.delete: redis error: {}", exc)
        self._memory.pop(key, None)

    @property
    def using_redis(self) -> bool:
        return self._redis is not None


__all__ = ["KVCache"]
