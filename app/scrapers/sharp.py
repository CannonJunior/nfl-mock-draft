"""
Scraper for www.sharpfootballanalysis.com advanced team analytics.

Pulls team-level efficiency metrics (DVOA-style) to provide context
for team needs and draft value assessments.
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup, Tag

from app.models.scrape import ScrapeResult
from app.scrapers.base import BaseScraper, ScraperError
from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger(__name__)

_SOURCE = "sharp"
_BASE = "https://www.sharpfootballanalysis.com"
_RANKINGS_URL = f"{_BASE}/rankings/nfl"


class TeamAnalytics(BaseModel):
    """
    Advanced efficiency metrics for a single NFL team.

    Attributes:
        team (str): Team name or abbreviation.
        overall_rank (Optional[int]): Overall team efficiency rank.
        offense_rank (Optional[int]): Offensive efficiency rank.
        defense_rank (Optional[int]): Defensive efficiency rank.
        overall_score (Optional[float]): Composite efficiency score.
        source (str): Scraper identifier.
        source_url (str): URL that was scraped.
    """

    team: str
    overall_rank: Optional[int] = None
    offense_rank: Optional[int] = None
    defense_rank: Optional[int] = None
    overall_score: Optional[float] = None
    source: str = _SOURCE
    source_url: str = ""


class SharpScraper(BaseScraper):
    """
    Scraper for SharpFootballAnalysis team efficiency rankings.
    """

    SOURCE = _SOURCE
    BASE_URL = _BASE

    async def fetch_team_analytics(
        self,
    ) -> tuple[list[TeamAnalytics], ScrapeResult]:
        """
        Scrape team efficiency rankings from SharpFootballAnalysis.

        Returns:
            tuple[list[TeamAnalytics], ScrapeResult]: Parsed analytics and
                a summary result object.
        """
        analytics: list[TeamAnalytics] = []
        try:
            soup = await self.fetch_html(_RANKINGS_URL)
            analytics = _parse_rankings(soup, _RANKINGS_URL)
            logger.info("[sharp] Team analytics: %d records", len(analytics))
            return analytics, ScrapeResult(
                source=_SOURCE, success=True, records_fetched=len(analytics)
            )
        except ScraperError as exc:
            logger.error("[sharp] Analytics fetch failed: %s", exc)
            return analytics, ScrapeResult(
                source=_SOURCE, success=False, error=str(exc)
            )


# ---------------------------------------------------------------------------
# Private parse helpers
# ---------------------------------------------------------------------------


def _parse_rankings(soup: BeautifulSoup, url: str) -> list[TeamAnalytics]:
    """
    Extract team efficiency rankings from a SharpFootballAnalysis rankings page.

    Args:
        soup (BeautifulSoup): Parsed HTML document.
        url (str): Source URL for attribution.

    Returns:
        list[TeamAnalytics]: Parsed analytics records.
    """
    analytics: list[TeamAnalytics] = []

    # SharpFootball uses various table structures; try class-based selectors first
    table = soup.find("table", class_=re.compile(r"ranking|team|efficiency", re.I))
    if not table or not isinstance(table, Tag):
        table = soup.find("table")

    if not table or not isinstance(table, Tag):
        logger.warning("[sharp] Could not locate rankings table")
        return analytics

    headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
    col_map = _build_col_map(headers)

    for row in table.find_all("tr")[1:]:
        cells = row.find_all("td")
        if not cells:
            continue
        vals = [c.get_text(strip=True) for c in cells]

        team = _safe_get(vals, col_map.get("team", 0))
        if not team:
            continue

        analytics.append(
            TeamAnalytics(
                team=team,
                overall_rank=_parse_int(_safe_get(vals, col_map.get("overall_rank"))),
                offense_rank=_parse_int(_safe_get(vals, col_map.get("off_rank"))),
                defense_rank=_parse_int(_safe_get(vals, col_map.get("def_rank"))),
                overall_score=_parse_float(_safe_get(vals, col_map.get("score"))),
                source=_SOURCE,
                source_url=url,
            )
        )

    return analytics


def _build_col_map(headers: list[str]) -> dict[str, int]:
    """
    Map semantic column names to column indices from header text.

    Args:
        headers (list[str]): Lowercased header text values.

    Returns:
        dict[str, int]: Semantic key to column index mapping.
    """
    keywords: dict[str, list[str]] = {
        "team": ["team", "name"],
        "overall_rank": ["rank", "overall rank", "#"],
        "off_rank": ["off", "offense"],
        "def_rank": ["def", "defense"],
        "score": ["score", "rating", "dvoa", "efficiency"],
    }
    col_map: dict[str, int] = {}
    for i, header in enumerate(headers):
        for key, aliases in keywords.items():
            if any(alias in header for alias in aliases):
                col_map.setdefault(key, i)
    return col_map


def _safe_get(values: list[str], idx: Optional[int]) -> Optional[str]:
    """
    Safely retrieve a list element by index.

    Args:
        values (list[str]): List of string values.
        idx (Optional[int]): Index to retrieve.

    Returns:
        Optional[str]: Value at index, or None if out of range or idx is None.
    """
    if idx is None or idx >= len(values):
        return None
    val = values[idx].strip()
    return val if val and val not in ("-", "—", "N/A") else None


def _parse_float(raw: Optional[str]) -> Optional[float]:
    """
    Parse string to float.

    Args:
        raw (Optional[str]): Raw string.

    Returns:
        Optional[float]: Float or None.
    """
    if not raw:
        return None
    try:
        return float(raw.replace("%", "").strip())
    except ValueError:
        return None


def _parse_int(raw: Optional[str]) -> Optional[int]:
    """
    Parse string to int.

    Args:
        raw (Optional[str]): Raw string.

    Returns:
        Optional[int]: Int or None.
    """
    if not raw:
        return None
    try:
        return int(re.sub(r"[^\d]", "", raw))
    except ValueError:
        return None
