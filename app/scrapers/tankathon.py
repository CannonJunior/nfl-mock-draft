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
        url = f"{_BASE}/nfl/full_draft"
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
        Return empty team needs — Tankathon has no standalone team-needs page.

        Reason: Tankathon encodes needs inside their mock algorithm but does
        not expose a separate team-needs URL. Return success with 0 records so
        the pipeline continues without error.

        Returns:
            tuple[list[ScrapedTeamNeed], ScrapeResult]: Empty list and a
                successful result object.
        """
        logger.info("[tankathon] Team needs page does not exist — skipping")
        return [], ScrapeResult(source=_SOURCE, success=True, records_fetched=0)

    async def fetch_mock_draft(self) -> tuple[list[ScrapedMockEntry], ScrapeResult]:
        """
        Scrape the Tankathon consensus mock draft.

        Returns:
            tuple[list[ScrapedMockEntry], ScrapeResult]: Parsed mock entries
                and a summary result object.
        """
        url = f"{_BASE}/nfl/mock_draft"
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
    Extract draft pick rows from the Tankathon full-draft page.

    The full_draft page uses round sections (div.full-draft-round-nfl) each
    containing a table.full-draft with rows of:
        <td class="pick-number">N</td>
        <td><div class="team-link"><a href="/nfl/slug">…<div class="desktop">Team</div></a></div></td>

    Args:
        soup (BeautifulSoup): Parsed HTML document.
        url (str): Source URL for attribution in returned models.

    Returns:
        list[ScrapedDraftPick]: Parsed pick objects.
    """
    picks: list[ScrapedDraftPick] = []

    for round_div in soup.select("div.full-draft-round-nfl"):
        # Derive round number from the round title (e.g. "1st Round", "2nd Round")
        current_round = 1
        title_div = round_div.find("div", class_="round-title")
        if title_div:
            round_match = re.search(r"(\d+)", title_div.get_text())
            if round_match:
                current_round = int(round_match.group(1))

        pick_in_round = 0
        for row in round_div.select("tr"):
            pick_td = row.find("td", class_="pick-number")
            if not pick_td:
                continue
            pick_text = pick_td.get_text(strip=True)
            if not pick_text.isdigit():
                continue

            pick_num = int(pick_text)
            pick_in_round += 1

            # Team name from the first link's desktop label
            team = ""
            team_link = row.find("a")
            if isinstance(team_link, Tag):
                desktop = team_link.find("div", class_="desktop")
                if desktop:
                    team = desktop.get_text(strip=True)

            picks.append(
                ScrapedDraftPick(
                    pick_number=pick_num,
                    round=current_round,
                    pick_in_round=pick_in_round,
                    team=team,
                    traded_from=None,
                    source=_SOURCE,
                    source_url=url,
                )
            )

    return picks


def _parse_mock_draft(soup: BeautifulSoup, url: str) -> list[ScrapedMockEntry]:
    """
    Extract projected picks from the Tankathon mock draft page.

    Each pick is in a div.mock-row containing:
        <div class="mock-row-pick-number">1</div>
        <div class="mock-row-logo"><a href="/nfl/slug"><img alt="LV" …/></a></div>
        <div class="mock-row-player">
            <a href="/nfl/players/…">
                <div class="mock-row-name">Player Name</div>
                <div class="mock-row-school-position">QB | Indiana </div>
            </a>
        </div>

    Args:
        soup (BeautifulSoup): Parsed HTML document.
        url (str): Source URL for attribution.

    Returns:
        list[ScrapedMockEntry]: Parsed mock draft entries.
    """
    entries: list[ScrapedMockEntry] = []

    for row in soup.select("div.mock-row"):
        # Pick number
        pick_div = row.find("div", class_="mock-row-pick-number")
        if not pick_div:
            continue
        pick_text = pick_div.get_text(strip=True)
        if not pick_text.isdigit():
            continue
        pick_num = int(pick_text)

        # Team abbreviation from the logo img alt attribute (e.g. alt="LV")
        team = ""
        logo_div = row.find("div", class_="mock-row-logo")
        if isinstance(logo_div, Tag):
            img = logo_div.find("img")
            if img:
                team = img.get("alt", "")  # type: ignore[arg-type]

        # Player name
        name_div = row.find("div", class_="mock-row-name")
        player_name = name_div.get_text(strip=True) if isinstance(name_div, Tag) else ""
        if not player_name:
            continue

        # Position and college from "QB | Indiana" text
        position = ""
        college = ""
        pos_div = row.find("div", class_="mock-row-school-position")
        if isinstance(pos_div, Tag):
            pos_text = pos_div.get_text(strip=True)
            parts = [p.strip() for p in pos_text.split("|")]
            if parts:
                position = parts[0]
            if len(parts) >= 2:
                college = parts[1]

        entries.append(
            ScrapedMockEntry(
                pick_number=pick_num,
                team=team,
                player_name=player_name,
                position=position,
                college=college,
                source=_SOURCE,
                source_url=url,
            )
        )

    return entries
