"""Экспорт данных в разных форматах: CSV, JSON, TSV, Markdown.

Используется:
- для выгрузки истории прогнозов пользователя.
- для админ-отчётов (список подписок, платежей, рефералов).
- для аналитики (выгрузка AnalyticsService.history в CSV).
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable
from dataclasses import asdict, is_dataclass
from typing import Any


def _row(obj: Any) -> dict[str, Any]:
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    if isinstance(obj, dict):
        return dict(obj)
    if hasattr(obj, "__dict__"):
        return dict(obj.__dict__)
    raise TypeError(f"Cannot serialize {type(obj).__name__}")


def _union_fieldnames(rows: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for r in rows:
        for k in r.keys():
            if k not in seen:
                seen.add(k)
                names.append(k)
    return names


def to_csv(rows: Iterable[Any], *, delimiter: str = ",") -> str:
    """Сериализовать iterable объектов в CSV-строку."""
    dicts = [_row(r) for r in rows]
    if not dicts:
        return ""
    fieldnames = _union_fieldnames(dicts)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, delimiter=delimiter)
    writer.writeheader()
    for d in dicts:
        writer.writerow({k: _csv_cell(v) for k, v in d.items()})
    return buf.getvalue()


def to_tsv(rows: Iterable[Any]) -> str:
    """Сериализовать в TSV (tab-separated)."""
    return to_csv(rows, delimiter="\t")


def to_json(rows: Iterable[Any], *, indent: int = 2) -> str:
    """Сериализовать в JSON-массив объектов."""
    dicts = [_row(r) for r in rows]
    return json.dumps(dicts, ensure_ascii=False, indent=indent, default=str)


def to_markdown_table(rows: Iterable[Any]) -> str:
    """Сериализовать в Markdown-таблицу."""
    dicts = [_row(r) for r in rows]
    if not dicts:
        return "_пусто_"
    fieldnames = _union_fieldnames(dicts)
    lines = [
        "| " + " | ".join(fieldnames) + " |",
        "|" + "|".join(["---"] * len(fieldnames)) + "|",
    ]
    for d in dicts:
        cells = [str(d.get(k, "")).replace("|", "\\|") for k in fieldnames]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _csv_cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, dict, tuple, set)):
        return json.dumps(v, ensure_ascii=False, default=str)
    return str(v)


__all__ = ["to_csv", "to_json", "to_markdown_table", "to_tsv"]
