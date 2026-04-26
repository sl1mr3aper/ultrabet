"""Универсальная пагинация для inline-сообщений.

Использование:
    page = Page(items=[...], page_size=10, page_index=0)
    text = format_paginated(page, render_item=lambda i, x: f"{i}. {x['name']}")
    kb = pagination_keyboard(prefix="leagues_page", page=page, extra_payload="")

Колбэки имеют вид: "<prefix>:<index>:<extra>"
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.styles import ICON_BACK, ICON_FORWARD, ICON_HOME

T = TypeVar("T")


@dataclass(slots=True)
class Page(Generic[T]):
    items: list[T]
    page_index: int
    page_size: int

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def total_pages(self) -> int:
        if self.page_size <= 0:
            return 1
        return max(1, (self.total + self.page_size - 1) // self.page_size)

    @property
    def has_prev(self) -> bool:
        return self.page_index > 0

    @property
    def has_next(self) -> bool:
        return self.page_index < self.total_pages - 1

    def slice(self) -> list[T]:
        start = self.page_index * self.page_size
        end = start + self.page_size
        return self.items[start:end]


def format_paginated(
    page: Page[T],
    *,
    render_item: Callable[[int, T], str],
    header_text: str = "",
    footer_text: str = "",
    base_index: int = 1,
) -> str:
    chunks = page.slice()
    lines: list[str] = []
    if header_text:
        lines.append(header_text)
    start_offset = page.page_index * page.page_size
    for i, item in enumerate(chunks):
        global_index = base_index + start_offset + i
        lines.append(render_item(global_index, item))
    if not chunks:
        lines.append("— пусто —")
    lines.append("")
    lines.append(f"Страница {page.page_index + 1} из {page.total_pages}")
    if footer_text:
        lines.append(footer_text)
    return "\n".join(lines)


def pagination_keyboard(
    prefix: str,
    page: Page[Any],
    *,
    extra_payload: str = "",
    home_callback: str | None = "menu_main",
) -> InlineKeyboardMarkup:
    """Строит клавиатуру с ◀ Назад / X / Y / ▶ Вперёд / 🏠 Меню."""
    builder = InlineKeyboardBuilder()
    if page.has_prev:
        builder.button(
            text=f"{ICON_BACK} Назад",
            callback_data=f"{prefix}:{page.page_index - 1}:{extra_payload}",
        )
    builder.button(
        text=f"{page.page_index + 1}/{page.total_pages}",
        callback_data="noop",
    )
    if page.has_next:
        builder.button(
            text=f"Вперёд {ICON_FORWARD}",
            callback_data=f"{prefix}:{page.page_index + 1}:{extra_payload}",
        )
    builder.adjust(3)
    if home_callback:
        builder.row(
            InlineKeyboardButton(text=f"{ICON_HOME} Меню", callback_data=home_callback)
        )
    return builder.as_markup()


def parse_pagination_callback(data: str, prefix: str) -> tuple[int, str]:
    """Разбирает callback-data вида "<prefix>:<index>:<extra>". Возвращает (index, extra)."""
    if not data.startswith(prefix + ":"):
        return 0, ""
    rest = data[len(prefix) + 1 :]
    if ":" in rest:
        idx_str, extra = rest.split(":", 1)
    else:
        idx_str, extra = rest, ""
    try:
        return int(idx_str), extra
    except ValueError:
        return 0, extra


__all__ = [
    "Page",
    "format_paginated",
    "pagination_keyboard",
    "parse_pagination_callback",
]
