"""Тесты шины уведомлений."""

from __future__ import annotations

import pytest

from services.notifications import Notification, NotificationBus, NotificationKind


@pytest.mark.asyncio
async def test_publish_no_subscribers():
    bus = NotificationBus()
    n = Notification(
        kind=NotificationKind.BROADCAST, target_tg_id=1, title="t", body="b"
    )
    out = await bus.publish(n)
    assert out == 0
    assert bus.delivered == 0


@pytest.mark.asyncio
async def test_subscribe_and_deliver():
    bus = NotificationBus()
    received = []

    async def h(n: Notification) -> None:
        received.append(n.title)

    bus.subscribe(NotificationKind.DAILY_DIGEST, h)
    await bus.publish(
        Notification(
            kind=NotificationKind.DAILY_DIGEST, target_tg_id=1, title="a", body="b"
        )
    )
    assert received == ["a"]
    assert bus.delivered == 1


@pytest.mark.asyncio
async def test_failed_handlers_counted():
    bus = NotificationBus()

    async def bad(_n: Notification) -> None:
        raise RuntimeError("fail")

    async def good(_n: Notification) -> None:
        pass

    bus.subscribe(NotificationKind.LIVE_ALERT, bad)
    bus.subscribe(NotificationKind.LIVE_ALERT, good)
    ok = await bus.publish(
        Notification(
            kind=NotificationKind.LIVE_ALERT, target_tg_id=1, title="", body=""
        )
    )
    assert ok == 1
    assert bus.failed == 1


@pytest.mark.asyncio
async def test_unsubscribe():
    bus = NotificationBus()
    received = []

    async def h(n: Notification) -> None:
        received.append(1)

    bus.subscribe(NotificationKind.BROADCAST, h)
    bus.unsubscribe(NotificationKind.BROADCAST, h)
    await bus.publish(
        Notification(kind=NotificationKind.BROADCAST, target_tg_id=1, title="", body="")
    )
    assert received == []


@pytest.mark.asyncio
async def test_multiple_subscribers():
    bus = NotificationBus()
    counter = [0]

    async def h1(_n: Notification) -> None:
        counter[0] += 1

    async def h2(_n: Notification) -> None:
        counter[0] += 10

    bus.subscribe(NotificationKind.MATCH_REMINDER, h1)
    bus.subscribe(NotificationKind.MATCH_REMINDER, h2)
    await bus.publish(
        Notification(
            kind=NotificationKind.MATCH_REMINDER, target_tg_id=0, title="", body=""
        )
    )
    assert counter[0] == 11
    assert bus.delivered == 2
