"""Backtest: прогоняем historical CSV через новые пороги value_engine.

Использование:
    python scripts/backtest_csv_predictions.py path/to/file1.csv path/to/file2.csv

CSV должен содержать колонки:
    Результат (WIN/LOSS), Счёт, Рынок, КФ (1/p), Модель %, Зашёл

Скрипт показывает:
    * Старые метрики (как было): сколько пиков было «брать», ROI;
    * Новые метрики (после фильтра кф ≥ 1.30 и MIN_PROB_TAKE=0.45):
      сколько пиков остаётся «брать», их ROI;
    * Сколько отсеяно по причине «низкий кф» / «низкая вероятность».
"""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from pathlib import Path

from core.value_engine import (
    MIN_FAIR_ODDS,
    MIN_PROB_TAKE,
    MIN_VALUE_PCT_TAKE,
)


@dataclass(slots=True)
class Pick:
    """Один pick из CSV-отчёта."""
    market: str
    fair_odds: float
    model_prob: float
    won: bool


def parse_csv(path: Path) -> list[Pick]:
    picks: list[Pick] = []
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("Результат") or row["Результат"] not in {"WIN", "LOSS"}:
                continue
            try:
                fair = float(str(row["КФ (1/p)"]).replace(",", "."))
                prob_s = str(row["Модель %"]).replace("%", "").replace(",", ".")
                prob = float(prob_s) / 100.0
                won = row["Результат"].upper() == "WIN"
            except (KeyError, ValueError):
                continue
            picks.append(
                Pick(
                    market=row.get("Рынок", "?"),
                    fair_odds=fair,
                    model_prob=prob,
                    won=won,
                )
            )
    return picks


def evaluate(
    picks: list[Pick],
    *,
    min_fair: float,
    min_prob: float,
) -> tuple[int, int, float, float]:
    """Возвращает (N_picks, N_wins, profit, roi%).

    NB: в CSV есть только fair_odds (1/p), а не реальный book-кф. Поэтому
    профит считается при ставке на fair_odd — это «модельный break-even»,
    т.е. если модель калиброванная, ROI на длине будет ~0%. Реальный
    минус ROI в выборке (-32%) показывает миска́либрейт модели.
    """
    profit = 0.0
    n = 0
    wins = 0
    for p in picks:
        if p.fair_odds < min_fair:
            continue
        if p.model_prob < min_prob:
            continue
        n += 1
        if p.won:
            profit += p.fair_odds - 1.0
            wins += 1
        else:
            profit -= 1.0
    roi = (profit / n) * 100.0 if n > 0 else 0.0
    return n, wins, profit, roi


def main(paths: list[str]) -> None:
    print(f"Бэктест: MIN_FAIR_ODDS={MIN_FAIR_ODDS}, MIN_PROB_TAKE={MIN_PROB_TAKE}, "
          f"MIN_VALUE_PCT_TAKE={MIN_VALUE_PCT_TAKE}%")
    print("─" * 80)
    print()

    all_picks: list[Pick] = []
    for p in paths:
        picks = parse_csv(Path(p))
        all_picks.extend(picks)
        print(f"{p}: {len(picks)} пиков")

    print()
    print(f"ИТОГО: {len(all_picks)} пиков")
    print()

    # Оригинальные метрики (как в CSV — все пики «брать»).
    orig_n = len(all_picks)
    orig_wins = sum(1 for p in all_picks if p.won)
    orig_profit = sum(
        (p.fair_odds - 1.0) if p.won else -1.0 for p in all_picks
    )
    orig_roi = (orig_profit / orig_n) * 100.0 if orig_n > 0 else 0.0

    print("📉 СТАРЫЕ ПОРОГИ (MIN_PROB_TAKE=0.35, без фильтра кф ≥1.30):")
    print(f"   N={orig_n}, WIN={orig_wins}, ROI={orig_roi:+.1f}%, "
          f"profit={orig_profit:+.2f}u")

    # Новые пороги.
    n, wins, profit, roi = evaluate(
        all_picks, min_fair=MIN_FAIR_ODDS, min_prob=MIN_PROB_TAKE,
    )
    print()
    print("📈 НОВЫЕ ПОРОГИ:")
    print(
        f"   N={n}, WIN={wins}, ROI={roi:+.1f}%, "
        f"profit={profit:+.2f}u, "
        f"отсеяно {orig_n - n} пиков"
    )

    # Промежуточный вариант: только фильтр кф ≥ 1.30.
    n2, wins2, profit2, roi2 = evaluate(
        all_picks, min_fair=MIN_FAIR_ODDS, min_prob=0.0,
    )
    print()
    print("🔬 Только фильтр кф ≥1.30 (без поднятия MIN_PROB_TAKE):")
    print(
        f"   N={n2}, WIN={wins2}, ROI={roi2:+.1f}%, "
        f"profit={profit2:+.2f}u"
    )

    # Промежуточный вариант: только MIN_PROB_TAKE=0.45.
    n3, wins3, profit3, roi3 = evaluate(
        all_picks, min_fair=1.0, min_prob=0.45,
    )
    print()
    print("🔬 Только MIN_PROB_TAKE=0.45 (без фильтра кф):")
    print(
        f"   N={n3}, WIN={wins3}, ROI={roi3:+.1f}%, "
        f"profit={profit3:+.2f}u"
    )

    # Жёсткие пороги — для сценариев когда модель в принципе плохо
    # калибрована (как сейчас). Смотрим, что происходит при p ≥ 0.55.
    n4, wins4, profit4, roi4 = evaluate(
        all_picks, min_fair=MIN_FAIR_ODDS, min_prob=0.55,
    )
    print()
    print("🚧 Жёсткий: кф ≥1.30 + MIN_PROB_TAKE=0.55 (рискованно):")
    print(
        f"   N={n4}, WIN={wins4}, ROI={roi4:+.1f}%, "
        f"profit={profit4:+.2f}u"
    )

    # Только пики с p > 0.65 (которые модель «уверенно» предсказывает).
    n5, wins5, profit5, roi5 = evaluate(
        all_picks, min_fair=MIN_FAIR_ODDS, min_prob=0.65,
    )
    print()
    print("🎯 Высокая уверенность: кф ≥1.30 + MIN_PROB_TAKE=0.65:")
    print(
        f"   N={n5}, WIN={wins5}, ROI={roi5:+.1f}%, "
        f"profit={profit5:+.2f}u"
    )

    # Анализ по категориям рынков — где конкретно модель проигрывает.
    print()
    print("🔍 По категориям рынков:")
    cat_stat: dict[str, tuple[int, int, float]] = {}
    for p in all_picks:
        m = p.market.lower()
        if "оз" in m or "забь" in m:
            cat = "BTTS"
        elif "тб" in m or "тм" in m or "ИТБ" in p.market or "ИТМ" in p.market:
            cat = "Total/IT"
        elif "п1" in m or "п2" in m or "победа" in m:
            cat = "1X2"
        elif "фора" in m:
            cat = "Handicap"
        elif "двойн" in m:
            cat = "DoubleChance"
        else:
            cat = "Other"
        n_, w_, pr_ = cat_stat.get(cat, (0, 0, 0.0))
        n_ += 1
        if p.won:
            w_ += 1
            pr_ += p.fair_odds - 1.0
        else:
            pr_ -= 1.0
        cat_stat[cat] = (n_, w_, pr_)
    for cat, (cn, cw, cp) in sorted(cat_stat.items()):
        roi_c = (cp / cn) * 100 if cn else 0
        print(f"   {cat}: N={cn}, WIN={cw}, ROI={roi_c:+.1f}%, profit={cp:+.2f}u")

    # MarketFilter: блокируем категории с N≥3 и ROI<-30% — это даёт
    # системную защиту от рынков с систематически отрицательным CLV.
    print()
    print("🛡️ После MarketFilter (блокируем категории ROI<-30% при N≥3):")
    blocked = {
        cat for cat, (cn, _, cp) in cat_stat.items()
        if cn >= 3 and (cp / cn) < -0.3
    }
    print(f"   Заблокированы: {blocked or '—'}")
    n6 = wins6 = 0
    profit6 = 0.0
    for p in all_picks:
        m = p.market.lower()
        if "оз" in m or "забь" in m:
            cat = "BTTS"
        elif "тб" in m or "тм" in m or "ИТБ" in p.market or "ИТМ" in p.market:
            cat = "Total/IT"
        elif "п1" in m or "п2" in m or "победа" in m:
            cat = "1X2"
        elif "фора" in m:
            cat = "Handicap"
        elif "двойн" in m:
            cat = "DoubleChance"
        else:
            cat = "Other"
        if cat in blocked:
            continue
        if p.fair_odds < MIN_FAIR_ODDS:
            continue
        if p.model_prob < MIN_PROB_TAKE:
            continue
        n6 += 1
        if p.won:
            wins6 += 1
            profit6 += p.fair_odds - 1.0
        else:
            profit6 -= 1.0
    roi6 = (profit6 / n6) * 100 if n6 else 0
    print(
        f"   N={n6}, WIN={wins6}, ROI={roi6:+.1f}%, "
        f"profit={profit6:+.2f}u"
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/backtest_csv_predictions.py file1.csv [file2.csv ...]")
        sys.exit(1)
    main(sys.argv[1:])
