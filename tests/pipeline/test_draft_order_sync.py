"""
Unit tests for app/pipeline/draft_order_sync.py.
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.pipeline.draft_order_sync import (
    _load_team_name_map,
    _resolve_team_abbrev,
    apply_draft_order_changes,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_NAME_MAP = {
    "baltimore ravens": "bal",
    "las vegas raiders": "lv",
    "new england patriots": "ne",
    "dallas cowboys": "dal",
    "baltimore": "bal",
    "las vegas": "lv",
    "new england": "ne",
    "dallas": "dal",
}

SAMPLE_PICKS_DATA = {
    "picks": [
        {"pick_number": 1, "current_team": "lv", "traded_from": []},
        {"pick_number": 2, "current_team": "nyj", "traded_from": []},
        {"pick_number": 14, "current_team": "bal", "traded_from": []},
        {"pick_number": 50, "current_team": "ne", "traded_from": []},
    ]
}


# ---------------------------------------------------------------------------
# _load_team_name_map
# ---------------------------------------------------------------------------


class TestLoadTeamNameMap:
    def test_returns_dict(self, tmp_path):
        map_file = tmp_path / "team_name_map.json"
        map_file.write_text(
            json.dumps({"Baltimore Ravens": "bal", "Las Vegas Raiders": "lv"}),
            encoding="utf-8",
        )
        with patch("app.pipeline.draft_order_sync._TEAM_NAME_MAP_PATH", map_file):
            result = _load_team_name_map()
        assert result["baltimore ravens"] == "bal"
        assert result["las vegas raiders"] == "lv"

    def test_keys_are_lowercased(self, tmp_path):
        map_file = tmp_path / "team_name_map.json"
        map_file.write_text(json.dumps({"New England Patriots": "ne"}), encoding="utf-8")
        with patch("app.pipeline.draft_order_sync._TEAM_NAME_MAP_PATH", map_file):
            result = _load_team_name_map()
        assert "new england patriots" in result
        assert "New England Patriots" not in result

    def test_missing_file_returns_empty(self, tmp_path):
        missing = tmp_path / "nonexistent.json"
        with patch("app.pipeline.draft_order_sync._TEAM_NAME_MAP_PATH", missing):
            result = _load_team_name_map()
        assert result == {}

    def test_invalid_json_returns_empty(self, tmp_path):
        bad_file = tmp_path / "team_name_map.json"
        bad_file.write_text("NOT JSON", encoding="utf-8")
        with patch("app.pipeline.draft_order_sync._TEAM_NAME_MAP_PATH", bad_file):
            result = _load_team_name_map()
        assert result == {}


# ---------------------------------------------------------------------------
# _resolve_team_abbrev
# ---------------------------------------------------------------------------


class TestResolveTeamAbbrev:
    def test_full_name_resolves(self):
        assert _resolve_team_abbrev("Baltimore Ravens", SAMPLE_NAME_MAP) == "bal"

    def test_case_insensitive(self):
        assert _resolve_team_abbrev("BALTIMORE RAVENS", SAMPLE_NAME_MAP) == "bal"

    def test_city_name_fallback(self):
        # "Baltimore Ravens" not in map but "Baltimore" is
        partial_map = {"baltimore": "bal"}
        assert _resolve_team_abbrev("Baltimore Ravens", partial_map) == "bal"

    def test_short_abbrev_passthrough(self):
        # 2-3 char strings treated as already-abbreviated
        result = _resolve_team_abbrev("LV", {})
        assert result == "lv"

    def test_empty_string_returns_none(self):
        assert _resolve_team_abbrev("", SAMPLE_NAME_MAP) is None

    def test_unknown_long_name_returns_none(self):
        assert _resolve_team_abbrev("Unknown Team Name", SAMPLE_NAME_MAP) is None


# ---------------------------------------------------------------------------
# apply_draft_order_changes
# ---------------------------------------------------------------------------


class TestApplyDraftOrderChanges:
    def _clone_picks(self):
        """Return a deep copy of SAMPLE_PICKS_DATA to avoid cross-test mutation."""
        return json.loads(json.dumps(SAMPLE_PICKS_DATA))

    def test_no_change_when_teams_match(self):
        picks_data = self._clone_picks()
        tankathon = [{"pick_number": 14, "team": "Baltimore Ravens"}]
        changed = apply_draft_order_changes(tankathon, picks_data, SAMPLE_NAME_MAP)
        assert changed == 0
        pick_14 = next(p for p in picks_data["picks"] if p["pick_number"] == 14)
        assert pick_14["current_team"] == "bal"
        assert pick_14["traded_from"] == []

    def test_ownership_change_updates_current_team(self):
        picks_data = self._clone_picks()
        # Tankathon says pick #1 now belongs to Dallas (was Las Vegas)
        tankathon = [{"pick_number": 1, "team": "Dallas Cowboys"}]
        changed = apply_draft_order_changes(tankathon, picks_data, SAMPLE_NAME_MAP)
        assert changed == 1
        pick_1 = next(p for p in picks_data["picks"] if p["pick_number"] == 1)
        assert pick_1["current_team"] == "dal"

    def test_old_owner_appended_to_traded_from(self):
        picks_data = self._clone_picks()
        tankathon = [{"pick_number": 1, "team": "Dallas Cowboys"}]
        apply_draft_order_changes(tankathon, picks_data, SAMPLE_NAME_MAP)
        pick_1 = next(p for p in picks_data["picks"] if p["pick_number"] == 1)
        assert "lv" in pick_1["traded_from"]

    def test_no_duplicate_in_traded_from_chain(self):
        picks_data = self._clone_picks()
        # Pre-populate traded_from with "lv" already
        picks_data["picks"][0]["traded_from"] = ["lv"]
        tankathon = [{"pick_number": 1, "team": "Dallas Cowboys"}]
        apply_draft_order_changes(tankathon, picks_data, SAMPLE_NAME_MAP)
        pick_1 = next(p for p in picks_data["picks"] if p["pick_number"] == 1)
        assert pick_1["traded_from"].count("lv") == 1

    def test_skips_picks_above_max(self):
        picks_data = {
            "picks": [{"pick_number": 97, "current_team": "min", "traded_from": []}]
        }
        # pick 97 > _MAX_SYNC_PICK=96 — should be skipped
        tankathon = [{"pick_number": 97, "team": "Dallas Cowboys"}]
        changed = apply_draft_order_changes(tankathon, picks_data, SAMPLE_NAME_MAP)
        assert changed == 0
        assert picks_data["picks"][0]["current_team"] == "min"

    def test_skips_unknown_team_name(self):
        picks_data = self._clone_picks()
        tankathon = [{"pick_number": 1, "team": "Bogus Team XYZ"}]
        changed = apply_draft_order_changes(tankathon, picks_data, SAMPLE_NAME_MAP)
        assert changed == 0

    def test_skips_pick_not_in_picks_json(self):
        picks_data = self._clone_picks()
        # Pick 99 not in our sample data
        tankathon = [{"pick_number": 99, "team": "Dallas Cowboys"}]
        changed = apply_draft_order_changes(tankathon, picks_data, SAMPLE_NAME_MAP)
        assert changed == 0

    def test_multiple_changes_counted(self):
        picks_data = self._clone_picks()
        tankathon = [
            {"pick_number": 1, "team": "Dallas Cowboys"},   # lv → dal
            {"pick_number": 2, "team": "New England Patriots"},  # nyj → ne
        ]
        changed = apply_draft_order_changes(tankathon, picks_data, SAMPLE_NAME_MAP)
        assert changed == 2

    def test_trade_notes_set_on_change(self):
        picks_data = self._clone_picks()
        tankathon = [{"pick_number": 1, "team": "Dallas Cowboys"}]
        apply_draft_order_changes(tankathon, picks_data, SAMPLE_NAME_MAP)
        pick_1 = next(p for p in picks_data["picks"] if p["pick_number"] == 1)
        assert "trade_notes" in pick_1
        assert "LV" in pick_1["trade_notes"]
        assert "DAL" in pick_1["trade_notes"]


# ---------------------------------------------------------------------------
# sync_draft_order (integration — mocked scraper)
# ---------------------------------------------------------------------------


class TestSyncDraftOrder:
    @pytest.mark.asyncio
    async def test_applies_changes_to_picks_json(self, tmp_path):
        """sync_draft_order writes updated picks.json when ownership changes."""
        picks_file = tmp_path / "picks.json"
        picks_file.write_text(
            json.dumps(
                {"picks": [{"pick_number": 1, "current_team": "lv", "traded_from": []}]}
            ),
            encoding="utf-8",
        )
        map_file = tmp_path / "team_name_map.json"
        map_file.write_text(
            json.dumps({"Dallas Cowboys": "dal", "Dallas": "dal"}), encoding="utf-8"
        )

        mock_pick = MagicMock()
        mock_pick.pick_number = 1
        mock_pick.team = "Dallas Cowboys"

        mock_result = MagicMock()
        mock_result.success = True

        mock_scraper = AsyncMock()
        mock_scraper.fetch_draft_order = AsyncMock(
            return_value=([mock_pick], mock_result)
        )

        with (
            patch("app.pipeline.draft_order_sync._PICKS_PATH", picks_file),
            patch("app.pipeline.draft_order_sync._TEAM_NAME_MAP_PATH", map_file),
            patch("app.scrapers.tankathon.TankathonScraper", return_value=mock_scraper),
        ):
            from app.pipeline.draft_order_sync import sync_draft_order
            changed = await sync_draft_order()

        assert changed == 1
        updated = json.loads(picks_file.read_text())
        assert updated["picks"][0]["current_team"] == "dal"
        assert "lv" in updated["picks"][0]["traded_from"]

    @pytest.mark.asyncio
    async def test_returns_zero_on_scraper_failure(self):
        """If Tankathon fetch fails, sync returns 0 without crashing."""
        mock_scraper = AsyncMock()
        mock_scraper.fetch_draft_order = AsyncMock(side_effect=Exception("network error"))

        with patch("app.scrapers.tankathon.TankathonScraper", return_value=mock_scraper):
            from app.pipeline.draft_order_sync import sync_draft_order
            changed = await sync_draft_order()

        assert changed == 0

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_picks_returned(self):
        """If Tankathon returns empty list, sync returns 0."""
        mock_result = MagicMock()
        mock_result.success = True

        mock_scraper = AsyncMock()
        mock_scraper.fetch_draft_order = AsyncMock(return_value=([], mock_result))

        with patch("app.scrapers.tankathon.TankathonScraper", return_value=mock_scraper):
            from app.pipeline.draft_order_sync import sync_draft_order
            changed = await sync_draft_order()

        assert changed == 0

    @pytest.mark.asyncio
    async def test_returns_zero_when_picks_json_missing(self, tmp_path):
        """If picks.json doesn't exist, sync returns 0 gracefully."""
        missing_picks = tmp_path / "nonexistent_picks.json"
        map_file = tmp_path / "team_name_map.json"
        map_file.write_text(json.dumps({"Dallas Cowboys": "dal"}), encoding="utf-8")

        mock_pick = MagicMock()
        mock_pick.pick_number = 1
        mock_pick.team = "Dallas Cowboys"

        mock_result = MagicMock()
        mock_result.success = True

        mock_scraper = AsyncMock()
        mock_scraper.fetch_draft_order = AsyncMock(
            return_value=([mock_pick], mock_result)
        )

        with (
            patch("app.pipeline.draft_order_sync._PICKS_PATH", missing_picks),
            patch("app.pipeline.draft_order_sync._TEAM_NAME_MAP_PATH", map_file),
            patch("app.scrapers.tankathon.TankathonScraper", return_value=mock_scraper),
        ):
            from app.pipeline.draft_order_sync import sync_draft_order
            changed = await sync_draft_order()

        assert changed == 0
