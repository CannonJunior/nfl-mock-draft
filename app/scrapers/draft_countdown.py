"""
Scraper for draftcountdown.com NFL Combine measurements.

Primary source: draftcountdown.com — server-rendered wpDataTable tables with
all 14 combine measurements for 300+ prospects, organised by position group.

Fallback source: bigboardlab.com — 450+ prospects stored in a ``const
COMBINE_DATA`` JavaScript array embedded in raw HTML (no JS execution needed).

Both sources return ``list[ScrapedCombineStat]`` using the shared model so
results feed directly into ``upsert_combine_stats()`` in storage.py.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from bs4 import BeautifulSoup, NavigableString, Tag

from app.models.scrape import ScrapedCombineStat, ScrapeResult
from app.scrapers.base import BaseScraper, ScraperError

logger = logging.getLogger(__name__)

_SOURCE = "draft_countdown"
_DC_BASE = "https://www.draftcountdown.com"
_DC_URL = f"{_DC_BASE}/nfl-combine/2026-nfl-combine-official-measurements/"

_BB_BASE = "https://bigboardlab.com"
_BB_URL = f"{_BB_BASE}/blog/2026-nfl-combine-results.html"

# Maps section heading text (lowercased) to canonical position codes
_POSITION_GROUP_MAP: dict[str, str] = {
    "quarterback": "QB",
    "quarterbacks": "QB",
    "qb": "QB",
    "wide receiver": "WR",
    "wide receivers": "WR",
    "wr": "WR",
    "running back": "RB",
    "running backs": "RB",
    "rb": "RB",
    "tight end": "TE",
    "tight ends": "TE",
    "te": "TE",
    "offensive line": "OL",
    "offensive lineman": "OL",
    "offensive linemen": "OL",
    "ol": "OL",
    "defensive line": "DL",
    "defensive lineman": "DL",
    "defensive linemen": "DL",
    "dl": "DL",
    "defensive end": "DE",
    "defensive ends": "DE",
    "linebacker": "LB",
    "linebackers": "LB",
    "lb": "LB",
    "defensive back": "DB",
    "defensive backs": "DB",
    "db": "DB",
    "cornerback": "CB",
    "cornerbacks": "CB",
    "cb": "CB",
    "safety": "S",
    "safeties": "S",
    "edge": "EDGE",
    "edge rusher": "EDGE",
    "edge rushers": "EDGE",
    "specialist": "K",
    "specialists": "K",
    "kicker": "K",
    "punter": "P",
}


class DraftCountdownScraper(BaseScraper):
    """
    Scraper for NFL Combine measurements.

    Tries draftcountdown.com first (server-rendered tables), then falls
    back to bigboardlab.com (JS array in raw HTML) if the primary source
    returns zero records.
    """

    SOURCE = _SOURCE
    BASE_URL = _DC_BASE

    async def fetch_combine_stats(
        self,
    ) -> tuple[list[ScrapedCombineStat], ScrapeResult]:
        """
        Scrape 2026 NFL Combine measurements.

        Tries draftcountdown.com first, falls back to bigboardlab.com on
        failure or zero results.

        Returns:
            tuple[list[ScrapedCombineStat], ScrapeResult]: Parsed combine
                measurements and a summary result object.
        """
        # --- Primary: draftcountdown.com ---
        try:
            stats, result = await self._fetch_draft_countdown()
            if stats:
                return stats, result
            logger.warning("[draft_countdown] Primary returned 0 records; trying fallback")
        except ScraperError as exc:
            logger.warning("[draft_countdown] Primary fetch failed: %s — trying fallback", exc)

        # --- Fallback: bigboardlab.com ---
        try:
            return await self._fetch_bigboardlab()
        except ScraperError as exc:
            logger.error("[draft_countdown] Fallback also failed: %s", exc)
            return [], ScrapeResult(source=_SOURCE, success=False, error=str(exc))

    # ------------------------------------------------------------------
    # Private fetch methods
    # ------------------------------------------------------------------

    async def _fetch_draft_countdown(
        self,
    ) -> tuple[list[ScrapedCombineStat], ScrapeResult]:
        """
        Fetch and parse draftcountdown.com combine measurements page.

        Returns:
            tuple[list[ScrapedCombineStat], ScrapeResult]: Parsed stats and result.
        """
        soup = await self.fetch_html(_DC_URL)
        stats = _parse_draft_countdown(soup, _DC_URL)
        logger.info("[draft_countdown] draftcountdown.com: %d records", len(stats))
        return stats, ScrapeResult(
            source=_SOURCE, success=True, records_fetched=len(stats)
        )

    async def _fetch_bigboardlab(
        self,
    ) -> tuple[list[ScrapedCombineStat], ScrapeResult]:
        """
        Fetch and parse bigboardlab.com combine results (JS array in HTML).

        Returns:
            tuple[list[ScrapedCombineStat], ScrapeResult]: Parsed stats and result.
        """
        soup = await self.fetch_html(_BB_URL)
        # Reason: data lives in a <script> tag as a JS array literal, not in
        # HTML markup — extract the raw page text, not soup's visible text.
        html = str(soup)
        stats = _parse_bigboardlab(html, _BB_URL)
        logger.info("[draft_countdown] bigboardlab.com fallback: %d records", len(stats))
        return stats, ScrapeResult(
            source=_SOURCE, success=True, records_fetched=len(stats)
        )


# ---------------------------------------------------------------------------
# DraftCountdown parse helpers
# ---------------------------------------------------------------------------


def _parse_draft_countdown(soup: BeautifulSoup, url: str) -> list[ScrapedCombineStat]:
    """
    Parse all wpDataTable combine tables from draftcountdown.com.

    The page has one table per position group (QB, WR, RB, TE, OL, DL, LB,
    DB). Position is inferred from the nearest preceding heading element.

    Args:
        soup (BeautifulSoup): Parsed HTML document.
        url (str): Source URL for attribution.

    Returns:
        list[ScrapedCombineStat]: All parsed combine records across all tables.
    """
    stats: list[ScrapedCombineStat] = []
    tables = soup.find_all("table", class_=re.compile(r"wpDataTable", re.I))

    if not tables:
        logger.warning("[draft_countdown] No wpDataTable elements found")
        return stats

    for table in tables:
        if not isinstance(table, Tag):
            continue
        position_group = _infer_position_from_context(table)
        stats.extend(_parse_dc_table(table, position_group, url))

    return stats


def _parse_dc_table(table: Tag, position_group: str, url: str) -> list[ScrapedCombineStat]:
    """
    Parse a single wpDataTable into ScrapedCombineStat records.

    Args:
        table (Tag): The <table> element.
        position_group (str): Position code inferred from the section heading.
        url (str): Source URL for attribution.

    Returns:
        list[ScrapedCombineStat]: Parsed records from this table.
    """
    stats: list[ScrapedCombineStat] = []

    # Build column index map from header row
    headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
    col = _build_dc_col_map(headers)

    for row in table.find_all("tr")[1:]:
        cells = row.find_all("td")
        if not cells:
            continue
        vals = [c.get_text(strip=True) for c in cells]

        name = _safe_get(vals, col.get("name"))
        if not name:
            continue

        school = _safe_get(vals, col.get("school")) or ""

        raw_hgt = _safe_get(vals, col.get("hgt"))
        raw_lbs = _safe_get(vals, col.get("lbs"))
        raw_hand = _safe_get(vals, col.get("hand"))
        raw_arm = _safe_get(vals, col.get("arm"))
        raw_40 = _safe_get(vals, col.get("40"))
        raw_bp = _safe_get(vals, col.get("bp"))
        raw_vj = _safe_get(vals, col.get("vj"))
        raw_bj = _safe_get(vals, col.get("bj"))
        raw_20s = _safe_get(vals, col.get("20s"))
        raw_3c = _safe_get(vals, col.get("3c"))

        stats.append(
            ScrapedCombineStat(
                name=name,
                position=position_group,
                college=school,
                height_inches=_decode_dc_height(raw_hgt),
                weight_lbs=_parse_int(raw_lbs),
                hand_size_inches=_decode_dc_limb(raw_hand),
                arm_length_inches=_decode_dc_limb(raw_arm),
                forty_yard_dash=_parse_float(raw_40),
                bench_press_reps=_parse_int(raw_bp),
                vertical_jump_inches=_parse_float(raw_vj),
                broad_jump_inches=_decode_dc_broad_jump(raw_bj),
                twenty_yard_shuttle=_parse_float(raw_20s),
                three_cone=_parse_float(raw_3c),
                source=_SOURCE,
                source_url=url,
            )
        )

    return stats


def _build_dc_col_map(headers: list[str]) -> dict[str, int]:
    """
    Map semantic keys to column indices from draftcountdown.com table headers.

    Args:
        headers (list[str]): Lowercased header text values.

    Returns:
        dict[str, int]: Semantic key to column index mapping.
    """
    keywords: dict[str, list[str]] = {
        "name": ["name", "player"],
        "school": ["school", "college", "team"],
        "hgt": ["hgt", "ht", "height"],
        "lbs": ["lbs", "wt", "weight"],
        "hand": ["hand"],
        "arm": ["arm"],
        # Reason: "10 s" is the ten-yard split — skip it, not in our model
        "40": ["40"],
        "bp": ["bp", "bench"],
        "vj": ["vj", "vert", "vertical"],
        "bj": ["bj", "broad"],
        "20s": ["20s", "shuttle"],
        "3c": ["3c", "3-cone", "cone"],
    }
    col_map: dict[str, int] = {}
    for i, header in enumerate(headers):
        for key, aliases in keywords.items():
            if any(alias in header for alias in aliases):
                col_map.setdefault(key, i)
    return col_map


def _infer_position_from_context(table: Tag) -> str:
    """
    Walk backwards through the DOM to find the nearest heading before this table.

    Args:
        table (Tag): The wpDataTable element.

    Returns:
        str: Inferred position code (e.g. "QB", "WR"), or "" if not found.
    """
    node = table.previous_sibling
    while node is not None:
        if isinstance(node, NavigableString):
            node = node.previous_sibling
            continue
        if isinstance(node, Tag) and node.name in ("h1", "h2", "h3", "h4", "p"):
            text = node.get_text(strip=True).lower()
            pos = _map_position_group(text)
            if pos:
                return pos
            break
        node = node.previous_sibling

    # Fallback: check the wrapping parent's id/class for position hints
    parent = table.parent
    if isinstance(parent, Tag):
        for attr_val in (parent.get("id", ""), " ".join(parent.get("class", []))):
            pos = _map_position_group(str(attr_val).lower())
            if pos:
                return pos

    return ""


def _map_position_group(text: str) -> str:
    """
    Convert a heading text or CSS class to a position code.

    Args:
        text (str): Lowercased string to match against position keywords.

    Returns:
        str: Position code (e.g. "QB") or "" if no match.
    """
    for keyword, code in _POSITION_GROUP_MAP.items():
        if keyword in text:
            return code
    return ""


# ---------------------------------------------------------------------------
# DraftCountdown measurement decoders
# ---------------------------------------------------------------------------


def _decode_dc_height(raw: Optional[str]) -> Optional[int]:
    """
    Decode draftcountdown.com 4-digit height encoding to total inches.

    Format: ``FIID`` where F = feet (1 digit), II = whole inches (zero-padded
    2 digits), D = decimal tenth of an inch.

    Examples:
        ``6030`` → 6'3.0" → 75 inches
        ``6065`` → 6'6.5" → 79 inches (rounded)

    Args:
        raw (Optional[str]): Raw height string from the table cell.

    Returns:
        Optional[int]: Height in total inches, rounded, or None.
    """
    if not raw:
        return None
    digits = re.sub(r"[^\d]", "", raw)
    if len(digits) < 4:
        # Fallback: try standard "6-4" or "6'4" format
        m = re.match(r"(\d+)['\-](\d+)", raw)
        if m:
            return int(m.group(1)) * 12 + int(m.group(2))
        return None
    try:
        feet = int(digits[0])
        whole_inches = int(digits[1:3])
        decimal_tenth = int(digits[3]) / 10.0
        total = feet * 12 + whole_inches + decimal_tenth
        # Reason: int(x + 0.5) gives conventional 0.5-rounds-up behaviour;
        # Python's built-in round() uses banker's rounding (round-half-to-even).
        return int(total + 0.5)
    except (ValueError, IndexError):
        return None


def _decode_dc_limb(raw: Optional[str]) -> Optional[float]:
    """
    Decode draftcountdown.com limb measurement encoding to inches.

    Format: ``WHOLE`` + ``N`` + ``8`` where WHOLE = whole inches, N = eighth
    numerator (0-7), and ``8`` is a fixed denominator marker.

    Examples:
        ``3338`` → 33 + 3/8 = 33.375 inches
        ``8158`` → 81 + 5/8 = 81.625 inches

    Args:
        raw (Optional[str]): Raw limb measurement string from the table cell.

    Returns:
        Optional[float]: Measurement in decimal inches, or None.
    """
    if not raw:
        return None
    digits = re.sub(r"[^\d]", "", raw)
    if len(digits) < 2:
        return None
    # Reason: last character is always '8' (fixed denominator indicator);
    # second-to-last is the fractional numerator; remainder is whole inches.
    if digits[-1] != "8":
        # Not the expected format — try direct float parse
        try:
            return float(raw)
        except ValueError:
            return None
    try:
        whole = int(digits[:-2]) if len(digits) > 2 else 0
        numerator = int(digits[-2])
        return round(whole + numerator / 8.0, 4)
    except (ValueError, IndexError):
        return None


def _decode_dc_broad_jump(raw: Optional[str]) -> Optional[int]:
    """
    Decode draftcountdown.com broad jump encoding to total inches.

    Format: ``FII`` where F = feet (1 digit), II = inches within that foot.

    Examples:
        ``901`` → 9'01" → 109 inches
        ``1003`` → 10'03" → 123 inches

    Args:
        raw (Optional[str]): Raw broad jump string from the table cell.

    Returns:
        Optional[int]: Broad jump in total inches, or None.
    """
    if not raw:
        return None
    digits = re.sub(r"[^\d]", "", raw)
    if len(digits) < 3:
        # May already be total inches (e.g. "109")
        try:
            val = int(digits)
            return val if 90 <= val <= 145 else None
        except ValueError:
            return None
    try:
        # Reason: last 2 digits are always inches; everything before is feet.
        # This handles both 3-digit (901 → 9'01"=109") and 4-digit (1003 → 10'03"=123").
        feet = int(digits[:-2])
        inches = int(digits[-2:])
        total = feet * 12 + inches
        # Sanity check: 7'6" (90") to 12'0" (144") is the plausible range
        return total if 90 <= total <= 145 else None
    except (ValueError, IndexError):
        return None


# ---------------------------------------------------------------------------
# BigBoardLab parse helpers
# ---------------------------------------------------------------------------


def _parse_bigboardlab(html: str, url: str) -> list[ScrapedCombineStat]:
    """
    Extract combine data from bigboardlab.com's embedded ``COMBINE_DATA`` JS array.

    The page embeds all prospect data as a JavaScript literal:
        ``const COMBINE_DATA = [{...}, ...];``
    This is present in the raw HTTP response, so no JS execution is required.

    Args:
        html (str): Raw HTML string from the HTTP response.
        url (str): Source URL for attribution.

    Returns:
        list[ScrapedCombineStat]: Parsed combine records.
    """
    stats: list[ScrapedCombineStat] = []

    # Reason: use re.DOTALL so the array literal can span multiple lines
    match = re.search(
        r"const\s+COMBINE_DATA\s*=\s*(\[.*?\]);",
        html,
        re.DOTALL,
    )
    if not match:
        logger.warning("[draft_countdown] COMBINE_DATA array not found in bigboardlab HTML")
        return stats

    try:
        records = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        logger.warning("[draft_countdown] Failed to parse COMBINE_DATA JSON: %s", exc)
        return stats

    for rec in records:
        if not isinstance(rec, dict):
            continue
        name = rec.get("name", "").strip()
        if not name:
            continue

        stats.append(
            ScrapedCombineStat(
                name=name,
                position=str(rec.get("pos", "")).strip().upper(),
                college=str(rec.get("school", "")).strip(),
                height_inches=_parse_bb_height(rec.get("height")),
                weight_lbs=_parse_int_val(rec.get("weight")),
                hand_size_inches=_parse_bb_limb(rec.get("hands")),
                arm_length_inches=_parse_bb_limb(rec.get("arms")),
                forty_yard_dash=_parse_float_val(rec.get("forty")),
                vertical_jump_inches=_parse_float_val(rec.get("vertical")),
                broad_jump_inches=_parse_int_val(rec.get("broad")),
                bench_press_reps=_parse_int_val(rec.get("bench")),
                three_cone=_parse_float_val(rec.get("cone")),
                twenty_yard_shuttle=_parse_float_val(rec.get("shuttle")),
                source=_SOURCE,
                source_url=url,
            )
        )

    return stats


def _parse_bb_height(raw: object) -> Optional[int]:
    """
    Convert bigboardlab.com height string to total inches.

    Accepts formats: ``"6-6"`` or ``"6'6"``.

    Args:
        raw (object): Raw height value from the JSON record.

    Returns:
        Optional[int]: Height in total inches, or None.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    m = re.match(r"(\d+)['\-](\d+(?:\.\d+)?)", s)
    if m:
        feet = int(m.group(1))
        inches = float(m.group(2))
        return round(feet * 12 + inches)
    return None


def _parse_bb_limb(raw: object) -> Optional[float]:
    """
    Convert bigboardlab.com limb measurement string to decimal inches.

    Accepts formats: ``"9 7/8\\""`` → 9.875, ``"34 6/8\\""`` → 34.75.

    Args:
        raw (object): Raw limb value from the JSON record.

    Returns:
        Optional[float]: Measurement in decimal inches, or None.
    """
    if raw is None:
        return None
    s = str(raw).strip().replace('"', "").strip()
    # Pattern: "WHOLE NUMERATOR/DENOMINATOR"
    m = re.match(r"(\d+)\s+(\d+)/(\d+)", s)
    if m:
        whole = int(m.group(1))
        numerator = int(m.group(2))
        denominator = int(m.group(3))
        if denominator == 0:
            return float(whole)
        return round(whole + numerator / denominator, 4)
    # Try plain decimal
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _safe_get(values: list[str], idx: Optional[int]) -> Optional[str]:
    """
    Safely retrieve a cell value by column index.

    Args:
        values (list[str]): Row cell text values.
        idx (Optional[int]): Column index.

    Returns:
        Optional[str]: Stripped cell text, or None if empty / missing / dash.
    """
    if idx is None or idx >= len(values):
        return None
    val = values[idx].strip()
    return val if val and val not in ("-", "—", "N/A", "–") else None


def _parse_float(raw: Optional[str]) -> Optional[float]:
    """
    Parse a string to float, returning None on failure.

    Args:
        raw (Optional[str]): Raw string value.

    Returns:
        Optional[float]: Parsed float or None.
    """
    if not raw:
        return None
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def _parse_int(raw: Optional[str]) -> Optional[int]:
    """
    Parse a string to int by stripping non-digit characters.

    Args:
        raw (Optional[str]): Raw string value.

    Returns:
        Optional[int]: Parsed int or None.
    """
    if not raw:
        return None
    digits = re.sub(r"[^\d]", "", raw)
    try:
        return int(digits) if digits else None
    except ValueError:
        return None


def _parse_float_val(val: Any) -> Optional[float]:
    """
    Coerce an arbitrary JSON value to float.

    Args:
        val (object): Value from JSON (may be float, int, str, or None).

    Returns:
        Optional[float]: Float or None.
    """
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _parse_int_val(val: Any) -> Optional[int]:
    """
    Coerce an arbitrary JSON value to int.

    Args:
        val (object): Value from JSON (may be int, float, str, or None).

    Returns:
        Optional[int]: Int or None.
    """
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None
