"""
Draft scoring engine for the NFL Mock Draft prediction engine.

Computes a team-specific value score for every available player at each
pick, incorporating position tier weights, team need boosts, and supply
pressure factors that update dynamically as the simulation progresses.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.analytics.player_pool import PlayerCandidate
    from app.analytics.team_context import TeamNeedState

from app.analytics.position_value import (
    apply_position_weight,
    get_supply_pressure_config,
)
from app.analytics.team_context import get_need_boost_for_team

logger = logging.getLogger(__name__)


def compute_team_value(
    player: "PlayerCandidate",
    team_state: "TeamNeedState",
    available_players: list["PlayerCandidate"],
) -> float:
    """
    Compute the team-specific value of a player for a given team at this pick.

    Formula:
        team_value = position_adjusted
                   * (1 + need_boost)
                   * supply_pressure_factor

    Args:
        player (PlayerCandidate): The candidate being evaluated.
        team_state (TeamNeedState): Current need state for the selecting team.
        available_players (list[PlayerCandidate]): All still-available players.

    Returns:
        float: Composite team value score (higher = better fit for this team).
    """
    # Step 1: position-adjusted base score
    pos_adjusted = apply_position_weight(player.base_score, player.position)

    # Step 2: team need boost (additive factor on top of 1.0)
    need_boost = get_need_boost_for_team(team_state, player.position)
    need_multiplier = 1.0 + need_boost

    # Step 3: supply pressure factor
    supply_factor = _supply_pressure_factor(
        player=player,
        team_state=team_state,
        available_players=available_players,
    )

    return pos_adjusted * need_multiplier * supply_factor


def _supply_pressure_factor(
    player: "PlayerCandidate",
    team_state: "TeamNeedState",
    available_players: list["PlayerCandidate"],
) -> float:
    """
    Compute a supply pressure multiplier for a player's position.

    Boosts the team value when:
    - The team needs this position AND
    - Either the talent cliff is steep (best vs 2nd-best gap > threshold)
      OR the position's top prospects are draining faster than expected.

    Args:
        player (PlayerCandidate): The candidate being scored.
        team_state (TeamNeedState): Current team need state.
        available_players (list[PlayerCandidate]): Remaining available players.

    Returns:
        float: Multiplier in range [1.0, max_boost]. 1.0 means no pressure.
    """
    sp_config = get_supply_pressure_config()
    cliff_threshold = sp_config["talent_cliff_threshold"]
    drain_threshold = sp_config["early_drain_threshold"]
    max_boost = sp_config["max_boost"]

    position = player.position
    need_level = team_state.get_need(position)

    # Reason: supply pressure only applies when team actually needs this position
    if need_level < 3:
        return 1.0

    # Collect available players at this position, sorted by base_score descending
    pos_players = sorted(
        [p for p in available_players if p.position == position],
        key=lambda p: p.base_score,
        reverse=True,
    )

    if not pos_players:
        return 1.0

    # Talent cliff: score gap between 1st and 2nd available
    talent_cliff = 0.0
    if len(pos_players) >= 2:
        talent_cliff = pos_players[0].base_score - pos_players[1].base_score

    # Drain rate: how many of the original top-10 at this position are gone
    drain_rate = _compute_drain_rate(position, available_players)

    cliff_pressure = talent_cliff > cliff_threshold
    drain_pressure = drain_rate > drain_threshold

    if not cliff_pressure and not drain_pressure:
        return 1.0

    # Scale boost based on how extreme the pressure is
    pressure_strength = 0.0
    if cliff_pressure:
        # Reason: normalise cliff so threshold = 0.5 strength, double = 1.0
        pressure_strength = max(pressure_strength, min(1.0, talent_cliff / (cliff_threshold * 2)))
    if drain_pressure:
        pressure_strength = max(pressure_strength, min(1.0, drain_rate))

    # Map [0, 1] pressure to [1.0, max_boost] multiplier
    factor = 1.0 + (max_boost - 1.0) * pressure_strength
    return min(max_boost, factor)


def _compute_drain_rate(
    position: str,
    available_players: list["PlayerCandidate"],
) -> float:
    """
    Estimate how much of the top talent at a position has already been picked.

    Compares the count of remaining top-10-score players vs. the expected 10.

    Args:
        position (str): Position code to evaluate.
        available_players (list[PlayerCandidate]): Remaining available players.

    Returns:
        float: Drain rate in [0.0, 1.0]; 1.0 = all top-10 gone.
    """
    pos_players = [p for p in available_players if p.position == position]
    _TOP_N = 10  # Reason: top-10 at any position is meaningful premium tier

    if not pos_players:
        # All players at this position have been drafted
        return 1.0

    # Approximate "top 10" by taking the 10th-highest score threshold
    scores = sorted([p.base_score for p in pos_players], reverse=True)
    # Count how many of the expected top 10 are still available
    still_available = min(_TOP_N, len(scores))
    return 1.0 - (still_available / _TOP_N)


def rank_players_for_team(
    available_players: list["PlayerCandidate"],
    team_state: "TeamNeedState",
) -> list[tuple[float, "PlayerCandidate"]]:
    """
    Score all available players for a team and return sorted (score, player) pairs.

    Args:
        available_players (list[PlayerCandidate]): All still-available players.
        team_state (TeamNeedState): Current team need state.

    Returns:
        list[tuple[float, PlayerCandidate]]: Sorted descending by team value.
    """
    scored = [
        (compute_team_value(p, team_state, available_players), p)
        for p in available_players
    ]
    return sorted(scored, key=lambda x: x[0], reverse=True)
