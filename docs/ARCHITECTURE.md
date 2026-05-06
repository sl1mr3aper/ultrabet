# Архитектура UltraBet

## Слои

```
┌──────────────────────────┐
│ Telegram (Bot API)       │
└─────────────┬────────────┘
              │ aiogram 3
┌─────────────▼────────────┐
│ bot/                     │  routers, FSM, keyboards, formatters
│  ├── handlers/           │   ↳ команды, callback'и, FSM-сценарии
│  ├── middlewares.py      │   ↳ throttling, ошибки, сессия БД
│  ├── keyboards.py        │   ↳ Inline/Reply markup
│  ├── formatters.py       │   ↳ форматирование текстовых отчётов
│  ├── states.py           │   ↳ FSM-группы
│  └── texts.py            │   ↳ все строки на русском
└─────────────┬────────────┘
              │
┌─────────────▼────────────┐
│ services/                │ бизнес-логика поверх API и core
│  ├── prediction_service  │   ↳ оркестрирует прогноз матча
│  ├── match_finder        │   ↳ поиск пары команд → game_id
│  ├── h2h_service         │   ↳ очные встречи
│  ├── daily_picks         │   ↳ скан дня → топ EV
│  ├── top_matches         │   ↳ топ матчей по престижу
│  ├── league_service      │   ↳ лиги, сезоны, standings
│  ├── team_service        │   ↳ карточки команд
│  ├── player_service      │   ↳ карточки игроков
│  ├── profile_service     │   ↳ профиль пользователя
│  ├── subscription_service│   ↳ планы подписок и квоты
│  ├── referral_service    │   ↳ реф-программа
│  ├── odds_parser         │   ↳ парсинг рыночных коэффициентов
│  └── countries           │   ↳ EN→RU + флаги
└─────────────┬────────────┘
              │
┌─────────────▼────────────┐    ┌────────────────────────────┐
│ core/                    │    │ api/                       │
│  ├── glicko_model        │    │  ├── sstats_client         │
│  ├── poisson_model       │    │  ├── cache (TTL)           │
│  ├── ensemble (55/45)    │    │  └── exceptions            │
│  ├── value_calculator    │    └────────────┬───────────────┘
│  └── markets             │                 │ HTTPS
└──────────────────────────┘                 │
                                ┌────────────▼───────────────┐
                                │ SStats.net API v0.9.14     │
                                └────────────────────────────┘

┌──────────────────────────┐
│ db/                      │  SQLAlchemy async + SQLite (по умолчанию)
│  ├── models.py           │   ↳ User, Referral, Subscription, Logs
│  └── repositories/       │   ↳ Repo-обёртки на Session
└──────────────────────────┘
```

## Поток предсказания

1. Пользователь отправляет `/match Team1 - Team2`.
2. `MatchFinder` ищет каждую команду через `/Teams/list` → пары кандидатов.
3. `PredictionService.predict(game_id)`:
   - Загружает `/Games/{id}`, `/Games/glicko/{id}`, `/Odds/{id}` параллельно.
   - `core/ensemble.build_predictions()` собирает 30+ рынков.
   - `OddsParser` извлекает реальные коэффициенты букмекеров.
   - `ValueCalculator` сравнивает вероятности с коэффициентами → топ-5 EV.
4. Форматер `format_prediction()` рендерит итоговый текст.

## Подписки и лимиты

- Базовый план: 5 бесплатных прогнозов в сутки (сбрасывается каждые 24 часа).
- Подписки: `1d`, `1w`, `1m`, `3m`, `12m` — увеличенные суточные квоты + бонусы.
- Реферальная программа: бонусные прогнозы за приведённых пользователей и их подписки.

## Кэш

In-memory TTL-кэш на каждом GET-запросе, типичные значения:
- лиги: 24ч
- список матчей: 15 минут
- детали матча: 5 минут
- glicko: 10 минут
- одды: 3 минуты

## Производительность

- aiohttp + bounded `asyncio.Semaphore` (см. `daily_picks.py`) исключает выгорание квоты SStats.
- Все handler'ы — short-lived: тяжёлые операции делает background задача (пока — синхронно с long-polling, в будущем — webhook + queue).
