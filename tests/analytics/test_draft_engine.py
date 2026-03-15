"""
Unit tests for app/analytics/draft_engine.py.
"""

from __future__ import annotations

import pytest

from app.analytics.draft_engine import (
    compute_team_value,
    rank_players_for_team,
    _compute_drain_rate,
    _supply_pressure_factor,
)
from app.analytics.player_pool import PlayerCandidate
from app.analytics.team_context import TeamNeedState


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _make_player(
    name: str = "Test Player",
    position: str = "WR",
    base_score: float = 70.0,
    available: bool = True,
) -> PlayerCandidate:
    """Create a minimal PlayerCandidate for testing."""
    return PlayerCandidate(
        player_id=name.lower().replace(" ", "-"),
        name=name,
        position=position,
        college="Test U",
        espn_grade=7.0,
        espn_rank=10,
        base_score=base_score,
        available=available,
    )


def _make_state(
    team: str = "lv",
    needs: dict | None = None,
) -> TeamNeedState:
    """Create a TeamNeedState for testing."""
    return TeamNeedState(team=team, needs=needs or {})


# ---------------------------------------------------------------------------
# compute_team_value
# ---------------------------------------------------------------------------


class TestComputeTeamValue:
    def test_high_need_boosts_value(self):
        """Player at a critical need position scores higher than same player at no-need."""
        player = _make_player(position="QB", base_score=70.0)
        available = [player]

        high_need_state = _make_state(needs={"QB": 5})
        low_need_state = _make_state(needs={"QB": 1})

        high_val = compute_team_value(player, high_need_state, available)
        low_val = compute_team_value(player, low_need_state, available)

        assert high_val > low_val

    def test_grade_dominates_position(self):
        """Higher-grade player should beat lower-grade regardless of position when need is equal."""
        # All position weights are 1.0; grade is what matters
        qb = _make_player(position="QB", base_score=90.0)
        rb = _make_player(position="RB", base_score=85.0, name="RB Player")
        available = [qb, rb]
        state = _make_state(needs={})  # default need=2 → boost=0.0 for both

        qb_val = compute_team_value(qb, state, available)
        rb_val = compute_team_value(rb, state, available)

        assert qb_val > rb_val

    def test_returns_float(self):
        player = _make_player()
        state = _make_state()
        val = compute_team_value(player, state, [player])
        assert isinstance(val, float)
        assert val > 0.0

    def test_zero_base_score_returns_near_zero(self):
        player = _make_player(base_score=0.0)
        state = _make_state()
        val = compute_team_value(player, state, [player])
        assert val == pytest.approx(0.0, abs=1.0)


# ---------------------------------------------------------------------------
# _compute_drain_rate
# ---------------------------------------------------------------------------


class TestComputeDrainRate:
    def test_full_pool_no_drain(self):
        """10+ available players at position → drain rate near 0."""
        pool = [_make_player(name=f"Player {i}", position="WR") for i in range(15)]
        rate = _compute_drain_rate("WR", pool)
        assert rate == 0.0

    def test_empty_pool_full_drain(self):
        """No available players → drain rate = 1.0."""
        rate = _compute_drain_rate("WR", [])
        assert rate == pytest.approx(1.0)

    def test_partial_pool_partial_drain(self):
        """5 of 10 top players remaining → rate = 0.5."""
        pool = [_make_player(name=f"WR {i}", position="WR") for i in range(5)]
        rate = _compute_drain_rate("WR", pool)
        assert rate == pytest.approx(0.5)

    def test_ignores_other_positions(self):
        """Other position players don't affect the drain rate."""
        pool = [_make_player(name=f"QB {i}", position="QB") for i in range(10)]
        rate = _compute_drain_rate("WR", pool)
        assert rate == pytest.approx(1.0)  # No WRs available → fully drained


# ---------------------------------------------------------------------------
# _supply_pressure_factor
# ---------------------------------------------------------------------------


class TestSupplyPressureFactor:
    def test_no_need_returns_1(self):
        """Low need level → no supply pressure boost."""
        player = _make_player(position="QB", base_score=80.0)
        state = _make_state(needs={"QB": 1})
        available = [player, _make_player(name="QB2", position="QB", base_score=79.0)]
        factor = _supply_pressure_factor(player, state, available)
        assert factor == pytest.approx(1.0)

    def test_talent_cliff_boosts_high_need_team(self):
        """Large talent cliff + high need → factor > 1.0."""
        best = _make_player(position="QB", base_score=90.0)
        second = _make_player(name="QB2", position="QB", base_score=70.0)
        state = _make_state(needs={"QB": 5})
        available = [best, second]
        factor = _supply_pressure_factor(best, state, available)
        assert factor > 1.0

    def test_factor_capped_at_max_boost(self):
        """Supply pressure cannot exceed max_boost from config."""
        from app.analytics.position_value import get_supply_pressure_config

        max_boost = get_supply_pressure_config()["max_boost"]
        best = _make_player(position="QB", base_score=100.0)
        second = _make_player(name="QB2", position="QB", base_score=0.0)
        state = _make_state(needs={"QB": 5})
        available = [best, second]
        factor = _supply_pressure_factor(best, state, available)
        assert factor <= max_boost


# ---------------------------------------------------------------------------
# rank_players_for_team
# ---------------------------------------------------------------------------


class TestRankPlayersForTeam:
    def test_returns_sorted_descending(self):
        players = [
            _make_player(name="A", position="WR", base_score=60.0),
            _make_player(name="B", position="QB", base_score=80.0),
            _make_player(name="C", position="EDGE", base_score=70.0),
        ]
        state = _make_state()
        ranked = rank_players_for_team(players, state)
        scores = [s for s, _ in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_empty_pool_returns_empty(self):
        state = _make_state()
        assert rank_players_for_team([], state) == []

    def test_need_affects_ranking(self):
        """Team with high CB need should rank CBs above equally-scored WRs."""
        cb = _make_player(name="CB1", position="CB", base_score=70.0)
        wr = _make_player(name="WR1", position="WR", base_score=70.0)
        state = _make_state(needs={"CB": 5, "WR": 1})
        ranked = rank_players_for_team([wr, cb], state)
        top_player = ranked[0][1]
        assert top_player.position == "CB"

    def test_critical_need_beats_significantly_better_off_need_player(self):
        """Level-5 need position beats a player ~20% stronger at a no-need position.

        The 35% boost for critical need (level 5) plus the -12% penalty for
        no-need (level 0) should overcome a raw base-score gap of ~20 points,
        reflecting realistic NFL draft behaviour where teams fill critical holes.
        """
        # CB at level-5 need: 70 * (1 + 0.35) = 94.5
        # QB at level-0 (already drafted): 84 * (1 - 0.12) = 73.9
        cb = _make_player(name="Need CB", position="CB", base_score=70.0)
        qb = _make_player(name="No-Need QB", position="QB", base_score=84.0)
        state = _make_state(needs={"CB": 5, "QB": 0})
        ranked = rank_players_for_team([qb, cb], state)
        assert ranked[0][1].position == "CB"

    def test_bpa_wins_when_talent_gap_is_extreme(self):
        """Best player available at a no-need position beats a modest need player.

        When the raw base-score gap is large, the BPA model should prevail so
        elite prospects are not wasted on teams that barely need them.
        Uses a deep CB pool to neutralise supply pressure, isolating the
        need boost signal.

        Math (no supply pressure since 10 CBs available):
          Elite WR level-0: 95 * (1 - 0.12) = 83.6
          Mediocre CB level-5: 60 * (1 + 0.35) = 81.0  → WR wins
        """
        wr = _make_player(name="Elite WR", position="WR", base_score=95.0)
        cb = _make_player(name="Need CB", position="CB", base_score=60.0)
        # Add 9 more CBs to suppress drain-rate supply pressure
        deep_cbs = [
            _make_player(name=f"CB Depth {i}", position="CB", base_score=55.0)
            for i in range(9)
        ]
        state = _make_state(needs={"CB": 5, "WR": 0})
        ranked = rank_players_for_team([wr, cb] + deep_cbs, state)
        assert ranked[0][1].position == "WR"

    def test_moderate_need_beats_slightly_better_off_need_player(self):
        """Level-3 need gives enough boost to prefer a player 8% worse in base score."""
        # Needed EDGE at level-3: 75 * (1 + 0.10) = 82.5
        # Off-need WR at level-2 (default): 80 * (1 + 0.00) = 80.0
        edge = _make_player(name="Need EDGE", position="EDGE", base_score=75.0)
        wr = _make_player(name="WR", position="WR", base_score=80.0)
        state = _make_state(needs={"EDGE": 3})  # WR gets default level 2 → 0%
        ranked = rank_players_for_team([wr, edge], state)
        assert ranked[0][1].position == "EDGE"

    def test_returns_tuples_of_float_and_candidate(self):
        players = [_make_player()]
        state = _make_state()
        ranked = rank_players_for_team(players, state)
        assert len(ranked) == 1
        score, player = ranked[0]
        assert isinstance(score, float)
        assert isinstance(player, PlayerCandidate)
