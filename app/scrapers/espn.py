"""
Scraper for www.espn.com NFL draft prospect rankings.

Pulls:
1. Big board / top prospect rankings from ESPN's draft tracker
2. Individual player detail pages for bio and stats
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from bs4 import BeautifulSoup, Tag

from app.models.scrape import ScrapedProspect, ScrapeResult
from app.scrapers.base import BaseScraper, ScraperError

logger = logging.getLogger(__name__)

_SOURCE = "espn"
_BASE = "https://www.espn.com"
_TRACKER_URL = f"{_BASE}/nfl/draft/tracker"


class ESPNScraper(BaseScraper):
    """
    Scraper for ESPN NFL draft prospect big board and player bios.
    """

    SOURCE = _SOURCE
    BASE_URL = _BASE

    async def fetch_prospects(
        self, max_pages: int = 5
    ) -> tuple[list[ScrapedProspect], ScrapeResult]:
        """
        Scrape ESPN's draft big board for the top prospects.

        ESPN paginates the draft tracker; this method fetches up to
        max_pages pages and deduplicates by player name.

        Args:
            max_pages (int): Maximum number of paginated pages to fetch.

        Returns:
            tuple[list[ScrapedProspect], ScrapeResult]: Parsed prospects and
                a summary result object.
        """
        all_prospects: list[ScrapedProspect] = []
        try:
            for page in range(1, max_pages + 1):
                url = f"{_TRACKER_URL}/_/class/2026/page/{page}"
                try:
                    soup = await self.fetch_html(url)
                    page_prospects = _parse_prospect_page(soup, url)
                    if not page_prospects:
                        # Reason: stop early if a page returns no data
                        logger.info(
                            "[espn] No prospects on page %d, stopping pagination", page
                        )
                        break
                    all_prospects.extend(page_prospects)
                    logger.info(
                        "[espn] Page %d: %d prospects (total %d)",
                        page,
                        len(page_prospects),
                        len(all_prospects),
                    )
                except ScraperError as page_exc:
                    logger.warning("[espn] Page %d failed: %s", page, page_exc)
                    break

            return all_prospects, ScrapeResult(
                source=_SOURCE, success=True, records_fetched=len(all_prospects)
            )
        except Exception as exc:
            logger.error("[espn] Prospects fetch failed: %s", exc)
            return all_prospects, ScrapeResult(
                source=_SOURCE,
                success=False,
                records_fetched=len(all_prospects),
                error=str(exc),
            )


# ---------------------------------------------------------------------------
# Private parse helpers
# ---------------------------------------------------------------------------


def _parse_prospect_page(soup: BeautifulSoup, url: str) -> list[ScrapedProspect]:
    """
    Parse a single ESPN draft tracker page into ScrapedProspect objects.

    Args:
        soup (BeautifulSoup): Parsed HTML of one prospects page.
        url (str): Source URL for attribution.

    Returns:
        list[ScrapedProspect]: Prospects found on this page.
    """
    prospects: list[ScrapedProspect] = []

    # ESPN renders a table with class "Table" or similar; try several selectors
    rows = soup.select(
        "table.Table tbody tr, "
        ".prospect-table tbody tr, "
        ".ResponsiveTable tbody tr"
    )

    if not rows:
        # Fall back: look for any table rows with rank-like first cell
        rows = soup.find_all("tr")

    for row in rows:
        if not isinstance(row, Tag):
            continue
        cells = row.find_all(["td", "th"])
        if len(cells) < 3:
            continue

        text_vals = [c.get_text(strip=True) for c in cells]

        # Skip header rows
        if not text_vals[0].isdigit():
            continue

        rank = int(text_vals[0])
        name = _clean_name(text_vals[1]) if len(text_vals) > 1 else "Unknown"
        position = text_vals[2] if len(text_vals) > 2 else ""
        college = text_vals[3] if len(text_vals) > 3 else ""
        grade = _parse_grade(text_vals[4]) if len(text_vals) > 4 else None

        if not name or name.lower() in ("player", "name"):
            continue

        prospects.append(
            ScrapedProspect(
                name=name,
                position=position,
                college=college,
                rank=rank,
                grade=grade,
                source=_SOURCE,
                source_url=url,
            )
        )

    return prospects


def _clean_name(raw: str) -> str:
    """
    Strip ESPN-appended junk from player name cells.

    Args:
        raw (str): Raw text content of the name cell.

    Returns:
        str: Cleaned player name.
    """
    # Remove trailing position/college abbreviations that ESPN sometimes appends
    # e.g. "Cam Ward QB" → "Cam Ward"
    cleaned = re.sub(r"\s+[A-Z]{1,3}$", "", raw.strip())
    return cleaned.strip()


def _parse_grade(raw: str) -> Optional[float]:
    """
    Parse a prospect grade string to float.

    Args:
        raw (str): Raw grade string (e.g. "8.5", "N/A", "").

    Returns:
        Optional[float]: Numeric grade or None if not parseable.
    """
    try:
        return float(raw)
    except (ValueError, TypeError):
        return None
