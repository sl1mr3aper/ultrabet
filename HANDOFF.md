# HANDOFF — текущее состояние проекта UltraBet

> **Это документ для следующего Devin-агента (или человека-разработчика),
> который продолжит работу.** Прочитай до конца перед любыми правками.

Дата последнего обновления: 2026-05-01
Сессия: Devin (продолжение с архива `ultrabet-work+3.tar.gz`)

---

## TL;DR

UltraBet — Telegram-бот для предматчевого футбольного value-беттинга.
Стек: aiogram 3 + SQLAlchemy (SQLite WAL) + Glicko-2 + двойная Пуассон + Gemini AI-refiner.
Источник данных: SStats API (один — это узкое место, см. NEXT.md).
572 теста, ruff чисто, бот стабильно стартует.

**Текущая оценка: 5.5/10** (см. ASSESSMENT.md). Хороший MVP уровня
«любительский value-tracker», но до топ-10 индустрии нужны:
xG-фид, Pinnacle closing odds, CLV-трекер, лайнап-парсер, публичный
аудит-дашборд.

---

## Что сделано в этой сессии (2026-04-30 → 2026-05-01)

### Архитектурные изменения

1. **Создан `core/value_engine.py`** — единый отбор пиков.
   - Composite score = `EV × √p` (вероятный + валуйный одновременно).
   - Вердикты: `брать` / `осторожно` / `не брать`.
   - Санити-фильтр кривых букмекерских кф (коридор `0.55× ; 1.8×` от честного `1/p`).
   - Функция `select_best_pick(probabilities, odds_map, ...)` — единая точка отбора.

2. **`core/value_calculator.py`** — `min_probability` снижен с **0.90 → 0.35**.
   Старый порог 0.90 пропускал большинство валуйных пиков с кф 1.5–4.0.

3. **`config.py`** — `min_value_probability = 0.35` (default).

4. **`bot/handlers/admin.py`** — два новых режима для админа:
   - **📊 Массовый анализ** (callback `admin:mass_analysis`):
     ввод даты ГГГГ-ММ-ДД, кнопки «Сегодня/Вчера/Завтра», прогон всех
     матчей даты, для прошедших — резолв результата, ROI, точность.
   - **🎯 Анализ прогнозов** (callback `admin:prediction_analysis`):
     **двухшаговый флоу** (FSM): сначала дата (тот же набор кнопок),
     потом количество матчей (10/20/50/100 пресеты или ввод 1–200).
     Кнопка 🛑 «Остановить» на каждом обновлении прогресса (интервал 1.5с).

5. **Главное меню админа** (`bot/handlers/main_menu.py` + `bot/keyboards.py`):
   обе кнопки (📊 и 🎯) ВСЕГДА видны админу — не прячутся в подменю.

6. **Topmatches** (`bot/handlers/topmatches.py`):
   - Сортировка по `composite` (EV × √p), а не по проценту вероятности.
   - Фильтр по вердикту: только `брать` (`осторожно` как fallback если пусто).
   - Иконки вердиктов: 🟢 брать, 🟡 осторожно, ⚪ не брать.

### UX-правки

7. **Глобально удалены «букмекер X.XX» из всех отчётов**
   (Анализ прогнозов, Массовый анализ, Топ-листы, Дневной пик-лист, экспресс).
   В выводе осталось только формульное `кф *X.XX*` = 1/p.
   *Причина: букмекерские кф приходили мусорные (32.68 при честном 1.45),
   санити-фильтр их отбрасывает; для пользователя смысла показывать нет.*

8. **Удалено слово «честный»** из пользовательских отчётов.
   Было: `кф *1.94* (честный)` → стало: `кф *1.94*`.
   В калькуляторе: `Честный КФ: *1.94*` → `КФ (1/p): *1.94*`.

9. **Удалены Пол-Келли и Четверть-Келли** из всех UI-выводов.
   Остался только полный «Келли *X.X%*» с пояснением «доля банка».
   Backend (`StakeKind.HALF_KELLY/QUARTER_KELLY`) оставлен для совместимости.

10. **Для прошлых дат в Анализе прогнозов** теперь резолвится результат
    каждого пика:
    - ✅ — пик зашёл
    - ❌ — пик не зашёл
    - ❔ — матч завершён, но рынок не определяется
    - 🔮 — матч ещё не сыгран

    В шапке: точность по выборке («брать»: X/Y), ROI, профит по `fair_odds`.

### Багфиксы

11. **Database locked** — был зомби-процесс старого бота (PID 7705)
    держал лок. Убит, WAL чекпоинтнут, бот переподключается чисто.
    Включён WAL-режим SQLite (см. `db/database.py`).

12. **Post-hoc real_odds override** — в `_run_prediction_analysis` после
    `select_best_pick()` real_odds перезаписывался сырыми `best_odds[market]`
    без санити, что выводило мусор «букмекер 20.00 при честном 1.94».
    **Удалён весь override** — `pick.odds` (None если отфильтровано) идёт
    как есть. Единый санитарный контур через `select_best_pick`.

13. **Telegram conflict 409** — был запущен второй инстанс бота
    с тем же токеном (где-то у пользователя). Перешли на новый
    токен `8526752314:...` (см. `.env`).

### Тесты

- 572 пройдено, ruff чисто.
- `tests/test_value_calculator.py` адаптирован под новый дефолт
  `min_probability=0.35`.

### Файлы тронуты в этой сессии

```
bot/handlers/admin.py            (+++)  массовый/прогнозный анализ
bot/handlers/main_menu.py        (++)   меню админа
bot/handlers/topmatches.py       (+)    composite sort, без букмекера
bot/handlers/dailypicks.py       (+)    без букмекера
bot/handlers/bankroll.py         (+)    Kelly only, КФ (1/p)
bot/handlers/calculator.py       (+)    Kelly only
bot/handlers/parlay.py           (+)    КФ (1/p)
bot/handlers/common.py           (+)    обработка FSM
bot/keyboards.py                 (+)    new admin keyboards
bot/states.py                    (+)    FSM-состояния для дата+count
bot/texts.py                     (+)    новые тексты
bot/formatters.py                (+)    Kelly-only output
config.py                        (+)    min_value_probability=0.35
core/value_engine.py             (НОВЫЙ) единый отбор пиков
core/value_calculator.py         (+)    дефолт min_probability=0.35
services/bankroll.py             (+)    Kelly-only describe
main.py                          (+)    WAL pragma, мелкие правки
tests/test_value_calculator.py   (+)    адаптировано под новый дефолт
```

---

## Запуск бота

```bash
# распаковать архив
tar -xzf ultrabet-final.tar.gz -C ultrabet/
cd ultrabet/

# окружение
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# директории под БД и логи
mkdir -p data logs

# .env уже внутри архива (с реальными токенами)
# при деплое в другое место — скопировать .env

# запуск
python -m main
# или фоном:
nohup .venv/bin/python -m main > /tmp/ultrabet.log 2>&1 &
```

### Проверка
```bash
# процесс жив?
ps aux | grep "python -m main" | grep -v grep

# логи
tail -50 /tmp/ultrabet.log

# нет ли конфликтов с другим инстансом?
grep -E "TelegramConflictError|database is locked" /tmp/ultrabet.log
```

### Остановка
```bash
pkill -f "python -m main"
sleep 2
# чекпоинт WAL → bot.db (нужно для чистого следующего запуска)
sqlite3 data/bot.db "PRAGMA wal_checkpoint(TRUNCATE);"
```

---

## Тесты, линтер

```bash
cd /home/ubuntu/repos/ultrabet

# тесты
.venv/bin/python -m pytest tests/ -x --tb=short -q
# Ожидание: 572 passed

# ruff
.venv/bin/ruff check bot/ core/ services/
# Ожидание: All checks passed!
```

---

## Ключевые контракты

### `select_best_pick(probabilities, odds_map, accept_only=True, fallback_to_caution=True) → PickScore | None`

Возвращает лучший пик матча по `composite = EV × √p`.
- `accept_only=True` — берёт только пики с вердиктом `брать` (`p≥0.35 AND ev_pct≥3.0 AND kelly>0`).
- `fallback_to_caution=True` — если `брать` нет, пытается вернуть лучший «осторожно».
- `pick.odds` — ИЛИ реальный санитарный кф, ИЛИ `None`. **Никогда не доверять `odds_map[key]` напрямую** — там может быть мусор.
- `pick.fair_odds` — всегда `1/p`.

### Вердикты (из `core/value_engine.py`)

| Условия | Вердикт |
|---|---|
| `p ≥ 0.35` AND `ev_pct ≥ 3.0` AND `kelly > 0` | **брать** |
| `p ≥ 0.28` AND `ev_pct ≥ 1.0` (но не «брать») | **осторожно** |
| иначе | **не брать** |

### Санити кф (из `core/value_engine.py`)

```
MAX_REAL_TO_FAIR = 1.8     # real_odds / fair_odds <= 1.8
MIN_REAL_TO_FAIR = 0.55    # real_odds / fair_odds >= 0.55
```

Если real_odds выходит за коридор → отбрасывается, в EV-расчёте
используется `fair_odds` (что даёт `EV = 0`).

---

## Известные проблемы

1. **SQLite не для прода**. На 1 пользователе работает, на 100 не выдержит.
   До публичного запуска — мигрировать на Postgres (см. NEXT.md).

2. **`admin.py` стал god-объектом** (53k символов). Разбить на
   `admin/mass_analysis.py`, `admin/prediction_analysis.py`,
   `admin/common.py`. Не критично, но чешется.

3. **`probability_regulator`** активно мешает на малых выборках (<500
   per-bin), сейчас в БД ~50 разрешённых пиков. Регулятор шумит больше,
   чем регулирует. Либо отключить до набора данных, либо добавить
   проверку min-samples.

4. **Gemini AI-refiner** — архитектурно сомнителен (LLM не калибруется).
   Использовать только как «sanity check текста», не как слой над probabilities.
   Сейчас он стоит **поверх** probabilities — стоит передвинуть в text-only.

5. **probability_regulator + Gemini stack-up** = двойная не-калиброванная
   коррекция. Иногда они тянут в разные стороны и итоговая вероятность
   уходит за разумные границы. Решение: holdout-валидация + один из них
   отключить.

---

## .env (содержит реальные токены)

```
BOT_TOKEN=8526752314:AAFn8eS0PXrhhqChY1exnpLyKFpmF-ZmQuY
BOT_USERNAME=ares_main_bot
SSTATS_API_KEY=8s6v6vx563doosb7
GEMINI_API_KEY=AIzaSyCqtDj5QPaHrxtXLw6Z6YL1DloSRuLX2X8
ADMIN_IDS=1169703231
PROXY_URL=socks5://127.0.0.1:10808     # на VM не нужен, на проде — сам реши
DATABASE_URL=sqlite+aiosqlite:///data/bot.db
```

⚠️ **Если архив попал к третьим лицам — перевыпустить токены через
BotFather (BOT_TOKEN) и панели SStats/Gemini.**

---

## Что прочитать дальше

1. **`REQUIREMENTS.md`** — все требования пользователя из переписки.
   Не нарушать, не отменять без согласования.
2. **`NEXT.md`** — план улучшений по приоритетам, что делать дальше.
3. **`ASSESSMENT.md`** — честная оценка проекта по 7 осям.
4. **`docs/ARCHITECTURE.md`** — старая архитектурная документация.
5. **`AGENTS.md`** (в корне) — стиль работы и принципы.
