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


__all__ = ["AdminStates", "FeedbackStates", "MatchSearchStates"]
