"""Тесты TTL-кэша."""

from __future__ import annotations

import asyncio

import pytest

from api.cache import APICache


@pytest.mark.asyncio
async def test_cache_hit_miss():
    cache = APICache()
    await cache.set("k", "v", ttl=60)
    assert await cache.get("k") == "v"
    assert await cache.get("missing") is None


@pytest.mark.asyncio
async def test_cache_expires():
    cache = APICache()
    await cache.set("k", "v", ttl=0.05)
    await asyncio.sleep(0.1)
    assert await cache.get("k") is None


@pytest.mark.asyncio
async def test_invalidate_prefix():
    cache = APICache()
    await cache.set("a:1", 1, ttl=10)
    await cache.set("a:2", 2, ttl=10)
    await cache.set("b:1", 3, ttl=10)
    await cache.invalidate(prefix="a:")
    assert await cache.get("a:1") is None
    assert await cache.get("a:2") is None
    assert await cache.get("b:1") == 3


@pytest.mark.asyncio
async def test_invalidate_all():
    cache = APICache()
    await cache.set("a", 1, ttl=10)
    await cache.invalidate(None)
    assert await cache.get("a") is None
