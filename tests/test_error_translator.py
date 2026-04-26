"""Тесты переводчика ошибок."""

from __future__ import annotations

from services.error_translator import translate


def test_timeout():
    t = translate(TimeoutError())
    assert t.kind == "timeout"
    assert t.retryable is True


def test_rate_limit_by_message():
    t = translate(Exception("HTTP 429 Too many requests"))
    assert t.kind == "rate_limit"
    assert t.retryable is True


def test_404():
    t = translate(Exception("HTTP 404 Not Found"))
    assert t.kind == "not_found"
    assert t.retryable is False


def test_500():
    t = translate(Exception("Bad gateway 502"))
    assert t.kind == "server"
    assert t.retryable is True


def test_network_class():
    class ConnectionReset(Exception):
        pass

    t = translate(ConnectionReset("reset by peer"))
    assert t.kind == "network"
    assert t.retryable is True


def test_generic():
    t = translate(ValueError("something weird"))
    assert t.kind == "generic"
    assert t.retryable is False
