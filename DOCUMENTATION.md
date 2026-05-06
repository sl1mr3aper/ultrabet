# UltraBet — Полная техническая документация

Telegram-бот для футбольных прогнозов на базе SStats API + ансамбль
Glicko-2 / Poisson / Monte-Carlo / value-анализ.

## 1. Архитектура

```
main.py (entrypoint)
   │
   ├── config.py            — конфигурация через env
   ├── api/                 — async клиент SStats, кэш, исключения
   ├── core/                — математические модели (Glicko/Poisson/ensemble)
   ├── services/            — бизнес-логика (prediction, value, analytics, ...)
   ├── bot/                 — aiogram 3 (handlers, keyboards, FSM, styles)
   ├── db/                  — SQLAlchemy async + SQLite
   └── utils/               — логирование
```

Потоки данных:

```
User → aiogram Dispatcher → Router → Handler
                                         │
                                         ├──→ SStatsClient (api/)
                                         │         │
                                         │         └──→ Cache (api/cache.py)
                                         │
                                         ├──→ PredictionService
                                         │         │
                                         │         ├──→ GlickoModel
                                         │         ├──→ PoissonModel
                                         │         └──→ Ensemble + Value
                                         │
                                         └──→ Formatters → Markdown → User
```

## 2. SStats API — карта эндпоинтов

| Эндпоинт | Метод клиента | Где используется |
|---|---|---|
| `GET /Account/Info` | `get_account_info` | `services.odds_parser`, `bot.handlers.admin` |
| `GET /Leagues` | `list_leagues` | `services.league_service`, `bot.handlers.leagues` |
| `GET /Games/list` | `list_games` | `services.match_finder`, `services.top_matches`, `services.live_monitor` |
| `GET /Games/{id}` | `get_game` | `bot.handlers.matches`, `bot.handlers.predictions` |
| `GET /Games/glicko/{id}` | `get_game_glicko` | `services.prediction_service` (ансамбль) |
| `POST /Games/query` | `query_games` | `services.match_finder` (поиск по командам) |
| `GET /Games/profits` | `get_profits` | `services.top_matches` (сортировка по профиту) |
| `GET /Games/text-summary` | `get_text_summary` | `services.odds_parser`, handlers extras |
| `GET /Games/last-games-stats` | `get_last_games_stats` | `services.accuracy_boost`, `services.form_analyzer` |
| `GET /Games/season-table` | `get_season_table` | `bot.handlers.extras.standings_for`, `services.league_power` |
| `GET /Games/injuries` | `get_injuries` | `services.accuracy_boost`, `bot.handlers.extras.injuries` |
| `GET /Odds/{id}` | `get_prematch_odds` | `services.odds_parser`, handlers |
| `GET /Odds/live/{id}` | `get_live_odds` | `services.live_monitor`, handlers extras |
| `GET /Odds/live-changes/{id}` | `get_live_changes` | `services.live_monitor` (diff) |
| `GET /Odds/bookmakers` | `list_bookmakers` | `bot.handlers.extras.bookmakers` |
| `GET /Odds/prematch-markets` | `get_prematch_markets` | `core.markets` (market registry) |
| `GET /Odds/live-markets` | `get_live_markets` | `services.live_monitor` |
| `GET /Teams/list` | `list_teams` | `services.team_service`, handlers teams |
| `GET /Teams/{id}` | `get_team` | `bot.handlers.teams` |
| `POST /Players/find` | `find_players` | `bot.handlers.players` |
| `GET /Players/{id}` | `get_player` | `bot.handlers.players` |
| `GET /Players/{id}/events` | `get_player_events` | `services.goalscorer` |
| `GET /Seasons/standings` | `get_standings` | `services.league_power` |

Все методы клиента обёрнуты в `@retry`, `@cache` и `@error_translate`,
так что handler-уровень не должен писать бойлерплейт.

## 3. Ключевые сервисы

### 3.1 PredictionService

Строит итоговую вероятность исходов:
1. Получает `Games/glicko/{id}` → сырые вероятности Glicko.
2. Получает `last-games-stats` → xG для каждой команды.
3. Вычисляет Poisson-матрицу на основе xG.
4. Комбинирует Glicko+Poisson через `Ensemble.combine()`:
   `p = 0.6 × Poisson + 0.4 × Glicko`.
5. Применяет `AccuracyBoost`:
   - Травмы ключевых игроков → −40 к Glicko рейтингу команды.
   - Форма за 5 игр → ±15% к xG.
   - Позиция в таблице → ±30 к Glicko.
6. Получает `Odds/{id}` → prematch coefs.
7. Считает `ValueBet` для каждого рынка:
   `fair = 1/p`, `value_pct = (p × odds - 1) × 100`.
8. Сортирует ставки по `value_percent DESC`, возвращает топ-5.

### 3.2 AnalyticsService

Хранит `PredictionTick` для каждой сделанной ставки (без необходимости в БД
на первом этапе). Агрегирует:
- total/settled/won/lost
- hit_rate_pct, ROI_pct, avg_value_pct, avg_odds
- best_streak/worst_streak
- markets_breakdown (топ-10 рынков по количеству)

Доступна через `/admin_analytics` админу.

### 3.3 Strategy (services/strategy.py)

4 предустановленные стратегии:
| Стратегия | prob | odds | EV | top-N |
|---|---|---|---|---|
| Conservative | ≥55% | 1.25–2.20 | ≥2% | 5 |
| Balanced | ≥35% | 1.50–4.50 | ≥5% | 5 |
| Aggressive | ≥18% | 3.00–15 | ≥8% | 5 |
| Underdog | ≥10% | 4.00–30 | ≥15% | 3 |

`/strategy` позволяет пользователю выбрать. Выбор хранится в
`PreferenceStore.strategy`.

### 3.4 BankrollManagement (services/bankroll.py)

Ставки на основе:
- **Flat** — фиксированная сумма.
- **Percent** — фиксированный % от банка.
- **Kelly / Half-Kelly / Quarter-Kelly** — математически оптимальный, с дроблением.
- **Martingale** — удвоение после проигрыша.
- **Anti-Martingale** — удвоение после выигрыша.

Cap на max_fraction (10% по умолчанию) защищает от ruin.

### 3.5 Arbitrage (services/arbitrage.py)

Поиск surebet-ов:
- **2-way**: 1/o₁ + 1/o₂ < 1 → profit = 1/margin - 1.
- **3-way (1x2)**: 1/o_home + 1/o_draw + 1/o_away < 1.

Возвращает:
- `is_arb: bool`
- `margin: float` (<1 значит арб)
- `profit_percent: float`
- `allocation: dict[str, float]` (доля банка на каждый исход).

### 3.6 Parlay (services/parlay.py)

Экспресс-калькулятор:
- `total_odds = ∏ odds_i`
- `combined_probability = ∏ prob_i`
- `fair_total_odds = 1 / combined_probability`
- `value_percent = (combined × total_odds - 1) × 100`

Риск-классификация по total_odds (низкий → умеренный → высокий → экстремальный).

### 3.7 Simulation (Monte-Carlo)

`simulate(home_xg, away_xg, n_runs=5000)` выдаёт:
- home_win/draw/away_win (%),
- BTTS, Over 1.5 / 2.5 (%),
- avg_total_goals, avg_home/away_goals,
- top-10 score_distribution.

Используется как «второй взгляд» на analytical Poisson (см. `compare_with_analytical`).

## 4. Пагинация

Все списки >5 элементов используют `bot.pagination`:
```python
page: Page[T] = Page(items=items, page_index=idx, page_size=N)
text = format_paginated(page, render_item=render_row, header_text=header, footer_text=footer)
kb = pagination_keyboard(page, callback_prefix="matches_page_today")
```

Размеры страниц:
| Раздел | Размер |
|---|---|
| Лиги | 8 |
| Матчи сегодня/завтра/live | 10 |
| Top-matches (Games/profits) | 8 |
| Daily picks | 5 |
| H2H история | 5 |
| Injuries | 8 |
| Bookmakers | 15 |
| Odds | 12 |
| Standings | 10 |

## 5. Unified Markdown

Единый стиль через `bot/styles.py`:
- Иконки: ICON_WIN, ICON_FIRE, ICON_CHART, ICON_TARGET, ICON_SWORDS, ...
- Хелперы: `header(text, icon)`, `divider()`, `status_ok/error/warning()`.
- Форматирование цифр: `fmt_pct(0.1234)` → "12.34%".

## 6. Error handling

`services/error_translator.py`:
- `translate(exc)` → `TranslatedError(kind, user_message, technical, retryable)`.
- Типы ошибок: timeout, rate_limit, not_found, server, network, generic.

`ErrorMiddleware` вызывает `translate()` для всех исключений handler-ов
и отвечает user_message пользователю.

## 7. EV сортировка

В каждом сообщении с прогнозом:
```
Фаворит: Реал (p=54.3%)
Fair odds: 1.84
Coef (bet365): 2.10
Value: +14.0% 🔥
```

Все список value_bets сортируются `ORDER BY value_percent DESC`.

## 8. Testing & CI

Все тесты запускаются `make test` (pytest, pytest-asyncio).
309+ тестов покрывают:
- math models (Glicko, Poisson, ensemble)
- services (analytics, reports, simulation, goalscorer, ...)
- utilities (pagination, formatters, cache_store, rate_limiter)

CI через `.github/workflows/ci.yml`:
1. ruff check
2. mypy (в continue-on-error пока dev)
3. pytest

## 9. Deployment

- SQLite по умолчанию. PostgreSQL можно включить через `DATABASE_URL`.
- Redis опционально для внешнего кэша.
- Docker-compose готов (см. `docs/DEPLOYMENT.md`).

## 10. Лицензии и зависимости

- aiogram 3
- aiohttp
- SQLAlchemy async
- loguru
- pytest + pytest-asyncio
- ruff, mypy (dev)

Никаких зависимостей на веб-фреймворки, PyTorch, LightGBM и пр. тяжёлое —
только чистый Python + математика.

## 11. Будущие расширения

- [ ] Реальная БД для analytics (сейчас in-memory).
- [ ] REST-прокси для доступа к прогнозам через API.
- [ ] Grafana dashboard через `WebhookPublisher`.
- [ ] ML-бустинг (XGBoost / LightGBM) поверх ансамбля (опционально).
- [ ] Кабинет админа в Telegram (полноценный CRUD подписок).
