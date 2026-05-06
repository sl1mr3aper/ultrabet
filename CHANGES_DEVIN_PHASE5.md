# Phase 5 — wiring + UI + бэктест-инфра

Эта фаза — про подключение готовых компонентов в основной конвейер и
вывод метрик качества модели в UI. Никаких новых тяжёлых сервисов
(вроде Celery worker'ов или ETL на 50K матчей) сюда не входило —
только то, что можно сделать в одной сессии и сразу же подключить.

## Что добавлено

### 1. Wiring `UnderstatXgProvider` → `PredictionService.predict()`

**Файл:** `services/prediction_service.py` (+ `main.py`).

В `PredictionService.__init__` добавлен опциональный параметр
`understat_xg_provider: UnderstatXgProvider | None`.

В методе `predict()`, **до вызова** `build_predictions(...)`, провайдер
запрашивается:

```python
estimate = await self._understat_xg_provider.get_match_xg_estimate(
    home_team=to_understat(home["name"]),
    away_team=to_understat(away["name"]),
    league_slug=league_to_understat_slug(league_name),
    league_avg_total=_league_avg_total,
)
```

Если провайдер вернул валидную пару (≥3 завершённых матча у каждой
команды), ей перезаписываются `home_xg_api`/`away_xg_api`. В extra
проставляется флаг `understat_xg_used: True` — для аудита.

Имена команд нормализуются через `services.team_name_alias.to_understat`
(см. ниже).

**Тесты:** `tests/test_prediction_service_understat_wiring.py` — 3 теста:
- провайдер с данными → флаг проставлен, xG переписан
- провайдер без данных → флаг отсутствует
- провайдер не передан → обратная совместимость

### 2. `DynamicBetfairMarketResolver` через `listMarketCatalogue`

**Файл:** `services/clv_tracker.py`.

Раньше CLV-tracker умел только статический маппинг
`{(game_id, market_key) → BetfairMarketRef}`. Теперь добавлен динамический
резолвер, который:

1. Через `BetfairClient.list_events(textQuery="Home Away", ...)` находит
   `event_id` по фуззи-матчу имён команд + временного окна (±6 ч от
   старта матча по умолчанию).
2. Через `BetfairClient.list_market_catalogue(eventIds=[event_id], marketTypeCodes=[type], ...)`
   получает `marketId` и список `runners`.
3. По `runnerName` находит правильный `selectionId`:
   - **MATCH_ODDS**: matching по home/away имени или "The Draw"
   - **OVER_UNDER_25**: "Over 2.5 Goals" / "Under 2.5 Goals"
   - **BOTH_TEAMS_TO_SCORE**: "Yes" / "No"

Кэш `event_id` per `game_id` и `market_id` per `(event_id, market_type)`
— чтобы не дёргать API повторно.

Зависимость на внешний `match_lookup: callable(game_id) -> (home, away,
start_dt) | None` — так резолвер не привязан к конкретной таблице.

**Тесты:** `tests/test_betfair_dynamic_resolver.py` — 8 тестов:
- 1×2 home, totals, btts — корректный selection
- неизвестный market_key → None
- нет event_id match → None
- кэш event_id (повторный вызов не дёргает API)
- match_lookup вернул None → None
- time_window корректно проброшен в фильтр

### 3. `services/team_name_alias.py` — кросс-источный маппинг команд/лиг

Источники называют команды по-разному:

| Источник | Манчестер Юнайтед | Атлетико Мадрид | ПСЖ |
|---|---|---|---|
| SStats | `Manchester United` | `Atletico Madrid` | `Paris Saint-Germain` |
| Understat | `Manchester United` | `Atletico Madrid` | `Paris Saint Germain` |
| FDC csv | `Man United` | `Ath Madrid` | `Paris SG` |

Модуль предоставляет:

- `normalize(name)` — канонический ключ (lowercase, без префиксов
  FC/AFC/CF, без диакритики, без не-alphanum). Используется как ключ
  в lookup'ах.
- `to_understat(sstats_name)` — имя в стиле Understat (fallback: исходное)
- `to_fdc(sstats_name)` — имя в стиле football-data.co.uk
- `league_to_understat_slug(league_name)` — `Premier League → "EPL"`,
  `La Liga → "La_liga"`, и т.д.
- `league_to_fdc_code(league_name)` — `Premier League → "E0"`,
  `Bundesliga → "D1"`, и т.д.

База алиасов — топ-50 европейских клубов из 5 топ-лиг + РПЛ (зашита в
код). Расширение через внешнюю таблицу — задача отдельной сессии,
сейчас покрытие достаточно для топ-лиг.

**Тесты:** `tests/test_team_name_alias.py` — 51 тест:
- normalize() с диакритикой, апострофами, префиксами
- to_understat/to_fdc для топ-клубов EPL/La Liga/Bundesliga/Serie A/Ligue 1
- league_to_understat_slug / league_to_fdc_code для всех топ-лиг
- fallback на исходное имя при unknown

### 4. `services/backtest_service.py` — Brier/ROI/CLV над `prediction_outcomes`

Новый сервис, который агрегирует метрики качества модели:

- **Brier score** = mean((p − y)²) — calibration + sharpness; baseline 0.25.
- **ROI%** = sum(profit_per_pick) / n_picks · 100% — финансовая метрика.
  По умолчанию учитывает только пики где `prob × actual_odds > 1`
  (EV+); опционально — все.
- **avg CLV** = mean(prob × closing_odds − 1) — проверяет, бьём ли мы
  closing line.
- **positive_clv_rate** — доля пиков с CLV > 0.
- **hit_rate** — доля сыгравших пиков.

Возвращает `BacktestMetrics` (dataclass со всеми полями + флаг `is_empty`).

API:
- `BacktestService(session_factory).run(league_id, market_category, market_key, period_from, period_to, only_ev_plus)` → общие метрики
- `BacktestService.by_league(period_from, period_to)` → `{league_id: BacktestMetrics}`
- `BacktestService.by_market(period_from, period_to)` → `{market_category: BacktestMetrics}`

**Тесты:** `tests/test_backtest_service.py` — 10 тестов:
- пустая выборка → `is_empty=True`
- Brier и hit_rate (4 пика, 2/4 hit, prob=0.7/0.4)
- ROI с/без EV-фильтра
- CLV агрегация (3 пика с разными CLV)
- фильтры по league_id/market_category/market_key/period
- группировка by_league / by_market

### 5. UI: «📈 Точность модели» в `/admin`

**Файлы:** `bot/keyboards.py`, `bot/handlers/admin.py`, `bot/texts.py`.

Третья кнопка в админ-меню (после «Массовый анализ» и «Анализ
прогнозов»). Открывает сводку:

```
📈 Точность модели

Всего пиков в БД: 248
С исходом (settled): 213
С actual_odds: 198 · С closing_odds: 145

Все пики:
  hit_rate = 64.2%
  Brier = 0.1845  (baseline 0.25)
  ROI = +6.34%
  CLV avg = +1.23%
  CLV>0 rate = 58.6%

Только EV+ (prob × odds > 1):
  пиков = 102
  hit_rate = 71.5%
  Brier = 0.1521
  ROI = +14.20%

По типу рынка:
  1x2        n=120  hit=58.3%  Brier=0.2143  ROI=+4.10%
  totals     n= 71  hit=70.4%  Brier=0.1654  ROI=+9.20%
  btts       n= 22  hit=63.6%  Brier=0.1820  ROI=+5.80%
```

Если в `prediction_outcomes` нет данных — выводится подсказка.

## Тесты

| До Phase 5 | После Phase 5 |
|---|---|
| 684 passed, 1 skipped | **756 passed, 1 skipped** |

Прибавка: **72 новых теста** (3 + 8 + 51 + 10).

Всё зелёное; `ruff check .` без замечаний.

## Удалена терминология «валуй»

В предыдущей сессии (по просьбе пользователя «вообще в корне убери
валуй») заменено 117 вхождений в 39 файлах: docstrings, UI-строки,
i18n переводы (Ukrainian, Kazakh), документация. Заменены на «EV»,
«EV-ставки», «+EV» — в зависимости от контекста.

## Не вошло в эту фазу

- **Wiring Celery в production** (отключение asyncio-loop'ов в
  `main.py` и регистрация задач): 4 ч. Скелет (`services/celery_app.py`,
  `services/tasks.py`, docker-compose `--profile worker`) уже готов.
- **Push-нотификации на line moves**: 1 день. Нужен production line
  history.
- **Personal performance tracking** (ROI/Sharpe per user UI): 1 день.
- **Бэктест над football-data 50K матчей**: 2 дня. Loader готов
  (`services/football_data_loader.py`), нужен ETL-пайплайн и UI отчёта.
- **LightGBM stacking ensemble**: 3 дня **+ блок**: нужно ≥1k размеченных
  пиков, у нас сейчас ~50–80.

## Файлы (новые)

```
services/team_name_alias.py            (271 строка)
services/backtest_service.py           (218 строк)
tests/test_prediction_service_understat_wiring.py  (164 строки)
tests/test_betfair_dynamic_resolver.py             (192 строки)
tests/test_team_name_alias.py                      (123 строки)
tests/test_backtest_service.py                     (185 строк)
CHANGES_DEVIN_PHASE5.md                            (этот файл)
```

## Файлы (изменены)

```
services/prediction_service.py     +43 строки  (Understat wiring)
services/clv_tracker.py            +228 строк  (DynamicBetfairMarketResolver)
main.py                            +9 строк    (instantiate провайдер)
bot/keyboards.py                   +6 строк    (новая кнопка)
bot/texts.py                       +1 строка   (ADMIN_MODEL_ACCURACY)
bot/handlers/admin.py              +93 строки  (handler model_accuracy)
```

## Примеры использования

### BacktestService — программный доступ

```python
from services.backtest_service import BacktestService

svc = BacktestService(session_factory=database.session_factory)

# Общие метрики за последние 30 дней
metrics = await svc.run(period_from=now - timedelta(days=30))
print(f"Brier={metrics.brier_score:.4f}, ROI={metrics.roi_pct:+.2f}%")

# По лигам
by_league = await svc.by_league()
for league_id, m in sorted(by_league.items(), key=lambda kv: -kv[1].n_picks):
    print(f"League {league_id}: {m.n_picks} picks, hit={m.hit_rate}")
```

### DynamicBetfairMarketResolver — production CLV pipeline

```python
async def match_lookup(game_id: int):
    async with session_factory() as s:
        row = await s.get(MatchPickHistory, game_id)
        if not row:
            return None
        return (row.home_name, row.away_name, row.match_datetime)

resolver = DynamicBetfairMarketResolver(
    betfair=betfair_client,
    match_lookup=match_lookup,
    time_window_hours=6,
)
tracker = ClvTracker(
    session_factory=session_factory,
    betfair=betfair_client,
    resolver=resolver,
)
await tracker.capture_pending_closes(concurrency=4)
```
