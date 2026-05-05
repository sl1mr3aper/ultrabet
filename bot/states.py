"""Состояния FSM."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class MatchSearchStates(StatesGroup):
    waiting_for_query = State()
    choosing_home_team = State()
    choosing_away_team = State()
    choosing_country = State()


class FeedbackStates(StatesGroup):
    waiting_for_text = State()


class AdminStates(StatesGroup):
    waiting_for_broadcast = State()
    waiting_for_user_id = State()
    waiting_for_backtest_date = State()
    # Массовый анализ (по дате) — пользователь вводит ГГГГ-ММ-ДД.
    waiting_for_mass_analysis_date = State()
    # Анализ прогнозов: сначала спросим дату, потом количество.
    waiting_for_prediction_date = State()
    waiting_for_prediction_count = State()


class LeagueSearchStates(StatesGroup):
    waiting_for_query = State()


class MatchesPageStates(StatesGroup):
    """Пользователь ввёл номер страницы в разделе «Матчи сегодня/завтра»."""

    waiting_for_page_today = State()
    waiting_for_page_tomorrow = State()
    waiting_for_page_live = State()


__all__ = [
    "AdminStates",
    "FeedbackStates",
    "LeagueSearchStates",
    "MatchSearchStates",
    "MatchesPageStates",
]
