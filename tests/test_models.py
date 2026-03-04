"""
Unit tests for app/models.py Pydantic data models.

Covers:
  - Expected construction
  - Optional field defaults
  - Validation failure on bad data
"""

import pytest
from pydantic import ValidationError

from app.models_core import (
    BiographicalInfo,
    EnrichedPick,
    InjuryRecord,
    MediaLink,
    Pick,
    Player,
    StatView,
    Team,
)


# -----------------------------------------------------------------------
# Team
# -----------------------------------------------------------------------


class TestTeam:
    """Tests for the Team model."""

    def test_expected_construction(self):
        """Team builds correctly from valid data."""
        team = Team(
            abbreviation="lv",
            name="Las Vegas Raiders",
            city="Las Vegas",
            nickname="Raiders",
            primary_color="#000000",
            secondary_color="#A5ACAF",
            logo_url="https://a.espncdn.com/i/teamlogos/nfl/500/lv.png",
        )
        assert team.abbreviation == "lv"
        assert team.nickname == "Raiders"

    def test_missing_required_field_raises(self):
        """Team raises ValidationError when a required field is absent."""
        with pytest.raises(ValidationError):
            Team(
                abbreviation="lv",
                name="Las Vegas Raiders",
                # missing city, nickname, colors, logo_url
            )

    def test_extra_fields_ignored(self):
        """Team silently ignores unknown fields (Pydantic v2 default)."""
        team = Team(
            abbreviation="lv",
            name="Las Vegas Raiders",
            city="Las Vegas",
            nickname="Raiders",
            primary_color="#000",
            secondary_color="#AAA",
            logo_url="https://example.com/lv.png",
        )
        assert team.abbreviation == "lv"


# -----------------------------------------------------------------------
# Pick
# -----------------------------------------------------------------------


class TestPick:
    """Tests for the Pick model."""

    def _minimal_pick(self, **kwargs) -> dict:
        base = {
            "pick_number": 1,
            "round": 1,
            "pick_in_round": 1,
            "current_team": "lv",
        }
        base.update(kwargs)
        return base

    def test_expected_construction(self):
        """Pick builds with required fields and sensible defaults."""
        pick = Pick(**self._minimal_pick())
        assert pick.pick_number == 1
        assert pick.traded_from == []
        assert pick.is_compensatory is False
        assert pick.player_id is None

    def test_traded_from_stores_list(self):
        """Pick stores a trade chain list correctly."""
        pick = Pick(**self._minimal_pick(traded_from=["atl", "gb"]))
        assert pick.traded_from == ["atl", "gb"]

    def test_compensatory_flag(self):
        """Pick marks compensatory picks correctly."""
        pick = Pick(**self._minimal_pick(is_compensatory=True))
        assert pick.is_compensatory is True

    def test_invalid_pick_number_type(self):
        """Pick raises ValidationError when pick_number is not an int."""
        with pytest.raises(ValidationError):
            Pick(**self._minimal_pick(pick_number="one"))


# -----------------------------------------------------------------------
# Player
# -----------------------------------------------------------------------


class TestPlayer:
    """Tests for the Player model."""

    def _minimal_player(self, **kwargs) -> dict:
        base = {
            "player_id": "p001",
            "name": "Caleb Williams",
            "position": "QB",
            "college": "USC",
        }
        base.update(kwargs)
        return base

    def test_expected_construction(self):
        """Player builds from minimal data with empty lists as defaults."""
        player = Player(**self._minimal_player())
        assert player.name == "Caleb Williams"
        assert player.injury_history == []
        assert player.stat_views == []
        assert player.media_links == []
        assert isinstance(player.bio, BiographicalInfo)

    def test_with_bio(self):
        """Player accepts and stores BiographicalInfo correctly."""
        player = Player(
            **self._minimal_player(
                bio={"height_inches": 76, "weight_lbs": 218, "age": 21}
            )
        )
        assert player.bio.height_inches == 76
        assert player.bio.weight_lbs == 218

    def test_with_injury_history(self):
        """Player stores a list of InjuryRecord objects."""
        player = Player(
            **self._minimal_player(
                injury_history=[
                    {"year": 2023, "injury_type": "Knee Sprain", "games_missed": 2}
                ]
            )
        )
        assert len(player.injury_history) == 1
        assert player.injury_history[0].injury_type == "Knee Sprain"

    def test_grade_optional(self):
        """Player grade is None by default."""
        player = Player(**self._minimal_player())
        assert player.grade is None


# -----------------------------------------------------------------------
# BiographicalInfo
# -----------------------------------------------------------------------


class TestBiographicalInfo:
    """Tests for BiographicalInfo."""

    def test_all_optional(self):
        """BiographicalInfo can be constructed with zero fields."""
        bio = BiographicalInfo()
        assert bio.height_inches is None
        assert bio.forty_yard_dash is None

    def test_partial_construction(self):
        """BiographicalInfo stores partial data correctly."""
        bio = BiographicalInfo(height_inches=76, weight_lbs=245)
        assert bio.height_inches == 76
        assert bio.weight_lbs == 245
        assert bio.age is None

    def test_invalid_height_type(self):
        """BiographicalInfo raises ValidationError for non-numeric height."""
        with pytest.raises(ValidationError):
            BiographicalInfo(height_inches="six foot four")


# -----------------------------------------------------------------------
# InjuryRecord
# -----------------------------------------------------------------------


class TestInjuryRecord:
    """Tests for InjuryRecord."""

    def test_expected_construction(self):
        """InjuryRecord builds with required fields."""
        rec = InjuryRecord(year=2024, injury_type="ACL Tear", games_missed=17)
        assert rec.games_missed == 17

    def test_games_missed_optional(self):
        """InjuryRecord does not require games_missed."""
        rec = InjuryRecord(year=2024, injury_type="Hamstring")
        assert rec.games_missed is None

    def test_missing_year_raises(self):
        """InjuryRecord raises ValidationError without year."""
        with pytest.raises(ValidationError):
            InjuryRecord(injury_type="Hamstring")


# -----------------------------------------------------------------------
# StatView
# -----------------------------------------------------------------------


class TestStatView:
    """Tests for StatView."""

    def test_expected_construction(self):
        """StatView stores stats dict correctly."""
        sv = StatView(view_name="Passing", season="2025", stats={"TD": 28, "INT": 6})
        assert sv.stats["TD"] == 28

    def test_empty_stats_default(self):
        """StatView defaults to empty dict for stats."""
        sv = StatView(view_name="Overview", season="Career")
        assert sv.stats == {}


# -----------------------------------------------------------------------
# MediaLink
# -----------------------------------------------------------------------


class TestMediaLink:
    """Tests for MediaLink."""

    def test_expected_construction(self):
        """MediaLink builds with required fields."""
        link = MediaLink(
            source_type="news",
            title="Top QB prospect",
            url="https://example.com/article",
            source_name="ESPN",
        )
        assert link.source_type == "news"
        assert link.published_at is None

    def test_missing_url_raises(self):
        """MediaLink raises ValidationError without url."""
        with pytest.raises(ValidationError):
            MediaLink(source_type="news", title="Article", source_name="ESPN")


# -----------------------------------------------------------------------
# EnrichedPick
# -----------------------------------------------------------------------


class TestEnrichedPick:
    """Tests for EnrichedPick composite model."""

    def _team(self, abbrev="lv") -> Team:
        return Team(
            abbreviation=abbrev,
            name="Test Team",
            city="Test City",
            nickname="Testers",
            primary_color="#000",
            secondary_color="#FFF",
            logo_url="https://example.com/logo.png",
        )

    def _pick(self) -> Pick:
        return Pick(pick_number=1, round=1, pick_in_round=1, current_team="lv")

    def test_expected_construction(self):
        """EnrichedPick builds with pick and team, no player."""
        ep = EnrichedPick(pick=self._pick(), team=self._team())
        assert ep.pick.pick_number == 1
        assert ep.player is None
        assert ep.traded_from_teams == []

    def test_with_traded_from_teams(self):
        """EnrichedPick stores traded-from team list."""
        ep = EnrichedPick(
            pick=self._pick(),
            team=self._team("lar"),
            traded_from_teams=[self._team("atl")],
        )
        assert len(ep.traded_from_teams) == 1
        assert ep.traded_from_teams[0].abbreviation == "atl"
