"""Value engine — единое ядро оценки главного прогноза.

Считаем для (probability, odds) расширенный набор показателей:
  • fair_odds = 1/p (честный коэффициент по формуле);
  • ev_pct = (p * odds - 1) * 100 (валуйность в процентах);
  • kelly = (b*p - q) / b (доля Келли);
  • verdict ∈ {"брать", "осторожно", "не брать"};
  • composite — единый score для сортировки прогнозов по «валуйности при
    разумной вероятности»;
  • accept — булево «попадает в выборку «брать»».

Цели:
  1. Уйти от сортировки топа по чистой вероятности — пользователь хочет
     «не самый высокий процент, а самый валуйный, при этом вероятная
     ставка».
  2. Гарантировать единое определение «вердикт = брать» по всему боту —
     чтобы массовый анализ и анализ прогнозов смотрели на одно и то же.
  3. Дать одну функцию `select_best_pick`, которой пользуются все
     поверхностные ленты (Топ дня, массовый анализ, анализ прогнозов и
     т.п.).

Пороги вынесены в константы и могут быть переопределены через
параметры — никакой магии, чистая математика.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# ── Пороги «вердикта» ─────────────────────────────────────────
# Минимальная вероятность модели, ниже которой пик в принципе не идёт
# в выборку «брать». 45% — после анализа исторических CSV (выбрасывали
# `Carabobo`, `Cobreloa`, `River Plate Asunción` с p ≈ 40-49%, все LOSS).
# Подняли с 0.35 → 0.45 чтобы не показывать «брать» с реальным шансом
# проиграть >55%.
MIN_PROB_TAKE = 0.55
# Минимальная валуйность (EV %), которую считаем «настоящей валуйкой».
# Подняли 3.0 → 5.0 — на коротких выборках 3% EV не отличим от шума,
# а на длинных дистанциях 5% EV даёт стабильный +ROI после маржи.
MIN_VALUE_PCT_TAKE = 7.0
# «Осторожно» — между «брать» и «не брать»: пик имеет небольшую
# валуйность или вероятность чуть ниже основного порога.
MIN_PROB_CAUTION = 0.38
MIN_VALUE_PCT_CAUTION = 2.0
# Максимальная разумная вероятность, чтобы не плодить «П1 при 99%»
# из-за коллапса калибратора.
MAX_PROB_SANE = 0.97
# ── Санити для реальных кф букмекера ─────────────────────────
# Бывает, что в `odds_map` приходят кфы из соседнего рынка (баг
# маппинга): для «двойной шанс 12 при p=0.69» кф 32.68 при честном
# 1.45 — это не валуй +795%, это мусор. Защита: если real_odds
# отклоняется от честного больше чем в `MAX_REAL_TO_FAIR` раз
# или меньше чем в `MIN_REAL_TO_FAIR` — игнорируем real_odds.
MAX_REAL_TO_FAIR = 1.8
MIN_REAL_TO_FAIR = 0.55
# Минимальный fair_odds (1/p) для попадания в выдачу.
# Если кф < 1.30 — слишком «очевидная» ставка, фильтруем.
MIN_FAIR_ODDS = 1.30


def _is_sane_real_odds(odds: float | None, fair: float) -> bool:
    if odds is None or odds <= 1.01 or fair <= 1.0:
        return False
    ratio = odds / fair
    return MIN_REAL_TO_FAIR <= ratio <= MAX_REAL_TO_FAIR


@dataclass(slots=True)
class PickScore:
    market_key: str
    probability: float
    odds: float | None       # реальный кф букмекера (None если нет данных)
    fair_odds: float          # честный кф = 1/p
    ev_pct: float             # валуйность %
    kelly: float              # доля Келли (0..1)
    verdict: str              # "брать" / "осторожно" / "не брать"
    composite: float          # score для сортировки (см. _composite_score)
    accept: bool              # True если verdict == "брать"


def _kelly(prob: float, odds: float) -> float:
    if odds <= 1.0 or prob <= 0.0 or prob >= 1.0:
        return 0.0
    b = odds - 1.0
    q = 1.0 - prob
    return max((b * prob - q) / b, 0.0)


def _ev_pct(prob: float, odds: float | None) -> float:
    if odds is None or odds <= 1.0:
        return 0.0
    return (prob * odds - 1.0) * 100.0


def _fair_odds(prob: float) -> float:
    if prob <= 0.0:
        return 0.0
    return 1.0 / max(prob, 1e-6)


def _composite_score(prob: float, odds: float | None) -> float:
    """Композитный score для сортировки пиков.

    Идея: «валуйный И вероятный». Берём EV (в долях) и взвешиваем его
    sqrt(p), чтобы при равной валуйности предпочесть более вероятный
    пик. Если кфа нет — score = 0 (такие пики идут в самый низ).
    """
    if odds is None or odds <= 1.0 or prob <= 0.0:
        return 0.0
    ev = prob * odds - 1.0
    if ev <= 0.0:
        # Отрицательную валуйность не «спасаем» вероятностью — пусть
        # уходит в хвост сортировки.
        return ev * (1.0 - math.sqrt(max(prob, 0.0)))
    return ev * math.sqrt(max(prob, 0.0))


def _verdict(prob: float, ev_pct: float, kelly: float) -> str:
    """Чистая функция вердикта.

    Жёсткое «не брать», если:
      * вероятность < `MIN_PROB_CAUTION`;
      * EV ≤ 0 (нет валуйности);
      * вероятность > `MAX_PROB_SANE` (модель явно перекалибровала).
    """
    if prob <= 0.0 or prob > MAX_PROB_SANE:
        return "не брать"
    fair = 1.0 / max(prob, 1e-6)
    if fair < MIN_FAIR_ODDS:
        return "не брать"
    if ev_pct <= 0.0:
        return "не брать"
    if prob >= MIN_PROB_TAKE and ev_pct >= MIN_VALUE_PCT_TAKE and kelly > 0.0:
        return "брать"
    if prob >= MIN_PROB_CAUTION and ev_pct >= MIN_VALUE_PCT_CAUTION:
        return "осторожно"
    return "не брать"


def score_pick(
    *,
    market_key: str,
    probability: float,
    odds: float | None,
    market_blocked: bool = False,
) -> PickScore:
    """Оценить один пик — вернуть `PickScore`.

    Параметр ``market_blocked`` (по умолчанию False) — если True, вердикт
    «брать» автоматически понижается до «осторожно» независимо от EV.
    Используется `MarketFilter` для блокировки рынков с систематически
    отрицательным CLV.
    """
    p = max(0.0, min(1.0, float(probability)))
    o_raw = float(odds) if odds is not None and odds > 0 else None
    fair = _fair_odds(p) if p > 0 else 0.0
    # Санити: отбрасываем кривые real_odds (мусор от букмекера
    # или неправильный маппинг рынка).
    o = o_raw if _is_sane_real_odds(o_raw, fair) else None
    ev = _ev_pct(p, o)
    kelly = _kelly(p, o) if o is not None else 0.0
    verdict = _verdict(p, ev, kelly)
    if market_blocked and verdict == "брать":
        verdict = "осторожно"
    composite = _composite_score(p, o)
    return PickScore(
        market_key=market_key,
        probability=p,
        odds=o,
        fair_odds=round(fair, 4),
        ev_pct=round(ev, 4),
        kelly=round(kelly, 6),
        verdict=verdict,
        composite=round(composite, 6),
        accept=verdict == "брать",
    )


def select_best_pick(
    probabilities: dict[str, float],
    odds_map: dict[str, float] | None = None,
    *,
    accept_only: bool = True,
    fallback_to_caution: bool = True,
    market_filter: object | None = None,
) -> PickScore | None:
    """Найти лучший пик по матчу.

    Алгоритм:
      1) Считаем `PickScore` для каждого ключа (учитывая реальные кф).
      2) Если `accept_only=True` и есть пики с verdict="брать" — берём
         из них с максимальным composite score.
      3) Иначе при `fallback_to_caution=True` — берём «осторожно».
      4) Иначе — None.

    Параметр ``market_filter`` (опциональный) — объект с методом
    ``is_blocked(market_key, model_prob) -> bool``: если возвращает True,
    пик не получит вердикт «брать» (понижается до «осторожно»). Это
    блокирует рынки с систематически отрицательным CLV (см. MarketFilter).
    """
    if not probabilities:
        return None
    odds_map = odds_map or {}

    scored: list[PickScore] = []
    for key, prob in probabilities.items():
        if not isinstance(key, str):
            continue
        odd_raw = odds_map.get(key)
        odd_f: float | None
        try:
            odd_f = (
                float(odd_raw)
                if odd_raw is not None and float(odd_raw) > 1.01
                else None
            )
        except (TypeError, ValueError):
            odd_f = None
        blocked = False
        if market_filter is not None:
            try:
                blocked = bool(market_filter.is_blocked(key, float(prob)))  # type: ignore[attr-defined]
            except Exception:
                blocked = False
        scored.append(
            score_pick(
                market_key=key,
                probability=float(prob),
                odds=odd_f,
                market_blocked=blocked,
            )
        )

    if not scored:
        return None

    take = [s for s in scored if s.verdict == "брать"]
    if take:
        return max(take, key=lambda s: (s.composite, s.probability))
    if not accept_only:
        # Без фильтра — отдаём лучший composite среди всех.
        return max(scored, key=lambda s: (s.composite, s.probability))
    if fallback_to_caution:
        caution = [s for s in scored if s.verdict == "осторожно"]
        if caution:
            return max(caution, key=lambda s: (s.composite, s.probability))
    return None


__all__ = [
    "MAX_PROB_SANE",
    "MAX_REAL_TO_FAIR",
    "MIN_FAIR_ODDS",
    "MIN_PROB_CAUTION",
    "MIN_PROB_TAKE",
    "MIN_REAL_TO_FAIR",
    "MIN_VALUE_PCT_CAUTION",
    "MIN_VALUE_PCT_TAKE",
    "PickScore",
    "score_pick",
    "select_best_pick",
]
