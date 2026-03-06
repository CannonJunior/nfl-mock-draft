"""
News article scraper using Google News RSS for 2026 NFL Draft prospects.

Fetches recent news articles for each prospect from Google News RSS (no API
key required). Articles are stored as ScrapedMediaArticle records and displayed
in the Media & Coverage tab of each pick's detail panel.
"""

from __future__ import annotations

import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Optional

import httpx

from app.models.scrape import ScrapedMediaArticle, ScrapeResult
from app.scrapers.base import BaseScraper, ScraperError

logger = logging.getLogger(__name__)

_SOURCE = "google_news"
_RSS_BASE = "https://news.google.com/rss/search"
_MAX_ARTICLES_PER_PLAYER = 5


class NewsScraper(BaseScraper):
    """
    Scraper that fetches recent news articles per prospect from Google News RSS.

    Google News RSS is publicly accessible with no authentication. Returns
    structured RSS XML with item titles, links, source names, and pub dates.
    """

    SOURCE = _SOURCE
    BASE_URL = "https://news.google.com"

    async def fetch_articles_for_pool(
        self,
        players: list[dict],
    ) -> tuple[list[ScrapedMediaArticle], ScrapeResult]:
        """
        Fetch news articles for a list of players sequentially.

        Args:
            players (list[dict]): Dicts with keys: name, position, college.
                At minimum, 'name' is required.

        Returns:
            tuple[list[ScrapedMediaArticle], ScrapeResult]: All articles and
                an aggregate result.
        """
        all_articles: list[ScrapedMediaArticle] = []
        failures = 0

        for player in players:
            name = player.get("name", "")
            if not name:
                continue
            articles, result = await self._fetch_for_player(name)
            all_articles.extend(articles)
            if not result.success:
                failures += 1

        total = len(all_articles)
        logger.info(
            "[%s] News: %d articles for %d players (%d failures)",
            _SOURCE, total, len(players), failures,
        )
        return all_articles, ScrapeResult(
            source=_SOURCE,
            success=failures < len(players),
            records_fetched=total,
            error=f"{failures} player(s) failed" if failures else None,
        )

    async def _fetch_for_player(
        self, name: str
    ) -> tuple[list[ScrapedMediaArticle], ScrapeResult]:
        """
        Fetch Google News RSS for a single player name.

        Args:
            name (str): Player full name.

        Returns:
            tuple[list[ScrapedMediaArticle], ScrapeResult]: Articles and result.
        """
        query = f"{name} NFL draft 2026"
        params = {
            "q": query,
            "hl": "en-US",
            "gl": "US",
            "ceid": "US:en",
        }
        url = f"{_RSS_BASE}?{urllib.parse.urlencode(params)}"
        articles: list[ScrapedMediaArticle] = []

        try:
            xml_text = await self._fetch_rss_text(url)
            articles = _parse_rss(xml_text, name, url)
            return articles, ScrapeResult(
                source=_SOURCE, success=True, records_fetched=len(articles)
            )
        except Exception as exc:
            logger.warning("[%s] RSS fetch failed for %s: %s", _SOURCE, name, exc)
            return articles, ScrapeResult(
                source=_SOURCE, success=False, error=str(exc)
            )

    async def _fetch_rss_text(self, url: str) -> str:
        """
        Fetch RSS feed content as raw text.

        Args:
            url (str): Full RSS URL including query parameters.

        Returns:
            str: Raw XML text.

        Raises:
            ScraperError: On HTTP error or network failure.
        """
        headers = {
            **self._HEADERS,
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
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
            return response.text


# ---------------------------------------------------------------------------
# RSS parse helpers
# ---------------------------------------------------------------------------


def _parse_rss(
    xml_text: str,
    player_name: str,
    source_url: str,
) -> list[ScrapedMediaArticle]:
    """
    Parse a Google News RSS XML response into ScrapedMediaArticle records.

    Args:
        xml_text (str): Raw RSS XML string.
        player_name (str): Player the articles are about.
        source_url (str): URL that was fetched (for attribution).

    Returns:
        list[ScrapedMediaArticle]: Up to _MAX_ARTICLES_PER_PLAYER records.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("[%s] XML parse error: %s", _SOURCE, exc)
        return []

    channel = root.find("channel")
    if channel is None:
        return []

    articles: list[ScrapedMediaArticle] = []
    for item in channel.findall("item"):
        if len(articles) >= _MAX_ARTICLES_PER_PLAYER:
            break

        title = _tag_text(item, "title")
        link = _tag_text(item, "link")
        pub_date = _tag_text(item, "pubDate")
        source_el = item.find("source")
        source_name = source_el.text.strip() if source_el is not None and source_el.text else "Google News"

        if not title or not link:
            continue

        # Clean Google News redirect URLs — they sometimes wrap the real URL
        clean_url = _clean_google_url(link)

        # Normalise publication date to ISO date string if possible
        pub_iso = _parse_pub_date(pub_date)

        # Classify as mock_draft if title contains relevant keywords
        source_type = "news"
        if re.search(r"mock draft|big board|projection|prediction", title, re.I):
            source_type = "mock_draft"
        elif re.search(r"highlight|film|tape|youtube", title, re.I):
            source_type = "video"

        articles.append(
            ScrapedMediaArticle(
                player_name=player_name,
                title=title[:200],  # cap title length
                url=clean_url,
                source_name=source_name,
                source_type=source_type,
                published_at=pub_iso,
                source=_SOURCE,
                source_url=source_url,
            )
        )

    return articles


def _tag_text(element: ET.Element, tag: str) -> Optional[str]:
    """Return stripped text content of a child element, or None."""
    child = element.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    return None


def _clean_google_url(url: str) -> str:
    """
    Strip Google News redirect wrapper from article URLs.

    Google News RSS sometimes wraps URLs as:
    https://news.google.com/rss/articles/...

    The real URL is usually the last item after 'url=' in a query string,
    or we return the original link if it's already a direct URL.

    Args:
        url (str): Raw URL from RSS item.

    Returns:
        str: Cleaned article URL.
    """
    # Some Google News links redirect; return as-is for now — the frontend
    # will still show and open them. A more complex decode requires signing.
    return url


def _parse_pub_date(raw: Optional[str]) -> Optional[str]:
    """
    Convert RSS pubDate (RFC 2822) to an ISO date string (YYYY-MM-DD).

    Args:
        raw (Optional[str]): Raw pubDate string from RSS.

    Returns:
        Optional[str]: ISO date string or None if unparseable.
    """
    if not raw:
        return None
    # Try common RFC 2822 patterns
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%d %b %Y %H:%M:%S %z",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(raw.strip(), fmt)
            return dt.date().isoformat()
        except ValueError:
            continue
    # Regex fallback: grab the date portion
    m = re.search(r"(\d{1,2}\s+\w{3}\s+\d{4})", raw)
    if m:
        try:
            dt = datetime.strptime(m.group(1), "%d %b %Y")
            return dt.date().isoformat()
        except ValueError:
            pass
    return None
