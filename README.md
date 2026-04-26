# UltraBet — Telegram-бот футбольных прогнозов

Бот строит прогнозы на матчи на основе [SStats.net](https://sstats.net) API:
- рейтинги Glicko-2,
- двойная Пуассон-модель (xG, точные счёта, тоталы, фора, ОЗ),
- ансамбль Glicko + Poisson,
- сравнение с реальными коэффициентами букмекеров → подсветка валуйных ставок.

В боте — никакого веба и сайтовых файлов: только Telegram, чистая структура, парсинг всех нужных эндпоинтов API.

## Возможности

- 🔍 Поиск матча по двум командам (`/match Команда1 - Команда2`)
- 📅 Подборки матчей: `today / tomorrow / live`
- 🏆 Лиги: список, ближайшие матчи, турнирная таблица
- 📊 Полный отчёт по матчу:
  - топ-15 прогнозов по вероятности
  - топ-5 валуйных прогнозов с реальными коэф
  - вероятные точные счёта
  - xG и Glicko-2 рейтинги
- 💎 Подписки: 1д / 1н / 1м / 3м / 12м
- 🤝 Реферальная программа (бонусы за регистрации и подписки)
- 🛠 Админ-панель: статистика, рассылка, ручная активация подписок

## Стек

- Python 3.11+
- [aiogram 3](https://docs.aiogram.dev) — Telegram bot framework
- [aiohttp](https://docs.aiohttp.org) — async HTTP клиент
- [SQLAlchemy 2.0 async](https://docs.sqlalchemy.org) + SQLite
- [pydantic-settings](https://docs.pydantic.dev/latest/usage/pydantic_settings/) — конфиг через `.env`
- [loguru](https://loguru.readthedocs.io) — логирование

## Структура

```
ultrabet/
├── api/                # SStatsClient + кэш + исключения
├── core/               # Glicko, Poisson, ensemble, value calc, markets
├── services/           # MatchFinder, PredictionService, Odds, Countries, Referral, Subscription
├── db/                 # SQLAlchemy модели + репозитории
├── bot/                # aiogram handlers, keyboards, FSM, middlewares
├── utils/              # логирование
├── tests/              # юнит-тесты
├── config.py
├── main.py
└── requirements*.txt
```

## Запуск

1. Скопируй `.env.example` → `.env` и заполни:
   ```bash
   cp .env.example .env
   ```
2. Установи зависимости:
   ```bash
   make dev
   ```
3. Создай таблицы:
   ```bash
   make db-init
   ```
4. Запусти бота:
   ```bash
   make run
   ```

### Минимальный `.env`

```dotenv
BOT_TOKEN=123:ABC...        # от @BotFather
BOT_USERNAME=ultrabet_predictions_bot
SSTATS_API_KEY=             # опционально (без ключа лимит ниже)
ADMIN_IDS=123456789
```

## Команды бота

| Команда | Описание |
| --- | --- |
| `/start` | Приветствие, главное меню |
| `/menu` | Главное меню |
| `/match Команда1 - Команда2` | Полный прогноз на матч |
| `/matches today / tomorrow / live` | Подборки матчей |
| `/league Название` | Расписание лиги |
| `/standings Лига` | Таблица сезона |
| `/subscribe` | Подписки |
| `/referral` | Реферальная программа |
| `/balance` | Баланс прогнозов |
| `/feedback` | Отзыв |
| `/help` | Помощь |

Админ:

| Команда | Описание |
| --- | --- |
| `/admin` | Статистика |
| `/grant <tg_id> <plan>` | Активировать подписку |
| `/ban <tg_id>` | Заблокировать |
| `/unban <tg_id>` | Разблокировать |
| `/broadcast Текст` | Рассылка всем |

## Тесты

```bash
make test
make lint
make typecheck
```

## Безопасность

- Не коммитим `.env` — он в `.gitignore`.
- API-ключ SStats и токен бота — только через переменные окружения.
- При ошибках API клиент делает retry с экспоненциальным backoff и троттлингом.

## Дисклеймер

Бот не гарантирует прибыль. Прогнозы — статистическое ожидание на основе моделей.
Ставьте ответственно.
