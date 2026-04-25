# Траблшутинг

### Бот не отвечает на `/start`

1. Проверь, что `TG_BOT_TOKEN` в `.env` правильный.
2. Запусти `make run` локально, посмотри логи.
3. У Telegram бывает throttle — подожди пару секунд.

### Падают запросы к SStats

1. Проверь `SSTATS_API_KEY` (опционально, но без ключа квота 30 запросов/минуту).
2. Сетевой firewall? Проверь `curl https://api.sstats.net/Account/Info`.
3. Если упирается в rate-limit — увеличь TTL кэша в `config.py`.

### `make test` упал на async-тесте

```
ERROR: pytest-asyncio is not installed
```

Установи dev-deps: `make install`.

### `mypy` ругается на сторонние пакеты

В `pyproject.toml` уже выставлен `ignore_missing_imports = true`. Если
добавляешь новый пакет — добавь stub или explicit `[[tool.mypy.overrides]]`.

### CI fails на GitHub

Открой раздел Actions, посмотри лог. Самые частые причины:
- забыли отформатировать (`make format`);
- забыли запустить `make lint`;
- импорт без аннотации `from __future__ import annotations` в новых модулях.

### База данных не открывается

SQLite файл `ultrabet.db` создаётся автоматически. Если лежит криво:

```bash
rm ultrabet.db
.venv/bin/python -m db.init_db
```

### Бот пишет «Превышен лимит запросов»

Это бизнес-логика квот. Купи подписку через `/subscribe` или подожди сброса
ежедневной квоты в полночь UTC.

### `aiogram.exceptions.TelegramBadRequest: text is too long`

Telegram режет сообщения > 4096 символов. Проверь форматтер: каждый отчёт
должен укладываться в лимит. Если используешь свой кастомный шаблон —
разбей на несколько `answer()`.
