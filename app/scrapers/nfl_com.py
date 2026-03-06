"""
Scraper for www.nfl.com NFL Combine results.

Pulls combine athletic testing data for 2026 draft prospects:
- 40-yard dash, vertical jump, broad jump, bench press, 3-cone, shuttle
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from bs4 import BeautifulSoup, Tag

from app.models.scrape import ScrapedCombineStat, ScrapeResult
from app.scrapers.base import BaseScraper, ScraperError

logger = logging.getLogger(__name__)

_SOURCE = "nfl"
_BASE = "https://www.nfl.com"
# Reason: NFL.com combine tracker is JS-rendered; this URL returns 200 but
# no table data will be extracted. The scraper returns success with 0 records
# rather than a 404 error, keeping the pipeline non-blocking.
_COMBINE_URL = f"{_BASE}/combine/"


class NFLComScraper(BaseScraper):
    """
    Scraper for NFL.com combine results and prospect listings.
    """

    SOURCE = _SOURCE
    BASE_URL = _BASE

    async def fetch_combine_stats(
        self,
    ) -> tuple[list[ScrapedCombineStat], ScrapeResult]:
        """
        Scrape NFL Combine results for 2026 prospects.

        Returns:
            tuple[list[ScrapedCombineStat], ScrapeResult]: Parsed combine
                measurements and a summary result object.
        """
        stats: list[ScrapedCombineStat] = []
        try:
            soup = await self.fetch_html(_COMBINE_URL)
            stats = _parse_combine_table(soup, _COMBINE_URL)
            logger.info("[nfl] Combine stats: %d records", len(stats))
            return stats, ScrapeResult(
                source=_SOURCE, success=True, records_fetched=len(stats)
            )
        except ScraperError as exc:
            logger.error("[nfl] Combine fetch failed: %s", exc)
            return stats, ScrapeResult(
                source=_SOURCE, success=False, error=str(exc)
            )


# ---------------------------------------------------------------------------
# Private parse helpers
# ---------------------------------------------------------------------------


def _parse_combine_table(soup: BeautifulSoup, url: str) -> list[ScrapedCombineStat]:
    """
    Extract combine measurements from the NFL.com prospects/combine table.

    Handles the main table structure:
    Name | Position | College | 40-Yd | Bench | Vert | Broad | Shuttle | 3-Cone

    Args:
        soup (BeautifulSoup): Parsed HTML document.
        url (str): Source URL for attribution.

    Returns:
        list[ScrapedCombineStat]: Parsed combine stat records.
    """
    stats: list[ScrapedCombineStat] = []

    # NFL.com renders combine data in a sortable table
    table = soup.find("table", class_=re.compile(r"combine|prospect", re.I))
    if not table or not isinstance(table, Tag):
        # Try generic table fallback
        table = soup.find("table")

    if not table or not isinstance(table, Tag):
        logger.warning("[nfl] Could not locate combine table")
        return stats

    # Map header column names to indices
    headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
    col = _build_column_map(headers)

    for row in table.find_all("tr")[1:]:
        cells = row.find_all("td")
        if not cells:
            continue
        text_vals = [c.get_text(strip=True) for c in cells]

        name = _get_col(text_vals, col, "name")
        position = _get_col(text_vals, col, "pos") or _get_col(text_vals, col, "position")
        college = _get_col(text_vals, col, "school") or _get_col(text_vals, col, "college")

        if not name:
            continue

        stats.append(
            ScrapedCombineStat(
                name=name,
                position=position or "",
                college=college or "",
                height_inches=_parse_height(_get_col(text_vals, col, "ht")),
                weight_lbs=_parse_int(_get_col(text_vals, col, "wt")),
                arm_length_inches=_parse_float(_get_col(text_vals, col, "arm")),
                hand_size_inches=_parse_float(_get_col(text_vals, col, "hand")),
                forty_yard_dash=_parse_float(_get_col(text_vals, col, "40")),
                vertical_jump_inches=_parse_float(_get_col(text_vals, col, "vert")),
                broad_jump_inches=_parse_int(_get_col(text_vals, col, "broad")),
                bench_press_reps=_parse_int(_get_col(text_vals, col, "bench")),
                three_cone=_parse_float(_get_col(text_vals, col, "3-cone")),
                twenty_yard_shuttle=_parse_float(_get_col(text_vals, col, "shuttle")),
                source=_SOURCE,
                source_url=url,
            )
        )

    return stats


def _build_column_map(headers: list[str]) -> dict[str, int]:
    """
    Build a keyword→column-index map from table header strings.

    Matches common column name patterns used by NFL.com.

    Args:
        headers (list[str]): Lowercased header text values.

    Returns:
        dict[str, int]: Keyword to column index mapping.
    """
    keywords = {
        "name": ["name", "player"],
        "pos": ["pos", "position"],
        "school": ["school", "college", "team"],
        "ht": ["ht", "height"],
        "wt": ["wt", "weight"],
        "arm": ["arm"],
        "hand": ["hand"],
        "40": ["40-yd", "40 yd", "40yard", "40"],
        "vert": ["vert", "vertical"],
        "broad": ["broad"],
        "bench": ["bench"],
        "3-cone": ["3-cone", "3cone", "cone"],
        "shuttle": ["shuttle", "20-yd"],
    }
    col_map: dict[str, int] = {}
    for i, header in enumerate(headers):
        for key, aliases in keywords.items():
            if any(alias in header for alias in aliases):
                col_map.setdefault(key, i)
    return col_map


def _get_col(
    values: list[str], col_map: dict[str, int], key: str
) -> Optional[str]:
    """
    Safely retrieve a cell value by column keyword.

    Args:
        values (list[str]): Row cell text values.
        col_map (dict[str, int]): Column keyword index map.
        key (str): Column keyword to look up.

    Returns:
        Optional[str]: Cell text or None if column not found or out of bounds.
    """
    idx = col_map.get(key)
    if idx is None or idx >= len(values):
        return None
    val = values[idx].strip()
    return val if val and val not in ("-", "—", "N/A") else None


def _parse_height(raw: Optional[str]) -> Optional[int]:
    """
    Convert a height string to total inches.

    Accepts formats: "6-4", "6'4\"", "6-04", "76" (already inches).

    Args:
        raw (Optional[str]): Raw height string.

    Returns:
        Optional[int]: Height in total inches or None.
    """
    if not raw:
        return None
    # Formats: "6-4", "6'4", "6-04"
    m = re.match(r"(\d+)['\-](\d+)", raw.strip())
    if m:
        return int(m.group(1)) * 12 + int(m.group(2))
    # Already pure inches integer
    try:
        val = int(re.sub(r"[^\d]", "", raw))
        return val if 60 <= val <= 84 else None  # sanity: 5'0" to 7'0"
    except ValueError:
        return None


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
        return float(raw)
    except ValueError:
        return None


def _parse_int(raw: Optional[str]) -> Optional[int]:
    """
    Parse a string to int, returning None on failure.

    Args:
        raw (Optional[str]): Raw string value.

    Returns:
        Optional[int]: Parsed int or None.
    """
    if not raw:
        return None
    try:
        return int(re.sub(r"[^\d]", "", raw))
    except ValueError:
        return None
