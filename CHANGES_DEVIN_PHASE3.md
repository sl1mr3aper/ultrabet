# Phase 3 — Production-readiness (Devin session 2026-05-05)

> Базовый коммит: Phase 2 (secondary pick learner). 617 → **651 тестов passing**, ruff clean.
> См. также `CHANGES_DEVIN.md` (Phase 1) и `CHANGES_TODAY.md` (правки UX).

## Что сделано

### P0 — Инфраструктура (Docker + Observability + Backups)

1. **`Dockerfile`** + **`.dockerignore`** — production-image на python:3.11-slim,
   без компилятора, под non-root пользователем, healthcheck.
2. **`docker-compose.yml`** — четыре сервиса:
   - `postgres:16-alpine` (БД, persistent volume `pgdata`).
   - `redis:7-alpine` (общий кэш + rate-limit, persistent `redisdata`).
   - `bot` — основной процесс, healthcheck'ом ждёт Postgres+Redis.
   - `backup` (профиль `--profile backup`) — крутит `scripts/backup_loop.py`,
     дампы в `botbackups`, опционально S3.
3. **Sentry интеграция** (`services/observability.py` + `main.py`):
   - При наличии `SENTRY_DSN` инициализирует `sentry_sdk` с конфигом из
     `SENTRY_ENVIRONMENT`/`SENTRY_TRACES_SAMPLE_RATE`.
   - Если SDK не установлен — мягкое предупреждение в лог, бот не падает.
4. **Prometheus метрики** (тот же модуль):
   - `PROMETHEUS_PORT > 0` поднимает HTTP-сервер `/metrics`.
   - Реестр счётчиков/гистограмм:
     `ultrabet_bot_started_total`, `_handler_calls_total`, `_handler_errors_total`,
     `_sstats_requests_total`, `_sstats_errors_total`, `_sstats_latency_seconds`,
     `_self_learner_runs_total`, `_secondary_calibrator_runs_total`,
     `_cache_hits_total`, `_cache_misses_total`, `_db_pool_size`.
   - Если `prometheus_client` не установлен — все метрики no-op
     (`_NoopMetric.inc()` ничего не делает), код handler'ов не нужно
     обкладывать условными проверками.
5. **DB бэкапы** (`services/db_backup.py` + `scripts/backup_loop.py`):
   - `backup_database(url, dir)`: SQLite — copy + gzip; Postgres — `pg_dump -Fc`.
   - `cleanup_old_backups(dir, retention_days=N)` — чистит старые файлы.
   - `upload_to_s3(...)` — опционально через boto3.
   - `run_backup_cycle(...)` — async-обёртка для cron.

### P0 — Postgres-готовность

6. **`db/database.py`** — soft-migrations теперь работают и для Postgres:
   `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` для всех колонок,
   что в SQLite добавляются по PRAGMA. Кладёт `closing_odds`, `clv`,
   `league_id`, `market_category` в `prediction_outcomes` и
   `subscription_expired_notified_at` в `users` без ручных миграций.
7. **`requirements.txt`** — добавлен `asyncpg>=0.29.0`. SQLAlchemy 2 async
   уже в комплекте; смена `DATABASE_URL` на
   `postgresql+asyncpg://...` достаточна для перехода.

### P0 — Источники данных (skeletons + тесты)

8. **`services/understat_client.py`** — парсер understat.com:
   - Лиги: EPL / La_liga / Bundesliga / Serie_A / Ligue_1 / RFPL.
   - `list_matches(league, season)` — расписание + xG завершённых.
   - `match_shots(match_id)` — детальный shotsData.
   - JS-парсер регуляркой по `var X = JSON.parse('...')`,
     unicode-escape декодирование.
   - Свой rate-limiter (1 req / 2s по умолчанию), кэш через любой
     объект с `get/set` (совместимо с `APICache` и `KVCache`).
   - 12 юнит-тестов (`tests/test_understat_client.py`), включая
     end-to-end через локальный aiohttp web-сервер.
9. **`services/betfair_client.py`** — скелет Betfair Exchange API:
   - Login: interactive (login/password) + non-interactive (mTLS-cert).
   - JSON-RPC: `listEventTypes`, `listEvents`, `listMarketCatalogue`,
     `listMarketBook`. Достаточно для CLV-трекера.
   - Logout + keepAlive.
   - 7 юнит-тестов (`tests/test_betfair_client.py`) через локальный
     aiohttp-stub: успешный login, отказ, RPC без логина, list_market_book.

### P0 — Rate-limiting

10. **`services/rate_limiter.py`** — расширен:
    - `RedisSlidingWindowLimiter` — distributed sliding window на Lua-скрипте
      (ZSET с timestamp'ами). Корректно работает между несколькими
      процессами/контейнерами.
    - `make_user_limiter(redis_client=...)` — фабрика, возвращает либо
      существующий `UserRateLimiter` (in-memory token bucket), либо
      адаптер поверх Redis. Drop-in замена для middleware.
    - 5 юнит-тестов (`tests/test_redis_rate_limiter.py`) на in-memory
      fake Redis.

### Конфиг

11. **`config.py`** — новые поля:
    - `redis_url: str | None`
    - `sentry_dsn: SecretStr | None`, `sentry_environment`,
      `sentry_traces_sample_rate`
    - `prometheus_port: int = 0`
    - `backup_dir`, `backup_retention_days`,
      `backup_s3_bucket`, `backup_s3_prefix`
12. **`.env.example`** — все новые опции задокументированы.

## Что НЕ вошло в эту сессию (вынесено в отдельные сессии)

- **Celery worker** — нужен реальный broker + рефакторинг loop'ов под task'и
  (2-3 дня).
- **football-data.co.uk бэктест** на 50K+ матчей — ETL + валидация (2-3 дня).
- **LightGBM stacking** — каркас в `services/stacking_model.py` уже есть;
  включится автоматически когда наберётся ≥1k размеченных пиков
  (сейчас ~50, ждём 2-4 недели).
- **Push-нотификации на line moves** — нужна продакшн-история линий
  (опирается на CLV-трекер из Betfair).
- **CLV-трекер** — следующий шаг поверх Betfair-клиента: cron за 5 мин
  до старта матча + сравнение `our_odds` vs Betfair closing.
- **Personal performance tracking** UI.

## Apgrade-инструкции

### С SQLite на Postgres

```bash
# 1. Поднять docker-compose.yml (Postgres+Redis+бот).
cp .env.example .env
# Заполнить BOT_TOKEN, ADMIN_IDS.
docker compose up -d --build postgres redis
# Дождаться healthy.
docker compose up -d bot

# 2. Если у тебя уже есть data/bot.db:
#    pgloader sqlite:///data/bot.db postgresql://ultrabet:ultrabet@localhost:5432/ultrabet
#    — это разовая миграция данных. После — soft-migrations подтянут
#    остальные колонки на старте бота.
```

### Включить Sentry

```bash
# В .env
SENTRY_DSN=https://your-public-key@o0.ingest.sentry.io/12345
SENTRY_ENVIRONMENT=production
SENTRY_TRACES_SAMPLE_RATE=0.05
docker compose restart bot
```

### Включить Prometheus

```bash
# В .env
PROMETHEUS_PORT=9108
# В docker-compose.yml порт уже проброшен.
docker compose restart bot
curl http://localhost:9108/metrics | head -20
```

### Запустить бэкапы

```bash
docker compose --profile backup up -d backup
# Дампы: docker compose exec backup ls /var/backups/ultrabet
# В S3 (опционально):
#   BACKUP_S3_BUCKET=ultrabet-backups в .env + AWS_ACCESS_KEY_ID/SECRET в .env.
```

## Верификация

- `ruff check .` — All checks passed.
- `pytest -q` — **651 passed** (было 617 + 34 новых).
- `docker build -t ultrabet:latest .` — собирается на python:3.11-slim
  без сетевых зависимостей кроме pip.

## Diff stats

| Файл | + / − |
|------|------:|
| `Dockerfile` | +49 / 0 |
| `docker-compose.yml` | +94 / 0 |
| `.dockerignore` | +18 / 0 |
| `services/observability.py` | +228 / 0 |
| `services/db_backup.py` | +209 / 0 |
| `scripts/backup_loop.py` | +73 / 0 |
| `services/understat_client.py` | +218 / 0 |
| `services/betfair_client.py` | +259 / 0 |
| `services/rate_limiter.py` | +127 / −1 |
| `db/database.py` | +29 / −7 |
| `config.py` | +24 / −1 |
| `main.py` | +12 / 0 |
| `requirements.txt` | +3 / 0 |
| `.env.example` | +33 / −0 |
| `tests/test_observability.py` | +91 / 0 |
| `tests/test_db_backup.py` | +93 / 0 |
| `tests/test_understat_client.py` | +211 / 0 |
| `tests/test_betfair_client.py` | +147 / 0 |
| `tests/test_redis_rate_limiter.py` | +95 / 0 |
| **Итого** | **+2013 / −9** |
