"""
Predictions API router for the NFL Mock Draft 2026 application.

Endpoints:
    POST /api/predictions/run  — auto-scrape + simulate all 100 picks
    GET  /api/predictions/status — last run metadata
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

predictions_router = APIRouter(prefix="/api/predictions", tags=["predictions"])

# In-process state for the last simulation run (resets on server restart)
_last_run: dict = {
    "last_run": None,
    "picks_assigned": 0,
    "players_in_pool": 0,
    "sources_scraped": [],
    "duration_ms": 0,
}


class RunResponse(BaseModel):
    """
    Response model for POST /api/predictions/run.

    Attributes:
        picks_assigned (int): Number of picks that received a player_id.
        players_created (int): Number of player records written to players.json.
        duration_ms (int): Wall-clock time of the full operation in milliseconds.
        sources_scraped (list[str]): Source identifiers successfully scraped.
        errors (list[str]): Any non-fatal errors encountered during scraping.
    """

    picks_assigned: int
    players_created: int
    duration_ms: int
    sources_scraped: list[str]
    errors: list[str]


class StatusResponse(BaseModel):
    """
    Response model for GET /api/predictions/status.

    Attributes:
        last_run (Optional[str]): ISO timestamp of the last run, or None.
        picks_assigned (int): Picks assigned in the last run.
        players_in_pool (int): Player pool size in the last run.
    """

    last_run: Optional[str]
    picks_assigned: int
    players_in_pool: int


@predictions_router.post("/run", response_model=RunResponse)
async def run_predictions(
    scrape: bool = Query(
        default=True,
        description="If true, run scrapers before simulating. Set false to use existing DB data.",
    ),
    sources: Optional[str] = Query(
        default=None,
        description=(
            "Comma-separated list of scraper sources to run (e.g. 'news,twitter'). "
            "Ignored when scrape=false. Defaults to all sources."
        ),
    ),
) -> RunResponse:
    """
    Run the full prediction pipeline: scrape → simulate → write results.

    Steps:
    1. (Optional) Run scrapers to refresh DB with latest data.
    2. Build player pool from DB (or synthetic fallback).
    3. Load team needs from DB.
    4. Run sequential simulation across all 100 picks.
    5. Write data/players.json and update data/picks.json player_ids.
    6. Clear data_loader LRU cache so API immediately serves new data.

    Args:
        scrape (bool): Whether to run scrapers before simulating. Default True.
        sources (Optional[str]): Comma-separated source names to limit scraping scope.
            When None, all sources are run. Example: "news,twitter".

    Returns:
        RunResponse: Summary of the operation including counts and timing.

    Raises:
        HTTPException 500: If the simulation itself fails.
    """
    start_ts = time.perf_counter()
    sources_scraped: list[str] = []
    errors: list[str] = []

    # Invalidate position_value cache so any config file changes are picked up
    # without requiring a server restart.
    from app.analytics.position_value import invalidate_cache as _invalidate_pv
    _invalidate_pv()

    # --- Phase 1: optional scraping ---
    if scrape:
        try:
            from app.pipeline.runner import run_pipeline

            source_list = [s.strip() for s in sources.split(",")] if sources else None
            results = await run_pipeline(sources=source_list)
            for r in results:
                if r.success:
                    sources_scraped.append(r.source)
                else:
                    errors.append(f"{r.source}: {r.error}")
        except Exception as exc:
            logger.warning("Scraping phase failed (non-fatal): %s", exc)
            errors.append(f"scraping: {exc}")

    # --- Phase 2: build player pool ---
    try:
        from app.analytics.player_pool import build_player_pool

        pool = build_player_pool()
        players_in_pool = len(pool)
    except Exception as exc:
        logger.error("Failed to build player pool: %s", exc)
        raise HTTPException(status_code=500, detail=f"Player pool build failed: {exc}")

    # --- Phase 3: simulate + write ---
    try:
        from app.analytics.simulator import simulate_and_write

        picks_assigned, players_created = simulate_and_write(player_pool=pool)
    except Exception as exc:
        logger.error("Simulation failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Simulation failed: {exc}")

    # --- Phase 4: clear data_loader cache ---
    try:
        from app import data_loader

        data_loader.clear_cache()
    except Exception as exc:
        logger.warning("Cache clear failed (non-fatal): %s", exc)

    duration_ms = int((time.perf_counter() - start_ts) * 1000)

    # Update in-process state
    _last_run.update(
        {
            "last_run": datetime.now(timezone.utc).isoformat(),
            "picks_assigned": picks_assigned,
            "players_in_pool": players_in_pool,
            "sources_scraped": sources_scraped,
            "duration_ms": duration_ms,
        }
    )

    logger.info(
        "Prediction run complete: %d picks assigned, %d players, %dms",
        picks_assigned,
        players_created,
        duration_ms,
    )

    return RunResponse(
        picks_assigned=picks_assigned,
        players_created=players_created,
        duration_ms=duration_ms,
        sources_scraped=sources_scraped,
        errors=errors,
    )


@predictions_router.get("/status", response_model=StatusResponse)
async def get_status() -> StatusResponse:
    """
    Return metadata about the most recent prediction run.

    Returns:
        StatusResponse: Last run timestamp, picks assigned, and pool size.
    """
    return StatusResponse(
        last_run=_last_run["last_run"],
        picks_assigned=_last_run["picks_assigned"],
        players_in_pool=_last_run["players_in_pool"],
    )
