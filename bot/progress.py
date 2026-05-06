"""Прогресс-индикатор для длинных операций.

Формат — минимальный, без графической полосы:
    ⚡ *Готовлю прогноз*   ·   35%
    _анализирую формы команд_   ·   *4 сек*

Заголовок · процент сверху, стадия · секунды снизу. Никаких █/░ —
проще и одинаково красиво на всех платформах Telegram.
"""

from __future__ import annotations

import asyncio
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def neural_loader(
    title: str,
    *,
    pct: float,
    frame: int = 0,
    stage: str = "",
    elapsed: str = "",
    next_in: str = "",
) -> str:
    """Отрисовать кадр индикатора.

    Args:
        title: основной заголовок («Считаю прогноз», «Ищу команды», ...).
        pct: текущий прогресс [0..1].
        frame: индекс кадра (игнорируется, сохранён для совместимости).
        stage: подпись текущего этапа.
        elapsed: «3 сек.» — прошедшее время от начала операции.
        next_in: оставлен для обратной совместимости, но не отображается.

    Returns:
        Готовый Markdown-V1 текст.
    """
    del frame, next_in  # поля не отображаются, оставлены ради обратной совместимости.
    pct_str = f"{int(round(pct * 100))}%"
    # Минималистичный двустрочный формат — без графической полосы:
    #     ⚡ *Готовлю прогноз*   ·   35%
    #     анализирую формы команд   ·   4 сек
    lines: list[str] = [f"⚡ *{title}*   ·   *{pct_str}*"]
    bottom: list[str] = []
    if stage:
        bottom.append(f"_{stage}_")
    if elapsed:
        bottom.append(f"*{elapsed}*")
    if bottom:
        lines.append("   ·   ".join(bottom))
    return "\n".join(lines)


# ── Стадии расчёта прогноза (без упоминаний внешних сервисов) ───
# Каждый элемент: (нижний порог секунд, pct, описание стадии).
PREDICTION_STAGES: tuple[tuple[float, float, str], ...] = (
    (0.0, 0.08, "загружаю матч"),
    (1.5, 0.20, "формы команд"),
    (3.0, 0.32, "рейтинги"),
    (4.5, 0.44, "сила атаки и обороны"),
    (6.0, 0.56, "объединяю модели"),
    (7.5, 0.68, "котировки"),
    (9.0, 0.78, "историческая коррекция"),
    (10.5, 0.86, "EV-ставки"),
    (12.0, 0.93, "AI-уточнение"),
    (14.0, 0.97, "сборка отчёта"),
)


def stage_for_elapsed(seconds: float) -> tuple[float, str]:
    """Вернуть (pct, stage) для текущего времени ожидания.

    Между двумя соседними стадиями pct интерполируется линейно — это
    устраняет эффект «застывания» полоски на одном значении на несколько
    секунд (раньше, например, с 3 с до 4.4 с бар оставался ровно на 32 %).
    Подпись стадии берётся от текущей (нижней) точки, чтобы текст не
    прыгал каждую секунду.
    """
    stages = PREDICTION_STAGES
    if seconds <= stages[0][0]:
        return stages[0][1], stages[0][2]
    for i, item in enumerate(stages):
        if seconds >= item[0]:
            # Следующая точка (или последняя)
            if i + 1 < len(stages):
                nxt = stages[i + 1]
                if seconds < nxt[0]:
                    # Линейная интерполяция pct между item и nxt.
                    span = nxt[0] - item[0]
                    if span > 0:
                        k = (seconds - item[0]) / span
                        pct = item[1] + (nxt[1] - item[1]) * k
                    else:
                        pct = item[1]
                    return max(0.0, min(0.99, pct)), item[2]
            else:
                return item[1], item[2]
    return stages[0][1], stages[0][2]


def next_stage_in(seconds: float) -> float:
    """Сколько секунд осталось до следующей стадии. 0 — если стадий больше нет."""
    for item in PREDICTION_STAGES:
        if item[0] > seconds:
            return max(0.0, item[0] - seconds)
    return 0.0


SEARCH_STAGES: tuple[tuple[float, float, str], ...] = (
    (0.0, 0.20, "поиск по алиасам"),
    (0.8, 0.45, "нормализация названий"),
    (1.6, 0.70, "подбор совпадений"),
    (2.4, 0.90, "сборка списка"),
)


def search_stage_for_elapsed(seconds: float) -> tuple[float, str]:
    current = SEARCH_STAGES[0]
    for item in SEARCH_STAGES:
        if seconds >= item[0]:
            current = item
        else:
            break
    return current[1], current[2]


# Минималистичный «спиннер» — крутящиеся четверти круга. Один символ,
# никаких длинных полос, элегантно. Кадр выбирается по elapsed_seconds.
_SPINNER_FRAMES = ("◐", "◓", "◑", "◒")


def _spinner(elapsed_seconds: float) -> str:
    idx = int(max(0.0, elapsed_seconds) * 2) % len(_SPINNER_FRAMES)
    return _SPINNER_FRAMES[idx]


def minimal_loader(title: str, *, elapsed_seconds: float) -> str:
    """Минимальный, элегантный лоадер для операций без явных стадий.

    Однострочник: `◐ *Готовлю отчёт*  ·  4 сек`. Без длинных полос —
    компактно и одинаково красиво на всех платформах Telegram.
    """
    sec = max(0, int(elapsed_seconds))
    return f"{_spinner(elapsed_seconds)} *{title}*   ·   *{sec} сек*"


def _indeterminate_frame(
    title: str, elapsed_seconds: float, *, hint: str = "",
) -> str:
    """Публичный вариант: одна строка с тикающим таймером и подсказкой."""
    sec = max(0, int(elapsed_seconds))
    spin = _spinner(elapsed_seconds)
    lines = [f"{spin} *{title}*   ·   *{sec} сек*"]
    if hint:
        lines.append(hint)
    return "\n".join(lines)


async def animate_message(
    message: Any,
    title: str,
    *,
    hint: str = "",
    interval: float = 1.0,
) -> None:
    """Корутина для фоновой анимации любого сообщения с бегущей волной.

    Использование:

        task = asyncio.create_task(animate_message(loading_msg, "Готовлю отчёт"))
        try:
            result = await do_work()
        finally:
            task.cancel()

    Корутина сама следит за тем, чтобы не отправлять лишних edit, если
    текст не изменился (rate-limit Telegram ≈ 1/сек на сообщение).
    """
    import asyncio as _asyncio
    import time as _time

    started = _time.monotonic()
    last_text: str | None = None
    try:
        while True:
            await _asyncio.sleep(interval)
            elapsed = _time.monotonic() - started
            text = _indeterminate_frame(title, elapsed, hint=hint)
            if text == last_text:
                continue
            try:
                await message.edit_text(text, parse_mode="Markdown")
                last_text = text
            except Exception:
                pass
    except _asyncio.CancelledError:
        raise


# ── Поддержка кнопки «Отмена» на длинных операциях ──────────────
# Регистр работает по ключу (chat_id, message_id): если пользователь
# жмёт «❌ Отмена» на сообщении с анимацией, обработчик common.cancel_op_cb
# проходится по всем зарегистрированным task'ам и вызывает cancel().
# Храним список, чтобы отменять сразу и рабочую task'у, и анимацию
# прогресса (иначе animator успеет перезаписать экран главного меню).
_cancel_tasks: dict[tuple[int, int], list[asyncio.Task[Any]]] = {}


def cancel_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с единственной кнопкой «❌ Отмена»."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel:op")]
        ]
    )


def register_cancel(
    chat_id: int, message_id: int, *tasks: asyncio.Task[Any],
) -> None:
    """Регистрирует одну или несколько task'ов на общую отмену."""
    bucket = _cancel_tasks.setdefault((chat_id, message_id), [])
    for t in tasks:
        if t is not None:
            bucket.append(t)


def trigger_cancel(chat_id: int, message_id: int) -> bool:
    bucket = _cancel_tasks.pop((chat_id, message_id), None)
    if not bucket:
        return False
    any_cancelled = False
    for task in bucket:
        if task is not None and not task.done():
            task.cancel()
            any_cancelled = True
    return any_cancelled


def clear_cancel(chat_id: int, message_id: int) -> None:
    _cancel_tasks.pop((chat_id, message_id), None)


__all__ = [
    "PREDICTION_STAGES",
    "SEARCH_STAGES",
    "animate_message",
    "cancel_keyboard",
    "clear_cancel",
    "minimal_loader",
    "neural_loader",
    "next_stage_in",
    "register_cancel",
    "search_stage_for_elapsed",
    "stage_for_elapsed",
    "trigger_cancel",
]
