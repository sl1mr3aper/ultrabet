"""Тесты WebhookPublisher (только логика без реальных HTTP)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from services.webhook_publisher import WebhookPublisher, WebhookTarget


def test_add_remove_target():
    p = WebhookPublisher()
    p.add_target(WebhookTarget(url="https://a.com"))
    p.add_target(WebhookTarget(url="https://b.com"))
    assert p.stats["targets"] == 2
    p.remove_target("https://a.com")
    assert p.stats["targets"] == 1


@pytest.mark.asyncio
async def test_publish_no_targets():
    p = WebhookPublisher()
    out = await p.publish("test", {"x": 1})
    assert out == 0


@pytest.mark.asyncio
async def test_event_type_filter():
    p = WebhookPublisher()
    p.add_target(
        WebhookTarget(url="https://a.com", event_types=("value_bet",))
    )

    sent = [0]

    async def fake_send(_session, _target, _body):
        sent[0] += 1
        return True

    p._send_one = fake_send  # type: ignore[method-assign]
    p._get_session = AsyncMock(return_value=MagicMock())  # type: ignore[method-assign]
    out = await p.publish("other_event", {})
    assert out == 0
    assert sent[0] == 0


@pytest.mark.asyncio
async def test_publish_sends_to_matching_target():
    p = WebhookPublisher()
    p.add_target(WebhookTarget(url="https://a.com"))

    async def fake_send(_session, _target, _body):
        return True

    p._send_one = fake_send  # type: ignore[method-assign]
    p._get_session = AsyncMock(return_value=MagicMock())  # type: ignore[method-assign]
    out = await p.publish("event", {"ok": True})
    assert out == 1
    assert p.stats["sent"] == 1


@pytest.mark.asyncio
async def test_failure_counted():
    p = WebhookPublisher()
    p.add_target(WebhookTarget(url="https://a.com"))

    async def fake_send(_s, _t, _b):
        return False

    p._send_one = fake_send  # type: ignore[method-assign]
    p._get_session = AsyncMock(return_value=MagicMock())  # type: ignore[method-assign]
    out = await p.publish("x", {})
    assert out == 0
    assert p.stats["failed"] == 1


@pytest.mark.asyncio
async def test_close_safe_without_session():
    p = WebhookPublisher()
    await p.close()  # no error
