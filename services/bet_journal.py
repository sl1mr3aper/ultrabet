"""Персональный журнал ставок — как ставочный дневник.

Позволяет:
- записать ставку вручную,
- отметить её выигравшей/проигравшей/вернулась,
- удалить, редактировать,
- фильтровать по дате, букмекеру, рынку, исходу,
- экспортировать в CSV.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum


class BetStatus(str, Enum):
    PENDING = "pending"
    WON = "won"
    LOST = "lost"
    REFUND = "refund"  # возврат
    VOID = "void"  # отменена


@dataclass(slots=True)
class JournalEntry:
    entry_id: int
    user_id: int
    created_at: datetime
    event_name: str  # "Real Madrid vs Barcelona"
    league: str
    market: str  # "home", "over_2_5", ...
    bookmaker: str
    stake: float
    odds: float
    probability: float  # our estimate
    status: BetStatus = BetStatus.PENDING
    settled_at: datetime | None = None
    note: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class JournalSummary:
    total_bets: int
    settled_bets: int
    won: int
    lost: int
    refund: int
    void: int
    total_staked: float
    total_profit: float
    roi_pct: float
    hit_rate_pct: float


class BetJournal:
    def __init__(self) -> None:
        self._entries: dict[int, JournalEntry] = {}
        self._next_id = 1

    def add(
        self,
        *,
        user_id: int,
        event_name: str,
        league: str,
        market: str,
        bookmaker: str,
        stake: float,
        odds: float,
        probability: float = 0.0,
        note: str = "",
        tags: list[str] | None = None,
    ) -> JournalEntry:
        entry = JournalEntry(
            entry_id=self._next_id,
            user_id=user_id,
            created_at=datetime.utcnow(),
            event_name=event_name,
            league=league,
            market=market,
            bookmaker=bookmaker,
            stake=max(0.0, stake),
            odds=max(1.0, odds),
            probability=max(0.0, min(1.0, probability)),
            note=note,
            tags=tags or [],
        )
        self._entries[self._next_id] = entry
        self._next_id += 1
        return entry

    def settle(self, entry_id: int, status: BetStatus) -> JournalEntry | None:
        entry = self._entries.get(entry_id)
        if entry is None or entry.status is not BetStatus.PENDING:
            return None
        entry.status = status
        entry.settled_at = datetime.utcnow()
        return entry

    def delete(self, entry_id: int) -> bool:
        return self._entries.pop(entry_id, None) is not None

    def get(self, entry_id: int) -> JournalEntry | None:
        return self._entries.get(entry_id)

    def filter(
        self,
        *,
        user_id: int | None = None,
        status: BetStatus | None = None,
        bookmaker: str | None = None,
        market: str | None = None,
        league: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        tag: str | None = None,
    ) -> list[JournalEntry]:
        out: list[JournalEntry] = []
        for e in self._entries.values():
            if user_id is not None and e.user_id != user_id:
                continue
            if status is not None and e.status is not status:
                continue
            if bookmaker is not None and e.bookmaker != bookmaker:
                continue
            if market is not None and e.market != market:
                continue
            if league is not None and e.league != league:
                continue
            if date_from is not None and e.created_at.date() < date_from:
                continue
            if date_to is not None and e.created_at.date() > date_to:
                continue
            if tag is not None and tag not in e.tags:
                continue
            out.append(e)
        return out

    def summary(self, *, user_id: int | None = None) -> JournalSummary:
        entries = self.filter(user_id=user_id) if user_id is not None else list(
            self._entries.values()
        )
        total = len(entries)
        settled = [e for e in entries if e.status in {BetStatus.WON, BetStatus.LOST}]
        won = sum(1 for e in settled if e.status is BetStatus.WON)
        lost = sum(1 for e in settled if e.status is BetStatus.LOST)
        refund = sum(1 for e in entries if e.status is BetStatus.REFUND)
        void = sum(1 for e in entries if e.status is BetStatus.VOID)
        total_staked = sum(e.stake for e in entries if e.status is not BetStatus.VOID)
        profit = 0.0
        for e in settled:
            if e.status is BetStatus.WON:
                profit += e.stake * (e.odds - 1.0)
            elif e.status is BetStatus.LOST:
                profit -= e.stake
        return JournalSummary(
            total_bets=total,
            settled_bets=len(settled),
            won=won,
            lost=lost,
            refund=refund,
            void=void,
            total_staked=total_staked,
            total_profit=profit,
            roi_pct=(profit / total_staked * 100.0) if total_staked > 0 else 0.0,
            hit_rate_pct=(won / len(settled) * 100.0) if settled else 0.0,
        )

    def recent(self, *, user_id: int, days: int = 7) -> list[JournalEntry]:
        cutoff = date.today() - timedelta(days=days)
        return self.filter(user_id=user_id, date_from=cutoff)

    def all(self) -> list[JournalEntry]:
        return list(self._entries.values())

    def clear(self) -> None:
        self._entries.clear()
        self._next_id = 1


__all__ = ["BetJournal", "BetStatus", "JournalEntry", "JournalSummary"]
