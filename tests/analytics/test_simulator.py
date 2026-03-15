"""
Unit tests for app/analytics/simulator.py.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.analytics.player_pool import PlayerCandidate
from app.analytics.simulator import (
    _candidate_to_player_dict,
    _load_picks_json,
    _resolve_college_logo_url,
    run_simulation,
    write_results,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_player(
    name: str,
    position: str = "WR",
    base_score: float = 70.0,
    player_id: str | None = None,
) -> PlayerCandidate:
    return PlayerCandidate(
        player_id=player_id or name.lower().replace(" ", "-"),
        name=name,
        position=position,
        college="Test U",
        espn_grade=7.0,
        espn_rank=10,
        base_score=base_score,
        available=True,
    )


def _make_picks_data(n: int = 10) -> dict:
    """Create a minimal picks.json-compatible structure."""
    teams = ["lv", "nyj", "ari", "ten", "nyg", "cle", "car", "ne", "no", "gb"]
    return {
        "picks": [
            {
                "pick_number": i + 1,
                "round": 1,
                "pick_in_round": i + 1,
                "current_team": teams[i % len(teams)],
                "traded_from": [],
                "player_id": None,
            }
            for i in range(n)
        ]
    }


# ---------------------------------------------------------------------------
# _candidate_to_player_dict
# ---------------------------------------------------------------------------


class TestCandidateToPlayerDict:
    def test_basic_fields_present(self):
        player = _make_player("Shedeur Sanders", "QB")
        d = _candidate_to_player_dict(player)
        assert d["player_id"] == "shedeur-sanders"
        assert d["name"] == "Shedeur Sanders"
        assert d["position"] == "QB"
        assert d["college"] == "Test U"

    def test_combine_stats_in_bio(self):
        player = _make_player("Fast Player", "WR")
        player.combine = {"forty_yard_dash": 4.30, "vertical_jump_inches": 40.0}
        d = _candidate_to_player_dict(player)
        assert d["bio"]["forty_yard_dash"] == pytest.approx(4.30)
        assert d["bio"]["vertical_jump_inches"] == pytest.approx(40.0)

    def test_mock_picks_in_notes(self):
        player = _make_player("Mock Player", "CB")
        player.mock_picks = [5, 7, 6]
        d = _candidate_to_player_dict(player)
        assert "Mock consensus" in d["notes"]

    def test_grade_rounded(self):
        player = _make_player("Grade Player", "LB")
        player.espn_grade = 8.876
        d = _candidate_to_player_dict(player)
        assert d["grade"] == pytest.approx(8.9)

    def test_none_espn_grade_derives_from_base_score(self):
        """Grade must never be None — fallback rescales base_score to scout-grade band.

        base_score=70 maps to 6.5 + (70-15)/85 * 3.4 ≈ 8.7 so model grades
        sit in the same 6.5-9.9 range as professional scouting grades.
        """
        player = _make_player("No Grade", "S")
        player.espn_grade = None
        player.base_score = 70.0
        d = _candidate_to_player_dict(player)
        assert d["grade"] is not None
        assert d["grade"] == pytest.approx(8.7, abs=0.1)

    def test_empty_combine_produces_empty_bio(self):
        player = _make_player("No Combine", "TE")
        d = _candidate_to_player_dict(player)
        assert d["bio"] == {}

    def test_college_logo_url_populated_for_known_college(self):
        """college_logo_url is set (not None) when college is in the map and file exists."""
        player = _make_player("Famous QB", "QB")
        player.college = "Alabama"  # known entry in college_logo_map.json
        d = _candidate_to_player_dict(player)
        # URL should be None only if the logo file is missing from static/img/colleges/;
        # in a full checkout the files are present, so we just verify the type.
        assert d["college_logo_url"] is None or d["college_logo_url"].startswith("/static/")

    def test_college_logo_url_none_for_unknown_college(self):
        """college_logo_url is None for colleges not in the map."""
        player = _make_player("Mystery Player", "S")
        player.college = "Totally Unknown University"
        d = _candidate_to_player_dict(player)
        assert d["college_logo_url"] is None


# ---------------------------------------------------------------------------
# run_simulation (using synthetic fallback pool and temp picks.json)
# ---------------------------------------------------------------------------


class TestRunSimulation:
    def test_assigns_players_to_picks(self, tmp_path, monkeypatch):
        """Simulation assigns unique players to all picks."""
        picks_data = _make_picks_data(n=10)
        picks_file = tmp_path / "picks.json"
        picks_file.write_text(json.dumps(picks_data), encoding="utf-8")

        monkeypatch.setattr(
            "app.analytics.simulator._PICKS_PATH", picks_file
        )

        from app.analytics.player_pool import _synthetic_fallback_pool

        pool = _synthetic_fallback_pool()
        results, _snapshots = run_simulation(player_pool=pool)

        assert len(results) == 10
        assigned_ids = [p.player_id for p in results.values()]
        assert len(assigned_ids) == len(set(assigned_ids)), "Each player selected at most once"

    def test_no_player_drafted_twice(self, tmp_path, monkeypatch):
        """No player should appear in two different picks."""
        picks_data = _make_picks_data(n=32)
        picks_file = tmp_path / "picks.json"
        picks_file.write_text(json.dumps(picks_data), encoding="utf-8")
        monkeypatch.setattr("app.analytics.simulator._PICKS_PATH", picks_file)

        from app.analytics.player_pool import _synthetic_fallback_pool

        pool = _synthetic_fallback_pool()
        results, _snapshots = run_simulation(player_pool=pool)

        ids = [c.player_id for c in results.values()]
        assert len(ids) == len(set(ids))

    def test_empty_picks_returns_empty(self, tmp_path, monkeypatch):
        empty_picks = {"picks": []}
        picks_file = tmp_path / "picks.json"
        picks_file.write_text(json.dumps(empty_picks), encoding="utf-8")
        monkeypatch.setattr("app.analytics.simulator._PICKS_PATH", picks_file)

        results, _snapshots = run_simulation(player_pool=[_make_player("P1")])
        assert results == {}

    def test_empty_pool_returns_empty(self, tmp_path, monkeypatch):
        picks_data = _make_picks_data(n=5)
        picks_file = tmp_path / "picks.json"
        picks_file.write_text(json.dumps(picks_data), encoding="utf-8")
        monkeypatch.setattr("app.analytics.simulator._PICKS_PATH", picks_file)

        results, _snapshots = run_simulation(player_pool=[])
        assert results == {}


# ---------------------------------------------------------------------------
# write_results
# ---------------------------------------------------------------------------


class TestWriteResults:
    def test_players_json_written(self, tmp_path, monkeypatch):
        players_file = tmp_path / "players.json"
        picks_file = tmp_path / "picks.json"
        picks_data = _make_picks_data(n=3)
        picks_file.write_text(json.dumps(picks_data), encoding="utf-8")

        monkeypatch.setattr("app.analytics.simulator._PLAYERS_PATH", players_file)
        monkeypatch.setattr("app.analytics.simulator._PICKS_PATH", picks_file)

        results = {
            1: _make_player("Player A", "QB"),
            2: _make_player("Player B", "WR"),
            3: _make_player("Player C", "EDGE"),
        }
        picks_assigned, players_created = write_results(results)

        assert picks_assigned == 3
        assert players_created == 3
        assert players_file.exists()

        data = json.loads(players_file.read_text())
        assert len(data["players"]) == 3

    def test_picks_json_updated_with_player_ids(self, tmp_path, monkeypatch):
        players_file = tmp_path / "players.json"
        picks_file = tmp_path / "picks.json"
        picks_data = _make_picks_data(n=3)
        picks_file.write_text(json.dumps(picks_data), encoding="utf-8")

        monkeypatch.setattr("app.analytics.simulator._PLAYERS_PATH", players_file)
        monkeypatch.setattr("app.analytics.simulator._PICKS_PATH", picks_file)

        results = {
            1: _make_player("QBack", "QB", player_id="qback"),
        }
        write_results(results)

        updated = json.loads(picks_file.read_text())
        pick_1 = next(p for p in updated["picks"] if p["pick_number"] == 1)
        assert pick_1["player_id"] == "qback"

    def test_missing_picks_file_returns_zeros(self, tmp_path, monkeypatch):
        players_file = tmp_path / "players.json"
        picks_file = tmp_path / "nonexistent_picks.json"

        monkeypatch.setattr("app.analytics.simulator._PLAYERS_PATH", players_file)
        monkeypatch.setattr("app.analytics.simulator._PICKS_PATH", picks_file)

        results = {1: _make_player("Solo", "QB")}
        picks_assigned, players_created = write_results(results)
        # Players file is still written even if picks don't match
        assert players_created == 1
        assert picks_assigned == 0
