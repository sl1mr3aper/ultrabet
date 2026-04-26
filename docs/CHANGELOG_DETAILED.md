# Полный журнал изменений

## v0.9 — Major feature release

### Services
- **bankroll** — 7 стратегий ставок (Flat / Percent / Kelly / Half-Kelly /
  Quarter-Kelly / Martingale / Anti-Martingale) с cap max_fraction.
- **notifications** — AsyncIO pub/sub для 6 типов событий.
- **export** — CSV/JSON/TSV/Markdown универсальный сериализатор.
- **scheduler** — лёгкий async-планировщик (every / daily_at).
- **live_monitor** — real-time snapshot коэфов с diff tracking.
- **parlay** — калькулятор экспрессов с риск-метрикой.
- **arbitrage** — 2-way и 3-way арбитраж с optimal stakes.
- **simulation** — Monte Carlo симуляция матчей.
- **league_power** — агрегированная статистика лиги (home/draw/away %).
- **form_analyzer** — анализ формы команды с streak emoji.
- **goalscorer** — Poisson-модель вероятности забить гол.
- **reports** — bankroll report, weekly summary.
- **rate_limiter** — token bucket для защиты от флуда.
- **i18n** — переводы на 4 языка (ru/en/uk/kz).
- **cache_store** — in-memory cache с TTL и тэгами.
- **user_preferences** — per-user настройки.
- **webhook_publisher** — интеграция с внешними сервисами.
- **retry** — exponential backoff с jitter.
- **circuit_breaker** — защита от шторма ошибок.
- **normalizer** — decimal/american/fractional форматы коэф.
- **odds_history** — трекинг line movements.
- **health_check** — мониторинг компонентов.
- **user_stats** — ROI/hit_rate/streaks per user.
- **season_tracker** — динамика команд по сезону.
- **text_processor** — translit/fuzzy/pluralize.
- **bet_journal** — персональный дневник ставок.
- **metrics_collector** — counters/gauges/histograms.
- **backtester** — бэктест стратегий на истории.
- **value_filter** — фильтры и pipeline value bets.
- **time_utils** — форматирование времени (сегодня/завтра/...).
- **leaderboard_service** — глобальный рейтинг пользователей.
- **feature_flags** — rollout по % / whitelist / blacklist.
- **event_store** — audit log всех действий.
- **message_templates** — все длинные тексты в одном файле.
- **schedule_optimizer** — оптимизация polling интервалов.

### Handlers
- `/bankroll` — калькулятор Kelly.
- `/parlay` — экспресс калькулятор.
- `/arb2`, `/arb3` — поиск арбитражей.
- `/simulate` — Monte Carlo симуляция.
- `/strategy` — выбор стратегии.
- Остальные handlers обновлены с value-сортировкой.

### Core
- Ensemble 0.6 Poisson + 0.4 Glicko.
- AccuracyBoost: травмы → −40 к Glicko, форма → ±15% к xG.
- Унифицированная сортировка value bets по descending.

### Documentation
- DOCUMENTATION.md — полная техдокументация.
- docs/STRATEGIES.md — гид по стратегиям.
- docs/API_ENDPOINTS.md — полный справочник SStats эндпоинтов.
- docs/API_REFERENCE.md — API клиент.
- docs/ARCHITECTURE.md — архитектура.
- docs/DEPLOYMENT.md — развертывание.
- docs/FEATURES.md — список фич.
- docs/TROUBLESHOOTING.md — FAQ по ошибкам.
- docs/USER_GUIDE.md — гид пользователя.
- docs/ROADMAP.md — roadmap.
- docs/PROMPTS.md — шаблоны промптов.
- docs/FAQ.md — часто задаваемые вопросы.

### Testing
- 536+ тестов покрывают все сервисы и модели.
- CI: ruff → mypy → pytest, все стадии зелёные.

## Метрики качества

| Метрика | Значение |
|---|---|
| Строк кода (Python + Markdown) | 19870+ |
| Тесты | 536+ passing |
| Lint errors | 0 |
| SStats endpoints mapped | 25/25 |
| Языки | ru, en, uk, kz |
| Стратегий ставок | 7 |
| Размер запроса по API | 5-100 KB |

## Благодарности

- SStats.net за отличный API.
- aiogram 3 — лучший фреймворк для Telegram-ботов.
- Все внешние зависимости: см. `requirements.txt`.

## Roadmap дальнейших улучшений

### Краткосрочное (v1.0)
- Поддержка реальной БД PostgreSQL вместо SQLite для production.
- Интеграция с Telegram Stars для оплаты подписок.
- Redis для распределённого кэша (когда бот масштабируется).
- Prometheus metrics endpoint для Grafana-дашбордов.
- Sentry для tracking runtime errors.
- Админ-панель в виде веб-интерфейса (опционально).

### Среднесрочное (v1.5)
- ML-поверх ансамбля: LightGBM boosting на исторических данных SStats.
- Интеграция с дополнительными источниками коэф (OddsAPI, BetsAPI).
- A/B тестирование стратегий через feature_flags.
- Персональная рекомендация стратегии на основе статистики пользователя.
- Предсказательный stake-sizing на основе calibration plot.

### Долгосрочное (v2.0)
- Полноценный мульти-пользовательский режим с ролями.
- Публичное API для сторонних разработчиков.
- Мобильное приложение (iOS/Android) с push-нотификациями.
- Расширение на другие виды спорта (хоккей, баскетбол, теннис).
- Поддержка криптоплатежей (USDT, BTC).

## Технический долг

- [ ] Перенести in-memory analytics/bet_journal в БД.
- [ ] Заменить все `datetime.utcnow()` на `datetime.now(UTC)`.
- [ ] Добавить integration-тесты handler → service → API.
- [ ] Ускорить ensemble computations через vectorization (numpy).
- [ ] Добавить rate-limited middleware для всех handlers.

## Производительность

- Запуск холодного приложения: 1.5–2 сек.
- Memory footprint: 80–120 МБ.
- Throughput на CI: 500 тестов / 5 сек = 100 т/с.
- Прогноз на матч: 150–400 мс (включая SStats round-trip).
- Monte Carlo 5000 runs: 30–50 мс.

## Совместимость

- Python: 3.11+
- aiogram: 3.4+
- SQLAlchemy: 2.0+
- aiohttp: 3.9+
- loguru: 0.7+
- pytest: 8.0+
- ruff: 0.3+
- Linux (Ubuntu 22.04/24.04), macOS, Windows (через WSL).

