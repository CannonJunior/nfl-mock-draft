"""
FastAPI route handlers for the NFL Mock Draft 2026 application.

Provides:
  - GET /          — Serve the main Jinja2 HTML page.
  - GET /api/picks — All enriched picks (optional ?round= filter).
  - GET /api/picks/{pick_number} — Single enriched pick.
  - GET /api/teams — All teams.
  - GET /api/teams/{abbreviation} — Single team.
  - POST /api/cache/clear — Flush data cache (dev utility).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app import data_loader
from app.models_core import EnrichedPick, Team

_DATA_DIR = Path(__file__).parent.parent / "data"

# Resolve templates directory relative to this file
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """
    Serve the main mock draft page.

    Args:
        request (Request): FastAPI request context (required by Jinja2).

    Returns:
        HTMLResponse: Rendered index.html template.
    """
    all_picks = data_loader.get_all_enriched_picks()

    # Single pass: group by round, count assigned, and build team draft log.
    # Reason: previously three separate loops (sort+iterate for team_draft_log,
    # iterate for round grouping, sum() for assigned). Now done in one traversal.
    rounds: dict[int, list[EnrichedPick]] = {1: [], 2: [], 3: []}
    assigned = 0
    # team_draft_log maps team → list of {pick_number, position, player_name}
    # ordered by pick_number (all_picks is already sorted ascending).
    team_draft_log: dict[str, list[dict]] = {}
    for ep in all_picks:
        if ep.pick.round in rounds:
            rounds[ep.pick.round].append(ep)
        if ep.player is not None:
            assigned += 1
            team_draft_log.setdefault(ep.pick.current_team, []).append(
                {
                    "pick_number": ep.pick.pick_number,
                    "position": ep.player.position,
                    "player_name": ep.player.name,
                }
            )

    # Last prediction run time from picks.json modification timestamp
    picks_path = _DATA_DIR / "picks.json"
    last_updated: str | None = None
    if picks_path.exists() and assigned > 0:
        mtime = picks_path.stat().st_mtime
        last_updated = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime(
            "%b %d, %Y %H:%M UTC"
        )

    # Build per-pick "prior filled needs" map for the Team Needs section.
    # For each pick, records which positions the same team filled with EARLIER
    # picks: {pick_number → {position → player_name}}.
    # Reason: Jinja2 can't do mutable dict updates in loops, so we pre-compute
    # this in Python. team_draft_log entries are already in pick_number order
    # since all_picks is sorted, so we can use a running per-team accumulator.
    pick_team_histories: dict[int, dict[str, str]] = {}
    team_filled: dict[str, dict[str, str]] = {}  # team → {position → first player name}
    for ep in all_picks:
        team = ep.pick.current_team
        pick_num = ep.pick.pick_number
        # Snapshot what the team has filled BEFORE this pick
        pick_team_histories[pick_num] = dict(team_filled.get(team, {}))
        # Then record this pick's player (if any) for subsequent picks
        if ep.player is not None:
            pos = ep.player.position
            team_filled.setdefault(team, {}).setdefault(pos, ep.player.name)

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "rounds": rounds,
            "total_picks": len(all_picks),
            "assigned_picks": assigned,
            "last_updated": last_updated,
            "pick_team_histories": pick_team_histories,
        },
    )


# ---------------------------------------------------------------------------
# API routes — picks
# ---------------------------------------------------------------------------


@router.get("/api/picks", response_model=list[EnrichedPick])
async def get_picks(
    round: int | None = Query(None, ge=1, le=3, description="Filter by round (1-3)")
) -> list[EnrichedPick]:
    """
    Return all enriched picks, optionally filtered by round.

    Args:
        round (int | None): If provided, only picks from this round are returned.

    Returns:
        list[EnrichedPick]: List of enriched pick objects.
    """
    if round is not None:
        return data_loader.get_enriched_picks_by_round(round)
    return data_loader.get_all_enriched_picks()


@router.get("/api/picks/{pick_number}", response_model=EnrichedPick)
async def get_pick(pick_number: int) -> EnrichedPick:
    """
    Return a single enriched pick by its overall pick number.

    Args:
        pick_number (int): The overall draft pick number.

    Returns:
        EnrichedPick: The enriched pick object.

    Raises:
        HTTPException 404: If no pick with that number exists.
    """
    ep = data_loader.get_enriched_pick_by_number(pick_number)
    if ep is None:
        raise HTTPException(
            status_code=404,
            detail=f"Pick #{pick_number} not found",
        )
    return ep


# ---------------------------------------------------------------------------
# API routes — teams
# ---------------------------------------------------------------------------


@router.get("/api/teams", response_model=list[Team])
async def get_teams() -> list[Team]:
    """
    Return all NFL teams sorted alphabetically by name.

    Returns:
        list[Team]: All 32 team objects.
    """
    teams = data_loader.load_teams()
    return sorted(teams.values(), key=lambda t: t.name)


@router.get("/api/teams/{abbreviation}", response_model=Team)
async def get_team(abbreviation: str) -> Team:
    """
    Return a single team by its ESPN abbreviation.

    Args:
        abbreviation (str): Team abbreviation (e.g. "lv", "nyj").

    Returns:
        Team: The team object.

    Raises:
        HTTPException 404: If no team with that abbreviation exists.
    """
    teams = data_loader.load_teams()
    team = teams.get(abbreviation.lower())
    if team is None:
        raise HTTPException(
            status_code=404,
            detail=f"Team '{abbreviation}' not found",
        )
    return team


# ---------------------------------------------------------------------------
# Dev utility
# ---------------------------------------------------------------------------


@router.post("/api/cache/clear", status_code=200)
async def clear_cache() -> dict[str, str]:
    """
    Clear the in-memory data cache to force reload from disk.

    Returns:
        dict[str, str]: Confirmation message.
    """
    data_loader.clear_cache()
    return {"message": "Cache cleared. Data will reload on next request."}
