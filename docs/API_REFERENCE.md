# Справочник по SStats.net API

Полный список эндпоинтов, которые использует UltraBet, с указанием обёрток в `api/sstats_client.py`.

> Базовый URL: `https://api.sstats.net`. Аутентификация — заголовок `X-Api-Key` (опциональный, увеличивает квоту).

## Account

| HTTP | Endpoint | Метод клиента |
|------|----------|----------------|
| GET  | `/Account/Info` | `account_info()` |

## Leagues

| HTTP | Endpoint | Метод клиента |
|------|----------|----------------|
| GET  | `/Leagues` | `list_leagues()` |

## Games

| HTTP | Endpoint | Метод клиента |
|------|----------|----------------|
| GET  | `/Games/list` | `list_games(...)` |
| GET  | `/Games/{id}` | `get_game(id)` |
| GET  | `/Games/glicko/{id}` | `get_glicko(id)` |
| POST | `/Games/query` | `query_games(body)` |
| GET  | `/Games/profits` | `get_profits(...)` |
| GET  | `/Games/text-summary` | `text_summary(id)` |
| GET  | `/Games/last-games-stats` | `last_games_stats(id)` |
| GET  | `/Games/season-table` | `season_table(...)` |
| GET  | `/Games/injuries` | `injuries(id)` |

## Odds

| HTTP | Endpoint | Метод клиента |
|------|----------|----------------|
| GET  | `/Odds/{id}` | `get_odds(id, opening=...)` |
| GET  | `/Odds/live/{id}` | `get_live_odds(id)` |
| GET  | `/Odds/live-changes/{id}` | `get_live_odds_changes(id)` |
| GET  | `/Odds/bookmakers` | `list_bookmakers()` |
| GET  | `/Odds/prematch-markets` | `list_prematch_markets()` |
| GET  | `/Odds/live-markets` | `list_live_markets()` |

## Teams / Players

| HTTP | Endpoint | Метод клиента |
|------|----------|----------------|
| GET  | `/Teams/list` | `search_teams(name)` |
| GET  | `/Teams/{id}` | `get_team(id)` |
| GET  | `/Players/find` | `find_players(name)` |
| GET  | `/Players/{id}` | `get_player(id)` |
| GET  | `/Players/{id}/events` | `get_player_events(id)` |

## Seasons / Lightweight

| HTTP | Endpoint | Метод клиента |
|------|----------|----------------|
| GET  | `/Seasons/standings` | `get_standings(season_uid)` |
| GET  | `/Ls/List` | `ls_list()` |
| GET  | `/Ls/Teams` | `ls_teams(...)` |
| GET  | `/Ls/Leagues` | `ls_leagues(...)` |
| GET  | `/Ls/Seasons` | `ls_seasons(...)` |
| GET  | `/Ls/GameInfo` | `ls_game_info(...)` |

## Обработка ошибок

`api/exceptions.py` определяет иерархию:

```
APIError
 ├── APIRequestError       — сетевые/таймауты
 ├── APIResponseError      — статусы ≥400 (кроме 404)
 ├── APINotFoundError      — 404
 └── APIRateLimitError     — 429
```

Все запросы клиента ретраются 3 раза с экспоненциальным backoff.
