"""
Scraper for college season statistics from NFL.com prospect profile pages.

Fetches each prospect's individual page at:
    https://www.nfl.com/prospects/{player-slug}/

Parses the college stats section (passing, rushing, receiving, or defense
depending on position) and returns ScrapedCollegeStat records.
"""

from __future__ import annotations

import json
import logging
import re

from bs4 import BeautifulSoup, Tag

from app.models.scrape import ScrapedCollegeStat, ScrapeResult
from app.scrapers.base import BaseScraper, ScraperError

logger = logging.getLogger(__name__)

_SOURCE = "nfl_prospects"
_BASE = "https://www.nfl.com"
_PROSPECT_URL = f"{_BASE}/prospects/{{slug}}/"


class CollegeStatsScraper(BaseScraper):
    """
    Scraper for college season stats from NFL.com individual prospect pages.

    Fetches one page per player using their name slug (e.g. "fernando-mendoza").
    """

    SOURCE = _SOURCE
    BASE_URL = _BASE

    async def fetch_stats_for_player(
        self,
        name: str,
        position: str,
        college: str,
        player_id: str,
    ) -> tuple[list[ScrapedCollegeStat], ScrapeResult]:
        """
        Scrape college stats for a single prospect from their NFL.com page.

        Args:
            name (str): Player full name.
            position (str): Normalised position code (e.g. "QB").
            college (str): College name.
            player_id (str): URL slug (e.g. "fernando-mendoza").

        Returns:
            tuple[list[ScrapedCollegeStat], ScrapeResult]: Stats and result summary.
        """
        url = _PROSPECT_URL.format(slug=player_id)
        stats: list[ScrapedCollegeStat] = []
        try:
            soup = await self.fetch_html(url)
            stats = _parse_prospect_page(soup, name, position, college, url)
            return stats, ScrapeResult(
                source=_SOURCE, success=True, records_fetched=len(stats)
            )
        except ScraperError as exc:
            logger.warning("[%s] Stats fetch failed for %s: %s", _SOURCE, name, exc)
            return stats, ScrapeResult(
                source=_SOURCE, success=False, records_fetched=0, error=str(exc)
            )

    async def fetch_stats_for_pool(
        self,
        players: list[dict],
    ) -> tuple[list[ScrapedCollegeStat], ScrapeResult]:
        """
        Fetch college stats for a list of players sequentially.

        Args:
            players (list[dict]): Dicts with keys: name, position, college, player_id.

        Returns:
            tuple[list[ScrapedCollegeStat], ScrapeResult]: All stats and aggregate result.
        """
        all_stats: list[ScrapedCollegeStat] = []
        failures = 0
        for player in players:
            stats, result = await self.fetch_stats_for_player(
                name=player["name"],
                position=player.get("position", ""),
                college=player.get("college", ""),
                player_id=player["player_id"],
            )
            all_stats.extend(stats)
            if not result.success:
                failures += 1

        total = len(all_stats)
        success = failures < len(players)
        logger.info(
            "[%s] Pool stats: %d records from %d players (%d failures)",
            _SOURCE, total, len(players), failures,
        )
        return all_stats, ScrapeResult(
            source=_SOURCE,
            success=success,
            records_fetched=total,
            error=f"{failures} player page(s) failed" if failures else None,
        )


# ---------------------------------------------------------------------------
# Page parse helpers
# ---------------------------------------------------------------------------


def _parse_prospect_page(
    soup: BeautifulSoup,
    name: str,
    position: str,
    college: str,
    url: str,
) -> list[ScrapedCollegeStat]:
    """
    Extract college season stats from an NFL.com prospect profile page.

    Tries multiple strategies:
    1. Look for __NEXT_DATA__ JSON with embedded stats.
    2. Find stat tables by heading keywords.
    3. Generic table rows with season-year patterns.

    Args:
        soup (BeautifulSoup): Parsed page HTML.
        name (str): Player name (for attribution).
        position (str): Position code.
        college (str): College name.
        url (str): Source URL.

    Returns:
        list[ScrapedCollegeStat]: Season stat records found.
    """
    # Strategy 1: __NEXT_DATA__ JSON
    records = _parse_stats_from_nextjs(soup, name, position, college, url)
    if records:
        return records

    # Strategy 2: stat tables in HTML
    records = _parse_stats_from_tables(soup, name, position, college, url)
    if records:
        return records

    return []


def _parse_stats_from_nextjs(
    soup: BeautifulSoup, name: str, position: str, college: str, url: str
) -> list[ScrapedCollegeStat]:
    """Extract stats from Next.js __NEXT_DATA__ script tag if present."""
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not isinstance(script, Tag):
        return []
    try:
        data = json.loads(script.string or "")
    except (json.JSONDecodeError, TypeError):
        return []

    # Try common Next.js paths for prospect data
    player_data = (
        _deep_get(data, ["props", "pageProps", "player"])
        or _deep_get(data, ["props", "pageProps", "prospect"])
        or _deep_get(data, ["props", "pageProps", "data"])
    )
    if not isinstance(player_data, dict):
        return []

    # Look for stats array
    stats_raw = (
        player_data.get("stats") or player_data.get("collegeStat")
        or player_data.get("collegeStats")
    )
    if not isinstance(stats_raw, list):
        return []

    records = []
    for season_block in stats_raw:
        if not isinstance(season_block, dict):
            continue
        season = str(season_block.get("season") or season_block.get("year") or "")
        stats_dict = {
            k: v for k, v in season_block.items()
            if k not in ("season", "year", "team", "school")
        }
        if season and stats_dict:
            records.append(ScrapedCollegeStat(
                name=name, position=position, college=college,
                season=season, stats_json=json.dumps(stats_dict),
                source=_SOURCE, source_url=url,
            ))
    return records


def _parse_stats_from_tables(
    soup: BeautifulSoup, name: str, position: str, college: str, url: str
) -> list[ScrapedCollegeStat]:
    """Find and parse HTML stat tables on the page."""
    records = []

    # Find all tables; try to identify which has season stats
    for table in soup.find_all("table"):
        if not isinstance(table, Tag):
            continue
        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        # Must have at least a year/season column
        if not any(re.search(r"year|season|2\d{3}", h, re.I) for h in headers):
            continue

        col_names = headers

        for row in table.find_all("tr")[1:]:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            values = [c.get_text(strip=True) for c in cells]
            if len(values) < 2:
                continue

            # First cell is usually year/season
            season_raw = values[0]
            if not re.match(r"2\d{3}|Career|career", season_raw):
                continue
            season = season_raw

            stats_dict: dict[str, str] = {}
            for i, val in enumerate(values[1:], 1):
                if i < len(col_names) and val:
                    stats_dict[col_names[i]] = val

            if stats_dict:
                records.append(ScrapedCollegeStat(
                    name=name, position=position, college=college,
                    season=season, stats_json=json.dumps(stats_dict),
                    source=_SOURCE, source_url=url,
                ))

    return records


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _deep_get(data: dict, keys: list[str]) -> object:
    """Traverse nested dict by key path; return None if any key misses."""
    current: object = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current
