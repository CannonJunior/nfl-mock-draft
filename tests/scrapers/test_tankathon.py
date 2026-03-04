"""
Unit tests for app.scrapers.tankathon.

Tests the private parse helpers using synthetic HTML fixtures,
avoiding any live HTTP calls.
"""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from app.scrapers.tankathon import (
    _parse_draft_order,
    _parse_mock_draft,
    _parse_team_needs,
    _extract_need_level,
)


# ---------------------------------------------------------------------------
# Fixtures: minimal HTML fragments that mimic Tankathon's structure
# ---------------------------------------------------------------------------

DRAFT_ORDER_HTML = """
<table class="draft-table">
  <tr><th>Pick</th><th>Team</th></tr>
  <tr><td>1</td><td>TEN</td></tr>
  <tr><td>2</td><td>CLE (via NE)</td></tr>
  <tr><td>3</td><td>NYG</td></tr>
</table>
"""

TEAM_NEEDS_HTML = """
<table>
  <tr>
    <th>Team</th><th>QB</th><th>OT</th><th>WR</th>
  </tr>
  <tr>
    <td>TEN</td>
    <td data-need="5"></td>
    <td data-need="3"></td>
    <td data-need="1"></td>
  </tr>
</table>
"""

MOCK_DRAFT_HTML = """
<table>
  <tr><th>#</th><th>Team</th><th>Player</th><th>Pos</th><th>College</th></tr>
  <tr><td>1</td><td>TEN</td><td>Cam Ward</td><td>QB</td><td>Miami</td></tr>
  <tr><td>2</td><td>CLE</td><td>Travis Hunter</td><td>CB</td><td>Colorado</td></tr>
</table>
"""


# ---------------------------------------------------------------------------
# Draft order tests
# ---------------------------------------------------------------------------


def test_parse_draft_order_basic():
    """Expected: parse three picks from well-formed draft order table."""
    soup = BeautifulSoup(DRAFT_ORDER_HTML, "lxml")
    picks = _parse_draft_order(soup, "https://example.com")
    assert len(picks) == 3
    assert picks[0].pick_number == 1
    assert picks[0].team == "TEN"
    assert picks[0].traded_from is None


def test_parse_draft_order_traded_pick():
    """Expected: detect traded pick and parse via team correctly."""
    soup = BeautifulSoup(DRAFT_ORDER_HTML, "lxml")
    picks = _parse_draft_order(soup, "https://example.com")
    traded = [p for p in picks if p.traded_from]
    assert len(traded) == 1
    assert traded[0].team == "CLE"
    assert traded[0].traded_from == "NE"


def test_parse_draft_order_empty_table():
    """Edge case: empty table returns empty list without raising."""
    soup = BeautifulSoup("<table></table>", "lxml")
    picks = _parse_draft_order(soup, "https://example.com")
    assert picks == []


def test_parse_draft_order_no_table():
    """Failure case: no table in HTML returns empty list without raising."""
    soup = BeautifulSoup("<div>no picks here</div>", "lxml")
    picks = _parse_draft_order(soup, "https://example.com")
    assert picks == []


# ---------------------------------------------------------------------------
# Team needs tests
# ---------------------------------------------------------------------------


def test_parse_team_needs_basic():
    """Expected: three position needs parsed for TEN with correct levels."""
    soup = BeautifulSoup(TEAM_NEEDS_HTML, "lxml")
    needs = _parse_team_needs(soup, "https://example.com/team-needs")
    assert len(needs) == 3
    qb_need = next(n for n in needs if n.position == "QB")
    assert qb_need.need_level == 5
    assert qb_need.team == "TEN"


def test_parse_team_needs_no_table():
    """Failure case: missing table returns empty list."""
    soup = BeautifulSoup("<p>nothing here</p>", "lxml")
    needs = _parse_team_needs(soup, "https://example.com/team-needs")
    assert needs == []


def test_extract_need_level_from_class():
    """Edge case: need level extracted from CSS class when data attr absent."""
    from bs4 import BeautifulSoup as BS
    cell = BS('<td class="need-4"></td>', "lxml").find("td")
    assert _extract_need_level(cell) == 4


def test_extract_need_level_clamped():
    """Edge case: values outside 1-5 are clamped to valid range."""
    from bs4 import BeautifulSoup as BS
    cell = BS('<td data-need="9"></td>', "lxml").find("td")
    level = _extract_need_level(cell)
    assert level == 5


# ---------------------------------------------------------------------------
# Mock draft tests
# ---------------------------------------------------------------------------


def test_parse_mock_draft_basic():
    """Expected: two mock entries parsed correctly."""
    soup = BeautifulSoup(MOCK_DRAFT_HTML, "lxml")
    entries = _parse_mock_draft(soup, "https://example.com/mock-draft")
    assert len(entries) == 2
    assert entries[0].pick_number == 1
    assert entries[0].player_name == "Cam Ward"
    assert entries[0].position == "QB"
    assert entries[0].college == "Miami"


def test_parse_mock_draft_empty():
    """Edge case: empty HTML returns empty list."""
    soup = BeautifulSoup("<html></html>", "lxml")
    entries = _parse_mock_draft(soup, "https://example.com/mock-draft")
    assert entries == []
