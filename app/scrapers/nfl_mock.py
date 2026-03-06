"""
Scraper for NFL.com mock draft articles.

Parses the latest NFL.com mock draft article to extract projected picks
for rounds 1–3. Falls back to a generic article list search if the
primary URL is not available.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from bs4 import BeautifulSoup, Tag

from app.models.scrape import ScrapedMockEntry, ScrapeResult
from app.scrapers.base import BaseScraper, ScraperError

logger = logging.getLogger(__name__)

_SOURCE = "nfl_mock"
_BASE = "https://www.nfl.com"

# Candidate article URLs for 2026 mocks, tried in order
_ARTICLE_URLS = [
    f"{_BASE}/news/lance-zierlein-2026-nfl-mock-draft-2-0-two-cbs-in-top-five-combine-star-sonny-styles-cracks-top-10",
    f"{_BASE}/news/daniel-jeremiah-2026-nfl-mock-draft-2-0",
    f"{_BASE}/news/lance-zierlein-2026-nfl-mock-draft-1-0",
    f"{_BASE}/news/daniel-jeremiah-2026-nfl-mock-draft-1-0",
]

# Compiled pattern for "1." or "Pick 1" style pick-number prefixes
_PICK_NUM_RE = re.compile(r"^\s*(?:Pick\s+)?(\d{1,3})[.)]\s*")

# Common position codes used by NFL.com writers
_POSITION_CODES = {
    "quarterback", "qb", "wide receiver", "wr", "offensive tackle", "ot",
    "edge rusher", "edge", "defensive end", "de", "cornerback", "cb",
    "running back", "rb", "tight end", "te", "linebacker", "lb",
    "defensive tackle", "dt", "safety", "s", "guard", "og", "center", "c",
    "interior offensive lineman", "iol",
}


class NFLMockScraper(BaseScraper):
    """
    Scraper for NFL.com mock draft articles.

    Fetches the most recent NFL.com mock draft article and extracts
    projected pick/player pairings. Returns a list of ScrapedMockEntry
    objects with source="nfl_mock".
    """

    SOURCE = _SOURCE
    BASE_URL = _BASE

    async def fetch_mock_draft(self) -> tuple[list[ScrapedMockEntry], ScrapeResult]:
        """
        Scrape the latest NFL.com mock draft article.

        Tries each URL in _ARTICLE_URLS sequentially until one succeeds.
        Falls back to an empty list on total failure (non-blocking).

        Returns:
            tuple[list[ScrapedMockEntry], ScrapeResult]: Parsed entries and
                a summary result object.
        """
        entries: list[ScrapedMockEntry] = []
        last_error: Optional[str] = None

        for url in _ARTICLE_URLS:
            try:
                soup = await self.fetch_html(url)
                entries = _parse_mock_article(soup, url)
                if entries:
                    logger.info("[nfl_mock] Mock draft: %d entries from %s", len(entries), url)
                    return entries, ScrapeResult(
                        source=_SOURCE, success=True, records_fetched=len(entries)
                    )
                logger.warning("[nfl_mock] No entries parsed from %s, trying next URL", url)
            except ScraperError as exc:
                last_error = str(exc)
                logger.warning("[nfl_mock] Failed to fetch %s: %s", url, exc)

        error_msg = last_error or "No picks found in any NFL.com mock article"
        logger.error("[nfl_mock] All URLs exhausted: %s", error_msg)
        return entries, ScrapeResult(source=_SOURCE, success=False, error=error_msg)


# ---------------------------------------------------------------------------
# Private parse helpers
# ---------------------------------------------------------------------------


def _parse_mock_article(soup: BeautifulSoup, url: str) -> list[ScrapedMockEntry]:
    """
    Extract pick entries from a parsed NFL.com mock draft article page.

    Tries multiple HTML structures:
    1. h3 sentinel pattern — NFL.com article format (<h3>Pick</h3><h3>N</h3>…)
    2. Structured draft-tracker table rows
    3. Numbered list items in article body
    4. Article paragraphs with "Pick N." format

    Args:
        soup (BeautifulSoup): Parsed HTML of the article page.
        url (str): Source URL for attribution in returned models.

    Returns:
        list[ScrapedMockEntry]: Parsed mock draft entries.
    """
    # Strategy 1: NFL.com nfl-o-ranked-item component (2026 article format)
    entries = _parse_ranked_items(soup, url)
    if entries:
        return entries

    # Strategy 2: structured table (draft tracker endpoint)
    entries = _parse_tracker_table(soup, url)
    if entries:
        return entries

    # Strategy 3: numbered list items (article format)
    entries = _parse_article_list(soup, url)
    if entries:
        return entries

    # Strategy 4: paragraphs with "1. Player Name, Position, College" format
    entries = _parse_paragraph_picks(soup, url)
    return entries


def _parse_ranked_items(soup: BeautifulSoup, url: str) -> list[ScrapedMockEntry]:
    """
    Parse picks from NFL.com nfl-o-ranked-item component structure.

    NFL.com mock draft articles (2026) use CSS-class-based components:
        <div class="nfl-o-ranked-item …">
          <div class="nfl-o-ranked-item__label--second">1</div>
          <div class="nfl-o-ranked-item__title">Las Vegas Raiders</div>   ← team
          <a href="/prospects/…">Fernando Mendoza</a>                     ← player
          <div class="nfl-o-ranked-item__info">Indiana·QB · Junior (RS)</div>
        </div>

    Args:
        soup (BeautifulSoup): Parsed HTML document.
        url (str): Source URL for attribution.

    Returns:
        list[ScrapedMockEntry]: Parsed entries, or empty list if not found.
    """
    entries: list[ScrapedMockEntry] = []

    for item in soup.select("div.nfl-o-ranked-item"):
        # Pick number
        pick_div = item.find("div", class_="nfl-o-ranked-item__label--second")
        if not isinstance(pick_div, Tag):
            continue
        pick_text = pick_div.get_text(strip=True)
        if not pick_text.isdigit():
            continue
        pick_num = int(pick_text)
        if not (1 <= pick_num <= 130):
            continue

        # Team name from title div
        team = ""
        title_div = item.find("div", class_="nfl-o-ranked-item__title")
        if isinstance(title_div, Tag):
            team = title_div.get_text(strip=True)

        # Player name from prospect link
        player_name = ""
        prospect_link = item.find("a", href=re.compile(r"/prospects/"))
        if isinstance(prospect_link, Tag):
            player_name = prospect_link.get_text(strip=True)
        if not player_name:
            continue

        # Position and college from info div: "Indiana·QB · Junior (RS)"
        position = ""
        college = ""
        for info_div in item.find_all("div", class_="nfl-o-ranked-item__info"):
            info_text = info_div.get_text(strip=True)
            if not info_text:
                continue
            # Split on middle-dot · or regular dot between college and pos
            parts = re.split(r"[·•]", info_text)
            if parts:
                college = parts[0].strip()
            if len(parts) >= 2:
                pos_match = re.search(r"\b([A-Z]{1,5})\b", parts[1])
                if pos_match:
                    position = pos_match.group(1)
            break  # Only need first non-empty info div

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


def _parse_tracker_table(soup: BeautifulSoup, url: str) -> list[ScrapedMockEntry]:
    """
    Parse picks from an NFL.com structured tracker table.

    Args:
        soup (BeautifulSoup): Parsed HTML document.
        url (str): Source URL for attribution.

    Returns:
        list[ScrapedMockEntry]: Entries found in any table structure.
    """
    entries: list[ScrapedMockEntry] = []
    table = soup.find("table")
    if not table or not isinstance(table, Tag):
        return entries

    for row in table.find_all("tr"):
        cells = row.find_all(["td", "th"])
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


def _parse_article_list(soup: BeautifulSoup, url: str) -> list[ScrapedMockEntry]:
    """
    Parse picks from an ordered list in an NFL.com article.

    Looks for <ol> elements containing <li> items with pick data.

    Args:
        soup (BeautifulSoup): Parsed HTML document.
        url (str): Source URL for attribution.

    Returns:
        list[ScrapedMockEntry]: Entries parsed from list items.
    """
    entries: list[ScrapedMockEntry] = []
    lists = soup.find_all("ol")

    for ol in lists:
        items = ol.find_all("li")
        if len(items) < 10:
            # Reason: skip navigation/footer lists; draft lists have 32+ items
            continue
        for i, item in enumerate(items, start=1):
            text = item.get_text(separator=" ", strip=True)
            entry = _parse_pick_text(i, text, url)
            if entry:
                entries.append(entry)

    return entries


def _parse_paragraph_picks(soup: BeautifulSoup, url: str) -> list[ScrapedMockEntry]:
    """
    Parse picks from article paragraphs using "N. Player, Pos, College" format.

    Args:
        soup (BeautifulSoup): Parsed HTML document.
        url (str): Source URL for attribution.

    Returns:
        list[ScrapedMockEntry]: Entries parsed from paragraphs.
    """
    entries: list[ScrapedMockEntry] = []
    body = soup.find("article") or soup.find("main") or soup.find("body")
    if not body:
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

    # Reason: deduplicate by pick_number, keeping first occurrence
    seen: set[int] = set()
    deduped: list[ScrapedMockEntry] = []
    for e in entries:
        if e.pick_number not in seen:
            seen.add(e.pick_number)
            deduped.append(e)
    return deduped


def _parse_pick_text(pick_number: int, text: str, url: str) -> Optional[ScrapedMockEntry]:
    """
    Parse a free-text pick description into a ScrapedMockEntry.

    Handles formats like:
    - "Shedeur Sanders, QB, Colorado — Las Vegas Raiders"
    - "Las Vegas Raiders: Shedeur Sanders (QB, Colorado)"
    - "Team | Player Name | QB | Colorado"

    Args:
        pick_number (int): The overall pick number for this entry.
        text (str): Raw text describing the pick.
        url (str): Source URL for attribution.

    Returns:
        Optional[ScrapedMockEntry]: Parsed entry, or None if unparseable.
    """
    if not text or len(text) < 5:
        return None

    # Try "Player Name, POSITION, College" pattern (most common in articles)
    comma_parts = [p.strip() for p in text.split(",") if p.strip()]
    if len(comma_parts) >= 2:
        player_name = comma_parts[0]
        position = ""
        college = ""

        for part in comma_parts[1:]:
            upper = part.upper().strip()
            if upper in {p.upper() for p in _POSITION_CODES} or len(upper) <= 4:
                position = upper
            elif not college:
                college = part.strip()

        if player_name and len(player_name.split()) >= 2:
            return ScrapedMockEntry(
                pick_number=pick_number,
                team="",
                player_name=player_name,
                position=position,
                college=college,
                source=_SOURCE,
                source_url=url,
            )

    # Try pipe-delimited format
    pipe_parts = [p.strip() for p in text.split("|") if p.strip()]
    if len(pipe_parts) >= 3:
        return ScrapedMockEntry(
            pick_number=pick_number,
            team=pipe_parts[0],
            player_name=pipe_parts[1],
            position=pipe_parts[2] if len(pipe_parts) > 2 else "",
            college=pipe_parts[3] if len(pipe_parts) > 3 else "",
            source=_SOURCE,
            source_url=url,
        )

    return None
