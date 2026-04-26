"""Тесты EventStore."""

from __future__ import annotations

from datetime import datetime, timedelta

from services.event_store import EventStore, EventType


def test_emit_and_count():
    s = EventStore()
    s.emit(EventType.LOGIN, user_id=1)
    s.emit(EventType.LOGIN, user_id=2)
    s.emit(EventType.LOGOUT, user_id=1)
    assert s.total() == 3


def test_event_has_id_and_timestamp():
    s = EventStore()
    e = s.emit(EventType.USER_REGISTERED, user_id=1)
    assert e.event_id > 0
    assert e.timestamp <= datetime.utcnow()


def test_filter_by_type():
    s = EventStore()
    s.emit(EventType.LOGIN, user_id=1)
    s.emit(EventType.LOGIN, user_id=2)
    s.emit(EventType.LOGOUT, user_id=1)
    assert len(s.filter(event_type=EventType.LOGIN)) == 2


def test_filter_by_user():
    s = EventStore()
    s.emit(EventType.LOGIN, user_id=1)
    s.emit(EventType.LOGIN, user_id=2)
    s.emit(EventType.LOGOUT, user_id=1)
    assert len(s.filter(user_id=1)) == 2


def test_filter_since():
    s = EventStore()
    s.emit(EventType.LOGIN, user_id=1)
    cutoff = datetime.utcnow() - timedelta(seconds=1)
    assert len(s.filter(since=cutoff)) == 1
    future = datetime.utcnow() + timedelta(hours=1)
    assert len(s.filter(since=future)) == 0


def test_subscribe():
    s = EventStore()
    received: list = []
    s.subscribe(EventType.LOGIN, lambda e: received.append(e))
    s.emit(EventType.LOGIN, user_id=1)
    s.emit(EventType.LOGOUT, user_id=1)
    assert len(received) == 1


def test_unsubscribe():
    s = EventStore()
    def handler(_e): return None
    s.subscribe(EventType.LOGIN, handler)
    s.unsubscribe(EventType.LOGIN, handler)
    s.emit(EventType.LOGIN, user_id=1)
    # no error


def test_subscriber_exception_isolated():
    s = EventStore()

    def bad(_e):
        raise RuntimeError("boom")

    received: list = []
    s.subscribe(EventType.LOGIN, bad)
    s.subscribe(EventType.LOGIN, lambda e: received.append(e))
    s.emit(EventType.LOGIN, user_id=1)
    # bad subscriber didn't break good one
    assert len(received) == 1


def test_count_by_type():
    s = EventStore()
    s.emit(EventType.LOGIN)
    s.emit(EventType.LOGIN)
    s.emit(EventType.LOGOUT)
    counts = s.count_by_type()
    assert counts["login"] == 2
    assert counts["logout"] == 1


def test_count_by_user():
    s = EventStore()
    s.emit(EventType.LOGIN, user_id=1)
    s.emit(EventType.LOGIN, user_id=1)
    s.emit(EventType.LOGIN, user_id=2)
    top = s.count_by_user()
    assert top[0] == (1, 2)


def test_events_per_hour_shape():
    s = EventStore()
    s.emit(EventType.LOGIN, user_id=1)
    buckets = s.events_per_hour(last_hours=24)
    assert len(buckets) == 24
    assert sum(buckets) >= 1


def test_last_n():
    s = EventStore()
    for _ in range(10):
        s.emit(EventType.LOGIN)
    assert len(s.last_n(3)) == 3


def test_max_events_cap():
    s = EventStore(max_events=5)
    for i in range(10):
        s.emit(EventType.LOGIN, user_id=i)
    assert s.total() == 5
    # last 5 preserved
    ids = [e.user_id for e in s.last_n(5)]
    assert ids == [5, 6, 7, 8, 9]


def test_clear():
    s = EventStore()
    s.emit(EventType.LOGIN)
    s.clear()
    assert s.total() == 0
