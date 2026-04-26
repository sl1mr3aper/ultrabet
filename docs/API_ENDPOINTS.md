# SStats API Endpoints — полный справочник

Все публичные методы SStats API, их параметры и использование в UltraBet.

## Аутентификация

Все запросы требуют заголовок `X-API-Key: {SSTATS_API_KEY}`.
Free-tier ключ `8s6v6vx563doosb7` имеет лимиты:
- 100 запросов в сутки,
- 50 запросов в час.

При превышении → 429 Too Many Requests.

## /Account

### GET /Account/Info
Возвращает информацию об аккаунте (план, оставшиеся запросы, ограничения).

**Клиент**: `await client.get_account_info()`  
**Где используется**: admin handler, проверка перед batch-операциями.

## /Leagues

### GET /Leagues
Список всех доступных лиг с мета-информацией (страна, сезон, id).

**Параметры**:
- `country_code` — фильтр по стране (ISO 3166 alpha-2)
- `only_active` — только активные сезоны (по умолчанию true)

**Клиент**: `await client.list_leagues(country_code=None, only_active=True)`  
**Где используется**: `/leagues` handler, `services.league_service`.

## /Games

### GET /Games/list
Список игр (prematch или live) с пагинацией и фильтрацией.

**Параметры**:
- `league_id` — ID лиги
- `date_from`, `date_to` — ISO 8601 даты
- `live` — только live (bool)
- `limit`, `offset` — пагинация

**Клиент**: `await client.list_games(league_id=..., date_from=..., live=False, limit=50)`  
**Где используется**: `services.match_finder`, `services.top_matches`.

### GET /Games/{game_id}
Подробная информация об одной игре: команды, дата, статус, счёт,
last-10 xG для каждой стороны.

**Клиент**: `await client.get_game(game_id)`  
**Где**: `bot.handlers.matches`, `predictions`.

### GET /Games/glicko/{game_id}
Вероятности исходов на основе Glicko-2 рейтингов команд.
Возвращает `{home_win, draw, away_win}` — сумма = 1.0.

**Клиент**: `await client.get_game_glicko(game_id)`  
**Где**: `services.prediction_service` (вход в ensemble).

### POST /Games/query
Поиск игр по имени команды (fuzzy search).

**Параметры body**: `{"query": "...", "limit": 20}`

**Клиент**: `await client.query_games(query="Real")`  
**Где**: `services.match_finder`.

### GET /Games/profits
Матчи, отсортированные по "прибыльности" модели (value_score × liquidity).

**Клиент**: `await client.get_profits(date=..., limit=30)`  
**Где**: `services.top_matches`, `/topmatches`.

### GET /Games/text-summary
Человекочитаемое описание матча (форма команд, last H2H, ключевые игроки).

**Клиент**: `await client.get_text_summary(game_id)`  
**Где**: `services.odds_parser`, `/matches` extras.

### GET /Games/last-games-stats
xG, xGA, корнеры, fouls и др. статистика последних N матчей каждой команды.

**Параметры**: `game_id`, `last=5`

**Клиент**: `await client.get_last_games_stats(game_id, last=5)`  
**Где**: `services.accuracy_boost`, `services.form_analyzer`.

### GET /Games/season-table
Актуальная турнирная таблица лиги.

**Параметры**: `league_id`, `season`

**Клиент**: `await client.get_season_table(league_id, season)`  
**Где**: `/standings` handler, `services.league_power`.

### GET /Games/injuries
Травмированные и дисквалифицированные игроки для предстоящего матча.

**Параметры**: `game_id`

**Клиент**: `await client.get_injuries(game_id)`  
**Где**: `services.accuracy_boost`, `/injuries` handler.

## /Odds

### GET /Odds/{game_id}
Prematch коэффициенты для матча.
Формат: `[{market: "home", bookmaker: "bet365", odds: 2.10}, ...]`.

**Клиент**: `await client.get_prematch_odds(game_id, markets=None)`  
**Где**: `services.odds_parser`.

### GET /Odds/live/{game_id}
Live-коэффициенты.

**Клиент**: `await client.get_live_odds(game_id)`  
**Где**: `services.live_monitor`.

### GET /Odds/live-changes/{game_id}
История изменений live-коэфов за последние 10 минут.

**Клиент**: `await client.get_live_changes(game_id)`  
**Где**: `services.live_monitor.diff_odds()`.

### GET /Odds/bookmakers
Список всех доступных букмекеров с логотипами и описанием.

**Клиент**: `await client.list_bookmakers()`  
**Где**: `/bookmakers` handler.

### GET /Odds/prematch-markets
Список всех prematch-рынков (home/away/draw, over/under, BTTS, ...).

**Клиент**: `await client.get_prematch_markets()`  
**Где**: `core.markets` (реестр).

### GET /Odds/live-markets
Список live-рынков.

**Клиент**: `await client.get_live_markets()`  
**Где**: `services.live_monitor`.

## /Teams

### GET /Teams/list
Список команд по лиге или стране.

**Клиент**: `await client.list_teams(league_id=..., country_code=...)`  
**Где**: `services.team_service`, `/teams`.

### GET /Teams/{team_id}
Подробная информация о команде: рейтинг, форма, текущий состав.

**Клиент**: `await client.get_team(team_id)`  
**Где**: `bot.handlers.teams`.

## /Players

### POST /Players/find
Поиск игроков по имени/команде/позиции.

**Клиент**: `await client.find_players(query="Ronaldo", team_id=None, position=None)`  
**Где**: `bot.handlers.players`.

### GET /Players/{player_id}
Подробная информация об игроке: статистика текущего сезона, позиция, фото.

**Клиент**: `await client.get_player(player_id)`  
**Где**: `/player_info` handler.

### GET /Players/{player_id}/events
События игрока: голы, ассисты, карточки, замены по сезону.

**Клиент**: `await client.get_player_events(player_id, season=...)`  
**Где**: `services.goalscorer`.

## /Seasons

### GET /Seasons/standings
Полная итоговая турнирная таблица (финальная или текущая).

**Параметры**: `league_id`, `season`.

**Клиент**: `await client.get_standings(league_id, season)`  
**Где**: `services.league_power`.

## Кэширование

Все GET-эндпоинты кэшируются по умолчанию:
- `/Leagues`: 24 часа (редко меняется).
- `/Games/list`: 5 минут для prematch, 30 сек для live.
- `/Games/{id}`: 10 минут.
- `/Odds/{id}`: 5 минут для prematch, 15 сек для live.
- `/Teams/{id}`, `/Players/{id}`: 24 часа.

Инвалидация:
- `api/cache.py` отдаёт `Cache` с ttl;
- явно обнуляется через `cache.invalidate_tag("game:{id}")` при записи
  результата матча админом.

## Обработка ошибок

- `APIError` — общий класс.
- `APIRateLimitError` — HTTP 429.
- `APITimeoutError` — TimeoutError.
- `APIForbiddenError` — HTTP 401/403.
- `APINotFoundError` — HTTP 404.
- `APIServerError` — 5xx.

См. `api/exceptions.py`.

## Retry-политика

Для retryable ошибок (`APITimeoutError`, `APIServerError`, `APIRateLimitError`):
- `max_attempts=3`
- `initial_delay=0.5s`, multiplier=2.0
- jitter ±25 %

См. `services/retry.py`.

## Circuit Breaker

Для защиты от SStats outage:
- `failure_threshold=5`
- `reset_timeout=60s`
- `half_open_max_calls=1`

При OPEN возвращает `CircuitBreakerError` немедленно, без запросов.
См. `services/circuit_breaker.py`.
