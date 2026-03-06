"""
Unit tests for app.scrapers.tankathon.

Tests the private parse helpers using synthetic HTML fixtures that match
Tankathon's actual CSS-class-based layout. Avoids any live HTTP calls.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from app.scrapers.tankathon import (
    _parse_draft_order,
    _parse_mock_draft,
)


# ---------------------------------------------------------------------------
# Fixtures: HTML that mimics Tankathon's actual page structure
# ---------------------------------------------------------------------------

# full_draft page structure: div.full-draft-round-nfl > table.full-draft > tr
DRAFT_ORDER_HTML = """
<div class="full-draft-round full-draft-round-nfl">
  <div class="round-title">1st Round</div>
  <table class="full-draft">
    <tr>
      <td class="pick-number">1</td>
      <td><div class="team-link"><a href="/nfl/raiders">
        <div class="team-link-section team-link-logo"><img src="lv.svg"/></div>
        <div class="team-link-section"><div class="desktop">Las Vegas</div></div>
      </a></div></td>
    </tr>
    <tr>
      <td class="pick-number">2</td>
      <td><div class="team-link"><a href="/nfl/jets">
        <div class="team-link-section"><div class="desktop">NY Jets</div></div>
      </a></div></td>
    </tr>
  </table>
</div>
<div class="full-draft-round full-draft-round-nfl">
  <div class="round-title">2nd Round</div>
  <table class="full-draft">
    <tr>
      <td class="pick-number">33</td>
      <td><div class="team-link"><a href="/nfl/raiders">
        <div class="team-link-section"><div class="desktop">Las Vegas</div></div>
      </a></div></td>
    </tr>
  </table>
</div>
"""

# mock_draft page structure: div.mock-row
MOCK_DRAFT_HTML = """
<div class="mock-row nfl">
  <div class="mock-row-pick-number">1</div>
  <div class="mock-row-logo"><a href="/nfl/raiders"><img alt="LV" src="lv.svg"/></a></div>
  <div class="mock-row-player">
    <a href="/nfl/players/cam-ward">
      <div class="mock-row-name">Cam Ward</div>
      <div class="mock-row-school-position">QB | Miami </div>
    </a>
  </div>
</div>
<div class="mock-row nfl">
  <div class="mock-row-pick-number">2</div>
  <div class="mock-row-logo"><a href="/nfl/jets"><img alt="NYJ" src="nyj.svg"/></a></div>
  <div class="mock-row-player">
    <a href="/nfl/players/travis-hunter">
      <div class="mock-row-name">Travis Hunter</div>
      <div class="mock-row-school-position">CB | Colorado </div>
    </a>
  </div>
</div>
"""


# ---------------------------------------------------------------------------
# _parse_draft_order
# ---------------------------------------------------------------------------


def test_parse_draft_order_basic():
    """Expected: picks parsed from table.full-draft rows with round detection."""
    soup = BeautifulSoup(DRAFT_ORDER_HTML, "lxml")
    picks = _parse_draft_order(soup, "https://example.com")
    assert len(picks) == 3
    assert picks[0].pick_number == 1
    assert picks[0].team == "Las Vegas"
    assert picks[0].round == 1
    assert picks[0].traded_from is None


def test_parse_draft_order_round_boundary():
    """Expected: pick 33 is assigned to round 2."""
    soup = BeautifulSoup(DRAFT_ORDER_HTML, "lxml")
    picks = _parse_draft_order(soup, "https://example.com")
    pick_33 = next(p for p in picks if p.pick_number == 33)
    assert pick_33.round == 2


def test_parse_draft_order_empty_html():
    """Failure case: no round divs returns empty list."""
    soup = BeautifulSoup("<div></div>", "lxml")
    picks = _parse_draft_order(soup, "https://example.com")
    assert picks == []


def test_parse_draft_order_source_tag():
    """Expected: all picks carry source='tankathon'."""
    soup = BeautifulSoup(DRAFT_ORDER_HTML, "lxml")
    picks = _parse_draft_order(soup, "https://example.com")
    assert all(p.source == "tankathon" for p in picks)


# ---------------------------------------------------------------------------
# _parse_mock_draft
# ---------------------------------------------------------------------------


def test_parse_mock_draft_basic():
    """Expected: two ScrapedMockEntry objects with correct fields."""
    soup = BeautifulSoup(MOCK_DRAFT_HTML, "lxml")
    entries = _parse_mock_draft(soup, "https://example.com/mock-draft")
    assert len(entries) == 2
    assert entries[0].pick_number == 1
    assert entries[0].player_name == "Cam Ward"
    assert entries[0].team == "LV"
    assert entries[0].position == "QB"
    assert entries[0].college == "Miami"


def test_parse_mock_draft_second_entry():
    """Expected: second entry parsed correctly."""
    soup = BeautifulSoup(MOCK_DRAFT_HTML, "lxml")
    entries = _parse_mock_draft(soup, "https://example.com/mock-draft")
    assert entries[1].player_name == "Travis Hunter"
    assert entries[1].position == "CB"


def test_parse_mock_draft_empty():
    """Edge case: empty HTML returns empty list."""
    soup = BeautifulSoup("<html></html>", "lxml")
    entries = _parse_mock_draft(soup, "https://example.com/mock-draft")
    assert entries == []


def test_parse_mock_draft_source_tag():
    """Expected: all entries carry source='tankathon'."""
    soup = BeautifulSoup(MOCK_DRAFT_HTML, "lxml")
    entries = _parse_mock_draft(soup, "https://example.com/mock-draft")
    assert all(e.source == "tankathon" for e in entries)
