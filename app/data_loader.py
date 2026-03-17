"""
Data loading utilities for the NFL Mock Draft 2026 application.

Reads and caches JSON config files from the data/ directory.
All data is loaded at startup and served from memory to avoid
repeated disk I/O.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

from app.models_core import EnrichedPick, Pick, Player, Team

# Resolve the data directory relative to this file's location
DATA_DIR = Path(__file__).parent.parent / "data"


@lru_cache(maxsize=1)
def load_teams() -> dict[str, Team]:
    """
    Load all NFL teams from data/teams.json and index by abbreviation.

    Returns:
        dict[str, Team]: Mapping of team abbreviation to Team object.

    Raises:
        FileNotFoundError: If teams.json does not exist.
        ValueError: If the JSON is malformed or missing required fields.
    """
    teams_path = DATA_DIR / "teams.json"
    with open(teams_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    return {
        team_data["abbreviation"]: Team(**team_data)
        for team_data in raw["teams"]
    }


@lru_cache(maxsize=1)
def load_picks() -> list[Pick]:
    """
    Load all draft picks from data/picks.json.

    Returns:
        list[Pick]: Ordered list of Pick objects (by pick_number).

    Raises:
        FileNotFoundError: If picks.json does not exist.
        ValueError: If the JSON is malformed.
    """
    picks_path = DATA_DIR / "picks.json"
    with open(picks_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    picks = [Pick(**pick_data) for pick_data in raw["picks"]]
    # Reason: sort defensively in case JSON order is changed
    return sorted(picks, key=lambda p: p.pick_number)


@lru_cache(maxsize=1)
def load_players() -> dict[str, Player]:
    """
    Load all player records from data/players.json, indexed by player_id.

    Returns:
        dict[str, Player]: Mapping of player_id to Player object.
            Returns empty dict if no players are defined yet.

    Raises:
        FileNotFoundError: If players.json does not exist.
    """
    players_path = DATA_DIR / "players.json"
    with open(players_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    return {
        player_data["player_id"]: Player(**player_data)
        for player_data in raw.get("players", [])
    }


def enrich_picks(
    picks: list[Pick],
    teams: dict[str, Team],
    players: dict[str, Player],
) -> list[EnrichedPick]:
    """
    Join picks with their Team and Player objects to produce EnrichedPick list.

    Args:
        picks (list[Pick]): Raw pick list.
        teams (dict[str, Team]): Team lookup by abbreviation.
        players (dict[str, Player]): Player lookup by player_id.

    Returns:
        list[EnrichedPick]: Picks with fully resolved team and player data.

    Raises:
        KeyError: If a pick's current_team abbreviation is not in teams dict.
    """
    enriched = []
    for pick in picks:
        team = teams[pick.current_team]
        traded_from_teams = [
            teams[abbrev]
            for abbrev in pick.traded_from
            if abbrev in teams
        ]
        player = players.get(pick.player_id) if pick.player_id else None
        enriched.append(
            EnrichedPick(
                pick=pick,
                team=team,
                traded_from_teams=traded_from_teams,
                player=player,
            )
        )
    return enriched


def get_all_enriched_picks() -> list[EnrichedPick]:
    """
    Convenience function: load and enrich all picks.

    Returns:
        list[EnrichedPick]: All picks enriched with team and player data.
    """
    teams = load_teams()
    picks = load_picks()
    players = load_players()
    return enrich_picks(picks, teams, players)


@lru_cache(maxsize=1)
def _get_enriched_picks_index() -> tuple[dict[int, list[EnrichedPick]], dict[int, EnrichedPick]]:
    """
    Build index structures for O(1) pick lookups, cached alongside the pick list.

    Returns:
        tuple: (by_round, by_number) dicts computed once from get_all_enriched_picks.
    """
    all_picks = get_all_enriched_picks()
    by_round: dict[int, list[EnrichedPick]] = {}
    by_number: dict[int, EnrichedPick] = {}
    for ep in all_picks:
        by_round.setdefault(ep.pick.round, []).append(ep)
        by_number[ep.pick.pick_number] = ep
    return by_round, by_number


def get_enriched_picks_by_round(round_number: int) -> list[EnrichedPick]:
    """
    Return enriched picks filtered to a specific round.

    Args:
        round_number (int): Round number to filter (1, 2, or 3).

    Returns:
        list[EnrichedPick]: Enriched picks for the given round.
    """
    by_round, _ = _get_enriched_picks_index()
    return by_round.get(round_number, [])


def get_enriched_pick_by_number(pick_number: int) -> Optional[EnrichedPick]:
    """
    Return a single enriched pick by overall pick number.

    Args:
        pick_number (int): The overall pick number (e.g., 1 for first pick).

    Returns:
        Optional[EnrichedPick]: The enriched pick, or None if not found.
    """
    _, by_number = _get_enriched_picks_index()
    return by_number.get(pick_number)


def clear_cache() -> None:
    """
    Clear all LRU caches, forcing data to reload from disk on next access.

    Useful for hot-reload scenarios during development.
    """
    load_teams.cache_clear()
    load_picks.cache_clear()
    load_players.cache_clear()
    _get_enriched_picks_index.cache_clear()
