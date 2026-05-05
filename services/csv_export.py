"""Экспорт сырых данных матча в CSV.

Возвращает байты CSV-файла, готового к отправке в Telegram. Содержит
плоскую (key,value) проекцию полного бандла SStats: game, glicko,
prematch/live odds, injuries, last_games, profits, season_table, summary.
"""
from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable
from typing import Any


def _flatten(prefix: str, value: Any) -> Iterable[tuple[str, str]]:
    """Развернуть произвольный JSON-объект в плоский поток (key, value).

    Списки разворачиваются как `prefix[i]`, словари — как `prefix.subkey`.
    Скалярные значения сериализуются в строку (None → пусто).
    """
    if value is None:
        yield prefix, ""
        return
    if isinstance(value, dict):
        if not value:
            yield prefix, "{}"
            return
        for k, v in value.items():
            sub = f"{prefix}.{k}" if prefix else str(k)
            yield from _flatten(sub, v)
        return
    if isinstance(value, list):
        if not value:
            yield prefix, "[]"
            return
        for i, item in enumerate(value):
            yield from _flatten(f"{prefix}[{i}]", item)
        return
    if isinstance(value, bool):
        yield prefix, "true" if value else "false"
        return
    if isinstance(value, (int, float)):
        yield prefix, str(value)
        return
    if isinstance(value, str):
        yield prefix, value
        return
    # Fallback на JSON-сериализацию для прочих типов.
    try:
        yield prefix, json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        yield prefix, repr(value)


def render_match_csv(bundle: dict[str, Any]) -> bytes:
    """Преобразовать full-match bundle в плоский CSV.

    Колонки: section, key, value. Раздел = верхний ключ бандла
    (game/glicko/odds/...), key — путь до листового поля, value — значение.
    """
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(["section", "key", "value"])
    for section, payload in bundle.items():
        for key, value in _flatten("", payload):
            writer.writerow([section, key, value])
    return buf.getvalue().encode("utf-8-sig")


__all__ = ["render_match_csv"]
