"""Тесты пагинации."""

from __future__ import annotations

from bot.pagination import (
    Page,
    format_paginated,
    pagination_keyboard,
    parse_pagination_callback,
)


def test_total_pages_basic():
    p: Page = Page(items=list(range(25)), page_index=0, page_size=10)
    assert p.total_pages == 3


def test_total_pages_zero_safe():
    p: Page = Page(items=[], page_index=0, page_size=10)
    assert p.total_pages == 1


def test_slice_correct():
    p: Page = Page(items=list(range(25)), page_index=1, page_size=10)
    assert p.slice() == list(range(10, 20))


def test_navigation_flags():
    p: Page = Page(items=list(range(25)), page_index=0, page_size=10)
    assert p.has_prev is False
    assert p.has_next is True

    p2: Page = Page(items=list(range(25)), page_index=2, page_size=10)
    assert p2.has_prev is True
    assert p2.has_next is False


def test_format_paginated_renders_items():
    p: Page = Page(items=["a", "b", "c"], page_index=0, page_size=2)
    text = format_paginated(p, render_item=lambda i, x: f"{i}.{x}", header_text="HDR")
    assert "HDR" in text
    assert "1.a" in text
    assert "Страница 1 из 2" in text


def test_format_paginated_empty():
    p: Page = Page(items=[], page_index=0, page_size=10)
    text = format_paginated(p, render_item=lambda i, x: str(x))
    assert "пусто" in text


def test_pagination_keyboard_buttons():
    p: Page = Page(items=list(range(25)), page_index=0, page_size=10)
    kb = pagination_keyboard("test", p)
    flat = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert any(d and d.startswith("test:1:") for d in flat)


def test_parse_pagination_callback():
    idx, extra = parse_pagination_callback("test:3:foo", "test")
    assert idx == 3
    assert extra == "foo"


def test_parse_pagination_callback_missing_extra():
    idx, extra = parse_pagination_callback("test:5", "test")
    assert idx == 5
    assert extra == ""


def test_parse_pagination_callback_bad_prefix():
    idx, _ = parse_pagination_callback("other:5:bar", "test")
    assert idx == 0
