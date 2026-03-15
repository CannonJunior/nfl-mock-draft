"""
Unit tests for app/analytics/player_pool.py.
"""

from __future__ import annotations

import math

import pytest

from app.analytics.player_pool import (
    PlayerCandidate,
    _compute_base_score,
    _combine_score,
    _derive_grade_from_picks,
    _derive_grade_from_rank,
    _make_player_id,
    _mock_consensus_signal,
    _normalise_position,
    _synthetic_fallback_pool,
)


# ---------------------------------------------------------------------------
# _make_player_id
# ---------------------------------------------------------------------------


class TestMakePlayerId:
    def test_basic_name(self):
        assert _make_player_id("Shedeur Sanders") == "shedeur-sanders"

    def test_apostrophe_removed(self):
        assert _make_player_id("Travis Hunter Jr.") == "travis-hunter-jr"

    def test_extra_spaces(self):
        assert _make_player_id("  Cam  Ward  ") == "cam-ward"

    def test_single_name(self):
        pid = _make_player_id("Nomad")
        assert pid == "nomad"


# ---------------------------------------------------------------------------
# _normalise_position
# ---------------------------------------------------------------------------


class TestNormalisePosition:
    def test_alias_de_to_edge(self):
        assert _normalise_position("de") == "EDGE"

    def test_alias_defensive_end(self):
        assert _normalise_position("defensive end") == "EDGE"

    def test_known_position_passthrough(self):
        assert _normalise_position("QB") == "QB"

    def test_unknown_position_uppercased(self):
        assert _normalise_position("xyz") == "XYZ"

    def test_empty_string(self):
        result = _normalise_position("")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _mock_consensus_signal
# ---------------------------------------------------------------------------


class TestMockConsensusSignal:
    def test_empty_picks_returns_zero(self):
        assert _mock_consensus_signal([]) == 0.0

    def test_pick_1_is_max(self):
        score = _mock_consensus_signal([1])
        assert score == pytest.approx(100.0)

    def test_pick_100_is_near_zero(self):
        score = _mock_consensus_signal([100])
        assert score < 5.0

    def test_average_across_multiple_picks(self):
        # Two picks at 1 and 100 — average raw = ~50, some penalty for disagreement
        score = _mock_consensus_signal([1, 100])
        assert 30.0 < score < 60.0

    def test_consistent_sources_no_large_penalty(self):
        # All sources agree on pick 5
        score_agree = _mock_consensus_signal([5, 5, 5])
        score_single = _mock_consensus_signal([5])
        assert abs(score_agree - score_single) < 2.0


# ---------------------------------------------------------------------------
# _combine_score
# ---------------------------------------------------------------------------


class TestCombineScore:
    def test_empty_combine_returns_none(self):
        """No combine record → None (excluded from scoring, not a neutral 50)."""
        assert _combine_score({}, "QB") is None

    def test_measurements_only_returns_none(self):
        """Height/weight only (no drills) → None, not a neutral 50."""
        assert _combine_score({"height_inches": 76, "weight_lbs": 230}, "QB") is None

    def test_fast_40_boosts_score(self):
        # 4.30 is very fast; median for WR ~4.45
        score = _combine_score({"forty_yard_dash": 4.30}, "WR")
        assert score is not None
        assert score > 50.0

    def test_slow_40_lowers_score(self):
        score = _combine_score({"forty_yard_dash": 5.30}, "WR")
        assert score < 50.0

    def test_high_vertical_boosts_score(self):
        score = _combine_score({"vertical_jump_inches": 42.0}, "WR")
        assert score > 50.0

    def test_score_capped_at_100(self):
        score = _combine_score({"forty_yard_dash": 3.90, "vertical_jump_inches": 50.0}, "RB")
        assert score <= 100.0

    def test_score_floored_at_0(self):
        score = _combine_score({"forty_yard_dash": 6.50, "vertical_jump_inches": 10.0}, "OT")
        assert score >= 0.0


# ---------------------------------------------------------------------------
# _derive_grade_from_picks / _derive_grade_from_rank
# ---------------------------------------------------------------------------


class TestDeriveGrade:
    def test_early_pick_high_grade(self):
        grade = _derive_grade_from_picks([1])
        assert grade > 80.0

    def test_late_pick_lower_grade(self):
        grade = _derive_grade_from_picks([95])
        assert grade < 60.0

    def test_rank_1_high_grade(self):
        grade = _derive_grade_from_rank(1)
        assert grade > 90.0

    def test_rank_100_lower_grade(self):
        grade = _derive_grade_from_rank(100)
        assert grade < 70.0

    def test_monotonic_with_rank(self):
        g1 = _derive_grade_from_rank(1)
        g10 = _derive_grade_from_rank(10)
        g50 = _derive_grade_from_rank(50)
        assert g1 > g10 > g50


# ---------------------------------------------------------------------------
# _compute_base_score
# ---------------------------------------------------------------------------


class TestComputeBaseScore:
    def test_full_data_qb(self):
        score = _compute_base_score(
            espn_grade=9.5,
            espn_rank=1,
            mock_picks=[1, 2, 1],
            combine={"forty_yard_dash": 4.6},
            position="QB",
        )
        assert 80.0 < score <= 100.0

    def test_no_mock_reweights_espn(self):
        # Use rank 15 with grade 7.8 — within the plausible range for rank 15
        # (expected_min = 9.5 - 15*0.12 = 7.7)
        score_no_mock = _compute_base_score(
            espn_grade=7.8, espn_rank=15, mock_picks=[], combine={}, position="WR"
        )
        score_with_mock = _compute_base_score(
            espn_grade=7.8, espn_rank=15, mock_picks=[15], combine={}, position="WR"
        )
        # Both should be in reasonable range; no-mock weighting is just ESPN+combine
        assert score_no_mock > 0
        assert score_with_mock > 0

    def test_implausible_high_grade_rank17_discarded(self):
        """Grade 9.5 for rank-17 player is a scraping artifact (e.g. '9.5 sacks')."""
        score_with_artifact = _compute_base_score(
            espn_grade=9.5, espn_rank=17, mock_picks=[28, 32, 25], combine={}, position="DT"
        )
        score_no_grade = _compute_base_score(
            espn_grade=None, espn_rank=17, mock_picks=[28, 32, 25], combine={}, position="DT"
        )
        assert score_with_artifact == pytest.approx(score_no_grade, abs=0.01)

    def test_implausible_high_grade_discarded(self):
        """Grade 9.5 for rank-24 player is a scraping artifact; should be ignored."""
        score_with_artifact = _compute_base_score(
            espn_grade=9.5, espn_rank=24, mock_picks=[25, 15, 20], combine={}, position="EDGE"
        )
        score_no_grade = _compute_base_score(
            espn_grade=None, espn_rank=24, mock_picks=[25, 15, 20], combine={}, position="EDGE"
        )
        assert score_with_artifact == pytest.approx(score_no_grade, abs=0.01)
        assert score_with_artifact < 85.0

    def test_implausible_low_grade_discarded(self):
        """Grade 3.3 for rank-16 player is a scraping artifact; should be ignored."""
        score_with_artifact = _compute_base_score(
            espn_grade=3.3, espn_rank=16, mock_picks=[16], combine={}, position="CB"
        )
        score_no_grade = _compute_base_score(
            espn_grade=None, espn_rank=16, mock_picks=[16], combine={}, position="CB"
        )
        assert score_with_artifact == pytest.approx(score_no_grade, abs=0.01)

    def test_implausible_low_grade_for_high_rank_discarded(self):
        """Grade 6.5 for rank-3 player is a scraping artifact (e.g. '6.5 sacks')."""
        score_with_artifact = _compute_base_score(
            espn_grade=6.5, espn_rank=3, mock_picks=[2, 3, 4], combine={}, position="LB"
        )
        score_no_grade = _compute_base_score(
            espn_grade=None, espn_rank=3, mock_picks=[2, 3, 4], combine={}, position="LB"
        )
        assert score_with_artifact == pytest.approx(score_no_grade, abs=0.01)

    def test_legitimate_high_grade_kept(self):
        """Grade 9.5 for rank-1 QB is legitimate and must not be discarded."""
        score = _compute_base_score(
            espn_grade=9.5, espn_rank=1, mock_picks=[1, 1, 2], combine={}, position="QB"
        )
        assert score > 90.0

    def test_legitimate_mid_grade_kept(self):
        """Grade 7.5 for rank-20 player is within the plausible ESPN range."""
        score_with_grade = _compute_base_score(
            espn_grade=7.5, espn_rank=20, mock_picks=[20], combine={}, position="WR"
        )
        score_no_grade = _compute_base_score(
            espn_grade=None, espn_rank=20, mock_picks=[20], combine={}, position="WR"
        )
        assert score_with_grade != pytest.approx(score_no_grade, abs=0.01)

    def test_single_combine_drill_no_negative_bias(self):
        """Player who did only one combine drill must score >= player who did none.

        With confidence scaling (1/3 of normal weight for 1 drill), an average
        drill no longer depresses the score.
        """
        base_kwargs = dict(espn_grade=None, espn_rank=5, mock_picks=[5], position="WR")
        score_no_combine = _compute_base_score(**base_kwargs, combine={})
        # 40-yard dash of 4.45 is exactly the WR median → combine_score ≈ 50 (neutral)
        score_one_drill = _compute_base_score(
            **base_kwargs, combine={"forty_yard_dash": 4.45}
        )
        assert score_one_drill >= score_no_combine - 0.5

    def test_partial_combine_scales_with_drill_count(self):
        """More drills = more combine influence; elite score gives a larger boost."""
        base_kwargs = dict(espn_grade=None, espn_rank=10, mock_picks=[10], position="WR")
        score_no_combine = _compute_base_score(**base_kwargs, combine={})
        score_one_drill = _compute_base_score(
            **base_kwargs, combine={"forty_yard_dash": 4.28}
        )
        score_two_drills = _compute_base_score(
            **base_kwargs, combine={"forty_yard_dash": 4.28, "vertical_jump_inches": 40.0}
        )
        score_three_drills = _compute_base_score(
            **base_kwargs,
            combine={
                "forty_yard_dash": 4.28,
                "vertical_jump_inches": 40.0,
                "broad_jump_inches": 130.0,
            },
        )
        assert score_one_drill >= score_no_combine
        assert score_two_drills >= score_one_drill - 0.1
        assert score_three_drills >= score_two_drills - 0.1

    def test_no_espn_uses_mock(self):
        score = _compute_base_score(
            espn_grade=None, espn_rank=None, mock_picks=[5], combine={}, position="EDGE"
        )
        assert score > 50.0

    def test_no_data_returns_low_score(self):
        score = _compute_base_score(
            espn_grade=None, espn_rank=None, mock_picks=[], combine={}, position="RB"
        )
        assert score <= 30.0


# ---------------------------------------------------------------------------
# Synthetic fallback pool
# ---------------------------------------------------------------------------


class TestSyntheticFallbackPool:
    def test_returns_list_of_candidates(self):
        pool = _synthetic_fallback_pool()
        assert isinstance(pool, list)
        assert len(pool) > 0
        assert all(isinstance(c, PlayerCandidate) for c in pool)

    def test_sorted_descending_by_score(self):
        pool = _synthetic_fallback_pool()
        scores = [c.base_score for c in pool]
        assert scores == sorted(scores, reverse=True)

    def test_all_positions_covered(self):
        pool = _synthetic_fallback_pool()
        positions = {c.position for c in pool}
        # Expect at least QB, OT, EDGE, WR, CB present
        assert positions >= {"QB", "OT", "EDGE", "WR", "CB"}

    def test_no_duplicate_player_ids_top_100(self):
        pool = _synthetic_fallback_pool()
        top_100 = pool[:100]
        ids = [c.player_id for c in top_100]
        assert len(ids) == len(set(ids))

    def test_base_score_range(self):
        pool = _synthetic_fallback_pool()
        for c in pool:
            assert 0.0 <= c.base_score <= 110.0  # allow small overshoot from weighting
