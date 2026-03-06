"""
Unit tests for app.scrapers.draft_countdown.

Tests all parse helpers and measurement decoders with synthetic fixtures.
No live HTTP calls are made.
"""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from app.scrapers.draft_countdown import (
    _build_dc_col_map,
    _decode_dc_broad_jump,
    _decode_dc_height,
    _decode_dc_limb,
    _infer_position_from_context,
    _map_position_group,
    _parse_bb_height,
    _parse_bb_limb,
    _parse_bigboardlab,
    _parse_dc_table,
    _parse_draft_countdown,
)


# ---------------------------------------------------------------------------
# HTML fixtures
# ---------------------------------------------------------------------------

# A minimal draftcountdown.com-style page with two position sections
DC_PAGE_HTML = """
<html><body>
  <h2>Quarterbacks</h2>
  <table class="wpDataTable" id="table_1">
    <thead>
      <tr>
        <th>NAME</th><th>SCHOOL</th><th>HGT</th><th>LBS</th>
        <th>HAND</th><th>ARM</th><th>WING</th>
        <th>10 S</th><th>40</th><th>BP</th>
        <th>VJ</th><th>BJ</th><th>20S</th><th>3C</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>Cam Ward</td><td>Miami</td><td>6030</td><td>223</td>
        <td>958</td><td>3228</td><td>7918</td>
        <td>1.55</td><td>4.55</td><td></td>
        <td>34.5</td><td>1003</td><td>4.28</td><td>6.89</td>
      </tr>
      <tr>
        <td>Shedeur Sanders</td><td>Colorado</td><td>6020</td><td>215</td>
        <td>908</td><td>3138</td><td>7748</td>
        <td>1.60</td><td>4.62</td><td></td>
        <td>31.0</td><td>924</td><td>4.35</td><td>7.12</td>
      </tr>
    </tbody>
  </table>

  <h2>Wide Receivers</h2>
  <table class="wpDataTable" id="table_2">
    <thead>
      <tr>
        <th>NAME</th><th>SCHOOL</th><th>HGT</th><th>LBS</th>
        <th>HAND</th><th>ARM</th><th>WING</th>
        <th>10 S</th><th>40</th><th>BP</th>
        <th>VJ</th><th>BJ</th><th>20S</th><th>3C</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>Travis Hunter</td><td>Colorado</td><td>6008</td><td>188</td>
        <td>908</td><td>3108</td><td>7538</td>
        <td>1.49</td><td>4.38</td><td>15</td>
        <td>38.5</td><td>1007</td><td>4.10</td><td>6.62</td>
      </tr>
    </tbody>
  </table>
</body></html>
"""

# Single table with no heading (position should be empty string)
DC_TABLE_NO_HEADING_HTML = """
<html><body>
  <table class="wpDataTable">
    <thead>
      <tr>
        <th>NAME</th><th>SCHOOL</th><th>HGT</th><th>LBS</th>
        <th>HAND</th><th>ARM</th><th>WING</th>
        <th>10 S</th><th>40</th><th>BP</th><th>VJ</th><th>BJ</th><th>20S</th><th>3C</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>Abdul Carter</td><td>Penn State</td><td>6030</td><td>248</td>
        <td>1008</td><td>3318</td><td>8008</td>
        <td>1.48</td><td>4.55</td><td>24</td>
        <td>40.0</td><td>1108</td><td>4.05</td><td>6.71</td>
      </tr>
    </tbody>
  </table>
</body></html>
"""

# bigboardlab.com-style HTML with embedded COMBINE_DATA JS array
BB_HTML = """
<html><body>
<script>
const COMBINE_DATA = [
  {
    "name": "Cam Ward",
    "pos": "QB",
    "school": "Miami",
    "height": "6-3",
    "weight": 223,
    "hands": "9 5/8\\"",
    "arms": "32 2/8\\"",
    "forty": 4.55,
    "vertical": 34.5,
    "broad": 121,
    "bench": null,
    "cone": 6.89,
    "shuttle": 4.28
  },
  {
    "name": "Travis Hunter",
    "pos": "WR",
    "school": "Colorado",
    "height": "6-0",
    "weight": 188,
    "hands": "9 0/8\\"",
    "arms": "31 0/8\\"",
    "forty": 4.38,
    "vertical": 38.5,
    "broad": 127,
    "bench": 15,
    "cone": 6.62,
    "shuttle": 4.10
  }
];
</script>
</body></html>
"""

# bigboardlab.com HTML with no COMBINE_DATA
BB_HTML_MISSING = "<html><body><p>No data</p></body></html>"


# ---------------------------------------------------------------------------
# _decode_dc_height
# ---------------------------------------------------------------------------


def test_decode_dc_height_standard():
    """Expected: 6030 decodes to 75 inches (6'3.0")."""
    assert _decode_dc_height("6030") == 75


def test_decode_dc_height_with_decimal():
    """Expected: 6065 decodes to 79 inches (6'6.5" rounded)."""
    assert _decode_dc_height("6065") == 79


def test_decode_dc_height_fallback_hyphen_format():
    """Edge case: short raw value falls back to 6-4 format."""
    assert _decode_dc_height("6-4") == 76


def test_decode_dc_height_none():
    """Failure case: None input returns None."""
    assert _decode_dc_height(None) is None


def test_decode_dc_height_empty():
    """Failure case: empty string returns None."""
    assert _decode_dc_height("") is None


# ---------------------------------------------------------------------------
# _decode_dc_limb
# ---------------------------------------------------------------------------


def test_decode_dc_limb_arm():
    """Expected: 3338 = 33 + 3/8 = 33.375 inches."""
    assert _decode_dc_limb("3338") == pytest.approx(33.375)


def test_decode_dc_limb_wingspan():
    """Expected: 8158 = 81 + 5/8 = 81.625 inches."""
    assert _decode_dc_limb("8158") == pytest.approx(81.625)


def test_decode_dc_limb_hand_zero_fraction():
    """Expected: 908 = 9 + 0/8 = 9.0 inches."""
    assert _decode_dc_limb("908") == pytest.approx(9.0)


def test_decode_dc_limb_none():
    """Failure case: None input returns None."""
    assert _decode_dc_limb(None) is None


def test_decode_dc_limb_non_standard_format():
    """Edge case: value not ending in 8 falls back to float parse."""
    assert _decode_dc_limb("9.5") == pytest.approx(9.5)


# ---------------------------------------------------------------------------
# _decode_dc_broad_jump
# ---------------------------------------------------------------------------


def test_decode_dc_broad_jump_standard():
    """Expected: 901 = 9'01" = 109 inches."""
    assert _decode_dc_broad_jump("901") == 109


def test_decode_dc_broad_jump_ten_feet():
    """Expected: 1003 = 10'03" = 123 inches."""
    assert _decode_dc_broad_jump("1003") == 123


def test_decode_dc_broad_jump_none():
    """Failure case: None input returns None."""
    assert _decode_dc_broad_jump(None) is None


def test_decode_dc_broad_jump_out_of_range():
    """Failure case: value outside plausible range returns None."""
    assert _decode_dc_broad_jump("200") is None


# ---------------------------------------------------------------------------
# _map_position_group
# ---------------------------------------------------------------------------


def test_map_position_group_qb():
    """Expected: 'quarterbacks' maps to 'QB'."""
    assert _map_position_group("quarterbacks") == "QB"


def test_map_position_group_edge():
    """Expected: 'edge rushers' maps to 'EDGE'."""
    assert _map_position_group("edge rushers") == "EDGE"


def test_map_position_group_no_match():
    """Failure case: unrecognised text returns empty string."""
    assert _map_position_group("unknown position group xyz") == ""


# ---------------------------------------------------------------------------
# _build_dc_col_map
# ---------------------------------------------------------------------------


def test_build_dc_col_map_standard_headers():
    """Expected: standard draftcountdown headers map to correct indices."""
    headers = ["name", "school", "hgt", "lbs", "hand", "arm", "wing",
               "10 s", "40", "bp", "vj", "bj", "20s", "3c"]
    col = _build_dc_col_map(headers)
    assert col["name"] == 0
    assert col["school"] == 1
    assert col["hgt"] == 2
    assert col["lbs"] == 3
    assert col["40"] == 8
    assert col["bp"] == 9
    assert col["3c"] == 13


def test_build_dc_col_map_empty():
    """Edge case: empty header list returns empty map."""
    assert _build_dc_col_map([]) == {}


# ---------------------------------------------------------------------------
# _infer_position_from_context
# ---------------------------------------------------------------------------


def test_infer_position_from_context_heading():
    """Expected: table preceded by <h2>Quarterbacks</h2> returns 'QB'."""
    soup = BeautifulSoup(DC_PAGE_HTML, "lxml")
    tables = soup.find_all("table", class_="wpDataTable")
    assert len(tables) == 2
    assert _infer_position_from_context(tables[0]) == "QB"
    assert _infer_position_from_context(tables[1]) == "WR"


def test_infer_position_from_context_no_heading():
    """Edge case: table with no preceding heading returns empty string."""
    soup = BeautifulSoup(DC_TABLE_NO_HEADING_HTML, "lxml")
    table = soup.find("table", class_="wpDataTable")
    assert _infer_position_from_context(table) == ""


# ---------------------------------------------------------------------------
# _parse_dc_table
# ---------------------------------------------------------------------------


def test_parse_dc_table_basic():
    """Expected: two QB rows parsed with correct fields."""
    soup = BeautifulSoup(DC_PAGE_HTML, "lxml")
    tables = soup.find_all("table", class_="wpDataTable")
    stats = _parse_dc_table(tables[0], "QB", "https://draftcountdown.com/test")

    assert len(stats) == 2
    ward = stats[0]
    assert ward.name == "Cam Ward"
    assert ward.position == "QB"
    assert ward.college == "Miami"
    assert ward.height_inches == 75   # 6030 → 75
    assert ward.weight_lbs == 223
    assert ward.forty_yard_dash == pytest.approx(4.55)
    assert ward.vertical_jump_inches == pytest.approx(34.5)
    assert ward.three_cone == pytest.approx(6.89)
    assert ward.twenty_yard_shuttle == pytest.approx(4.28)


def test_parse_dc_table_bench_press_empty():
    """Edge case: empty bench press cell is parsed as None."""
    soup = BeautifulSoup(DC_PAGE_HTML, "lxml")
    tables = soup.find_all("table", class_="wpDataTable")
    stats = _parse_dc_table(tables[0], "QB", "https://draftcountdown.com/test")
    # QBs have no bench press in the fixture
    assert stats[0].bench_press_reps is None


def test_parse_dc_table_wr_with_bench():
    """Expected: WR row with bench press reps parsed correctly."""
    soup = BeautifulSoup(DC_PAGE_HTML, "lxml")
    tables = soup.find_all("table", class_="wpDataTable")
    stats = _parse_dc_table(tables[1], "WR", "https://draftcountdown.com/test")
    assert stats[0].bench_press_reps == 15


# ---------------------------------------------------------------------------
# _parse_draft_countdown (full page)
# ---------------------------------------------------------------------------


def test_parse_draft_countdown_full_page():
    """Expected: three records total from two position-group tables."""
    soup = BeautifulSoup(DC_PAGE_HTML, "lxml")
    stats = _parse_draft_countdown(soup, "https://draftcountdown.com/test")
    assert len(stats) == 3


def test_parse_draft_countdown_positions_inferred():
    """Expected: positions are correctly inferred from section headings."""
    soup = BeautifulSoup(DC_PAGE_HTML, "lxml")
    stats = _parse_draft_countdown(soup, "https://draftcountdown.com/test")
    positions = {s.name: s.position for s in stats}
    assert positions["Cam Ward"] == "QB"
    assert positions["Shedeur Sanders"] == "QB"
    assert positions["Travis Hunter"] == "WR"


def test_parse_draft_countdown_no_tables():
    """Failure case: page with no wpDataTable returns empty list."""
    soup = BeautifulSoup("<html><body><p>nothing</p></body></html>", "lxml")
    assert _parse_draft_countdown(soup, "https://test") == []


# ---------------------------------------------------------------------------
# _parse_bb_height
# ---------------------------------------------------------------------------


def test_parse_bb_height_hyphen_format():
    """Expected: '6-3' → 75 inches."""
    assert _parse_bb_height("6-3") == 75


def test_parse_bb_height_zero_inches():
    """Expected: '6-0' → 72 inches."""
    assert _parse_bb_height("6-0") == 72


def test_parse_bb_height_none():
    """Failure case: None returns None."""
    assert _parse_bb_height(None) is None


# ---------------------------------------------------------------------------
# _parse_bb_limb
# ---------------------------------------------------------------------------


def test_parse_bb_limb_fraction_format():
    """Expected: '9 5/8' → 9.625 inches."""
    assert _parse_bb_limb('9 5/8"') == pytest.approx(9.625)


def test_parse_bb_limb_eighth_denominator():
    """Expected: '32 2/8' → 32.25 inches."""
    assert _parse_bb_limb('32 2/8"') == pytest.approx(32.25)


def test_parse_bb_limb_none():
    """Failure case: None returns None."""
    assert _parse_bb_limb(None) is None


# ---------------------------------------------------------------------------
# _parse_bigboardlab
# ---------------------------------------------------------------------------


def test_parse_bigboardlab_basic():
    """Expected: two records parsed from embedded COMBINE_DATA array."""
    stats = _parse_bigboardlab(BB_HTML, "https://bigboardlab.com/test")
    assert len(stats) == 2

    ward = stats[0]
    assert ward.name == "Cam Ward"
    assert ward.position == "QB"
    assert ward.college == "Miami"
    assert ward.height_inches == 75  # "6-3" → 75
    assert ward.weight_lbs == 223
    assert ward.forty_yard_dash == pytest.approx(4.55)
    assert ward.vertical_jump_inches == pytest.approx(34.5)
    assert ward.broad_jump_inches == 121
    assert ward.bench_press_reps is None
    assert ward.three_cone == pytest.approx(6.89)
    assert ward.twenty_yard_shuttle == pytest.approx(4.28)


def test_parse_bigboardlab_hand_size():
    """Expected: hand size fraction string decoded to decimal inches."""
    stats = _parse_bigboardlab(BB_HTML, "https://bigboardlab.com/test")
    # "9 5/8\"" → 9.625
    assert stats[0].hand_size_inches == pytest.approx(9.625)


def test_parse_bigboardlab_missing_array():
    """Failure case: page without COMBINE_DATA returns empty list."""
    stats = _parse_bigboardlab(BB_HTML_MISSING, "https://bigboardlab.com/test")
    assert stats == []


def test_parse_bigboardlab_source_attribution():
    """Expected: all records have source='draft_countdown' and correct URL."""
    stats = _parse_bigboardlab(BB_HTML, "https://bigboardlab.com/2026")
    for s in stats:
        assert s.source == "draft_countdown"
        assert s.source_url == "https://bigboardlab.com/2026"
