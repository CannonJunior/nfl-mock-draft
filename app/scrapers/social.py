"""
Social and analyst community buzz scraper for 2026 NFL Draft prospects.

Pulls two signals:
1. The Draft Network community consensus board — analyst grades and big board rank.
2. Reddit r/nflmocks public JSON API — post/mention count as buzz proxy.

Both signals feed into the `buzz_signals` DB table and are combined with ESPN
grades and mock consensus in the analytics engine to produce final scores.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup, Tag

from app.models.scrape import ScrapedBuzzRecord, ScrapeResult
from app.scrapers.base import BaseScraper, ScraperError

logger = logging.getLogger(__name__)

_SOURCE_TDN = "thedraftnetwork"
_SOURCE_REDDIT = "reddit"

_TDN_BOARD_URL = "https://www.thedraftnetwork.com/consensus-big-board"
_REDDIT_SEARCH_URL = (
    "https://www.reddit.com/r/nflmocks/search.json"
    "?q=2026+nfl+draft&sort=top&t=month&limit=100&restrict_sr=1"
)



class SocialScraper(BaseScraper):
    """
    Scraper for social/community buzz signals about 2026 NFL Draft prospects.

    Combines The Draft Network community grades with Reddit mention counts
    to produce buzz signals that supplement pure analytics grades.
    """

    SOURCE = "social"
    BASE_URL = "https://www.thedraftnetwork.com"

    async def fetch_tdn_board(
        self,
    ) -> tuple[list[ScrapedBuzzRecord], ScrapeResult]:
        """
        Scrape The Draft Network community consensus big board.

        Tries multiple parse strategies:
        1. Next.js __NEXT_DATA__ JSON embedded in page script tag.
        2. Structured list/card elements with class patterns for player rows.
        3. Generic table fallback.

        Returns:
            tuple[list[ScrapedBuzzRecord], ScrapeResult]: Parsed records and
                a summary result.
        """
        records: list[ScrapedBuzzRecord] = []
        try:
            soup = await self.fetch_html(_TDN_BOARD_URL)
            records = _parse_tdn_page(soup, _TDN_BOARD_URL)
            logger.info("[%s] TDN board: %d records", _SOURCE_TDN, len(records))
            return records, ScrapeResult(
                source=_SOURCE_TDN, success=True, records_fetched=len(records)
            )
        except ScraperError as exc:
            logger.error("[social] TDN fetch failed: %s", exc)
            return records, ScrapeResult(
                source=_SOURCE_TDN, success=False, error=str(exc)
            )

    async def fetch_reddit_buzz(
        self, known_players: Optional[list[str]] = None
    ) -> tuple[list[ScrapedBuzzRecord], ScrapeResult]:
        """
        Count prospect mentions in recent r/nflmocks posts via Reddit JSON API.

        Uses the public (no-auth) Reddit JSON API to fetch the top posts for
        the month, then tallies name mentions per player.

        Args:
            known_players (Optional[list[str]]): List of player names to look for.
                If None, relies on common prospect name patterns.

        Returns:
            tuple[list[ScrapedBuzzRecord], ScrapeResult]: Buzz records with
                mention counts and a summary result.
        """
        records: list[ScrapedBuzzRecord] = []
        try:
            data = await self._fetch_json(_REDDIT_SEARCH_URL)
            records = _parse_reddit_posts(data, known_players or [], _REDDIT_SEARCH_URL)
            logger.info("[%s] Reddit buzz: %d player mentions", _SOURCE_REDDIT, len(records))
            return records, ScrapeResult(
                source=_SOURCE_REDDIT, success=True, records_fetched=len(records)
            )
        except (ScraperError, Exception) as exc:
            logger.error("[social] Reddit fetch failed: %s", exc)
            return records, ScrapeResult(
                source=_SOURCE_REDDIT, success=False, error=str(exc)
            )

    async def _fetch_json(self, url: str) -> dict:
        """
        Fetch a URL that returns JSON directly (not HTML).

        Args:
            url (str): URL to fetch.

        Returns:
            dict: Parsed JSON response body.

        Raises:
            ScraperError: On HTTP error or JSON parse failure.
        """
        headers = {
            **self._HEADERS,
            # Reddit requires a custom User-Agent for API access
            "User-Agent": "nfl-mock-draft-app/1.0 (by /u/draftbot_research)",
        }
        async with httpx.AsyncClient(
            headers=headers, timeout=self.timeout, follow_redirects=True
        ) as client:
            response = await client.get(url)
            if response.status_code != 200:
                raise ScraperError(
                    self.SOURCE,
                    f"HTTP {response.status_code} from {url}",
                    status_code=response.status_code,
                )
            try:
                return response.json()
            except Exception as exc:
                raise ScraperError(self.SOURCE, f"JSON parse error: {exc}")


# ---------------------------------------------------------------------------
# The Draft Network parse helpers
# ---------------------------------------------------------------------------


def _parse_tdn_page(soup: BeautifulSoup, url: str) -> list[ScrapedBuzzRecord]:
    """
    Extract prospect grades from The Draft Network consensus board page.

    Tries strategies in order:
    1. __NEXT_DATA__ embedded JSON (Next.js pages).
    2. JSON-LD or application/json script tags.
    3. Structured player card/row elements.

    Args:
        soup (BeautifulSoup): Parsed page HTML.
        url (str): Source URL for attribution.

    Returns:
        list[ScrapedBuzzRecord]: Extracted buzz records.
    """
    # Strategy 1: Next.js __NEXT_DATA__
    records = _parse_nextjs_data(soup, url)
    if records:
        return records

    # Strategy 2: Embedded JSON in script tags
    records = _parse_embedded_json(soup, url)
    if records:
        return records

    # Strategy 3: HTML player cards/rows
    records = _parse_tdn_html_elements(soup, url)
    if records:
        return records

    logger.warning("[thedraftnetwork] Could not extract player data from page")
    return []


def _parse_nextjs_data(soup: BeautifulSoup, url: str) -> list[ScrapedBuzzRecord]:
    """
    Extract player data from a __NEXT_DATA__ script tag.

    Args:
        soup (BeautifulSoup): Parsed HTML.
        url (str): Source URL.

    Returns:
        list[ScrapedBuzzRecord]: Records if found, else empty list.
    """
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not isinstance(script, Tag):
        return []

    try:
        data = json.loads(script.string or "")
    except (json.JSONDecodeError, TypeError):
        return []

    # Navigate common Next.js data shapes for player board pages
    players_raw = (
        _deep_get(data, ["props", "pageProps", "players"])
        or _deep_get(data, ["props", "pageProps", "board"])
        or _deep_get(data, ["props", "pageProps", "prospects"])
        or _deep_get(data, ["props", "pageProps", "data", "players"])
    )

    if not isinstance(players_raw, list):
        return []

    records = []
    for i, player in enumerate(players_raw):
        name = player.get("name") or player.get("fullName") or player.get("player_name")
        if not name:
            continue
        grade_raw = player.get("grade") or player.get("community_grade") or player.get("score")
        grade = _safe_float(grade_raw)
        if grade is not None and grade > 10:
            # Reason: some boards use 0-100 scale — normalise to 0-10
            grade = grade / 10.0
        rank = _safe_int(player.get("rank") or player.get("big_board_rank") or (i + 1))
        records.append(
            ScrapedBuzzRecord(
                name=name, grade=grade, rank=rank, source=_SOURCE_TDN, source_url=url
            )
        )
    return records


def _parse_embedded_json(soup: BeautifulSoup, url: str) -> list[ScrapedBuzzRecord]:
    """
    Look for JSON-LD or application/json script tags with player data.

    Args:
        soup (BeautifulSoup): Parsed HTML.
        url (str): Source URL.

    Returns:
        list[ScrapedBuzzRecord]: Records if found, else empty list.
    """
    for script in soup.find_all("script", type=re.compile(r"json", re.I)):
        if not isinstance(script, Tag):
            continue
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, list) and data and "name" in data[0]:
            records = []
            for i, item in enumerate(data):
                name = item.get("name")
                if not name:
                    continue
                grade = _safe_float(item.get("grade") or item.get("score"))
                records.append(
                    ScrapedBuzzRecord(
                        name=name,
                        grade=grade,
                        rank=_safe_int(item.get("rank") or (i + 1)),
                        source=_SOURCE_TDN,
                        source_url=url,
                    )
                )
            if records:
                return records
    return []


def _parse_tdn_html_elements(soup: BeautifulSoup, url: str) -> list[ScrapedBuzzRecord]:
    """
    Fall back to parsing visible HTML player card or table row elements.

    Args:
        soup (BeautifulSoup): Parsed HTML.
        url (str): Source URL.

    Returns:
        list[ScrapedBuzzRecord]: Records if found, else empty list.
    """
    records = []

    # Try player card patterns
    player_els = (
        soup.find_all(class_=re.compile(r"player[-_]?card|prospect[-_]?row|board[-_]?item", re.I))
        or soup.find_all("li", class_=re.compile(r"player|prospect", re.I))
    )

    for i, el in enumerate(player_els):
        if not isinstance(el, Tag):
            continue
        # Look for name in heading or strong element
        name_tag = el.find(["h2", "h3", "h4", "strong", "a"])
        if not isinstance(name_tag, Tag):
            continue
        name = name_tag.get_text(strip=True)
        if not name or len(name) < 4 or not re.search(r"[A-Z][a-z]+ [A-Z]", name):
            continue
        # Look for grade/score in a numeric span
        grade = None
        for span in el.find_all(["span", "div"]):
            if not isinstance(span, Tag):
                continue
            txt = span.get_text(strip=True)
            g = _safe_float(txt)
            if g is not None and 4.0 <= g <= 10.0:
                grade = g
                break
        records.append(
            ScrapedBuzzRecord(
                name=name,
                grade=grade,
                rank=i + 1,
                source=_SOURCE_TDN,
                source_url=url,
            )
        )

    return records


# ---------------------------------------------------------------------------
# Reddit parse helpers
# ---------------------------------------------------------------------------


def _parse_reddit_posts(
    data: dict, known_players: list[str], url: str
) -> list[ScrapedBuzzRecord]:
    """
    Count how many Reddit posts mention each known player name.

    Args:
        data (dict): Reddit search JSON response.
        known_players (list[str]): Player names to count mentions for.
        url (str): Source URL for attribution.

    Returns:
        list[ScrapedBuzzRecord]: One record per player with mention > 0.
    """
    # Extract all post titles + selftext from Reddit JSON response
    posts: list[str] = []
    try:
        children = data.get("data", {}).get("children", [])
        for child in children:
            post_data = child.get("data", {})
            title = post_data.get("title", "")
            selftext = post_data.get("selftext", "")
            posts.append(f"{title} {selftext}".lower())
    except (KeyError, TypeError):
        logger.warning("[reddit] Unexpected response structure")
        return []

    corpus = " ".join(posts)

    records = []
    for player_name in known_players:
        # Reason: use last name for more robust matching; full name is also tried
        parts = player_name.split()
        last_name = parts[-1] if parts else player_name
        full_lower = player_name.lower()
        last_lower = last_name.lower()

        # Count occurrences of last name and full name
        full_count = corpus.count(full_lower)
        # Only count last-name hits if last name is >=6 chars to avoid false positives
        last_count = corpus.count(last_lower) if len(last_lower) >= 6 else 0
        # Prefer full name match; fall back to last-name count
        mentions = full_count if full_count > 0 else last_count

        if mentions > 0:
            records.append(
                ScrapedBuzzRecord(
                    name=player_name,
                    mentions=mentions,
                    source=_SOURCE_REDDIT,
                    source_url=url,
                )
            )

    return records


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _deep_get(data: dict, keys: list[str]) -> Any:
    """
    Traverse a nested dict following a list of keys, returning None if any key misses.

    Args:
        data (dict): Root dict to traverse.
        keys (list[str]): Sequence of keys.

    Returns:
        object: The value at the end of the key chain, or None.
    """
    current: object = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _safe_float(val: Any) -> Optional[float]:
    """
    Safely convert a value to float, returning None on failure.

    Args:
        val (Any): Value to convert.

    Returns:
        Optional[float]: Converted float or None.
    """
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_int(val: Any) -> Optional[int]:
    """
    Safely convert a value to int, returning None on failure.

    Args:
        val (Any): Value to convert.

    Returns:
        Optional[int]: Converted int or None.
    """
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None
