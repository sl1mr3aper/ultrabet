"""Репозитории работы с БД."""

from db.repositories.feedback_repo import FeedbackRepository
from db.repositories.payment_repo import PaymentRepository
from db.repositories.prediction_repo import PredictionLogRepository
from db.repositories.query_history_repo import QueryHistoryRepository
from db.repositories.user_repo import UserRepository

__all__ = [
    "FeedbackRepository",
    "PaymentRepository",
    "PredictionLogRepository",
    "QueryHistoryRepository",
    "UserRepository",
]
