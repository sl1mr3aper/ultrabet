"""ETL для массивной загрузки исторических матчей с 2010 года.

Запуск:
    python -m scripts.historical_etl --from 2010 --to 2025 [--leagues 1,2,3] [--limit 200]

Алгоритм:
1. Перебираем все (или указанные) лиги из SStats /Leagues/list.
2. Для каждой пары (лига, год) запрашиваем /Games/list?LeagueId=X&Year=Y&Ended=true
   с пагинацией по 1000 матчей.
3. Идемпотентно записываем в `match_results` (UPSERT по game_id).
4. Прогресс пишем в лог раз в 50 матчей.
5. На любую ошибку — логируем и продолжаем со следующего батча.

ВАЖНО: SStats ограничивает rate (≈30 req/min на бесплатных тарифах);
скрипт намеренно медленный — 1 секунда между запросами. Для 50 лиг × 16
лет это ~13–20 часов чистого времени. Запускайте в screen/tmux.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.sstats_client import SStatsClient
from config import Settings
from db.database import Database
from db.models import MatchResult


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


async def _fetch_year(
    sstats: SStatsClient,
    league_id: int,
    year: int,
    *,
    page_size: int = 1000,
) -> list[dict[str, Any]]:
    """Скачать все завершённые матчи лиги за конкретный год."""
    out: list[dict[str, Any]] = []
    offset = 0
    while True:
        try:
            batch = await sstats.list_games(
                league_id=league_id,
                year=year,
                ended=True,
                offset=offset,
                limit=page_size,
                order=-1,
            )
        except Exception as exc:
            logger.warning(
                "fetch league={} year={} offset={} failed: {}",
                league_id, year, offset, exc,
            )
            return out
        if not batch:
            break
        out.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
        await asyncio.sleep(1.0)  # лёгкое торможение под rate-limit
    return out


def _to_row(g: dict[str, Any]) -> dict[str, Any] | None:
    gid = g.get("id")
    if not isinstance(gid, int):
        return None
    home = g.get("homeTeam") or {}
    away = g.get("awayTeam") or {}
    season = g.get("season") or {}
    league = season.get("league") if isinstance(season, dict) else {}
    country = (league or {}).get("country") if isinstance(league, dict) else {}
    # Счёт хранится в полях homeFTResult/awayFTResult или homeResult/awayResult.
    home_score = g.get("homeFTResult")
    away_score = g.get("awayFTResult")
    if home_score is None or away_score is None:
        home_score = g.get("homeResult")
        away_score = g.get("awayResult")
    return {
        "game_id": gid,
        "date": _parse_iso(g.get("date")),
        "league_id": (league or {}).get("id") if isinstance(league, dict) else None,
        "league_name": (league or {}).get("name") if isinstance(league, dict) else None,
        "country_name": (country or {}).get("name") if isinstance(country, dict) else None,
        "home_id": home.get("id") if isinstance(home, dict) else None,
        "away_id": away.get("id") if isinstance(away, dict) else None,
        "home_name": home.get("name") if isinstance(home, dict) else None,
        "away_name": away.get("name") if isinstance(away, dict) else None,
        "home_score": home_score if isinstance(home_score, int) else None,
        "away_score": away_score if isinstance(away_score, int) else None,
        "home_xg": None,
        "away_xg": None,
    }


async def _upsert_batch(session: AsyncSession, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    stmt = sqlite_insert(MatchResult).values(rows)
    # При повторе обновляем счёт/имена/лигу — позволяет дозалить score'ы.
    stmt = stmt.on_conflict_do_update(
        index_elements=[MatchResult.game_id],
        set_={
            "home_score": stmt.excluded.home_score,
            "away_score": stmt.excluded.away_score,
            "league_id": stmt.excluded.league_id,
            "league_name": stmt.excluded.league_name,
            "country_name": stmt.excluded.country_name,
            "home_id": stmt.excluded.home_id,
            "away_id": stmt.excluded.away_id,
            "home_name": stmt.excluded.home_name,
            "away_name": stmt.excluded.away_name,
        },
    )
    await session.execute(stmt)
    await session.commit()
    return len(rows)


async def run_etl(
    *,
    year_from: int,
    year_to: int,
    league_ids: list[int] | None = None,
    league_limit: int | None = None,
) -> None:
    import aiohttp

    settings = Settings()  # type: ignore[call-arg]
    settings.ensure_dirs()
    http = aiohttp.ClientSession()
    sstats = SStatsClient(
        http,
        api_key=settings.sstats_api_key_value,
        base_url=settings.sstats_base_url,
        timeout=settings.sstats_timeout,
    )
    database = Database(settings.database_url)
    await database.init_models()

    try:
        await _do_etl(sstats, database, year_from, year_to, league_ids, league_limit)
    finally:
        await http.close()


async def _do_etl(
    sstats: SStatsClient,
    database: Database,
    year_from: int,
    year_to: int,
    league_ids: list[int] | None,
    league_limit: int | None,
) -> None:
    leagues = await sstats.list_leagues()
    if league_ids:
        leagues = [
            l for l in leagues
            if isinstance(l, dict) and l.get("id") in set(league_ids)
        ]
    elif league_limit:
        leagues = leagues[:league_limit]

    logger.info(
        "ETL start: {} лиг, годы {}–{}",
        len(leagues), year_from, year_to,
    )

    total_inserted = 0
    for li, league in enumerate(leagues, 1):
        if not isinstance(league, dict):
            continue
        league_id = league.get("id")
        league_name = league.get("name") or "?"
        if not isinstance(league_id, int):
            continue
        for year in range(year_from, year_to + 1):
            games = await _fetch_year(sstats, league_id, year)
            if not games:
                continue
            rows = [r for r in (_to_row(g) for g in games) if r is not None]
            async with database.session() as session:
                inserted = await _upsert_batch(session, rows)
            total_inserted += inserted
            logger.info(
                "[{}/{}] {} {}: {} матчей (всего {})",
                li, len(leagues), league_name, year, inserted, total_inserted,
            )
            await asyncio.sleep(0.5)

    logger.info(
        "ETL done. Всего записей вставлено: {} (на {})",
        total_inserted, datetime.now(tz=UTC).isoformat(),
    )

    async with database.session() as session:
        total = (await session.execute(select(MatchResult).limit(1))).first()
        logger.info("Sanity check (one row exists): {}", bool(total))


def _main() -> None:
    parser = argparse.ArgumentParser(description="Historical matches ETL since 2010.")
    parser.add_argument("--from", dest="year_from", type=int, default=2010)
    parser.add_argument("--to", dest="year_to", type=int, default=datetime.now().year)
    parser.add_argument(
        "--leagues",
        type=str,
        default="",
        help="Список ID лиг через запятую (если пусто — все).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Топ-N лиг из /Leagues/list, если --leagues не задан.",
    )
    args = parser.parse_args()
    league_ids = (
        [int(x) for x in args.leagues.split(",") if x.strip()]
        if args.leagues else None
    )
    asyncio.run(
        run_etl(
            year_from=args.year_from,
            year_to=args.year_to,
            league_ids=league_ids,
            league_limit=args.limit,
        )
    )


if __name__ == "__main__":
    _main()
