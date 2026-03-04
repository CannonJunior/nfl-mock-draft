"""
FastAPI routes for on-demand web data scraping.

Endpoints:
  POST /api/scrape/refresh          — Run all scrapers (or a subset via ?source=)
  GET  /api/scrape/status           — Last successful run timestamps per source
  GET  /api/scrape/prospects        — Scraped prospect big board from DB
  GET  /api/scrape/picks            — Scraped draft order from DB
  GET  /api/scrape/mock             — Scraped mock draft entries from DB
  GET  /api/scrape/needs            — Scraped team needs from DB
"""

from __future__ import annotations

import sqlite3
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.models.scrape import ScrapeResult
from app.pipeline import storage
from app.pipeline.runner import ALL_SOURCES, run_pipeline

logger = logging.getLogger(__name__)

scrape_router = APIRouter(prefix="/api/scrape", tags=["scraping"])


@scrape_router.post("/refresh", response_model=list[ScrapeResult])
async def refresh(
    background_tasks: BackgroundTasks,
    source: str = Query(
        default="all",
        description=(
            f"Comma-separated source(s) to refresh, or 'all'. "
            f"Valid: {', '.join(ALL_SOURCES)}"
        ),
    ),
    background: bool = Query(
        default=False,
        description="If true, run in background and return immediately.",
    ),
) -> list[ScrapeResult]:
    """
    Trigger on-demand data refresh from web sources.

    Args:
        source (str): Comma-separated list of sources or "all".
        background (bool): Run the pipeline in a background task.

    Returns:
        list[ScrapeResult]: Run results per scraper operation.
            Returns an empty list with a 202 note if background=True.
    """
    sources = [s.strip() for s in source.split(",")]
    unknown = [s for s in sources if s not in ALL_SOURCES and s != "all"]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown sources: {unknown}. Valid: {ALL_SOURCES}",
        )

    if background:
        background_tasks.add_task(run_pipeline, sources=sources)
        return []

    results = await run_pipeline(sources=sources)
    return results


@scrape_router.get("/status")
async def scrape_status() -> dict[str, Optional[str]]:
    """
    Return the last successful scrape timestamp for each known source.

    Returns:
        dict[str, Optional[str]]: Source name → ISO timestamp or null.
    """
    storage.init_db()
    timestamps = storage.get_last_run_timestamps()
    return {source: timestamps.get(source) for source in ALL_SOURCES}


@scrape_router.get("/prospects")
async def get_scraped_prospects(
    limit: int = Query(default=100, ge=1, le=500),
    source: Optional[str] = Query(default=None),
) -> list[dict]:
    """
    Return scraped prospect big board records from the database.

    Args:
        limit (int): Maximum number of records to return.
        source (Optional[str]): Filter to a specific scraper source.

    Returns:
        list[dict]: Prospect records ordered by rank ascending.
    """
    storage.init_db()
    return _query_table("prospects", limit=limit, source_filter=source, order_by="rank ASC")


@scrape_router.get("/picks")
async def get_scraped_picks(
    limit: int = Query(default=300, ge=1, le=1000),
    source: Optional[str] = Query(default=None),
) -> list[dict]:
    """
    Return scraped draft pick records from the database.

    Args:
        limit (int): Maximum number of records to return.
        source (Optional[str]): Filter to a specific scraper source.

    Returns:
        list[dict]: Draft pick records ordered by pick_number ascending.
    """
    storage.init_db()
    return _query_table("draft_picks", limit=limit, source_filter=source, order_by="pick_number ASC")


@scrape_router.get("/mock")
async def get_mock_draft(
    limit: int = Query(default=300, ge=1, le=1000),
    source: Optional[str] = Query(default=None),
) -> list[dict]:
    """
    Return scraped mock draft projection records.

    Args:
        limit (int): Maximum number of records to return.
        source (Optional[str]): Filter to a specific scraper source.

    Returns:
        list[dict]: Mock draft entries ordered by pick_number ascending.
    """
    storage.init_db()
    return _query_table("mock_draft", limit=limit, source_filter=source, order_by="pick_number ASC")


@scrape_router.get("/needs")
async def get_team_needs(
    team: Optional[str] = Query(default=None, description="Filter by team name"),
    source: Optional[str] = Query(default=None),
) -> list[dict]:
    """
    Return scraped team positional need records.

    Args:
        team (Optional[str]): Filter to a specific team name.
        source (Optional[str]): Filter to a specific scraper source.

    Returns:
        list[dict]: Team need records.
    """
    storage.init_db()
    filters: dict[str, str] = {}
    if team:
        filters["team"] = team
    if source:
        filters["source"] = source
    return _query_table("team_needs", filters=filters)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _query_table(
    table: str,
    limit: int = 500,
    source_filter: Optional[str] = None,
    order_by: str = "rowid ASC",
    filters: Optional[dict[str, str]] = None,
) -> list[dict]:
    """
    Execute a SELECT against a SQLite table and return rows as dicts.

    Args:
        table (str): Table name to query.
        limit (int): Row limit.
        source_filter (Optional[str]): Optional WHERE source = ? clause.
        order_by (str): ORDER BY clause fragment.
        filters (Optional[dict[str, str]]): Additional column=value filters.

    Returns:
        list[dict]: Query results as list of column→value dicts.
    """
    from app.pipeline.storage import _get_conn

    where_parts: list[str] = []
    params: list[str | int] = []

    if source_filter:
        where_parts.append("source = ?")
        params.append(source_filter)

    if filters:
        for col, val in filters.items():
            where_parts.append(f"{col} = ?")
            params.append(val)

    where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    sql = f"SELECT * FROM {table} {where_clause} ORDER BY {order_by} LIMIT ?"
    params.append(limit)

    try:
        with _get_conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall()
            return [dict(row) for row in rows]
    except sqlite3.OperationalError as exc:
        logger.warning("Query failed on table %s: %s", table, exc)
        return []
