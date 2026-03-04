"""
Scraper for www.tankathon.com.

Pulls three data sets:
1. Draft order (current pick ownership, round-by-round)
2. Team needs (positional need ratings per team)
3. Consensus mock draft (projected picks by expert consensus)
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from bs4 import BeautifulSoup, Tag

from app.models.scrape import (
    ScrapedDraftPick,
    ScrapedMockEntry,
    ScrapedTeamNeed,
    ScrapeResult,
)
from app.scrapers.base import BaseScraper, ScraperError

logger = logging.getLogger(__name__)

_SOURCE = "tankathon"
_BASE = "https://www.tankathon.com"

# Tankathon uses numeric need levels inside colored cells; we normalise to 1-5
_NEED_LABEL_MAP: dict[str, int] = {
    "critical": 5,
    "high": 4,
    "medium": 3,
    "low": 2,
    "minimal": 1,
}


class TankathonScraper(BaseScraper):
    """
    Scraper for tankathon.com draft order, team needs, and mock draft data.
    """

    SOURCE = _SOURCE
    BASE_URL = _BASE

    async def fetch_draft_order(self) -> tuple[list[ScrapedDraftPick], ScrapeResult]:
        """
        Scrape the current NFL draft pick order from tankathon.com.

        Returns:
            tuple[list[ScrapedDraftPick], ScrapeResult]: Parsed picks and
                a summary result object.
        """
        url = f"{_BASE}/"
        picks: list[ScrapedDraftPick] = []
        try:
            soup = await self.fetch_html(url)
            picks = _parse_draft_order(soup, url)
            logger.info("[tankathon] Draft order: %d picks", len(picks))
            return picks, ScrapeResult(
                source=_SOURCE, success=True, records_fetched=len(picks)
            )
        except ScraperError as exc:
            logger.error("[tankathon] Draft order failed: %s", exc)
            return picks, ScrapeResult(
                source=_SOURCE, success=False, error=str(exc)
            )

    async def fetch_team_needs(self) -> tuple[list[ScrapedTeamNeed], ScrapeResult]:
        """
        Scrape team positional needs from tankathon.com/team-needs.

        Returns:
            tuple[list[ScrapedTeamNeed], ScrapeResult]: Parsed needs and
                a summary result object.
        """
        url = f"{_BASE}/team-needs"
        needs: list[ScrapedTeamNeed] = []
        try:
            soup = await self.fetch_html(url)
            needs = _parse_team_needs(soup, url)
            logger.info("[tankathon] Team needs: %d records", len(needs))
            return needs, ScrapeResult(
                source=_SOURCE, success=True, records_fetched=len(needs)
            )
        except ScraperError as exc:
            logger.error("[tankathon] Team needs failed: %s", exc)
            return needs, ScrapeResult(
                source=_SOURCE, success=False, error=str(exc)
            )

    async def fetch_mock_draft(self) -> tuple[list[ScrapedMockEntry], ScrapeResult]:
        """
        Scrape the Tankathon consensus mock draft.

        Returns:
            tuple[list[ScrapedMockEntry], ScrapeResult]: Parsed mock entries
                and a summary result object.
        """
        url = f"{_BASE}/mock-draft"
        entries: list[ScrapedMockEntry] = []
        try:
            soup = await self.fetch_html(url)
            entries = _parse_mock_draft(soup, url)
            logger.info("[tankathon] Mock draft: %d entries", len(entries))
            return entries, ScrapeResult(
                source=_SOURCE, success=True, records_fetched=len(entries)
            )
        except ScraperError as exc:
            logger.error("[tankathon] Mock draft failed: %s", exc)
            return entries, ScrapeResult(
                source=_SOURCE, success=False, error=str(exc)
            )


# ---------------------------------------------------------------------------
# Private parse helpers
# ---------------------------------------------------------------------------


def _parse_draft_order(soup: BeautifulSoup, url: str) -> list[ScrapedDraftPick]:
    """
    Extract draft pick rows from the Tankathon homepage table.

    Args:
        soup (BeautifulSoup): Parsed HTML document.
        url (str): Source URL for attribution in returned models.

    Returns:
        list[ScrapedDraftPick]: Parsed pick objects.
    """
    picks: list[ScrapedDraftPick] = []
    # Tankathon renders picks inside a table with class "draft-table" or similar
    rows = soup.select("table.draft-table tr, #draft-board tr, .pick-row")
    if not rows:
        # Fall back to any table row containing a pick number cell
        rows = soup.find_all("tr")

    overall = 0
    current_round = 1
    pick_in_round = 0

    for row in rows:
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        text_vals = [c.get_text(strip=True) for c in cells]

        # Detect round header rows like "Round 1", "Round 2"
        full_text = " ".join(text_vals)
        round_match = re.search(r"Round\s+(\d)", full_text, re.IGNORECASE)
        if round_match and len(text_vals) <= 2:
            current_round = int(round_match.group(1))
            pick_in_round = 0
            continue

        # Skip header/label rows
        if not text_vals[0].isdigit():
            continue

        overall += 1
        pick_in_round += 1
        pick_num = int(text_vals[0]) if text_vals[0].isdigit() else overall
        team = text_vals[1] if len(text_vals) > 1 else "UNK"
        traded_from: Optional[str] = None

        # Reason: traded picks appear as "NYJ (via NE)" or similar
        via_match = re.search(r"\(via\s+(.+?)\)", team)
        if via_match:
            traded_from = via_match.group(1).strip()
            team = re.sub(r"\s*\(via.+?\)", "", team).strip()

        picks.append(
            ScrapedDraftPick(
                pick_number=pick_num,
                round=current_round,
                pick_in_round=pick_in_round,
                team=team,
                traded_from=traded_from,
                source=_SOURCE,
                source_url=url,
            )
        )

    return picks


def _parse_team_needs(soup: BeautifulSoup, url: str) -> list[ScrapedTeamNeed]:
    """
    Extract team positional need ratings from the Tankathon team-needs page.

    Args:
        soup (BeautifulSoup): Parsed HTML document.
        url (str): Source URL for attribution.

    Returns:
        list[ScrapedTeamNeed]: Parsed need records.
    """
    needs: list[ScrapedTeamNeed] = []
    # Tankathon renders needs as a grid: rows = teams, columns = positions
    # Header row contains position names
    table = soup.find("table")
    if not table or not isinstance(table, Tag):
        logger.warning("[tankathon] Could not find needs table")
        return needs

    header_cells = table.find_all("th")
    positions = [th.get_text(strip=True) for th in header_cells[1:]]

    for row in table.find_all("tr")[1:]:
        cells = row.find_all("td")
        if not cells:
            continue
        team_name = cells[0].get_text(strip=True)
        for i, cell in enumerate(cells[1:]):
            if i >= len(positions):
                break
            # Reason: need level is encoded as a CSS class like "need-5" or data attr
            level = _extract_need_level(cell)
            if level is not None:
                needs.append(
                    ScrapedTeamNeed(
                        team=team_name,
                        position=positions[i],
                        need_level=level,
                        source=_SOURCE,
                        source_url=url,
                    )
                )

    return needs


def _extract_need_level(cell: Tag) -> Optional[int]:
    """
    Determine the integer need level from a Tankathon needs table cell.

    Args:
        cell (Tag): A BeautifulSoup <td> element.

    Returns:
        Optional[int]: Need level 1-5, or None if it cannot be determined.
    """
    # Try data attributes first
    for attr in ("data-need", "data-level", "data-value"):
        val = cell.get(attr)
        if val and str(val).isdigit():
            return max(1, min(5, int(val)))

    # Try CSS class names like "need-4" or "level-3"
    classes = " ".join(cell.get("class", []))
    class_match = re.search(r"(?:need|level)-(\d)", classes)
    if class_match:
        return max(1, min(5, int(class_match.group(1))))

    # Try text label
    label = cell.get_text(strip=True).lower()
    return _NEED_LABEL_MAP.get(label)


def _parse_mock_draft(soup: BeautifulSoup, url: str) -> list[ScrapedMockEntry]:
    """
    Extract projected picks from the Tankathon mock draft page.

    Args:
        soup (BeautifulSoup): Parsed HTML document.
        url (str): Source URL for attribution.

    Returns:
        list[ScrapedMockEntry]: Parsed mock draft entries.
    """
    entries: list[ScrapedMockEntry] = []
    rows = soup.select("table tr, .mock-pick, .pick-row")

    for row in rows:
        cells = row.find_all(["td", "th"])
        if len(cells) < 3:
            continue
        text_vals = [c.get_text(strip=True) for c in cells]

        if not text_vals[0].isdigit():
            continue

        pick_number = int(text_vals[0])
        team = text_vals[1] if len(text_vals) > 1 else "UNK"
        player_name = text_vals[2] if len(text_vals) > 2 else "TBD"
        position = text_vals[3] if len(text_vals) > 3 else ""
        college = text_vals[4] if len(text_vals) > 4 else ""

        entries.append(
            ScrapedMockEntry(
                pick_number=pick_number,
                team=team,
                player_name=player_name,
                position=position,
                college=college,
                source=_SOURCE,
                source_url=url,
            )
        )

    return entries
