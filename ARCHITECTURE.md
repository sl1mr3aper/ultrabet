# ARCHITECTURE — текущая структура проекта

> Этот файл описывает **актуальную** архитектуру (на 2026-05-01).
> Старая `docs/ARCHITECTURE.md` сохранена как исторический документ,
> при расхождении — приоритет у этого файла.

---

## Top-level

```
ultrabet/
├── main.py                  # точка входа, инициализация, polling
├── config.py                # Settings (pydantic-settings, ENV)
├── requirements.txt
├── .env                     # токены (НЕ коммитить!)
├── .gitignore
├── AGENTS.md                # стиль работы агента
├── HANDOFF.md               # ← этот файл, что сделано
├── REQUIREMENTS.md          # ← закреплённые требования пользователя
├── NEXT.md                  # ← план улучшений
├── ASSESSMENT.md            # ← честная оценка проекта
├── ARCHITECTURE.md          # ← текущая архитектура (этот файл)
│
├── api/                     # FastAPI endpoints (минимум, для health/metrics)
├── bot/                     # Telegram-бот (aiogram 3)
│   ├── handlers/            # хэндлеры команд и callback'ов
│   ├── keyboards.py         # inline-клавиатуры
│   ├── states.py            # FSM-состояния
│   ├── texts.py             # все тексты UI (i18n-ready)
│   ├── formatters.py        # форматирование прогнозов
│   ├── progress.py          # анимации loading + cancel-кнопка
│   ├── pagination.py        # пагинация для топов и лиг
│   ├── middlewares/         # auth, rate-limit, logging
│   └── context.py           # DI контейнер
│
├── core/                    # ЯДРО — модели и алгоритмы
│   ├── glicko_model.py      # Glicko-2 рейтинги
│   ├── poisson_model.py     # Двойная Пуассон, тоталы, BTTS, hand-cap
│   ├── ensemble.py          # Glicko + Poisson смесь, адаптивные веса
│   ├── markets.py           # MarketKey-enum, описания рынков
│   ├── value_engine.py      # ⭐ единый отбор пиков (verdict, EV×√p, sanity)
│   ├── value_calculator.py  # подсчёт valueable bets (legacy, использует value_engine)
│   ├── probability_regulator.py  # коррекция вероятностей по истории (на малых данных шумит)
│   ├── accuracy_boost.py    # эвристики усиления точности
│   ├── form_analyzer.py     # форма команды (последние N матчей)
│   ├── momentum.py          # импульс, серия побед/поражений
│   ├── market_evaluator.py  # «насколько рынок переоценён»
│   └── bankroll.py          # Kelly, fractional Kelly (legacy)
│
├── services/                # бизнес-логика, источники данных
│   ├── prediction_service.py   # главный orchestrator: матч → прогноз
│   ├── topmatches_precompute.py # фоновый прогрев топ-матчей
│   ├── daily_picks.py / dailypicks-related
│   ├── sstats_client.py     # клиент SStats API (единственный источник)
│   ├── ai_refiner.py        # Gemini AI пост-обработка прогноза (text + soft scores)
│   ├── self_learner.py      # обновление весов ансамбля (на малых данных шумит)
│   ├── calibration_service.py  # Platt/isotonic калибровка (заготовка)
│   ├── backtester.py        # бэктест по дате (используется массовым анализом)
│   ├── predictions_resolver.py # резолв результатов завершённых матчей
│   ├── league_service.py / league_standings.py
│   ├── form_analyzer.py
│   ├── analytics.py / event_store.py
│   ├── cache_store.py / kv_cache.py / cache_warmer.py
│   ├── bankroll.py          # описание стейков (Kelly, flat, percent)
│   ├── bet_journal.py       # журнал ставок пользователя
│   ├── feature_flags.py
│   ├── error_translator.py
│   ├── i18n.py              # многоязычность (заготовка)
│   ├── circuit_breaker.py   # защита от падений SStats
│   ├── webhook_publisher.py
│   └── oracle/              # «оракул» — пакет агрегатор предсказаний
│
├── db/                      # SQLAlchemy 2.x async
│   ├── database.py          # engine + session_factory + WAL pragma
│   ├── models.py            # ORM-модели (User, Prediction, Bet, BacktestResult, ...)
│   ├── repositories/        # по одному файлу на сущность
│   └── migrations/          # alembic (если используется)
│
├── tests/                   # 572 теста (pytest, asyncio)
├── utils/                   # logger, time helpers, country flags
├── scripts/                 # отдельные скрипты для бэк-офис задач
├── worker/                  # заготовка под отдельный воркер-процесс
├── data/                    # bot.db (SQLite WAL)
├── logs/
├── docs/                    # старая документация (FAQ, USER_GUIDE и т.д.)
└── .devin/skills/           # ← skill для следующего Devin-агента
    └── CONTINUE_HERE/SKILL.md
```

---

## Поток обработки одного прогноза

```
User /predict 12345
       ↓
[bot/handlers/predictions.py] — приём команды, проверка квот
       ↓
[services/prediction_service.py] — orchestrator
       ↓                                         ↓
[services/sstats_client.py] ←───── одноразовое ────→ [SStats API]
       ↓
[core/glicko_model.py] glicko_outcome_probs(home_rating, away_rating)
       ↓
[core/poisson_model.py] correct_score_distribution(home_xg, away_xg)
       ↓
[core/ensemble.py] build_predictions(...)  → probabilities (1X2, тоталы, BTTS, AH, IT, score)
       ↓
[core/probability_regulator.py] apply (опционально, на малых данных шумит)
       ↓
[services/ai_refiner.py] Gemini пост-обработка (text + soft adjustments)
       ↓
[core/value_engine.select_best_pick()]  ← главный отбор пика
       ↓
PickScore { market_key, probability, odds, fair_odds, ev_pct, kelly, verdict, composite }
       ↓
[bot/formatters.py] отрисовка
       ↓
[bot] → Telegram
```

---

## Ключевые потоки UX

### Главное меню
- `bot/handlers/main_menu.py` — `home_keyboard(user_id)` строит клавиатуру.
  Если `user_id ∈ ADMIN_IDS` → добавляет 📊 Массовый анализ и 🎯 Анализ прогнозов.

### Массовый анализ (admin)
```
admin:mass_analysis (callback)
  → ASK_DATE  ← кнопки Сегодня/Вчера/Завтра + ввод ГГГГ-ММ-ДД
  → _run_backtest(date)
       ↓
       SStats: список матчей даты
       prediction_service на каждый матч
       value_engine.select_best_pick на каждом
       резолв результата (если матч закончен)
       ROI/точность статистика
       Сообщение в Telegram (top-10) + .txt полный отчёт
```

### Анализ прогнозов (admin)
```
admin:prediction_analysis (callback)
  → ASK_DATE  ← как в массовом
  → ASK_COUNT ← пресеты 10/20/50/100 + ввод 1–200
  → _run_prediction_analysis(date, count)
       ↓
       (то же что массовый, но на N матчей)
       Кнопка 🛑 Остановить — register_cancel(work_task)
```

### Топ-сегодня / Топ-завтра
```
[topmatches] → _topmatches.py
  → topmatches_precompute (cron) генерирует кэш
  → отрисовка с фильтром verdict ∈ {"брать", "осторожно"} и сортировкой по composite
```

---

## База данных

SQLite WAL-mode. Файл `data/bot.db` + `data/bot.db-wal` + `data/bot.db-shm`.

**Основные таблицы**:
- `users` — Telegram-юзеры, бесплатные предсказания, реферальная цепочка.
- `subscriptions` — оплаченные подписки (free/basic/vip).
- `predictions` — журнал предсказаний (game_id, kind, payload JSON).
- `prediction_outcomes` — резолв (hit/miss) для self-learning.
- `bet_journal` — ставки пользователя (журнал прибыли/убытков).
- `backtest_results` — кэш бэктестов по дате.
- `bonus_predictions` / `referral_bonus` — бонусы.
- `cache_kv` — KV-кэш (TTL).
- `event_log` — телеметрия событий бота.

**Чувствительные операции** (записи) идут через `session_factory()`,
читающие — через тот же async session.

WAL-mode включён в `db/database.py` или `main.py` через PRAGMA при инициализации.

---

## Конфигурация (Settings из `config.py`)

Загружается из `.env` через pydantic-settings.

Ключевые поля:
- `bot_token: str`
- `bot_username: str`
- `sstats_api_key: str`, `sstats_base_url: str`
- `database_url: str`
- `admin_ids: list[int]`
- `proxy_url: str | None`
- `min_value_odds: float = 1.15`
- `min_value_percent: float = 2.0`
- **`min_value_probability: float = 0.35`** ← важно (см. REQUIREMENTS.md R2.2/R2.3)
- `top_predictions: int = 15`
- `top_value_bets: int = 15`
- `gemini_api_key: str | None`, `gemini_model: str`
- TTL'ы кэшей (`cache_ttl_*`)
- `referral_bonus_*`
- `timezone_offset: int = 3` (Москва)

---

## Cache-стратегия

3 уровня:
1. **In-memory** (`services/cache_store.py`): TTL-словарь, на процесс.
2. **KV-table** (`services/kv_cache.py`): SQLite-таблица для долгого кэша.
3. **HTTP-кэш** SStats: ETag + If-Modified-Since (где умеет).

TTL по умолчанию (см. `.env`):
```
CACHE_TTL_TEAMS=3600
CACHE_TTL_MATCHES=900
CACHE_TTL_GAME=300
CACHE_TTL_GLICKO=600
CACHE_TTL_ODDS=180
CACHE_TTL_LEAGUES=86400
```

**Прогрев**: `services/cache_warmer.py` → `_initial_warm()` в main.py
запускает прогрев лиг + матчей сегодня/завтра при старте.

---

## Точки расширения для NEXT.md

1. **Новый источник данных** → новый модуль в `services/`
   (например, `services/sofascore_client.py`), интеграция в
   `services/prediction_service.py` через DI.
2. **Новая модель** → новый файл в `core/` с интерфейсом
   `def predict(home_id, away_id, ...) -> dict[market_key, prob]`,
   подключение в `core/ensemble.py`.
3. **Новая команда бота** → новый хэндлер в `bot/handlers/`,
   регистрация в `bot/handlers/__init__.py`.
4. **Новая БД-таблица** → модель в `db/models.py`,
   репозиторий в `db/repositories/`, alembic-миграция.

---

## Что НЕ менять без причины

- Контракт `core/value_engine.PickScore` — много мест зависит.
- WAL-режим SQLite — только в продакшене на Postgres снимать (см. NEXT.md 5.1).
- API-формат сообщений Telegram (Markdown, эмодзи) — UX-стиль установлен.
- Имена callback_data (`admin:mass_analysis`, `admin:prediction_analysis`,
  `menu:home`, ...) — могут стучаться из старых сессий пользователей.

---

## Полезные команды

```bash
# тесты
.venv/bin/python -m pytest tests/ -x --tb=short -q

# линтер
.venv/bin/ruff check bot/ core/ services/

# форматер
.venv/bin/ruff format bot/ core/ services/

# просмотр БД
sqlite3 data/bot.db ".tables"
sqlite3 data/bot.db "SELECT count(*) FROM prediction_outcomes WHERE hit IS NOT NULL"

# чекпоинт WAL → bot.db (перед бэкапом)
sqlite3 data/bot.db "PRAGMA wal_checkpoint(TRUNCATE);"

# граф зависимостей модуля (если нужно для рефакторинга)
.venv/bin/pydeps bot/handlers/admin.py --noshow -o admin.svg
```
