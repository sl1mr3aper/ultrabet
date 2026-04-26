"""Line-shopping: ищет лучшие коэффициенты по разным букмекерам в одном матче."""

from __future__ import annotations

from dataclasses import dataclass

from api.sstats_client import SStatsClient


@dataclass(slots=True)
class BookmakerOffer:
    bookmaker_id: int
    bookmaker_name: str
    odds: float


@dataclass(slots=True)
class MarketSnapshot:
    market_key: str
    selection: str
    offers: list[BookmakerOffer]

    @property
    def best(self) -> BookmakerOffer | None:
        return max(self.offers, key=lambda o: o.odds) if self.offers else None

    @property
    def worst(self) -> BookmakerOffer | None:
        return min(self.offers, key=lambda o: o.odds) if self.offers else None

    @property
    def spread_pct(self) -> float:
        if not self.offers or len(self.offers) < 2:
            return 0.0
        b, w = self.best, self.worst
        if not b or not w or w.odds <= 0:
            return 0.0
        return (b.odds / w.odds - 1.0) * 100.0


class LineShoppingService:
    """Сравнивает коэффициенты разных букмекеров для конкретного матча.

    Возвращает словарь market_key → MarketSnapshot.
    """

    def __init__(self, sstats: SStatsClient) -> None:
        self._sstats = sstats

    async def compare(
        self, game_id: int, market_keys: list[str]
    ) -> dict[str, MarketSnapshot]:
        odds_data = await self._sstats.get_prematch_odds(game_id)
        bookmakers = await self._sstats.list_bookmakers()
        bk_names = {bk.get("id"): bk.get("name") or "?" for bk in bookmakers if bk.get("id")}
        result: dict[str, MarketSnapshot] = {}
        if not isinstance(odds_data, dict):
            return result
        markets = odds_data.get("markets") or []
        for mk in market_keys:
            offers: list[BookmakerOffer] = []
            for entry in markets:
                if not isinstance(entry, dict):
                    continue
                if entry.get("key") != mk and entry.get("name") != mk:
                    continue
                for offer in entry.get("offers") or []:
                    if not isinstance(offer, dict):
                        continue
                    bid = offer.get("bookmakerId") or offer.get("bookmaker_id")
                    odds = offer.get("odds")
                    if bid is None or odds is None:
                        continue
                    try:
                        offers.append(
                            BookmakerOffer(
                                bookmaker_id=int(bid),
                                bookmaker_name=bk_names.get(int(bid)) or "?",
                                odds=float(odds),
                            )
                        )
                    except (TypeError, ValueError):
                        continue
            offers.sort(key=lambda o: o.odds, reverse=True)
            result[mk] = MarketSnapshot(market_key=mk, selection=mk, offers=offers)
        return result


__all__ = ["BookmakerOffer", "LineShoppingService", "MarketSnapshot"]
