# Contributing

Спасибо за интерес к UltraBet! Гайд для контрибуторов.

## Требования

- Python 3.11+
- ruff, mypy, pytest (ставятся через `requirements-dev.txt`)

## Установка окружения

```bash
make install      # установка dev-зависимостей в .venv
cp .env.example .env
```

## Пайплайн перед PR

```bash
make lint         # ruff check
make format       # ruff format
make typecheck    # mypy
make test         # pytest
```

Все 4 шага должны проходить чисто.

## Стиль кода

- `ruff` (см. `pyproject.toml`) — длина строки 110.
- Импорты на верхнем уровне, без отложенных, кроме случаев цикличных ссылок.
- Все публичные функции/методы — с типами и docstring.
- Без `Any`, `getattr/setattr` для бизнес-логики.

## Архитектура

Любое нововведение должно укладываться в слойную архитектуру:

| Слой | Где жить |
|------|----------|
| Транспорт TG | `bot/handlers/...`, `bot/keyboards.py` |
| Бизнес-логика | `services/` |
| Алгоритмы | `core/` |
| HTTP-API | `api/sstats_client.py` |
| Хранилище | `db/models.py` + `db/repositories/...` |

Смотри `docs/ARCHITECTURE.md`.

## Тесты

Каждый PR с новым кодом должен включать тесты. Юнит-тесты хранятся в `tests/`,
именование `test_<module>.py`.

Async-тесты используют `pytest-asyncio` и фикстуру `session` (см. `tests/conftest.py`).

## Локализация

Все строки, видимые пользователю, — на русском, в `bot/texts.py`. Никаких
строк "в коде", только импортированные константы.

## Pull Request

1. Бранч от `main`: `feat/<topic>`, `fix/<topic>`, `chore/<topic>`.
2. Заголовок PR в Conventional Commits-стиле:
   `feat(prediction): добавить ИТ обеих команд 2.5`.
3. Описание PR — обязательно: мотивация, ключевые решения, как тестировал.
