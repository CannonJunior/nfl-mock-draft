"""
Scraper for ESPN mock draft articles.

Fetches the latest ESPN 2026 NFL mock draft article and extracts
projected pick/player pairings for rounds 1–3.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from bs4 import BeautifulSoup, Tag

from app.models.scrape import ScrapedMockEntry, ScrapeResult
from app.scrapers.base import BaseScraper, ScraperError

logger = logging.getLogger(__name__)

_SOURCE = "espn_mock"
_BASE = "https://www.espn.com"

# Candidate URLs for ESPN mock draft articles (2026), tried in order.
_ARTICLE_URLS = [
    f"{_BASE}/nfl/draft2026/story/_/id/47989848/2026-nfl-mock-draft-kiper-32-picks-pre-combine-predictions-round-1",
    f"{_BASE}/nfl/draft2026/story/_/id/48053564/2026-nfl-mock-draft-two-rounds-64-picks-jordan-reid-combine",
    f"{_BASE}/nfl/draft2026/story/_/id/47756543/2026-nfl-mock-draft-two-rounds-64-picks-matt-miller-senior-bowl",
    f"{_BASE}/nfl/draft2026/story/_/id/47840791/2026-nfl-mock-draft-field-yates-first-round-predictions-32-picks",
]

# Matches "1.Las Vegas Raiders" or "1. Las Vegas Raiders" in h2 elements
_H2_PICK_TEAM_RE = re.compile(r"^(\d+)\.\s*(.+)$")

# Compiled pattern to detect numbered pick lines like "1." or "Pick 1:"
_PICK_NUM_RE = re.compile(r"^\s*(?:Pick\s+)?(\d{1,3})[.):\-]\s*")

# ESPN often embeds position + college in parentheses: "Shedeur Sanders (QB, Colorado)"
_PLAYER_PAREN_RE = re.compile(
    r"^(.+?)\s*\(([A-Z]{1,4}),?\s*([^)]*)\)",
    re.IGNORECASE,
)


class ESPNMockScraper(BaseScraper):
    """
    Scraper for ESPN.com mock draft articles.

    Fetches the most recent ESPN mock draft article and extracts projected
    pick/player pairings. Returns a list of ScrapedMockEntry objects with
    source="espn_mock".
    """

    SOURCE = _SOURCE
    BASE_URL = _BASE

    async def fetch_mock_draft(self) -> tuple[list[ScrapedMockEntry], ScrapeResult]:
        """
        Scrape the latest ESPN mock draft article.

        Tries each URL in _ARTICLE_URLS sequentially until one succeeds
        and yields picks. Non-blocking on full failure.

        Returns:
            tuple[list[ScrapedMockEntry], ScrapeResult]: Parsed entries and
                a summary result object.
        """
        entries: list[ScrapedMockEntry] = []
        last_error: Optional[str] = None

        for url in _ARTICLE_URLS:
            try:
                soup = await self.fetch_html(url)
                entries = _parse_espn_mock(soup, url)
                if entries:
                    logger.info(
                        "[espn_mock] Mock draft: %d entries from %s", len(entries), url
                    )
                    return entries, ScrapeResult(
                        source=_SOURCE, success=True, records_fetched=len(entries)
                    )
                logger.warning("[espn_mock] No entries from %s, trying next URL", url)
            except ScraperError as exc:
                last_error = str(exc)
                logger.warning("[espn_mock] Failed to fetch %s: %s", url, exc)

        error_msg = last_error or "No picks found in any ESPN mock article"
        logger.error("[espn_mock] All URLs exhausted: %s", error_msg)
        return entries, ScrapeResult(source=_SOURCE, success=False, error=error_msg)


# ---------------------------------------------------------------------------
# Private parse helpers
# ---------------------------------------------------------------------------


def _parse_espn_mock(soup: BeautifulSoup, url: str) -> list[ScrapedMockEntry]:
    """
    Dispatch to the appropriate parsing strategy for an ESPN mock page.

    Tries structured containers first, then falls back to article-body parsing.

    Args:
        soup (BeautifulSoup): Parsed HTML document.
        url (str): Source URL for attribution.

    Returns:
        list[ScrapedMockEntry]: All parsed mock draft entries.
    """
    # Strategy 1: ESPN 2026 article format — <h2>N.Team</h2><p>Player, POS, College</p>
    entries = _parse_h2_team_mock(soup, url)
    if entries:
        return entries

    # Strategy 2: ESPN draft tracker structured rows
    entries = _parse_tracker_rows(soup, url)
    if entries:
        return entries

    # Strategy 3: story pick containers (ESPN article format)
    entries = _parse_story_picks(soup, url)
    if entries:
        return entries

    # Strategy 4: generic ordered list items
    entries = _parse_ordered_lists(soup, url)
    if entries:
        return entries

    # Strategy 5: paragraph-level pick detection
    return _parse_paragraph_picks(soup, url)


def _parse_h2_team_mock(soup: BeautifulSoup, url: str) -> list[ScrapedMockEntry]:
    """
    Parse ESPN mock draft articles where each pick uses:
        <h2>N.Team Name</h2>
        <p>Player Name, POSITION, College</p>

    This is the layout used by Kiper, Jordan Reid, and Field Yates 2026 articles.

    Args:
        soup (BeautifulSoup): Parsed HTML document.
        url (str): Source URL for attribution.

    Returns:
        list[ScrapedMockEntry]: Parsed entries, or empty list if not found.
    """
    entries: list[ScrapedMockEntry] = []

    for h2 in soup.find_all("h2"):
        text = h2.get_text(strip=True)
        m = _H2_PICK_TEAM_RE.match(text)
        if not m:
            continue

        pick_num = int(m.group(1))
        if not (1 <= pick_num <= 130):
            continue

        team = m.group(2).strip()

        # Find the first <p> sibling — it contains "Player, POS, College"
        node = h2.next_sibling
        while node is not None:
            if hasattr(node, "name") and node.name:
                if node.name == "p":
                    p_text = node.get_text(strip=True)
                    parts = [p.strip() for p in p_text.split(",")]
                    # Validate: at least "Name, POS" with a multi-word name
                    if len(parts) >= 2 and len(parts[0].split()) >= 2:
                        player_name = parts[0]
                        position = parts[1].upper()
                        college = parts[2] if len(parts) > 2 else ""
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
                    break  # Only use the first <p> per h2
                elif node.name == "h2":
                    break  # Next pick block — no player found for this pick
            node = node.next_sibling

    return entries


def _parse_tracker_rows(soup: BeautifulSoup, url: str) -> list[ScrapedMockEntry]:
    """
    Parse picks from ESPN's structured draft tracker table.

    Args:
        soup (BeautifulSoup): Parsed HTML document.
        url (str): Source URL for attribution.

    Returns:
        list[ScrapedMockEntry]: Entries from the tracker table.
    """
    entries: list[ScrapedMockEntry] = []

    # ESPN tracker uses divs with class patterns like "pick-row" or "draftTracker"
    rows = soup.select(
        ".draftTracker__pick, .pick-row, tr.Table__TR"
    )

    for row in rows:
        cells = row.find_all(["td", "div"])
        if len(cells) < 3:
            continue
        vals = [c.get_text(strip=True) for c in cells]
        if not vals[0].isdigit():
            continue

        entries.append(
            ScrapedMockEntry(
                pick_number=int(vals[0]),
                team=vals[1] if len(vals) > 1 else "UNK",
                player_name=vals[2] if len(vals) > 2 else "TBD",
                position=vals[3] if len(vals) > 3 else "",
                college=vals[4] if len(vals) > 4 else "",
                source=_SOURCE,
                source_url=url,
            )
        )
    return entries


def _parse_story_picks(soup: BeautifulSoup, url: str) -> list[ScrapedMockEntry]:
    """
    Parse picks from ESPN article story containers.

    ESPN mock draft stories use divs with class names like "story-pick"
    or section headers followed by player info blocks.

    Args:
        soup (BeautifulSoup): Parsed HTML document.
        url (str): Source URL for attribution.

    Returns:
        list[ScrapedMockEntry]: Parsed entries from story pick containers.
    """
    entries: list[ScrapedMockEntry] = []
    containers = soup.select(".story-pick, .mock-pick, .pick__content")

    pick_counter = 0
    for container in containers:
        pick_counter += 1
        text = container.get_text(separator=" ", strip=True)
        entry = _parse_pick_text(pick_counter, text, url)
        if entry:
            entries.append(entry)

    return entries


def _parse_ordered_lists(soup: BeautifulSoup, url: str) -> list[ScrapedMockEntry]:
    """
    Parse picks from ordered list elements in the article body.

    Args:
        soup (BeautifulSoup): Parsed HTML document.
        url (str): Source URL for attribution.

    Returns:
        list[ScrapedMockEntry]: Entries from list items.
    """
    entries: list[ScrapedMockEntry] = []
    for ol in soup.find_all("ol"):
        items = ol.find_all("li")
        if len(items) < 10:
            # Reason: skip short nav lists; mock drafts have 32+ entries
            continue
        for i, item in enumerate(items, start=1):
            text = item.get_text(separator=" ", strip=True)
            entry = _parse_pick_text(i, text, url)
            if entry:
                entries.append(entry)
        if entries:
            break

    return entries


def _parse_paragraph_picks(soup: BeautifulSoup, url: str) -> list[ScrapedMockEntry]:
    """
    Parse picks from article paragraphs with "N. Player, Pos, College" format.

    Args:
        soup (BeautifulSoup): Parsed HTML document.
        url (str): Source URL for attribution.

    Returns:
        list[ScrapedMockEntry]: Entries from inline pick paragraphs.
    """
    entries: list[ScrapedMockEntry] = []
    body = soup.find("article") or soup.find("main") or soup.find("body")
    if not body or not isinstance(body, Tag):
        return entries

    for tag in body.find_all(["p", "h2", "h3", "li"]):
        text = tag.get_text(separator=" ", strip=True)
        m = _PICK_NUM_RE.match(text)
        if m:
            pick_num = int(m.group(1))
            if 1 <= pick_num <= 130:
                entry = _parse_pick_text(pick_num, text[m.end():], url)
                if entry:
                    entries.append(entry)

    # Deduplicate by pick_number (keep first occurrence)
    seen: set[int] = set()
    deduped: list[ScrapedMockEntry] = []
    for e in entries:
        if e.pick_number not in seen:
            seen.add(e.pick_number)
            deduped.append(e)
    return deduped


def _parse_pick_text(pick_number: int, text: str, url: str) -> Optional[ScrapedMockEntry]:
    """
    Convert a raw text description of a pick into a ScrapedMockEntry.

    Handles ESPN article formats including:
    - "Shedeur Sanders (QB, Colorado)"
    - "Team: Shedeur Sanders, QB, Colorado"
    - "Shedeur Sanders | QB | Colorado | Las Vegas Raiders"

    Args:
        pick_number (int): Overall pick number for this entry.
        text (str): Raw text description of the pick.
        url (str): Source URL for attribution.

    Returns:
        Optional[ScrapedMockEntry]: Parsed entry, or None if unparseable.
    """
    if not text or len(text) < 5:
        return None

    text = text.strip()

    # Strategy A: "Player Name (POS, College)" — ESPN's most common format
    paren_match = _PLAYER_PAREN_RE.match(text)
    if paren_match:
        player_name = paren_match.group(1).strip()
        position = paren_match.group(2).strip().upper()
        college = paren_match.group(3).strip()
        if len(player_name.split()) >= 2:
            return ScrapedMockEntry(
                pick_number=pick_number,
                team="",
                player_name=player_name,
                position=position,
                college=college,
                source=_SOURCE,
                source_url=url,
            )

    # Strategy B: "Team: Player, POS, College" (colon separator)
    colon_parts = text.split(":", 1)
    if len(colon_parts) == 2:
        team_candidate = colon_parts[0].strip()
        remainder = colon_parts[1].strip()
        comma_parts = [p.strip() for p in remainder.split(",")]
        if len(comma_parts) >= 2 and len(comma_parts[0].split()) >= 2:
            return ScrapedMockEntry(
                pick_number=pick_number,
                team=team_candidate,
                player_name=comma_parts[0],
                position=comma_parts[1].upper() if len(comma_parts) > 1 else "",
                college=comma_parts[2] if len(comma_parts) > 2 else "",
                source=_SOURCE,
                source_url=url,
            )

    # Strategy C: comma-separated "Player, POS, College"
    comma_parts = [p.strip() for p in text.split(",")]
    if len(comma_parts) >= 2 and len(comma_parts[0].split()) >= 2:
        return ScrapedMockEntry(
            pick_number=pick_number,
            team="",
            player_name=comma_parts[0],
            position=comma_parts[1].upper() if len(comma_parts) > 1 else "",
            college=comma_parts[2] if len(comma_parts) > 2 else "",
            source=_SOURCE,
            source_url=url,
        )

    return None
