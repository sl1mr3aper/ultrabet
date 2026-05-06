"""Тесты services/understat_client — парсер JS + HTTP-обвязка."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
import pytest
from aiohttp import web

from services import understat_client as uc

# ─── HTML fixtures ─────────────────────────────────────────────────────────


def _make_league_html(matches: list[dict[str, Any]]) -> str:
    """Эмитит страницу understat в формате
    ``var datesData = JSON.parse('<escaped>'); ...``.
    """
    import codecs
    import json

    raw = json.dumps(matches, ensure_ascii=True)
    # Понимай как «обратный JSON.parse»: каждое \u… и \x… raw-сериализатор
    # уже даёт. Но Understat дополнительно эскейпит апострофы.
    payload = (
        codecs.encode(raw, "unicode_escape")
        .decode("ascii")
        .replace("'", "\\'")
    )
    return (
        "<html><body>"
        f"var datesData = JSON.parse('{payload}');"
        "</body></html>"
    )


def _make_match_html(shots_h: list[dict[str, Any]], shots_a: list[dict[str, Any]]) -> str:
    import codecs
    import json

    raw = json.dumps({"h": shots_h, "a": shots_a}, ensure_ascii=True)
    payload = (
        codecs.encode(raw, "unicode_escape")
        .decode("ascii")
        .replace("'", "\\'")
    )
    return f"<html>var shotsData = JSON.parse('{payload}');</html>"


# ─── Юнит-тесты парсера (без сети) ─────────────────────────────────────────


def test_parse_league_matches_finished() -> None:
    raw = [
        {
            "id": "12345",
            "isResult": True,
            "h": {"id": "1", "title": "Arsenal", "short_title": "ARS"},
            "a": {"id": "2", "title": "Chelsea", "short_title": "CHE"},
            "goals": {"h": "2", "a": "1"},
            "xG": {"h": "1.85", "a": "1.10"},
            "datetime": "2026-04-30 18:00:00",
        }
    ]
    html = _make_league_html(raw)
    matches = uc.parse_league_matches(html, league="EPL", season="2025")
    assert len(matches) == 1
    m = matches[0]
    assert m.match_id == 12345
    assert m.home_team == "Arsenal"
    assert m.away_team == "Chelsea"
    assert m.home_goals == 2
    assert m.away_goals == 1
    assert m.home_xg == pytest.approx(1.85)
    assert m.away_xg == pytest.approx(1.10)
    assert m.is_finished is True


def test_parse_league_matches_scheduled() -> None:
    raw = [
        {
            "id": "9001",
            "isResult": False,
            "h": {"title": "Real Madrid"},
            "a": {"title": "Sevilla"},
            "goals": {"h": None, "a": None},
            "xG": {"h": None, "a": None},
            "datetime": "2026-05-10 21:00:00",
        }
    ]
    html = _make_league_html(raw)
    matches = uc.parse_league_matches(html, league="La_liga", season="2025")
    assert len(matches) == 1
    assert matches[0].home_goals is None
    assert matches[0].home_xg is None
    assert matches[0].is_finished is False


def test_parse_league_matches_empty_when_no_var() -> None:
    matches = uc.parse_league_matches(
        "<html>nothing here</html>", league="EPL", season="2025"
    )
    assert matches == []


def test_parse_match_shots() -> None:
    html = _make_match_html(
        [{"player": "Saka", "xG": "0.45", "result": "Goal"}],
        [{"player": "Sterling", "xG": "0.10", "result": "MissedShots"}],
    )
    out = uc.parse_match_shots(html)
    assert out["h"][0]["player"] == "Saka"
    assert out["a"][0]["xG"] == "0.10"


# ─── HTTP-интеграция (через локальный aiohttp web-сервер) ──────────────────


@pytest.fixture
async def local_server() -> Any:
    """Минимальный stub Understat: /league/{name}/{season} и /match/{id}."""

    async def league_handler(request: web.Request) -> web.Response:
        league = request.match_info["name"]
        season = request.match_info["season"]
        if league == "EPL" and season == "2025":
            html = _make_league_html(
                [
                    {
                        "id": "1",
                        "isResult": True,
                        "h": {"title": "Liverpool"},
                        "a": {"title": "Everton"},
                        "goals": {"h": "3", "a": "0"},
                        "xG": {"h": "2.4", "a": "0.6"},
                        "datetime": "2026-04-29 18:00:00",
                    }
                ]
            )
            return web.Response(text=html, content_type="text/html")
        return web.Response(status=404)

    async def match_handler(request: web.Request) -> web.Response:
        return web.Response(
            text=_make_match_html(
                [{"player": "Salah", "xG": "0.3"}],
                [{"player": "DCL", "xG": "0.05"}],
            ),
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/league/{name}/{season}", league_handler)
    app.router.add_get("/match/{id}", match_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
    yield f"http://127.0.0.1:{port}"
    await runner.cleanup()


@pytest.mark.asyncio
async def test_client_list_matches(monkeypatch: pytest.MonkeyPatch, local_server: str) -> None:
    monkeypatch.setattr(uc, "UNDERSTAT_BASE", local_server)
    async with aiohttp.ClientSession() as session:
        client = uc.UnderstatClient(session, rate_limit_seconds=0.0)
        out = await client.list_matches("EPL", "2025")
    assert len(out) == 1
    assert out[0].home_team == "Liverpool"
    assert out[0].home_xg == pytest.approx(2.4)


@pytest.mark.asyncio
async def test_client_match_shots(monkeypatch: pytest.MonkeyPatch, local_server: str) -> None:
    monkeypatch.setattr(uc, "UNDERSTAT_BASE", local_server)
    async with aiohttp.ClientSession() as session:
        client = uc.UnderstatClient(session, rate_limit_seconds=0.0)
        out = await client.match_shots(42)
    assert out["h"][0]["player"] == "Salah"


@pytest.mark.asyncio
async def test_client_unsupported_league() -> None:
    async with aiohttp.ClientSession() as session:
        client = uc.UnderstatClient(session, rate_limit_seconds=0.0)
        with pytest.raises(ValueError):
            await client.list_matches("NotALeague", "2025")


@pytest.mark.asyncio
async def test_client_uses_cache(monkeypatch: pytest.MonkeyPatch, local_server: str) -> None:
    monkeypatch.setattr(uc, "UNDERSTAT_BASE", local_server)

    class _MemCache:
        def __init__(self) -> None:
            self.store: dict[str, str] = {}
            self.hits = 0
            self.sets = 0

        async def get(self, key: str) -> str | None:
            v = self.store.get(key)
            if v is not None:
                self.hits += 1
            return v

        async def set(self, key: str, value: str, *, ttl: int) -> None:
            self.store[key] = value
            self.sets += 1

    cache = _MemCache()
    async with aiohttp.ClientSession() as session:
        client = uc.UnderstatClient(
            session, cache=cache, rate_limit_seconds=0.0
        )
        first = await client.list_matches("EPL", "2025")
        second = await client.list_matches("EPL", "2025")
    assert len(first) == 1 and len(second) == 1
    assert cache.sets == 1
    assert cache.hits == 1


def test_rate_limiter_serializes() -> None:
    rl = uc._RateLimiter(min_interval=0.05)

    async def run() -> float:
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        await rl.acquire()
        await rl.acquire()
        return loop.time() - t0

    elapsed = asyncio.run(run())
    assert elapsed >= 0.05
