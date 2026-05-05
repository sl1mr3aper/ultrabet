"""Глобальная навигация: стек переходов пользователя.

Каждый переход запоминается в FSM-данных пользователя. Кнопка «Назад»
возвращает на предыдущий экран с восстановлением состояния (страница,
фильтр и т.д.), «Главное меню» очищает стек.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from aiogram.fsm.context import FSMContext


@dataclass(slots=True)
class NavEntry:
    """Одна запись в стеке навигации."""
    callback_data: str  # callback для перехода обратно
    extra: dict[str, Any] = field(default_factory=dict)


MAX_STACK_DEPTH = 20


async def nav_push(state: FSMContext, callback_data: str, **extra: Any) -> None:
    """Сохранить текущее место в стек навигации."""
    data = await state.get_data()
    stack: list[dict] = data.get("_nav_stack", [])
    entry = NavEntry(callback_data=callback_data, extra=extra)
    stack.append(asdict(entry))
    if len(stack) > MAX_STACK_DEPTH:
        stack = stack[-MAX_STACK_DEPTH:]
    await state.update_data(_nav_stack=stack)


async def nav_pop(state: FSMContext) -> NavEntry | None:
    """Извлечь последнюю запись из стека навигации."""
    data = await state.get_data()
    stack: list[dict] = data.get("_nav_stack", [])
    if not stack:
        return None
    raw = stack.pop()
    await state.update_data(_nav_stack=stack)
    return NavEntry(
        callback_data=raw.get("callback_data", "menu:home"),
        extra=raw.get("extra", {}),
    )


async def nav_clear(state: FSMContext) -> None:
    """Очистить стек навигации (при переходе в главное меню)."""
    await state.update_data(_nav_stack=[])


async def nav_peek(state: FSMContext) -> NavEntry | None:
    """Посмотреть верхнюю запись стека без извлечения."""
    data = await state.get_data()
    stack: list[dict] = data.get("_nav_stack", [])
    if not stack:
        return None
    raw = stack[-1]
    return NavEntry(
        callback_data=raw.get("callback_data", "menu:home"),
        extra=raw.get("extra", {}),
    )


__all__ = ["NavEntry", "nav_clear", "nav_peek", "nav_pop", "nav_push"]
