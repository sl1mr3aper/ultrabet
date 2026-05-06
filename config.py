"""Глобальная конфигурация бота (pydantic-settings)."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Telegram ────────────────────────────────────────────
    bot_token: SecretStr = Field(..., description="Токен бота от @BotFather")
    bot_username: str = Field("ultrabet_predictions_bot")
    admin_ids: str | list[int] = Field(default_factory=list)
    timezone_offset: int = Field(3, ge=-12, le=12)

    # ── SStats API ──────────────────────────────────────────
    sstats_api_key: SecretStr | None = Field(default=None)
    sstats_base_url: str = Field("https://api.sstats.net")
    sstats_timeout: int = Field(30, ge=5, le=120)
    sstats_max_retries: int = Field(3, ge=0, le=10)

    # ── Free tier / billing ─────────────────────────────────
    free_predictions_initial: int = Field(5, ge=0)
    referral_bonus_signup: int = Field(3, ge=0)
    referral_bonus_sub_1m: int = Field(5, ge=0)
    referral_bonus_sub_3m: int = Field(15, ge=0)
    referral_bonus_sub_12m: int = Field(45, ge=0)

    # ── Predictions ─────────────────────────────────────────
    top_predictions: int = Field(15, ge=1, le=50)
    top_value_bets: int = Field(15, ge=1, le=30)
    min_value_odds: float = Field(1.51, ge=1.01)
    min_value_percent: float = Field(2.0, ge=0.0)
    min_value_probability: float = Field(0.35, ge=0.0, le=1.0)
    subscription_daily_limit: int = Field(40, ge=1, le=200)

    # ── Cache TTL ───────────────────────────────────────────
    cache_ttl_teams: int = Field(3600)
    cache_ttl_matches: int = Field(900)
    cache_ttl_game: int = Field(300)
    cache_ttl_glicko: int = Field(600)
    cache_ttl_odds: int = Field(180)
    cache_ttl_leagues: int = Field(86400)

    # ── Database ────────────────────────────────────────────
    # Можно задать любой поддерживаемый SQLAlchemy async URL, например
    # postgresql+asyncpg://user:pass@host/db. По умолчанию — локальный SQLite.
    database_url: str = Field("sqlite+aiosqlite:///data/bot.db")

    # ── Redis (опциональный кэш-бэкенд) ─────────────────────
    # Если задан — сервисы будут использовать Redis для общего кэша,
    # иначе работаем на in-memory TTLCache без изменений поведения.
    redis_url: str | None = Field(default=None)

    # ── Logging ─────────────────────────────────────────────
    log_level: str = Field("INFO")
    log_file: str = Field("logs/bot.log")

    # ── AI / Gemini ─────────────────────────────────────────
    gemini_api_key: SecretStr | None = Field(default=None)
    gemini_model: str = Field("gemini-2.5-flash-lite")
    gemini_timeout: float = Field(15.0, ge=2.0, le=60.0)

    # ── Observability (опционально) ─────────────────────────
    # Sentry: если задан DSN — инициализируем sentry_sdk в main.py.
    sentry_dsn: SecretStr | None = Field(default=None)
    sentry_environment: str = Field("production")
    sentry_traces_sample_rate: float = Field(0.0, ge=0.0, le=1.0)
    # Prometheus: 0 → выключено; иначе HTTP-сервер на /metrics.
    prometheus_port: int = Field(0, ge=0, le=65535)

    # ── Бэкапы БД (используется scripts/db_backup.py) ───────
    backup_dir: str = Field("data/backups")
    backup_retention_days: int = Field(7, ge=0, le=3650)
    backup_s3_bucket: str | None = Field(default=None)
    backup_s3_prefix: str = Field("ultrabet")

    # ── Betfair Exchange API (опционально, для CLV-tracking) ─
    # Без этих credentials Betfair-интеграция отключается gracefully —
    # модель работает на SStats данных, CLV не считается.
    # Если заполнены — клиент логинится при старте и пишет closing line
    # в `pinnacle_closing_odds` (название историческое, теперь Betfair).
    betfair_app_key: SecretStr | None = Field(default=None)
    betfair_username: SecretStr | None = Field(default=None)
    betfair_password: SecretStr | None = Field(default=None)
    betfair_cert_pem_path: str | None = Field(default=None)
    betfair_cert_key_path: str | None = Field(default=None)
    # Минут до старта матча, когда снимаем closing line.
    betfair_close_capture_minutes: int = Field(15, ge=1, le=120)

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, value: object) -> list[int]:
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return [int(x) for x in value]
        if isinstance(value, str):
            return [int(x.strip()) for x in value.replace(";", ",").split(",") if x.strip()]
        if isinstance(value, int):
            return [value]
        return []

    @property
    def sstats_api_key_value(self) -> str | None:
        if self.sstats_api_key is None:
            return None
        secret = self.sstats_api_key.get_secret_value().strip()
        return secret or None

    @property
    def bot_token_value(self) -> str:
        return self.bot_token.get_secret_value()

    @property
    def gemini_api_key_value(self) -> str | None:
        if self.gemini_api_key is None:
            return None
        secret = self.gemini_api_key.get_secret_value().strip()
        return secret or None

    @property
    def sentry_dsn_value(self) -> str | None:
        if self.sentry_dsn is None:
            return None
        secret = self.sentry_dsn.get_secret_value().strip()
        return secret or None

    @property
    def betfair_app_key_value(self) -> str | None:
        if self.betfair_app_key is None:
            return None
        v = self.betfair_app_key.get_secret_value().strip()
        return v or None

    @property
    def betfair_username_value(self) -> str | None:
        if self.betfair_username is None:
            return None
        v = self.betfair_username.get_secret_value().strip()
        return v or None

    @property
    def betfair_password_value(self) -> str | None:
        if self.betfair_password is None:
            return None
        v = self.betfair_password.get_secret_value().strip()
        return v or None

    @property
    def betfair_enabled(self) -> bool:
        """True если есть достаточно credentials для логина в Betfair."""
        if not self.betfair_app_key_value:
            return False
        # Cert-based auth ИЛИ password-based.
        has_cert = bool(self.betfair_cert_pem_path and self.betfair_cert_key_path)
        has_pwd = bool(self.betfair_username_value and self.betfair_password_value)
        return has_cert or has_pwd

    def ensure_dirs(self) -> None:
        (PROJECT_ROOT / "data").mkdir(parents=True, exist_ok=True)
        (PROJECT_ROOT / "logs").mkdir(parents=True, exist_ok=True)
        (PROJECT_ROOT / self.backup_dir).mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
        _settings.ensure_dirs()
    return _settings
