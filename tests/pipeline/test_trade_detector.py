"""
Unit tests for app/pipeline/trade_detector.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from app.pipeline.trade_detector import (
    TradeUpdate,
    apply_trades_to_picks,
    load_known_trades,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_picks(path: Path, picks: list[dict]) -> None:
    path.write_text(json.dumps({"picks": picks}), encoding="utf-8")


def _write_trades(path: Path, trades: list[dict]) -> None:
    path.write_text(json.dumps({"trades": trades}), encoding="utf-8")


def _pick(number: int, team: str, traded_from: list[str] | None = None) -> dict:
    return {
        "pick_number": number,
        "round": 1,
        "pick_in_round": number,
        "current_team": team,
        "traded_from": traded_from or [],
        "player_id": None,
    }


# ---------------------------------------------------------------------------
# load_known_trades
# ---------------------------------------------------------------------------


class TestLoadKnownTrades:
    def test_returns_empty_when_file_missing(self, tmp_path):
        """Expected: missing file → empty list (no crash)."""
        with patch("app.pipeline.trade_detector._TRADES_PATH", tmp_path / "missing.json"):
            result = load_known_trades()
        assert result == []

    def test_parses_valid_trade(self, tmp_path):
        """Expected: one valid entry → one TradeUpdate with correct fields."""
        path = tmp_path / "known_trades.json"
        _write_trades(path, [
            {
                "pick_number": 7,
                "new_current_team": "dal",
                "traded_from_append": "nyg",
                "trade_notes": "Acquired for a 2nd",
                "confirmed_date": "2026-02-20",
            }
        ])
        with patch("app.pipeline.trade_detector._TRADES_PATH", path):
            result = load_known_trades()
        assert len(result) == 1
        t = result[0]
        assert t.pick_number == 7
        assert t.new_current_team == "dal"
        assert t.traded_from_append == "nyg"
        assert t.trade_notes == "Acquired for a 2nd"

    def test_normalises_team_abbrev_to_lowercase(self, tmp_path):
        """Edge case: uppercase team names in JSON are lowercased."""
        path = tmp_path / "known_trades.json"
        _write_trades(path, [
            {"pick_number": 3, "new_current_team": "DAL", "traded_from_append": "NYG"}
        ])
        with patch("app.pipeline.trade_detector._TRADES_PATH", path):
            result = load_known_trades()
        assert result[0].new_current_team == "dal"
        assert result[0].traded_from_append == "nyg"

    def test_skips_malformed_entry_keeps_valid(self, tmp_path):
        """Edge case: one bad entry skipped; valid entry still returned."""
        path = tmp_path / "known_trades.json"
        _write_trades(path, [
            {"pick_number": "not_a_number", "new_current_team": "dal"},  # bad
            {"pick_number": 10, "new_current_team": "sf"},               # good
        ])
        with patch("app.pipeline.trade_detector._TRADES_PATH", path):
            result = load_known_trades()
        assert len(result) == 1
        assert result[0].pick_number == 10

    def test_returns_empty_when_trades_list_empty(self, tmp_path):
        """Expected: file with empty trades array → empty result."""
        path = tmp_path / "known_trades.json"
        _write_trades(path, [])
        with patch("app.pipeline.trade_detector._TRADES_PATH", path):
            result = load_known_trades()
        assert result == []


# ---------------------------------------------------------------------------
# apply_trades_to_picks
# ---------------------------------------------------------------------------


class TestApplyTradesToPicks:
    def test_updates_current_team_and_traded_from(self, tmp_path):
        """Expected: pick ownership changes, old owner pushed into traded_from."""
        picks_path = tmp_path / "picks.json"
        _write_picks(picks_path, [_pick(5, "nyg")])

        trade = TradeUpdate(pick_number=5, new_current_team="dal", traded_from_append="nyg")
        with patch("app.pipeline.trade_detector._PICKS_PATH", picks_path):
            count = apply_trades_to_picks([trade])

        assert count == 1
        saved = json.loads(picks_path.read_text())
        pick = saved["picks"][0]
        assert pick["current_team"] == "dal"
        assert "nyg" in pick["traded_from"]

    def test_trade_notes_written_to_pick(self, tmp_path):
        """Expected: trade_notes field is persisted when provided."""
        picks_path = tmp_path / "picks.json"
        _write_picks(picks_path, [_pick(2, "lv")])

        trade = TradeUpdate(
            pick_number=2, new_current_team="sf", trade_notes="Acquired for RB + 4th"
        )
        with patch("app.pipeline.trade_detector._PICKS_PATH", picks_path):
            apply_trades_to_picks([trade])

        saved = json.loads(picks_path.read_text())
        assert saved["picks"][0].get("trade_notes") == "Acquired for RB + 4th"

    def test_idempotent_on_second_run(self, tmp_path):
        """Edge case: running the same trade twice does not duplicate traded_from."""
        picks_path = tmp_path / "picks.json"
        _write_picks(picks_path, [_pick(5, "nyg")])

        trade = TradeUpdate(pick_number=5, new_current_team="dal", traded_from_append="nyg")
        with patch("app.pipeline.trade_detector._PICKS_PATH", picks_path):
            apply_trades_to_picks([trade])  # first run — changes nyg → dal
            count2 = apply_trades_to_picks([trade])  # second run — already dal, no change

        assert count2 == 0
        saved = json.loads(picks_path.read_text())
        assert saved["picks"][0]["traded_from"].count("nyg") == 1

    def test_skips_unknown_pick_number(self, tmp_path):
        """Failure case: trade references pick #999 not in picks.json."""
        picks_path = tmp_path / "picks.json"
        _write_picks(picks_path, [_pick(1, "lv")])

        trade = TradeUpdate(pick_number=999, new_current_team="dal")
        with patch("app.pipeline.trade_detector._PICKS_PATH", picks_path):
            count = apply_trades_to_picks([trade])

        assert count == 0

    def test_returns_zero_for_empty_trades(self, tmp_path):
        """Edge case: no trades → no modifications → returns 0."""
        picks_path = tmp_path / "picks.json"
        _write_picks(picks_path, [_pick(1, "lv")])
        with patch("app.pipeline.trade_detector._PICKS_PATH", picks_path):
            count = apply_trades_to_picks([])
        assert count == 0

    def test_falls_back_to_old_team_when_no_traded_from_append(self, tmp_path):
        """Edge case: traded_from_append=None — old team is used as fallback."""
        picks_path = tmp_path / "picks.json"
        _write_picks(picks_path, [_pick(8, "min")])

        trade = TradeUpdate(pick_number=8, new_current_team="dal", traded_from_append=None)
        with patch("app.pipeline.trade_detector._PICKS_PATH", picks_path):
            apply_trades_to_picks([trade])

        saved = json.loads(picks_path.read_text())
        pick = saved["picks"][0]
        assert pick["current_team"] == "dal"
        assert "min" in pick["traded_from"]  # old team used as fallback

    def test_multiple_trades_applied(self, tmp_path):
        """Expected: two separate picks traded → both updated."""
        picks_path = tmp_path / "picks.json"
        _write_picks(picks_path, [_pick(3, "nyj"), _pick(15, "car")])

        trades = [
            TradeUpdate(pick_number=3, new_current_team="ne"),
            TradeUpdate(pick_number=15, new_current_team="atl"),
        ]
        with patch("app.pipeline.trade_detector._PICKS_PATH", picks_path):
            count = apply_trades_to_picks(trades)

        assert count == 2
        saved = json.loads(picks_path.read_text())
        teams = {p["pick_number"]: p["current_team"] for p in saved["picks"]}
        assert teams[3] == "ne"
        assert teams[15] == "atl"
