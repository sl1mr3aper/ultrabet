# Изменения в этой сборке (Devin)

Ветка: `devin/1777208256-report-ux-improvements`
Базовый коммит: origin/main

## Что сделано (по списку требований)

1. **Glicko unavailable** — в отчёте теперь явно пишется
   `🌟 Glicko-2: данные недоступны`, если рейтинги отсутствуют/нулевые
   (`services/prediction_service.py`, `bot/formatters.py`).
2. **Топ-15 котировок без фильтра 85%** — отчёт показывает топ-15 прогнозов
   по убыванию вероятности, без отсечки `≥85%`
   (`bot/formatters.py`).
3. **Прогресс при клике на матч** во вкладках «Сегодня/Завтра» —
   динамический индикатор работает и в режиме `edit` (нажатие inline-кнопки),
   и при ответе новым сообщением (`bot/handlers/predictions.py`).
4. **Динамический ETA** — 4 стадии с расчётом остатка `≈ N сек.`
   (`bot/texts.py`, `bot/handlers/predictions.py`).
5. **Удалён раздел «топ-15 валуйных ставок»** — секция убрана из отчёта
   (`bot/formatters.py`).
6. **Корректные флаги Англии/Шотландии/Уэльса** + UK-алиасы
   (`services/countries.py`, тесты).
7. **Самообучение реализовано** —
   - `SelfLearner` подключён в `bot.context.services`,
   - вероятности калибруются перед расчётом value-bets
     (`services/prediction_service.py`),
   - после каждого отчёта пишутся `PredictionOutcome` (топ-10),
   - в `main.py` крутится фон-цикл `_self_learning_loop` каждые 6 часов:
     `evaluate_pending` + `compute_snapshot`.
8. **Парсер коэффициентов сделан устойчивее** — нормализация
   bookmakers/markets/outcomes из разных JSON-форматов SStats,
   список синонимов рынков (`Match Winner`, `1x2`, `H2H`, `Match Result`,
   `Money Line` …), мягкая детекция Over/Under, Handicap, BTTS, Team Totals
   (`services/odds_parser.py`).
9. **Дата в шапке отчёта** — теперь `(актуально на YYYY-MM-DD)` без времени
   (`bot/formatters.py`).
10. **Без эмодзи после процентов** — строки прогнозов
    больше не оканчиваются на 🔥/🟡/✅
    (`bot/formatters.py`, тесты).

## Как запустить локально

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # подставьте свои BOT_TOKEN / SSTATS_API_KEY / DATABASE_URL
python -m alembic upgrade head    # если используете миграции
python main.py
```

## Доработки второй итерации

11. **Лимит 8 страниц снят** — в «Сегодня/Завтра» теперь подгружается до
    500 матчей за один раз, на одной странице 10 (`bot/handlers/matches.py`).
12. **Сортировка матчей по стране** — внутри списка «Сегодня/Завтра»
    матчи группируются по стране → лиге → времени.
13. **Флаг страны на кнопках матча** — `🇪🇸 Real — Atletico` и т.п.
14. **Inline-кф в топ-15** — в каждой строке прогноза теперь
    показывается коэффициент `· кф *2.10*` если он есть; если есть
    лучший кф из всех источников — также имя букмекера в скобках.
15. **Главный пик «🎯 ГЛАВНЫЙ ПИК»** — отдельный блок в конце отчёта,
    выбирает рынок с лучшим Expected Value (вероятность × кф).
16. **Лайв-режим** — для матчей в игре отчёт компактный: `🔴 МАТЧ В ЛАЙВЕ`,
    текущий счёт и минута `(22’)`, вместо топ-15 — только главный пик
    и самый вероятный точный счёт. Подключён `/Odds/live/{id}` для
    свежих кфов.
17. **Внешние агрегаторы кф (best-effort)**:
    - **NB-Bet** — `services/external_odds.NBBetClient`: парсит
      `__NEXT_DATA__` со страницы события, выводит 1X2 по ближайшей
      перестановке относительно SStats average. Slug-кэш на 5 мин.
    - **Flashscore** — поддержка через Playwright предусмотрена в коде,
      но без надёжного маппинга `gameId → matchHash` фактически
      не возвращает кф. Реализация специально gracefully degraded,
      чтобы не валить прогноз.

## Тесты

```bash
pytest -q             # 563 проходят
ruff check .          # чисто
```

## Сборка от 26 апреля (вечер) — Wave 1+2+3

### Wave 1: UX
- **Пагинация при ручном поиске двух команд** — теперь не «топ-20 в одной портянке», а 10 команд на страницу с кнопками `← Назад / Вперёд →` и подписью `Стр. X/Y`. Поднял лимит расширенного поиска до 100 команд (`bot/handlers/predictions.py`, `bot/keyboards.py`).
- **CSV-экспорт сырых данных** — после генерации отчёта появилась кнопка `📊 CSV сырые данные`. По клику бот собирает полный bundle SStats (`/Games/{id}` + `/Glicko` + `/Odds` + `/injuries` + `/last-games-stats` + `/profits` + `/season-table` + `/Odds/live`) и отдаёт CSV-файл с плоской проекцией (`section,key,value`). Удобно для аудита и ручного анализа (`services/csv_export.py`, `bot/handlers/predictions.py`).
- **Фильтр-санитайзер кфов** (из предыдущей итерации, в этой сборке закреплено) — кф > 30 на популярных рынках (1X2, DC, O/U, BTTS, Handicap, Team Total) считается мусором и игнорируется (`bot/formatters.py`).

### Wave 2: AI
- **Gemini-уточнение топ-1 пика** — после построения отчёта бот вызывает Google Gemini (по умолчанию `gemini-2.5-flash-lite`, free tier) с подборкой данных матча: топ-вероятности модели, кфы, травмы, форма. Возвращается короткий текст из 3-х строк (`✅ почему пик надёжен / ⚠️ главный риск / 🎯 подтверждение или альтернатива`), приклеивается к отчёту блоком `🤖 AI-уточнение`. Падение Gemini не валит отчёт — graceful degrade. Кэш на game_id 30 минут (`services/ai_refiner.py`, `bot/handlers/predictions.py`, `config.py`).
- Нужен `GEMINI_API_KEY` в `.env` (бесплатно, https://aistudio.google.com/apikey). Без ключа фича отключается без ошибок.

### Wave 3: Историческая БД
- **`scripts/historical_etl.py`** — ETL-скрипт для массовой загрузки матчей с 2010 года из SStats. Идёт по всем (или указанным) лигам × годам, скачивает завершённые матчи через `/Games/list?Ended=true`, идемпотентно сохраняет в `match_results` (UPSERT по `game_id`). Дросселирование 0.5–1 сек между запросами, чтобы не словить rate-limit. Запуск: `python -m scripts.historical_etl --from 2010 --to 2025 [--leagues 1,2,3] [--limit 50]`. Объём — ~13–20 часов на топ-50 лиг × 16 лет. Запускайте в `screen`/`tmux`.
- Существующая таблица `MatchResult` (используется `SelfLearner` и `evaluate_pending`) переиспользуется для исторических данных — никакой схемы заводить не нужно.
- Планируемое использование: со-инициализация Glicko рейтингов, обучение веса xG-компонента ансамбля, контекст «домашняя серия» / «выезды без побед».

### Wave 1.3 (отложено)
- Кэш итогового отчёта в БД на повторные клики признан низкоприоритетным: SStats-клиент уже кэширует все сетевые вызовы (`game:300s`, `glicko:600s`, `odds:180s`), поэтому реальное время повторного клика — это 1–2 сек на пересчёт Глико/Пуассона, а не 5–10. Если позже всплывёт жалоба — заведём `prediction_cache` таблицу.

## Затронутые файлы

```
api/sstats_client.py
bot/context.py
bot/formatters.py
bot/handlers/matches.py
bot/handlers/predictions.py
bot/texts.py
db/repositories/user_repo.py
main.py
services/countries.py
services/external_odds.py        ← новый
services/odds_parser.py
services/prediction_service.py
tests/test_countries.py
tests/test_external_odds.py      ← новый
tests/test_formatters.py
```
