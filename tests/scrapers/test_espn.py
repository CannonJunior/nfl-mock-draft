"""
Unit tests for app.scrapers.espn.

Tests the HTML parse helpers with synthetic fixtures to avoid live HTTP calls.
"""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from app.scrapers.espn import _parse_prospect_page, _clean_name, _parse_grade


PROSPECTS_HTML = """
<table class="Table">
  <thead>
    <tr><th>Rank</th><th>Player</th><th>Pos</th><th>School</th><th>Grade</th></tr>
  </thead>
  <tbody>
    <tr>
      <td>1</td><td>Cam Ward</td><td>QB</td><td>Miami</td><td>8.5</td>
    </tr>
    <tr>
      <td>2</td><td>Travis Hunter</td><td>CB</td><td>Colorado</td><td>8.1</td>
    </tr>
    <tr>
      <td>3</td><td>Abdul Carter</td><td>EDGE</td><td>Penn State</td><td>N/A</td>
    </tr>
  </tbody>
</table>
"""


# ---------------------------------------------------------------------------
# Prospect page parse tests
# ---------------------------------------------------------------------------


def test_parse_prospect_page_basic():
    """Expected: three prospects parsed with correct rank, position, grade."""
    soup = BeautifulSoup(PROSPECTS_HTML, "lxml")
    prospects = _parse_prospect_page(soup, "https://espn.com/nfl/draft/tracker")
    assert len(prospects) == 3
    assert prospects[0].rank == 1
    assert prospects[0].name == "Cam Ward"
    assert prospects[0].position == "QB"
    assert prospects[0].college == "Miami"
    assert prospects[0].grade == 8.5


def test_parse_prospect_page_na_grade():
    """Edge case: 'N/A' grade is parsed as None, not a float."""
    soup = BeautifulSoup(PROSPECTS_HTML, "lxml")
    prospects = _parse_prospect_page(soup, "https://espn.com/nfl/draft/tracker")
    assert prospects[2].grade is None


def test_parse_prospect_page_empty():
    """Failure case: no table rows returns empty list."""
    soup = BeautifulSoup("<html><body></body></html>", "lxml")
    prospects = _parse_prospect_page(soup, "https://espn.com/nfl/draft/tracker")
    assert prospects == []


def test_parse_prospect_page_skip_header_row():
    """Edge case: header row with non-numeric rank cell is skipped."""
    html = """
    <table>
      <tr><th>Rank</th><th>Player</th><th>Pos</th></tr>
      <tr><td>1</td><td>Cam Ward</td><td>QB</td></tr>
    </table>
    """
    soup = BeautifulSoup(html, "lxml")
    prospects = _parse_prospect_page(soup, "https://espn.com")
    assert len(prospects) == 1


# ---------------------------------------------------------------------------
# _clean_name tests
# ---------------------------------------------------------------------------


def test_clean_name_removes_trailing_position():
    """Expected: trailing all-caps position abbreviation stripped."""
    assert _clean_name("Cam Ward QB") == "Cam Ward"


def test_clean_name_no_change_when_clean():
    """Expected: already-clean name returned unchanged."""
    assert _clean_name("Travis Hunter") == "Travis Hunter"


def test_clean_name_strips_whitespace():
    """Edge case: leading/trailing whitespace stripped."""
    assert _clean_name("  Abdul Carter  ") == "Abdul Carter"


# ---------------------------------------------------------------------------
# _parse_grade tests
# ---------------------------------------------------------------------------


def test_parse_grade_valid():
    """Expected: valid float string parsed correctly."""
    assert _parse_grade("8.5") == 8.5


def test_parse_grade_na():
    """Failure case: 'N/A' returns None."""
    assert _parse_grade("N/A") is None


def test_parse_grade_empty():
    """Edge case: empty string returns None."""
    assert _parse_grade("") is None
