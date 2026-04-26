"""Тесты экспорта данных."""

from __future__ import annotations

from dataclasses import dataclass

from services.export import to_csv, to_json, to_markdown_table, to_tsv


@dataclass
class Row:
    name: str
    age: int
    tags: list[str]


def test_empty_to_csv():
    assert to_csv([]) == ""


def test_csv_dataclass():
    rows = [Row("Alice", 30, ["a", "b"]), Row("Bob", 25, [])]
    out = to_csv(rows)
    lines = out.strip().splitlines()
    assert lines[0] == "name,age,tags"
    assert "Alice" in lines[1]


def test_tsv():
    rows = [{"k": "v", "n": 1}]
    out = to_tsv(rows)
    assert "k\tn" in out.split("\r\n")[0] or "k\tn" in out.split("\n")[0]


def test_json_format():
    rows = [Row("A", 1, [])]
    out = to_json(rows)
    assert "Alice" not in out  # just A
    assert "A" in out


def test_markdown_table_empty():
    assert to_markdown_table([]) == "_пусто_"


def test_markdown_table_basic():
    rows = [{"a": 1, "b": 2}]
    out = to_markdown_table(rows)
    assert "| a | b |" in out
    assert "| 1 | 2 |" in out


def test_csv_escapes_commas_via_quote():
    rows = [{"a": "x,y", "b": "z"}]
    out = to_csv(rows)
    assert '"x,y"' in out


def test_mixed_dict_and_dataclass():
    rows = [Row("A", 1, []), {"name": "B", "age": 2, "tags": []}]
    out = to_csv(rows)
    assert "A" in out and "B" in out
