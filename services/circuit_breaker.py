"""Circuit Breaker для защиты от шторма ошибок.

Состояния:
- closed: обычная работа, запросы идут.
- open: отклоняет все запросы, пока не пройдёт cooldown.
- half_open: один тест-запрос; если ок → closed, если ошибка → open.

Использование:
    cb = CircuitBreaker(failure_threshold=5, reset_timeout=60.0)
    async with cb:
        await external_call()
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import Enum


class State(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerError(Exception):
    """Поднимается, когда CB в состоянии OPEN."""


@dataclass(slots=True)
class BreakerStats:
    total_calls: int = 0
    total_failures: int = 0
    total_successes: int = 0
    state_changes: int = 0
    current_state: State = State.CLOSED


class CircuitBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        reset_timeout: float = 60.0,
        half_open_max_calls: int = 1,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._half_open_max = half_open_max_calls
        self._state = State.CLOSED
        self._failures = 0
        self._opened_at: float | None = None
        self._half_open_calls = 0
        self._lock = asyncio.Lock()
        self._stats = BreakerStats()

    @property
    def state(self) -> State:
        return self._state

    @property
    def stats(self) -> BreakerStats:
        return self._stats

    def _transition(self, new_state: State) -> None:
        if new_state != self._state:
            self._stats.state_changes += 1
            self._state = new_state
            self._stats.current_state = new_state

    async def check_and_record(self, ok: bool) -> None:
        async with self._lock:
            self._stats.total_calls += 1
            if ok:
                self._stats.total_successes += 1
                if self._state == State.HALF_OPEN:
                    self._transition(State.CLOSED)
                    self._failures = 0
                    self._half_open_calls = 0
                elif self._state == State.CLOSED:
                    self._failures = 0
            else:
                self._stats.total_failures += 1
                if self._state == State.HALF_OPEN:
                    self._transition(State.OPEN)
                    self._opened_at = time.monotonic()
                    self._half_open_calls = 0
                elif self._state == State.CLOSED:
                    self._failures += 1
                    if self._failures >= self._failure_threshold:
                        self._transition(State.OPEN)
                        self._opened_at = time.monotonic()

    async def allow(self) -> bool:
        async with self._lock:
            if self._state == State.CLOSED:
                return True
            if self._state == State.OPEN:
                if (
                    self._opened_at is not None
                    and time.monotonic() - self._opened_at >= self._reset_timeout
                ):
                    self._transition(State.HALF_OPEN)
                    self._half_open_calls = 0
                    return True
                return False
            # HALF_OPEN
            if self._half_open_calls < self._half_open_max:
                self._half_open_calls += 1
                return True
            return False


__all__ = ["BreakerStats", "CircuitBreaker", "CircuitBreakerError", "State"]
