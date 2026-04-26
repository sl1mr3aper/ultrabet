"""Event sourcing store для аудита важных действий.

Пишет все пользовательские действия в лог:
- покупка подписки
- ставка
- валуй-открытие
- оплата реферала
- отключение нотификаций
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any


class EventType(str, Enum):
    USER_REGISTERED = "user_registered"
    PREDICTION_REQUESTED = "prediction_requested"
    PREDICTION_SHOWN = "prediction_shown"
    VALUE_BET_PROPOSED = "value_bet_proposed"
    SUBSCRIPTION_PURCHASED = "subscription_purchased"
    SUBSCRIPTION_EXPIRED = "subscription_expired"
    REFERRAL_CREATED = "referral_created"
    REFERRAL_REWARDED = "referral_rewarded"
    BANKROLL_CALCULATED = "bankroll_calculated"
    ARBITRAGE_FOUND = "arbitrage_found"
    SIMULATION_RUN = "simulation_run"
    ERROR_OCCURRED = "error_occurred"
    LOGIN = "login"
    LOGOUT = "logout"


@dataclass(slots=True)
class Event:
    event_id: int
    timestamp: datetime
    event_type: EventType
    user_id: int | None
    payload: dict[str, Any] = field(default_factory=dict)


class EventStore:
    def __init__(self, *, max_events: int = 10_000) -> None:
        self._events: list[Event] = []
        self._max_events = max_events
        self._next_id = 1
        self._subscribers: dict[EventType, list[Callable[[Event], None]]] = {}

    def emit(
        self,
        event_type: EventType,
        *,
        user_id: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Event:
        event = Event(
            event_id=self._next_id,
            timestamp=datetime.utcnow(),
            event_type=event_type,
            user_id=user_id,
            payload=payload or {},
        )
        self._next_id += 1
        self._events.append(event)
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events:]
        for sub in self._subscribers.get(event_type, []):
            try:
                sub(event)
            except Exception:  # защита подписчиков друг от друга
                pass
        return event

    def subscribe(
        self, event_type: EventType, handler: Callable[[Event], None]
    ) -> None:
        self._subscribers.setdefault(event_type, []).append(handler)

    def unsubscribe(
        self, event_type: EventType, handler: Callable[[Event], None]
    ) -> None:
        if event_type in self._subscribers:
            try:
                self._subscribers[event_type].remove(handler)
            except ValueError:
                pass

    def filter(
        self,
        *,
        event_type: EventType | None = None,
        user_id: int | None = None,
        since: datetime | None = None,
    ) -> list[Event]:
        out: list[Event] = []
        for e in self._events:
            if event_type is not None and e.event_type != event_type:
                continue
            if user_id is not None and e.user_id != user_id:
                continue
            if since is not None and e.timestamp < since:
                continue
            out.append(e)
        return out

    def last_n(self, n: int) -> list[Event]:
        return self._events[-n:]

    def count_by_type(self, *, since: datetime | None = None) -> dict[str, int]:
        events = self._events if since is None else [e for e in self._events if e.timestamp >= since]
        return dict(Counter(e.event_type.value for e in events))

    def count_by_user(self, *, top_n: int = 10) -> list[tuple[int, int]]:
        users = [e.user_id for e in self._events if e.user_id is not None]
        return Counter(users).most_common(top_n)

    def events_per_hour(self, *, last_hours: int = 24) -> list[int]:
        cutoff = datetime.utcnow() - timedelta(hours=last_hours)
        events = [e for e in self._events if e.timestamp >= cutoff]
        buckets = [0] * last_hours
        now = datetime.utcnow()
        for e in events:
            diff_sec = (now - e.timestamp).total_seconds()
            idx = last_hours - 1 - int(diff_sec // 3600)
            if 0 <= idx < last_hours:
                buckets[idx] += 1
        return buckets

    def total(self) -> int:
        return len(self._events)

    def clear(self) -> None:
        self._events.clear()
        self._next_id = 1


__all__ = ["Event", "EventStore", "EventType"]
