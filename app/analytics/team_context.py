"""
Team context module for the NFL Mock Draft prediction engine.

Loads team positional needs from the database and maintains per-team
TeamNeedState objects that are updated throughout the simulation as
teams make picks.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "draft.db"
_TEAM_MAP_PATH = (
    Path(__file__).parent.parent.parent / "data" / "config" / "team_name_map.json"
)
_TEAM_NEEDS_CONFIG_PATH = (
    Path(__file__).parent.parent.parent / "data" / "config" / "team_needs_2026.json"
)

# Default need level applied when no data exists for a team-position pair
_DEFAULT_NEED_LEVEL = 2

# How much to reduce a need level after a team drafts that position
_NEED_REDUCTION_HIGH = 2  # applied when current level >= 4
_NEED_REDUCTION_LOW = 1   # applied when current level 1-3
_NEED_FLOOR = 0           # need level cannot go below this

# Positions where drafting one player should fully zero out the team's need.
# QB is the prime example: teams never draft two franchise QBs in the same draft.
_ZERO_OUT_AFTER_DRAFT: set[str] = {"QB"}


@dataclass
class TeamNeedState:
    """
    Mutable need state for a single team during simulation.

    Attributes:
        team (str): Team abbreviation (e.g. "lv").
        needs (dict[str, int]): Position → need level 1-5.
        picks_made (list[str]): Positions drafted so far in this simulation.
    """

    team: str
    needs: dict[str, int] = field(default_factory=dict)
    picks_made: list[str] = field(default_factory=list)

    def get_need(self, position: str) -> int:
        """
        Return the current need level for a position.

        Args:
            position (str): Position code (e.g. "QB").

        Returns:
            int: Need level 1-5; defaults to _DEFAULT_NEED_LEVEL if unknown.
        """
        return self.needs.get(position, _DEFAULT_NEED_LEVEL)


def build_team_need_states(team_abbrevs: list[str]) -> dict[str, TeamNeedState]:
    """
    Build a TeamNeedState for every team abbreviation, loaded from the DB.

    Teams not found in the DB receive default need levels for all positions.

    Args:
        team_abbrevs (list[str]): List of team abbreviations (e.g. ["lv", "nyj"]).

    Returns:
        dict[str, TeamNeedState]: Mapping of team abbreviation → TeamNeedState.
    """
    db_needs = _load_team_needs_from_db()
    team_map = _load_team_name_map()

    config_needs = _load_team_needs_from_config()

    states: dict[str, TeamNeedState] = {}
    for abbrev in team_abbrevs:
        # Resolve DB key for this abbreviation (DB may use full names)
        needs = _resolve_needs_for_team(abbrev, db_needs, team_map)
        # Reason: fall back to the curated config file when the DB table is
        # empty (scraper hasn't run yet). DB data always takes precedence.
        if not needs:
            needs = config_needs.get(abbrev.lower(), {})
        states[abbrev] = TeamNeedState(team=abbrev, needs=needs)

    logger.info(
        "Team need states built for %d teams (%d with DB data)",
        len(states),
        sum(1 for s in states.values() if s.needs),
    )
    return states


def update_team_need(state: TeamNeedState, position_drafted: str) -> None:
    """
    Reduce a team's need for a position after they draft a player there.

    Applies a larger reduction for critical/high needs (level >= 4) and
    a smaller one for moderate/low needs. Need floor is _NEED_FLOOR (0).

    Args:
        state (TeamNeedState): The team's current need state (mutated in place).
        position_drafted (str): Position code of the player just drafted.
    """
    current = state.needs.get(position_drafted, _DEFAULT_NEED_LEVEL)

    # Reason: certain positions (QB) should never be double-dipped; zero out need
    # entirely so later picks aren't steered towards the same franchise position.
    if position_drafted in _ZERO_OUT_AFTER_DRAFT:
        state.needs[position_drafted] = _NEED_FLOOR
    elif current >= _NEED_REDUCTION_HIGH:
        reduction = _NEED_REDUCTION_HIGH
        state.needs[position_drafted] = max(_NEED_FLOOR, current - reduction)
    else:
        reduction = _NEED_REDUCTION_LOW
        state.needs[position_drafted] = max(_NEED_FLOOR, current - reduction)

    state.picks_made.append(position_drafted)

    logger.debug(
        "[%s] Drafted %s — need level %d → %d",
        state.team,
        position_drafted,
        current,
        state.needs[position_drafted],
    )


def get_need_boost_for_team(state: TeamNeedState, position: str) -> float:
    """
    Return the need boost multiplier for a team-position pair.

    Args:
        state (TeamNeedState): Current team need state.
        position (str): Position to evaluate.

    Returns:
        float: Additive boost value from the position_value config.
    """
    from app.analytics.position_value import get_need_boost

    need_level = state.get_need(position)
    return get_need_boost(need_level)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _load_team_needs_from_db() -> dict[str, dict[str, int]]:
    """
    Load team needs from the SQLite team_needs table.

    Aggregates by averaging across sources and rounding to nearest int.

    Returns:
        dict[str, dict[str, int]]: Raw team name → {position: avg_need_level}.
    """
    if not _DB_PATH.exists():
        return {}

    try:
        conn = sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT team, position, AVG(need_level) AS avg_level
            FROM team_needs
            GROUP BY team, position
            """
        ).fetchall()
        conn.close()

        result: dict[str, dict[str, int]] = {}
        for row in rows:
            team_key = row["team"].lower().strip()
            pos = row["position"].upper().strip()
            result.setdefault(team_key, {})[pos] = round(row["avg_level"])
        return result

    except sqlite3.OperationalError as exc:
        logger.warning("Could not load team needs from DB: %s", exc)
        return {}


def _load_team_name_map() -> dict[str, str]:
    """
    Load the scraped-name → abbreviation map from team_name_map.json.

    Returns:
        dict[str, str]: Lower-cased name/alias → team abbreviation.
    """
    if not _TEAM_MAP_PATH.exists():
        return {}

    import json

    with open(_TEAM_MAP_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)

    return {k.lower(): v.lower() for k, v in raw.items()}


def _load_team_needs_from_config() -> dict[str, dict[str, int]]:
    """
    Load curated team needs from data/config/team_needs_2026.json.

    Used as a fallback when the DB team_needs table is empty (scraper not yet
    run). DB data always takes precedence via build_team_need_states().

    Returns:
        dict[str, dict[str, int]]: Lower-cased team abbreviation →
            {position: need_level}. Empty dict if file is missing or invalid.
    """
    import json

    if not _TEAM_NEEDS_CONFIG_PATH.exists():
        return {}

    try:
        with open(_TEAM_NEEDS_CONFIG_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return {k.lower(): v for k, v in raw.get("teams", {}).items()}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not load team_needs_2026.json: %s", exc)
        return {}


def _resolve_needs_for_team(
    abbrev: str,
    db_needs: dict[str, dict[str, int]],
    team_map: dict[str, str],
) -> dict[str, int]:
    """
    Resolve DB need data for a team abbreviation.

    DB data may use full team names or other formats. This function tries
    the abbreviation directly, then searches the team_map for a match.

    Args:
        abbrev (str): Team abbreviation (e.g. "lv").
        db_needs (dict): Raw DB data keyed by lower-cased team name.
        team_map (dict): Name alias → abbreviation map.

    Returns:
        dict[str, int]: Position → need level; empty dict if not found.
    """
    # Direct match by abbreviation
    if abbrev.lower() in db_needs:
        return db_needs[abbrev.lower()]

    # Reverse lookup through team_map: find DB keys whose mapped abbrev == abbrev
    for db_key, db_data in db_needs.items():
        mapped = team_map.get(db_key)
        if mapped and mapped.lower() == abbrev.lower():
            return db_data

    return {}
