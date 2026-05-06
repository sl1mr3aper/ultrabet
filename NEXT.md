# NEXT — план улучшений (по приоритету)

> План построен на принципе **бесплатных источников + минимум платных
> API**. Цель — двинуть бота с 5.5/10 (текущая оценка) в сторону 8/10
> и реальной прибыльности на дистанции.

> Перед стартом любого блока: читать `REQUIREMENTS.md` (ограничения)
> и `HANDOFF.md` (текущее состояние).

---

## Стратегия

Три моата, в порядке impact:

1. **Данные** — без honest closing odds и xG лучшая модель в мире выдаёт
   шум. Это узкое место №1.
2. **Прозрачность** — публичный аудит-дашборд. Никто из топ-50 этого
   не делает. Кто сделает — заберёт доверие пользователей.
3. **Математика** — Dixon-Coles, time-decay, stacking, isotonic-калибровка.
   Без п.1 эффект слабый, с ним — кратный.

---

## ЭТАП 1 — Данные и санити (~2 недели)

### 1.1. SofaScore-скрейпер ⭐ (приоритет №1, 2 дня)

**Файл**: `services/sofascore_client.py` (создать).

**Что даёт**:
- Прокси-Pinnacle closing odds (обычно через категорию «sharp»).
- Лайнапы и формации.
- xG матча.
- Статистика игроков.
- Бесплатно, без ключа.

**Эндпоинты**:
```
https://api.sofascore.com/api/v1/sport/football/scheduled-events/{date}
https://api.sofascore.com/api/v1/event/{event_id}
https://api.sofascore.com/api/v1/event/{event_id}/odds/1/all
https://api.sofascore.com/api/v1/event/{event_id}/lineups
https://api.sofascore.com/api/v1/event/{event_id}/statistics
```

**Технически**:
```python
class SofaScoreClient:
    def __init__(self, session: aiohttp.ClientSession, cache: CacheStore):
        self.headers = {"User-Agent": "Mozilla/5.0 ..."}
        # rate-limit: 1 req / 2 sec
        # cache: 5 min для live, 24ч для исторических
```

**Интеграция**:
- `services/external_odds.py` — добавить SofaScore как второй источник кф.
- Кросс-валидация: если SStats и SofaScore расходятся >20% по одному рынку —
  лог в `services/odds_anomaly.log`, пик попадает в «осторожно».

**Тесты**: моки HTTP, проверка парсинга, fallback при 429/5xx.

---

### 1.2. CLV-трекер (1 день, после 1.1)

**Файл**: `services/clv_tracker.py` (создать).

**Что даёт**: главную метрику долгосрочной прибыльности.
CLV (Closing Line Value) = `(наш_кф / closing_кф) - 1`. Если стабильно
>+1.5% — обыгрываем рынок.

**Реализация**:
```sql
CREATE TABLE clv_records (
    id INTEGER PRIMARY KEY,
    pick_id INTEGER REFERENCES prediction_outcomes(id),
    our_odds REAL,
    sofascore_close_odds REAL,
    pinnacle_close_odds REAL,         -- если найдём
    market_key TEXT,
    clv_pct REAL,                     -- precomputed
    captured_at TIMESTAMP
);
```

**Захват closing line**: cron-таск в `services/clv_tracker.py`,
пробегает за 5 минут до старта матча, забирает SofaScore close.

**Команда `/clv` в админке**: средний CLV за 7/30/90 дней,
по лигам, по рынкам.

---

### 1.3. Understat-скрейпер ⭐ (1 день)

**Файл**: `services/understat_client.py` (создать).

**Что даёт**: настоящий xG, удары, ассисты, минута каждого xG-события
для топ-5 лиг (АПЛ, La Liga, Bundesliga, Serie A, Ligue 1) + РПЛ.

**Эндпоинты**:
```
https://understat.com/league/{league}/{year}     # таблица
https://understat.com/match/{match_id}            # матч
https://understat.com/team/{team}/{year}          # команда
```

Данные приходят как **встроенный JSON в HTML** (`var matchesData = JSON.parse(...)`),
парсится regex'ом + json.loads.

**Интеграция**:
- `core/ensemble.py` — заменить `expected_goals_from_glicko()` на
  rolling-30 матчей xG из Understat (если для лиги покрыто).
- Если Understat не покрывает лигу — fallback на старую формулу.

**Effect**: +5–8% точности на топ-5 лигах за выходные.

---

### 1.4. FBref-скрейпер (1 день, медленный)

**Файл**: `services/fbref_client.py` (создать).

**Покрытие**: 200+ лиг по миру, в т.ч. экзотические (Гватемала, Эквадор,
Исландия — все, что есть в твоих бэктестах).

**Что даёт**:
- Per-team rolling stats: xG, xGA, deep passes, PPDA, possession.
- Per-player stats: xG-индивидуальный, сборы голевой.
- Историческая глубина 5+ сезонов.

**Технически**:
- Rate-limit FBref: 6 req → 429. Решение: кэшировать на **24 часа**.
- Запускать **ночным cron'ом** (один раз в день в 04:00 UTC).
- Использовать `pandas.read_html()` — таблицы с FBref парсятся легко.

**Интеграция**: дополнительные фичи для модели (см. этап 3).

---

### 1.5. Лайнап-парсер (1 день)

**Файл**: расширить `services/sofascore_client.py`.

**Что даёт**: пересчёт прогноза при публикации составов
(обычно за 60 минут до матча).

**Триггер**: cron каждые 5 минут — для матчей в горизонте 0–120 минут
проверять `lineups.confirmed == true`. Если стартовый состав изменился
от ожидаемого — пересчитать вероятности.

**Эффект на UX**: кнопка в матче «Обновить с лайнапом» (или авто-пуш
подписчикам).

---

### 1.6. OddsPortal closing (опционально, 2 дня — сложно)

**Файл**: `services/oddsportal_scraper.py`.

**Что даёт**: настоящий Pinnacle close (не прокси). У SofaScore Pinnacle
часто нет, но closing line любого sharp-букмекера — это точный CLV.

**Сложность**: Cloudflare Turnstile + JS-rendering.
Решение: `playwright-python` с реальным fingerprint, медленно.

**Если сложно** — пропускать. SofaScore-close через 1.1+1.2 даст 80%
качества.

---

### Итог этапа 1

После него:
- 4 источника данных вместо 1.
- Pinnacle/SofaScore closing odds → честный CLV-замер.
- Реальный xG в модели → +5–8% точности.
- Лайнап-чувствительность → -10% вероятности когда без ключевого игрока.

**Стек**: чисто Python + aiohttp + playwright. Бесплатно.

---

## ЭТАП 2 — Прозрачность и доверие (~1 неделя)

### 2.1. Публичный аудит-дашборд ⭐⭐⭐ (3 дня)

**Это ГЛАВНЫЙ маркетинговый дифференциатор. Никто из топ-50 этого не
делает.** Сделать первым = выиграть рынок доверия.

**Стек**: уже есть FastAPI в `api/`. Добавить:
- `api/dashboard.py` — endpoint'ы.
- `static/dashboard.html` — простой одностраничник на vanilla JS / HTMX.

**Что показывает**:
1. **Все исторические пики**, без удалений. Каждый пик с хешем
   (`sha256(pick + timestamp)`) для верификации.
2. **ROI / Hit-rate / CLV** в разрезе:
   - Лига
   - Рынок
   - Диапазон кф (1.0–1.3, 1.3–1.7, 1.7–2.5, 2.5+)
   - Месяц
3. **«Наш прогноз vs Pinnacle close»** — обновляется автоматически.
4. **Drawdown-кривая** банкролла (если играть Kelly).
5. **Поле «Last 7 days» / «Last 30 days» / «All-time»**.

**Anti-cheat**:
- Каждый пик пишется в БД до старта матча (timestamp с подписью).
- Невозможно задним числом удалить — есть таблица `pick_audit_log` с
  insert-only логикой.
- Хеш каждого пика публикуется в Telegram-канал @ultrabet_audit
  (отдельный канал, только для аудита) при публикации.

### 2.2. Honest «accuracy» в боте

В `bot/handlers/main_menu.py` добавить кнопку **📈 Точность модели**
которая показывает текущие цифры с дашборда — без приукрашивания.
Если ROI -5% за месяц — так и сказать. Доверие важнее показухи.

---

## ЭТАП 3 — Математика модели (~2 недели)

### 3.1. Dixon-Coles коррекция (2 дня)

**Файл**: `core/poisson_model.py` → новая функция `dc_corrected_matrix()`.

**Что даёт**: корректные вероятности низких счетов (0:0, 1:0, 0:1, 1:1).
Двойная Пуассон системно их недооценивает.

```python
RHO = -0.18  # калибруется на исторических данных
def _tau(home_goals, away_goals, lam_h, lam_a, rho=RHO):
    if home_goals == 0 and away_goals == 0: return 1 - lam_h*lam_a*rho
    if home_goals == 0 and away_goals == 1: return 1 + lam_h*rho
    if home_goals == 1 and away_goals == 0: return 1 + lam_a*rho
    if home_goals == 1 and away_goals == 1: return 1 - rho
    return 1.0
```

Калибровка `RHO` на накопленных данных Understat (см. этап 1.3).

### 3.2. Time-decay параметров (1 день)

**Файл**: `core/glicko_model.py` + `core/poisson_model.py`.

**Что**: новые матчи весят больше старых. `weight = exp(-Δt / τ)`,
где τ ≈ 18 месяцев.

```python
def time_weight(match_date: datetime, now: datetime, tau_days=540) -> float:
    delta_days = (now - match_date).days
    return math.exp(-delta_days / tau_days)
```

При расчёте rolling-xG, формы команды, head-to-head — взвешивать.

### 3.3. Per-league shrinkage (2 дня)

**Файл**: `core/probability_regulator.py` или новый `core/shrinkage.py`.

**Что даёт**: команды с малым числом матчей (3–10) не должны иметь
экстремальные оценки xG. Сжимать к среднему лиги.

```python
def shrink(team_xg, league_avg_xg, team_matches, k=10):
    weight = team_matches / (team_matches + k)
    return weight * team_xg + (1 - weight) * league_avg_xg
```

`k=10` означает: пока матчей < 10, доминирует среднее лиги.

### 3.4. LightGBM-stacking (5 дней)

**Файл**: `core/ml_stacker.py` (создать).

**Архитектура**:
- **L0 (базовые)**: Glicko вероятности, Poisson вероятности, форма,
  Understat xG, FBref features.
- **L1 (мета)**: LightGBM классификатор на 1X2, обученный на
  Brier loss, фичи L0 + контекст (home/away, лига, месяц).
- **Калибровка**: isotonic regression на остатках L1.

**Тренировка**: оффлайн на накопленных данных (минимум 5000 матчей),
один раз в неделю по cron.

**A/B в проде**: 50% запросов идёт через старый Poisson+Glicko,
50% через L1. Сравнение по CLV → победитель.

### 3.5. Per-market specialization (3 дня)

Разные модели для разных рынков:

| Рынок | Модель |
|---|---|
| 1X2 | LightGBM (3.4) |
| Тоталы | Dixon-Coles + skellam |
| Гандикапы | Dixon-Coles |
| BTTS | Bivariate Poisson + copula |
| Угловые | Poisson на rolling-10 corner-rate |
| Карточки | Poisson на rolling-10 + контекст (дерби, судья) |

Сейчас всё через одну Poisson. Per-market даст +3–5% точности.

---

## ЭТАП 4 — Продукт и удержание (~2 недели)

### 4.1. Push-уведомления (2 дня)
- «Лайнап вышел, прогноз обновлён».
- «Через 30 минут стартует ваш матч N — текущий кф SofaScore: X.XX».
- «Пик дня: команда А — команда Б, EV +12%».

### 4.2. Подписки в проде (3 дня)
Уже есть код в `bot/handlers/subscription.py`. Не подключена реальная
оплата.
- Telegram Stars (легче всего).
- ЮMoney / Crystal Pay для России.
- ЮСDT/USDT для криптанов (TONcoin, BNB).

Тарифы:
- Free: 3 пика/день.
- Basic ($15/мес): все «брать», без VIP-каналов.
- VIP ($60/мес): + лайв-уведомления, + персональный bankroll,
  + еженедельный отчёт «как ты играешь».

### 4.3. Реферальная система в продакшен (1 день)
Код есть в `bot/handlers/referral.py`. Активировать.

### 4.4. Affiliate с букмекерами (3 дня + согласование)
Партнёрки с легальными бк (например, Леон, Винлайн в РФ; Bet365 в EU).
Когда бот находит value bet — кидает депth-link через partner-tag.
Топ-10 ботов в нише живут на этом > чем на подписках.

### 4.5. Многоязычность (3 дня)
RU + EN + ES + PT покрывают 80% мирового беттинг-рынка.
Использовать существующий `services/i18n.py`.

---

## ЭТАП 5 — Инфраструктура к проду (~1 неделя)

### 5.1. Postgres вместо SQLite (1 день)

`services/db_migrate.py` уже есть — adopt to PostgreSQL.

```python
# .env
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/ultrabet
```

Миграции через Alembic (есть в проекте).

### 5.2. Docker / docker-compose (1 день)

```yaml
# docker-compose.yml
services:
  bot:
    build: .
    env_file: .env
    depends_on: [postgres, redis]
  postgres:
    image: postgres:16
    volumes: [pgdata:/var/lib/postgresql/data]
  redis:
    image: redis:7
```

### 5.3. Вынести парсер в воркер (2 дня)

Сейчас всё в одном процессе с ботом → если SStats тупит, бот висит.

Архитектура:
```
[bot]      ←──── Redis pub/sub ────→  [parser-worker]
   ↓                                       ↓
[postgres]                          [SStats/SofaScore/Understat/FBref]
```

### 5.4. Sentry / Prometheus (полдня)

Минимальный observability для прода. Sentry для ошибок, Prometheus
для метрик (latency предсказания, кэш-хитрейт, ошибки парсера).

### 5.5. systemd-юнит / k8s манифест (полдня)

Чтобы пользователь мог поднять у себя за 5 минут.

---

## ЭТАП 6 — Self-learning v2 (~1 неделя, после ЭТАП 1+3)

Текущий self_learner — декорация. Нужно:

### 6.1. Online learning per league
Веса параметров обновляются после каждого матча, **отдельно для каждой
лиги** (а не глобально). Маленькие лиги получают больший lr (быстрее
учатся).

### 6.2. Holdout-валидация
30% последних разрешённых пиков — holdout.
**Не использовать для тренировки.** Оценивать качество модели на
holdout перед деплоем новых весов.

### 6.3. A/B-тестинг в проде
2 модели работают одновременно:
- Model A (текущая).
- Model B (кандидат).

50/50 splits на пользователях. После 200+ разрешённых пиков на
каждой → сравнение по CLV. Победитель становится Model A.

### 6.4. Anti-overfit guard
Если модель резко улучшилась на бэктесте (>5%) — это **подозрительно**,
почти наверняка дата-лик. Holdout должен совпадать ±1% с тренировочной
производительностью.

---

## ЭТАП 7 — Live-беттинг (~3-4 недели, последний этап)

70% мирового беттинг-объёма в лайве. Без него ты на 30% рынка.

### 7.1. Real-time event feed (SofaScore live API)
- Голы, удары, угловые, ЖК/КК, замены, минута.
- Обновление каждые 30–60 сек.

### 7.2. State-space модель
Текущее состояние матча → пересчёт всех вероятностей.

Простая версия (на старте):
- Скорректированный Poisson по оставшемуся времени.
- Учёт счёта (если 1:0 на 60-й — переоценка ТБ 2.5).
- Учёт удалений.

### 7.3. Latency-sensitive UX
- Live-уведомления через WebSocket в Telegram.
- Кнопка «лайв-кф» в каждом матче.

---

## Приоритезация (если ограничены ресурсы)

### Если есть 1 неделя — сделай только это
1. SofaScore-скрейпер (этап 1.1) — 2 дня
2. CLV-трекер (этап 1.2) — 1 день
3. Публичный дашборд (этап 2.1) — 3 дня
4. Dixon-Coles (этап 3.1) — 2 дня

### Если есть 1 месяц
+ Understat (1.3), FBref (1.4), Time-decay (3.2), Shrinkage (3.3),
push-уведомления (4.1), Postgres (5.1), Docker (5.2).

### Если есть 3 месяца
Полный план + Live-беттинг (этап 7).

---

## KPI после внедрения

| Метрика | Сейчас | После этапа 1+3 | После всего плана |
|---|---|---|---|
| ROI на bigger sample | -2…0% | +1…+3% | +3…+6% |
| CLV (vs Pinnacle close) | не измеряется | +1.5% | +2.5% |
| Точность 1X2 | ~52% | ~55% | ~58% |
| Brier score | 0.14 | 0.12 | 0.10 |
| DAU (активные) | 1 (админ) | 50 | 1000+ |
| MRR (выручка) | $0 | $300 | $5000+ |

Цифры — реалистичные, не маркетинговые. После этапа 1+3 продукт
станет реально прибыльным для пользователя, после этапа 4 — для тебя.
