"""ETL-скрипт для bulk-выгрузки football-data.co.uk.

Использование:

    python -m scripts.football_data_etl \
        --leagues E0 D1 SP1 I1 F1 \
        --seasons 1819 1920 2021 2122 2223 2324 2425 \
        --output data/fdb.json

По умолчанию обрабатывает все главные лиги за последние 7 сезонов.
Печатает в stderr прогресс, в stdout — sanity-check метрики (hit-rate
стратегии "ставлю всегда на фаворита Pinnacle").
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Iterable

import aiohttp

from services.football_data_loader import (
    LEAGUE_NAMES,
    FootballDataLoader,
    compute_naive_backtest_metrics,
    season_short_from_year,
)

_DEFAULT_LEAGUES = ["E0", "D1", "SP1", "I1", "F1"]


def _seasons_for_recent_years(n_years: int = 7) -> list[str]:
    # 2026 (current) → последние 7: 18/19, 19/20, 20/21, 21/22, 22/23, 23/24, 24/25.
    return [season_short_from_year(2018 + i) for i in range(n_years)]


async def _run(
    *,
    leagues: Iterable[str],
    seasons: Iterable[str],
    output: str | None,
) -> int:
    leagues_list = list(leagues)
    seasons_list = list(seasons)
    print(
        f"Скачиваю football-data.co.uk: {len(leagues_list)} лиг "
        f"× {len(seasons_list)} сезонов = "
        f"{len(leagues_list) * len(seasons_list)} файлов",
        file=sys.stderr,
    )
    all_matches = []
    metrics_per_league = {}
    async with aiohttp.ClientSession() as session:
        loader = FootballDataLoader(session=session)
        for code in leagues_list:
            ms = await loader.fetch_seasons(
                league_code=code, seasons_short=seasons_list
            )
            metrics_per_league[code] = compute_naive_backtest_metrics(ms)
            print(
                f"  {code} ({LEAGUE_NAMES.get(code, code)}): "
                f"{len(ms)} матчей",
                file=sys.stderr,
            )
            all_matches.extend(ms)
    overall = compute_naive_backtest_metrics(all_matches)
    report = {
        "overall": overall,
        "by_league": metrics_per_league,
    }
    print(json.dumps(report, indent=2, default=str))
    if output:
        with open(output, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "overall": overall,
                    "by_league": metrics_per_league,
                    "matches": [
                        {
                            "date": m.date.isoformat(),
                            "home": m.home_team,
                            "away": m.away_team,
                            "score": f"{m.home_goals}-{m.away_goals}",
                            "ftr": m.full_time_result,
                            "pinnacle": [
                                m.pinnacle_home,
                                m.pinnacle_draw,
                                m.pinnacle_away,
                            ],
                        }
                        for m in all_matches
                    ],
                },
                f,
                ensure_ascii=False,
                default=str,
            )
        print(
            f"Сохранил {len(all_matches)} матчей в {output}",
            file=sys.stderr,
        )
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ETL для football-data.co.uk: скачать "
        "историю матчей по нескольким лигам и сезонам.",
    )
    parser.add_argument(
        "--leagues",
        nargs="+",
        default=_DEFAULT_LEAGUES,
        help="Внутренние коды лиг (E0, D1, SP1, I1, F1, …).",
    )
    parser.add_argument(
        "--seasons",
        nargs="+",
        default=_seasons_for_recent_years(),
        help="Сезоны в формате 'YYZZ' (1819 = 2018/19).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Путь к файлу для сохранения JSON-дампа (опционально).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    return asyncio.run(
        _run(
            leagues=args.leagues,
            seasons=args.seasons,
            output=args.output,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
