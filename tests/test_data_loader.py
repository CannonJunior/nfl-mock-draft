"""
Unit tests for app/data_loader.py.

Uses the real data files in data/.
Covers:
  - Expected data loading
  - Edge cases (empty players list)
  - Failure cases (missing file)
"""

import pytest
from app import data_loader
from app.models_core import Pick, Team


@pytest.fixture(autouse=True)
def clear_lru_cache():
    """Ensure LRU caches are cleared between tests to avoid state leakage."""
    data_loader.clear_cache()
    yield
    data_loader.clear_cache()


# -----------------------------------------------------------------------
# load_teams
# -----------------------------------------------------------------------


class TestLoadTeams:
    """Tests for data_loader.load_teams()."""

    def test_loads_32_teams(self):
        """load_teams returns all 32 NFL teams from data/teams.json."""
        teams = data_loader.load_teams()
        assert len(teams) == 32

    def test_teams_indexed_by_abbreviation(self):
        """load_teams indexes teams by their abbreviation."""
        teams = data_loader.load_teams()
        assert "lv" in teams
        assert teams["lv"].name == "Las Vegas Raiders"

    def test_all_teams_have_logo_url(self):
        """Every team has a non-empty logo_url."""
        teams = data_loader.load_teams()
        for abbrev, team in teams.items():
            assert team.logo_url, f"Team {abbrev} missing logo_url"

    def test_team_colors_are_hex(self):
        """Team colors look like hex color strings."""
        teams = data_loader.load_teams()
        for abbrev, team in teams.items():
            assert team.primary_color.startswith("#"), (
                f"Team {abbrev} primary_color not hex: {team.primary_color}"
            )

    def test_missing_file_raises(self, tmp_path, monkeypatch):
        """load_teams raises FileNotFoundError when teams.json is absent."""
        monkeypatch.setattr(data_loader, "DATA_DIR", tmp_path)
        data_loader.clear_cache()
        with pytest.raises(FileNotFoundError):
            data_loader.load_teams()


# -----------------------------------------------------------------------
# load_picks
# -----------------------------------------------------------------------


class TestLoadPicks:
    """Tests for data_loader.load_picks()."""

    def test_loads_all_picks(self):
        """load_picks returns 100 picks across 3 rounds."""
        picks = data_loader.load_picks()
        assert len(picks) == 100

    def test_picks_sorted_by_pick_number(self):
        """load_picks returns picks in ascending pick_number order."""
        picks = data_loader.load_picks()
        numbers = [p.pick_number for p in picks]
        assert numbers == sorted(numbers)

    def test_round_1_has_32_picks(self):
        """Round 1 contains exactly 32 picks."""
        picks = data_loader.load_picks()
        r1 = [p for p in picks if p.round == 1]
        assert len(r1) == 32

    def test_traded_picks_have_from_list(self):
        """Known traded picks (e.g. pick 13) have non-empty traded_from."""
        picks = data_loader.load_picks()
        pick_13 = next(p for p in picks if p.pick_number == 13)
        assert pick_13.current_team == "lar"
        assert "atl" in pick_13.traded_from

    def test_first_pick_is_raiders(self):
        """Overall pick #1 belongs to the Raiders."""
        picks = data_loader.load_picks()
        assert picks[0].current_team == "lv"

    def test_missing_file_raises(self, tmp_path, monkeypatch):
        """load_picks raises FileNotFoundError when picks.json is absent."""
        monkeypatch.setattr(data_loader, "DATA_DIR", tmp_path)
        data_loader.clear_cache()
        with pytest.raises(FileNotFoundError):
            data_loader.load_picks()


# -----------------------------------------------------------------------
# load_players
# -----------------------------------------------------------------------


class TestLoadPlayers:
    """Tests for data_loader.load_players()."""

    def test_empty_players_returns_empty_dict(self):
        """load_players returns empty dict when players.json has no entries."""
        players = data_loader.load_players()
        # data/players.json is initially empty
        assert isinstance(players, dict)
        assert len(players) == 0

    def test_missing_file_raises(self, tmp_path, monkeypatch):
        """load_players raises FileNotFoundError when players.json is absent."""
        monkeypatch.setattr(data_loader, "DATA_DIR", tmp_path)
        data_loader.clear_cache()
        with pytest.raises(FileNotFoundError):
            data_loader.load_players()


# -----------------------------------------------------------------------
# enrich_picks
# -----------------------------------------------------------------------


class TestEnrichPicks:
    """Tests for data_loader.enrich_picks()."""

    def _make_team(self, abbrev: str) -> Team:
        return Team(
            abbreviation=abbrev,
            name=f"Team {abbrev}",
            city="City",
            nickname="Nick",
            primary_color="#000",
            secondary_color="#FFF",
            logo_url="https://example.com/logo.png",
        )

    def test_expected_enrichment(self):
        """enrich_picks joins pick with team correctly."""
        picks = [Pick(pick_number=1, round=1, pick_in_round=1, current_team="lv")]
        teams = {"lv": self._make_team("lv")}
        result = data_loader.enrich_picks(picks, teams, {})
        assert len(result) == 1
        assert result[0].team.abbreviation == "lv"
        assert result[0].player is None

    def test_traded_from_teams_resolved(self):
        """enrich_picks resolves traded_from abbreviations to Team objects."""
        picks = [
            Pick(
                pick_number=13,
                round=1,
                pick_in_round=13,
                current_team="lar",
                traded_from=["atl"],
            )
        ]
        teams = {"lar": self._make_team("lar"), "atl": self._make_team("atl")}
        result = data_loader.enrich_picks(picks, teams, {})
        assert len(result[0].traded_from_teams) == 1
        assert result[0].traded_from_teams[0].abbreviation == "atl"

    def test_missing_team_raises_key_error(self):
        """enrich_picks raises KeyError when current_team is not in teams dict."""
        picks = [Pick(pick_number=1, round=1, pick_in_round=1, current_team="xyz")]
        with pytest.raises(KeyError):
            data_loader.enrich_picks(picks, {}, {})

    def test_unknown_traded_from_skipped(self):
        """enrich_picks silently skips unknown traded_from abbreviations."""
        picks = [
            Pick(
                pick_number=1,
                round=1,
                pick_in_round=1,
                current_team="lv",
                traded_from=["unknown"],
            )
        ]
        teams = {"lv": self._make_team("lv")}
        result = data_loader.enrich_picks(picks, teams, {})
        assert result[0].traded_from_teams == []


# -----------------------------------------------------------------------
# get_enriched_picks_by_round / get_enriched_pick_by_number
# -----------------------------------------------------------------------


class TestConvenienceFunctions:
    """Tests for the convenience accessor functions."""

    def test_get_by_round_filters_correctly(self):
        """get_enriched_picks_by_round returns only the requested round."""
        r1 = data_loader.get_enriched_picks_by_round(1)
        assert all(ep.pick.round == 1 for ep in r1)
        assert len(r1) == 32

    def test_get_pick_by_number_found(self):
        """get_enriched_pick_by_number returns the correct pick."""
        ep = data_loader.get_enriched_pick_by_number(1)
        assert ep is not None
        assert ep.pick.pick_number == 1

    def test_get_pick_by_number_not_found(self):
        """get_enriched_pick_by_number returns None for a nonexistent pick."""
        ep = data_loader.get_enriched_pick_by_number(9999)
        assert ep is None
