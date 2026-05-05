"""SQLAlchemy модели."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class Base(DeclarativeBase):
    """Базовый класс моделей."""


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    language_code: Mapped[str | None] = mapped_column(String(8), nullable=True, default="ru")

    # Подписка
    subscription_plan: Mapped[str | None] = mapped_column(String(8), nullable=True)
    subscription_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    subscription_daily_quota: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Когда последний раз уведомили об истечении подписки (чтобы не спамить).
    subscription_expired_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Бесплатные / бонусные прогнозы
    free_predictions_left: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bonus_predictions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Дневной лимит
    daily_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    daily_reset_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Реферальная система
    referral_code: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    referred_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    referral_signup_bonus_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    referral_sub_bonus_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Метаданные
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    badge: Mapped[str] = mapped_column(String(8), default="", nullable=False)
    strategy: Mapped[str | None] = mapped_column(String(16), default="balanced", nullable=True)
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
        nullable=False,
    )

    # Связи
    referrer: Mapped[User | None] = relationship(
        "User", remote_side="User.id", foreign_keys=[referred_by_id]
    )

    def display_name(self) -> str:
        if self.username:
            return f"@{self.username}"
        parts = [p for p in (self.first_name, self.last_name) if p]
        return " ".join(parts) or f"user{self.tg_id}"


class Referral(Base):
    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    referrer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    referred_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subscription_plan: Mapped[str | None] = mapped_column(String(8), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("referrer_id", "referred_id", name="uq_referrer_referred"),
    )


class PaymentLog(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_code: Mapped[str] = mapped_column(String(8), nullable=False)
    amount: Mapped[float] = mapped_column(nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="RUB", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    provider: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), nullable=False
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PredictionLog(Base):
    __tablename__ = "prediction_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    game_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    home_name: Mapped[str] = mapped_column(String(128), nullable=False)
    away_name: Mapped[str] = mapped_column(String(128), nullable=False)
    league_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    home_xg: Mapped[float] = mapped_column(default=0.0, nullable=False)
    away_xg: Mapped[float] = mapped_column(default=0.0, nullable=False)
    home_rating: Mapped[float] = mapped_column(default=1500.0, nullable=False)
    away_rating: Mapped[float] = mapped_column(default=1500.0, nullable=False)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_predlogs_user_created", "user_id", "created_at"),)


class QueryHistory(Base):
    __tablename__ = "query_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    query_text: Mapped[str] = mapped_column(String(256), nullable=False)
    matched_game_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), nullable=False
    )


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), nullable=False
    )


class MatchResult(Base):
    """Историческая запись сыгранного матча для self-learning.

    Заполняется фоновой задачей из SStats /Games/list с order=-1 по лигам.
    Используется `SelfLearner` для пересчёта весов ансамбля по реальным
    результатам.
    """

    __tablename__ = "match_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    league_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    league_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    country_name: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    home_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    away_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    home_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    away_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    home_xg: Mapped[float | None] = mapped_column(nullable=True)
    away_xg: Mapped[float | None] = mapped_column(nullable=True)
    home_rating: Mapped[float | None] = mapped_column(nullable=True)
    away_rating: Mapped[float | None] = mapped_column(nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), nullable=False
    )
    __table_args__ = (
        Index("ix_match_results_home_away", "home_id", "away_id"),
        Index("ix_match_results_date_desc", "date"),
    )


class PredictionCache(Base):
    """Кэш сгенерированного отчёта по матчу.

    Используется при повторных кликах: если кэш свежий, отдаём отчёт
    мгновенно без пересчёта. Инвалидируется кнопкой «🔄 обновить».
    """

    __tablename__ = "prediction_cache"

    game_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    rendered_text: Mapped[str] = mapped_column(Text, nullable=False)
    is_live: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_finished: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
        nullable=False,
    )


class PredictionOutcome(Base):
    """Наш прогноз + реальный исход — для feedback loop self-learning."""

    __tablename__ = "prediction_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    market_key: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    predicted_probability: Mapped[float] = mapped_column(nullable=False)
    actual_odds: Mapped[float | None] = mapped_column(nullable=True)
    # Закрывающий кф Pinnacle/Betfair (фиксируем за 5 мин до старта).
    # Используется для расчёта CLV = prob × closing_odds - 1.
    closing_odds: Mapped[float | None] = mapped_column(nullable=True)
    # Closing Line Value: насколько наш прогноз превзошёл рыночную «правду».
    # >0 → бьём рынок (потенциально + ROI), <0 → проигрываем рынку.
    clv: Mapped[float | None] = mapped_column(nullable=True)
    # Лига и рынок-категория для per-league/per-market калибровки.
    league_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    market_category: Mapped[str | None] = mapped_column(String(24), nullable=True)
    # итог: True = рынок сыграл, False = нет, None = пока неизвестно
    hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), nullable=False
    )
    evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    __table_args__ = (
        Index("ix_pred_outcome_game_market", "game_id", "market_key"),
    )


class LeagueStanding(Base):
    """Кэш турнирной таблицы лиги для быстрых отрисовок и автообновления.

    Заполняется фоном `LeagueStandingsService` (обновление раз в час)
    и из inline-запросов (если кэш пуст). Используется в:
    - UI-вкладке «📋 Турнирная таблица» (внутри лиги),
    - корректировке вероятностей через `adjust_for_standings`.
    """

    __tablename__ = "league_standings"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True,
    )
    league_id: Mapped[int] = mapped_column(
        BigInteger, index=True, nullable=False,
    )
    season_uid: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True,
    )
    team_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    team_name: Mapped[str] = mapped_column(String(128), nullable=False)
    team_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    played: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    wins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    draws: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    losses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    goals_for: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    goals_against: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
    )
    goal_diff: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    country_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
    )
    league_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "league_id", "team_id", name="uq_league_standing_team",
        ),
        Index("ix_league_standing_league_rank", "league_id", "team_rank"),
    )


class CalibrationSnapshot(Base):
    """Сохранённая изотоническая кривая калибровки по рынку.

    Обновляется ежедневно `CalibrationService`:
    фитим `IsotonicRegression` на `(p_raw → hit 0/1)` из `PredictionOutcome`
    за последние 90 дней по каждому market_key. Храним опорные точки
    как JSON, потом делаем интерполяцию при инференсе.
    """

    __tablename__ = "calibration_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_key: Mapped[str] = mapped_column(
        String(48), nullable=False, index=True
    )
    # curve_json: [{ "x": float, "y": float }, ...], по возрастанию x
    curve_json: Mapped[str] = mapped_column(Text, nullable=False)
    fit_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    brier_before: Mapped[float | None] = mapped_column(nullable=True)
    brier_after: Mapped[float | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
        nullable=False,
        index=True,
    )


class LeagueAggregate(Base):
    """Агрегаты лиги, считающиеся фоном из MatchResult.

    Используется для:
    * подстановки `league_avg_total` в xG-расчёт (вместо хардкода 2.7),
    * показа «Ср. тотал лиги» в отчёте (даже когда SStats не отдал
      `season_table`),
    * `btts_rate` / `home_win_rate` / `over_25_rate` для регулятора и
      market_filter (не использовать рынки, исторически проигрывающие).

    Перерасчёт раз в 6 часов, окно — все доступные `MatchResult` (или
    последние `lookback_games` если будем сужать). Уникальность по
    `league_id` (не по сезону) — для большинства лиг этого достаточно.
    """

    __tablename__ = "league_aggregates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    league_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, index=True, nullable=False,
    )
    league_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    country_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    n_matches: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_total_goals: Mapped[float | None] = mapped_column(nullable=True)
    avg_home_goals: Mapped[float | None] = mapped_column(nullable=True)
    avg_away_goals: Mapped[float | None] = mapped_column(nullable=True)
    btts_rate: Mapped[float | None] = mapped_column(nullable=True)
    home_win_rate: Mapped[float | None] = mapped_column(nullable=True)
    draw_rate: Mapped[float | None] = mapped_column(nullable=True)
    over_25_rate: Mapped[float | None] = mapped_column(nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
        nullable=False,
    )


class PinnacleClosingOdds(Base):
    """Снимок закрывающих кф Pinnacle/Betfair для CLV-метрики.

    Заполняется фоновой задачей за ~5 минут до старта матча. Используется
    `SelfLearner` для расчёта Closing Line Value (`prob × close_odds - 1`)
    — единственная индустрия-стандартная метрика «обыгрываем ли мы рынок».

    Если для матча нет закрывающего кф — поле в `PredictionOutcome.closing_odds`
    остаётся `None`, CLV не считается, но прогноз всё равно идёт в обычную
    калибровку.
    """

    __tablename__ = "pinnacle_closing_odds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    market_key: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    closing_odds: Mapped[float] = mapped_column(nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "game_id", "market_key", name="uq_pinnacle_closing_game_market",
        ),
        Index("ix_pinnacle_closing_game", "game_id"),
    )


class BacktestResult(Base):
    """Результаты бэктеста за конкретную дату.

    Сохраняется при каждом запуске анализа. Используется для
    корректировки прогнозов — SelfLearner читает агрегированные
    hit_rate / avg_brier и подтягивает калибровку.
    """

    __tablename__ = "backtest_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    game_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    home_name: Mapped[str] = mapped_column(String(128), nullable=False)
    away_name: Mapped[str] = mapped_column(String(128), nullable=False)
    league_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    market_key: Mapped[str] = mapped_column(String(48), nullable=False)
    probability: Mapped[float] = mapped_column(nullable=False)
    fair_odds: Mapped[float] = mapped_column(nullable=False)
    home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("date", "game_id", name="uq_backtest_date_game"),
        Index("ix_backtest_date_hit", "date", "hit"),
    )


class MatchPickHistory(Base):
    """Полная история ВСЕХ пиков по матчу (а не только главного).

    В отличие от `prediction_outcomes` (один main pick на матч), сюда
    пишется КАЖДЫЙ из ~40 рынков, которые модель посчитала. Это нужно
    чтобы калибратор учитывал условные вероятности типа «когда главный
    пик пролетел и счёт получился X:Y, какие из вторичных пиков обычно
    заходят».

    Заполняется автоматически:
      * `PredictionService.predict()` — на каждый live-прогноз
      * `Backtester.simulate()` — на каждый бэктест (с `is_backtest=True`)

    После того как матч завершился, `SelfLearner.evaluate_pending`
    проставляет `hit` (через `MarketResolver`).

    Используется `SecondaryPickCalibrator` для подсчёта
    per-market `adjustment_factor`.
    """

    __tablename__ = "match_pick_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    league_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, index=True,
    )
    market_key: Mapped[str] = mapped_column(
        String(48), nullable=False, index=True,
    )
    market_category: Mapped[str | None] = mapped_column(
        String(24), nullable=True, index=True,
    )
    # Вероятность модели на момент прогноза (до калибровки или после
    # — храним «как показали пользователю»).
    predicted_probability: Mapped[float] = mapped_column(nullable=False)
    fair_odds: Mapped[float | None] = mapped_column(nullable=True)
    # Был ли этот пик главным (top-1 composite score) в рамках матча.
    is_main_pick: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True,
    )
    # Бэктест (на исторических данных) или live-прогноз пользователя.
    is_backtest: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True,
    )
    # Реальный результат после матча.
    home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True, index=True)
    # Зашёл ли главный пик матча. Заполняется при resolve, дублируется
    # на КАЖДЫЙ pick того же game_id чтобы быстро запрашивать
    # «пики при провале главного».
    main_pick_hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
        nullable=False,
    )
    evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "game_id", "market_key", "is_backtest",
            name="uq_pick_hist_game_market_btx",
        ),
        Index("ix_pick_hist_market_hit", "market_key", "hit"),
        Index("ix_pick_hist_main_hit", "is_main_pick", "main_pick_hit"),
    )


class PickAdjustment(Base):
    """Накопленный adjustment_factor на market_key из эмпирики.

    Создаётся `SecondaryPickCalibrator` (ежедневный cron):
      * Для каждого market_key считаем empirical hit-rate из
        `match_pick_history` (>=30 семплов).
      * Сравниваем с avg(predicted_probability) того же market_key.
      * `adjustment_factor = empirical / predicted` (clip [0.5, 1.5]).
      * Дополнительно — отдельный adjustment для условия
        `main_pick_hit=False` (если главный пик пролетел).

    Применяется в `value_engine.score_pick()`: умножаем probability
    на factor перед расчётом EV. Это меняет решение «брать/не брать»
    в сторону рынков, где модель действительно точнее.
    """

    __tablename__ = "pick_adjustments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_key: Mapped[str] = mapped_column(
        String(48), nullable=False, index=True,
    )
    # "any" — общий, "main_lost" — условный когда главный пик пролетел.
    condition: Mapped[str] = mapped_column(
        String(16), nullable=False, default="any", index=True,
    )
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    empirical_hit_rate: Mapped[float] = mapped_column(nullable=False)
    avg_predicted_prob: Mapped[float] = mapped_column(nullable=False)
    adjustment_factor: Mapped[float] = mapped_column(nullable=False, default=1.0)
    confidence: Mapped[float] = mapped_column(nullable=False, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "market_key", "condition", name="uq_pick_adjust_market_cond",
        ),
        Index(
            "ix_pick_adjust_lookup", "market_key", "condition",
        ),
    )


__all__ = [
    "BacktestResult",
    "Base",
    "CalibrationSnapshot",
    "Feedback",
    "LeagueAggregate",
    "LeagueStanding",
    "MatchPickHistory",
    "MatchResult",
    "PaymentLog",
    "PickAdjustment",
    "PinnacleClosingOdds",
    "PredictionCache",
    "PredictionLog",
    "PredictionOutcome",
    "QueryHistory",
    "Referral",
    "User",
]
