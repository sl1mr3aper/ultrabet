"""Исключения SStats API."""

from __future__ import annotations


class SStatsAPIError(Exception):
    """Базовое исключение клиента SStats."""


class APIConnectionError(SStatsAPIError):
    """Ошибка соединения с API."""


class APITimeoutError(SStatsAPIError):
    """Таймаут запроса."""


class APINotFoundError(SStatsAPIError):
    """Ресурс не найден (404)."""


class APIRateLimitError(SStatsAPIError):
    """Превышен лимит запросов (429)."""

    def __init__(self, message: str, retry_after: float = 10.0) -> None:
        super().__init__(message)
        # Пол в 10с: даём API полноценно отдохнуть, прежде чем ретраить.
        self.retry_after = max(retry_after, 10.0)


class APIInvalidDataError(SStatsAPIError):
    """Невалидный ответ от API."""


__all__ = [
    "APIConnectionError",
    "APIInvalidDataError",
    "APINotFoundError",
    "APIRateLimitError",
    "APITimeoutError",
    "SStatsAPIError",
]
