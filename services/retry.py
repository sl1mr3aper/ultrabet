"""Универсальный async-retry с экспоненциальным бэкоффом и jitter.

Поддерживает:
- максимальное число попыток,
- exponential backoff с множителем,
- случайный jitter ±25%,
- whitelist retryable исключений,
- callback on_retry для логирования/метрик.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from loguru import logger

T = TypeVar("T")


@dataclass(slots=True)
class RetryPolicy:
    max_attempts: int = 3
    initial_delay: float = 0.5
    max_delay: float = 10.0
    multiplier: float = 2.0
    jitter_ratio: float = 0.25
    retryable_exceptions: tuple[type[BaseException], ...] = (
        TimeoutError,
        ConnectionError,
    )

    def compute_delay(self, attempt: int) -> float:
        """attempt 1-indexed."""
        base = self.initial_delay * (self.multiplier ** (attempt - 1))
        base = min(base, self.max_delay)
        jitter = random.uniform(-self.jitter_ratio, self.jitter_ratio) * base
        return max(0.0, base + jitter)


OnRetry = Callable[[int, BaseException, float], Awaitable[None] | None]


async def retry_async(
    func: Callable[[], Awaitable[T]],
    *,
    policy: RetryPolicy | None = None,
    on_retry: OnRetry | None = None,
) -> T:
    """Запускает корутину с повтором по policy. Бросает последнее исключение."""
    policy = policy or RetryPolicy()
    last_exc: BaseException | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return await func()
        except policy.retryable_exceptions as exc:
            last_exc = exc
            if attempt >= policy.max_attempts:
                break
            delay = policy.compute_delay(attempt)
            logger.debug(
                "retry attempt={} exc={} delay={:.3f}s",
                attempt, type(exc).__name__, delay,
            )
            if on_retry is not None:
                result = on_retry(attempt, exc, delay)
                if asyncio.iscoroutine(result):
                    await result
            await asyncio.sleep(delay)
        except Exception:
            # non-retryable — бросаем немедленно
            raise
    assert last_exc is not None
    raise last_exc


__all__ = ["OnRetry", "RetryPolicy", "retry_async"]
