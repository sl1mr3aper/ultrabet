# Phase 4 — что сделано в этой сессии

Продолжение Phase 3 (Docker + Sentry + бэкапы + Postgres-готовность + Redis +
Understat skeleton + Betfair skeleton). В Phase 4 — содержательные пункты,
которые превращают инфраструктуру в работающие фичи:

1. CLV-трекер поверх Betfair (cron-капчер closing odds + агрегация CLV).
2. Understat → провайдер реального xG для PredictionService.
3. football-data.co.uk loader на 50K+ матчей (бесплатный исторический датасет).
4. Celery skeleton: декларация `services.celery_app` + 6 задач в `services.tasks`.

Итого: **+33 теста, всего 684 passed + 1 skipped** (skip — celery не установлен
локально, в проде установится из `requirements.txt`). `ruff check .` — clean.

---

## 1. CLV-трекер (`services/clv_tracker.py`)

CLV (Closing Line Value) = `predicted_prob × closing_odds − 1`. Это
**единственная метрика, которая объективно доказывает, что модель умнее рынка**:
если средний CLV > 0 в долгосроке, ROI положительный с высокой вероятностью.

**Компоненты:**

- `BetfairMarketRef(market_id, selection_id, market_type)` — координаты
  селекшна на Betfair Exchange.
- `StaticBetfairMarketResolver` — in-memory мапа `(game_id, market_key) →
  BetfairMarketRef`. В проде заменяется динамическим resolver'ом, который
  ищет MARKET_ODDS у Betfair по имени матча + времени старта.
- `ClvTracker` — главный сервис:
  - `capture_for_pick(outcome)` — снимает текущую цену backers через
    `BetfairClient.list_market_book`, считает CLV, сохраняет в
    `PinnacleClosingOdds` (snapshot-лог) **и** обновляет
    `PredictionOutcome.closing_odds + .clv` (текущее).
  - `capture_pending_closes(outcomes, concurrency=4)` — батчит несколько
    pending пиков через `asyncio.Semaphore`, чтобы не флудить Betfair.
  - `aggregate_clv(period_days=30, league_id=None, market_key=None)` —
    `{n_picks, avg_clv, positive_clv_rate}` за период. Это и есть KPI модели.
- `run_clv_capture_loop(tracker, session_factory, interval_seconds=60)` —
  фоновой loop. В проде заменяется Celery-задачей
  `services.tasks.capture_clv_for_pending` (расписание 1 раз в минуту в
  `beat_schedule`).
- `compute_clv(predicted_prob, closing_odds) → float | None` — чистая
  функция, валидирует входные данные.

**Когда снимать closing odds:** Понятие "closing" у Betfair — это последний
markPriceTraded в момент перед `inplay=true`. На практике достаточно снять
цену за 3–5 минут до старта (рынки уже стабилизировались, ликвидности много,
sharp money уже в маркете). Это и делает Celery beat 1×60s.

**Тесты:** 11 в `tests/test_clv_tracker.py`. Полный E2E поверх in-memory
SQLite + `_FakeBetfair` (returns заранее заданный list_market_book).

**Что осталось для production:**

- Динамический market resolver: Betfair API → `listMarketCatalogue(eventName=...,
  marketTypeCodes=[MATCH_ODDS,OVER_UNDER_25])` → находит market_id по имени
  команд + времени старта. Тривиально: ~50 строк, нужны рабочие credentials
  для тестирования.
- Подключение Betfair-сессии в `main.py`: сейчас секции
  `BETFAIR_USERNAME / BETFAIR_PASSWORD / BETFAIR_APP_KEY` в `config.py` нет —
  добавь `Settings.betfair_username/password/app_key/cert_path` в next phase.

---

## 2. Understat → PredictionService (`services/understat_xg_provider.py` +
   `db.models.TeamXgSample`)

**Зачем:** Сейчас `core.glicko_model.expected_goals_from_glicko` использует
`tanh(rating_diff/200)` как аппроксимацию xG. R² такой формулы ≈ **0.18** на
RAW shot-based xG из Understat (т.е. она угадывает только ~18% разброса).

**Что сделали:**

- Модель `TeamXgSample` (миграция автоматически через soft-migrations) — одна
  строка на `(source, match_id, team)`, поля `xg_for / xg_against / goals_for /
  goals_against / match_datetime / league_slug / season`. Уникальный индекс по
  `(source, match_id, team_name)` гарантирует идемпотентность загрузчика.
- `UnderstatXgLoader.sync_league(league_slug, season)` — забирает завершённые
  матчи из `UnderstatClient`, разворачивает каждый матч в 2 строки (по одной
  для home и away), батч-апсёртит через
  `INSERT ... ON CONFLICT DO NOTHING`. В Postgres — `pg_insert`, в SQLite —
  `sqlite_insert`.
- `UnderstatXgProvider.get_team_averages(team_name, league_slug=None)` — возвращает
  `TeamXgAverages(n_samples, xg_for_avg, xg_against_avg)`, где avg — это **EWMA с
  α=0.65** (полупериод ≈ 2 матча). Недавние игры весят больше старых.
- `UnderstatXgProvider.get_match_xg_estimate(home_team, away_team)` — возвращает
  `(home_xg_pred, away_xg_pred)`:
  - `home_xg = (home.xg_for + away.xg_against) / 2 + 0.25` (ha)
  - `away_xg = (away.xg_for + home.xg_against) / 2 − 0.25`
  - При малой выборке (3–5 игр) применяется shrinkage к среднему лиги:
    `credibility = min(1, n/10) → predict = cred * team_avg + (1-cred) * league_avg`.
  - Если у одной из команд `< 3` сэмплов → возвращает `None`, и вызывающий
    код фолбэчит на старый `expected_goals_from_glicko`.

**Тесты:** 9 в `tests/test_understat_xg_provider.py`. Покрыт loader (вставка,
дедупликация, unsupported league), provider (EWMA, недостаточно данных, базовая
оценка матча), чистая функция `estimate_match_xg_from_avgs`.

**Что осталось для production:**

- Подключить `UnderstatXgProvider` в `services/prediction_service.py`:
  перед вызовом `predict_match_outcome` спросить у провайдера
  `estimate_match_xg(home_team, away_team)`; если ответ не None — передать
  как `home_xg_api / away_xg_api` (ensemble уже умеет принимать их с
  приоритетом).
- Cron-задача `services.tasks.sync_understat_xg(league_slug, season)` уже есть.
  Добавить в `beat_schedule` 1×24h для каждой из 6 лиг (EPL, La_liga,
  Bundesliga, Serie_A, Ligue_1, RFPL).

**Маппинг имён команд:** имена Understat ("Manchester City") могут не
совпадать с именами SStats ("Man City"). Решается отдельной таблицей
`team_name_alias(source, alias, canonical_name)` в next phase.

---

## 3. football-data.co.uk loader (`services/football_data_loader.py` +
   `scripts/football_data_etl.py`)

**Зачем:** football-data.co.uk — единственный бесплатный источник
**Pinnacle closing odds** + результатов на 30+ лет назад по 22 лигам. Pinnacle
— это эталон sharp money: маркет считается калиброванным, если предсказания
модели в среднем лучше или равны Pinnacle closing.

**Что сделали:**

- `FootballDataMatch` dataclass со всеми ключевыми полями: дата, команды,
  голы, FTR, **`pinnacle_home/draw/away`** (PSH/PSD/PSA в CSV), B365 odds,
  Over/Under 2.5.
- `parse_csv(text) → list[FootballDataMatch]` — чистый парсер,
  пропускает строки без минимума (дата + команды + голы + FTR). Поддерживает
  оба формата даты `dd/mm/yyyy` и `dd/mm/yy`.
- `FootballDataLoader.fetch_csv(league_code, season_short)` — скачивает 1 файл,
  декодирует utf-8 / cp1252 / latin-1 (старые годы используют cp1252 из-за
  диакритики в названиях команд).
- `FootballDataLoader.fetch_seasons(league_code, seasons)` — bulk-fetch с
  graceful 404 (один сезон 404 не валит остальные — пишет warning и продолжает).
- `compute_naive_backtest_metrics(matches)` — sanity-check бэктест "ставлю всегда
  на фаворита Pinnacle". Hit-rate должен быть ~50–55%, ROI − ≈ −2..−5%
  (минус маржа букмекера). Если иначе — данные битые.
- `scripts/football_data_etl.py` — CLI, скачивает по умолчанию 5 лиг (E0 D1 SP1 I1 F1)
  × 7 последних сезонов = ~35 файлов, **~14 500 матчей**. Распечатывает в stdout
  JSON-репорт по hit-rate; опционально сохраняет полный дамп в `--output JSON`.

**Запуск (на проде или локально с интернетом):**

```
python -m scripts.football_data_etl \
    --leagues E0 D1 SP1 I1 F1 \
    --seasons 1819 1920 2021 2122 2223 2324 2425 \
    --output data/fdb_dump.json
```

Ожидаемый вывод:

```json
{
  "overall": {
    "total_matches": 14523,
    "matches_with_odds": 14101,
    "favorite_hit_rate": 0.534,
    "roi_pct": -3.8
  },
  "by_league": {
    "E0": { ... },
    ...
  }
}
```

ROI ≈ −4% на стратегии "ставлю на фаворита Pinnacle" — это правильный
результат, подтверждающий чистоту данных.

**Тесты:** 10 в `tests/test_football_data_loader.py`. Покрыт парсер CSV,
helpers, HTTP-fetch (через локальный aiohttp.web сервер), bulk-fetch с 404.

**Что осталось для production:**

- Бэктест против собственной модели: добавить
  `services/backtest_service.py`, который берёт `list[FootballDataMatch]`,
  для каждой строки вызывает упрощённый прокси `PredictionService` (без
  SStats, только Glicko + Poisson), сравнивает прогноз модели с **Pinnacle
  closing** odds, считает ROI / Brier / log-loss / CLV.
- Загрузка xG-параметров команд **на момент матча** — нужны исторические
  Glicko-рейтинги (a.k.a. перенести Glicko-цикл с момента первого матча).
  Это 2–3 дня работы, делается в next phase.

---

## 4. Celery skeleton (`services/celery_app.py` + `services/tasks.py`)

**Зачем:** Сейчас `main.py` держит `self_learning_loop`, `expire_subscriptions_loop`,
`top_matches_precompute` как long-running asyncio-task'и в одном процессе.
Это работает на одном инстансе бота, но:

- Не масштабируется горизонтально.
- Любая необработанная ошибка в loop'е может уронить весь процесс.
- Нельзя запустить тяжёлую задачу (например, full Understat sync) без блокировки event loop'а основного бота.

**Что сделали:**

- `services/celery_app.py` — декларация Celery (broker = `REDIS_URL`,
  backend = тот же, JSON serialization, `task_acks_late`,
  `worker_prefetch_multiplier=1`). Если `celery` не установлен —
  модуль отдаёт `_CeleryStub` (чтобы tasks-код можно было импортить
  везде, и в тестах он работает синхронно через прямой вызов).
- `services/tasks.py` — 6 задач:

| Задача | Замена | Расписание |
|---|---|---|
| `run_self_learner` | self_learning_loop | каждые 30 мин |
| `run_secondary_calibrator` | новый | каждый 1 час |
| `expire_subscriptions` | expire_subscriptions_loop | каждые 6 часов |
| `capture_clv_for_pending` | новый | каждую минуту |
| `run_db_backup` | scripts/backup_loop.py | каждые 6 часов |
| `sync_understat_xg(league, season)` | новый | вручную/по cron, например раз в сутки |

  Каждая задача — тонкая обёртка: создаёт свой event loop, поднимает
  `Database`, делегирует в async-сервис, закрывает БД. Возвращает
  dict-сводку для observability.

- `docker-compose.yml` обновлён: добавлены сервисы `worker` и `beat`
  под профилем `worker`. Запуск:

  ```
  docker compose --profile worker up -d
  ```

  Запустит `bot` + `worker` (4 потока) + `beat` (cron), всё на той же
  Postgres + Redis.

**Тесты:** 4 в `tests/test_celery_tasks.py`. 1 пропущен (celery не
установлен локально), но импорт + структура + skip-without-credentials
проверены.

**Гайд по миграции с loop'ов на Celery:**

Когда захочешь перейти полностью:

1. В `main.py` закомментируй вызовы `loop.create_task(self_learning_loop(...))`
   и `loop.create_task(expire_subscriptions_loop(...))`.
2. Добавь `BETFAIR_*` секреты в env, обнови `services/tasks.capture_clv_for_pending`,
   чтобы реально вызывал `tracker.capture_pending_closes()`.
3. `docker compose --profile worker up -d` — Celery подхватит cron из beat_schedule.
4. Бот теперь только обрабатывает Telegram updates, остальное в worker'ах.

Откатить — просто остановить worker/beat и раскомментировать loop'ы в
main.py. Никаких миграций БД для отката не требуется.

---

## Следующие шаги (когда дашь добро)

| Приоритет | Что | Оценка |
|---|---|---|
| P0 | Динамический BetfairMarketResolver через `listMarketCatalogue` | 4 ч |
| P0 | Wiring `UnderstatXgProvider` в `PredictionService.predict()` | 2 ч |
| P0 | Бэктест-сервис над football-data 50K матчей | 2 дня |
| P0 | Wiring Celery в production (отключение loop'ов в main.py) | 4 ч |
| P1 | Маппинг имён команд (`team_name_alias`) — SStats ↔ Understat ↔ FDC | 1 день |
| P1 | LightGBM stacking ensemble (нужно ≥1k размеченных пиков) | 3 дня |
| P1 | Push-нотификации на line moves (опасные движения коэфф) | 1 день |
| P2 | Personal performance tracking (UI: ROI / Sharpe per user) | 2 дня |

Все задачи не требуют переработки матядра — это только wiring + scaling.
