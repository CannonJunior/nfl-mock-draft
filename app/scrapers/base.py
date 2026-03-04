"""
Base scraper class for NFL mock draft data ingestion.

All source-specific scrapers inherit from BaseScraper, which handles:
- HTTP fetching with httpx
- Raw response caching to data/raw/
- Retry logic on transient failures
- Consistent error propagation via ScraperError
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Resolve data/raw/ relative to project root (two levels up from this file)
RAW_CACHE_DIR = Path(__file__).parent.parent.parent / "data" / "raw"


class ScraperError(Exception):
    """Raised when a scraper fails to fetch or parse data."""

    def __init__(self, source: str, message: str, status_code: Optional[int] = None):
        """
        Initialize ScraperError.

        Args:
            source (str): Scraper identifier (e.g. "tankathon").
            message (str): Human-readable description of the failure.
            status_code (Optional[int]): HTTP status code if applicable.
        """
        self.source = source
        self.status_code = status_code
        super().__init__(f"[{source}] {message}")


class BaseScraper:
    """
    Abstract base for all NFL data scrapers.

    Subclasses must define:
        SOURCE (str): Unique source identifier used for cache paths.
        BASE_URL (str): Root URL for the target site.

    Provides:
        fetch_html(): GET a URL and return parsed BeautifulSoup.
        _save_raw(): Persist raw HTML to data/raw/<source>/<timestamp>.html.
    """

    SOURCE: str = "base"
    BASE_URL: str = ""

    # Shared headers to mimic a browser and avoid simple bot blocks
    _HEADERS: dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    def __init__(self, timeout: float = 30.0, max_retries: int = 3):
        """
        Initialize the scraper.

        Args:
            timeout (float): HTTP request timeout in seconds.
            max_retries (int): Number of retry attempts on transient HTTP errors.
        """
        self.timeout = timeout
        self.max_retries = max_retries
        RAW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (RAW_CACHE_DIR / self.SOURCE).mkdir(parents=True, exist_ok=True)

    async def fetch_html(self, url: str) -> BeautifulSoup:
        """
        Fetch a URL and return a parsed BeautifulSoup document.

        Retries on 429, 503, and connection errors. Saves the raw HTML
        to data/raw/<source>/<timestamp>.html before returning.

        Args:
            url (str): Full URL to fetch.

        Returns:
            BeautifulSoup: Parsed HTML document using the lxml parser.

        Raises:
            ScraperError: If the request fails after all retries or returns
                a non-2xx status code.
        """
        last_error: Optional[Exception] = None

        async with httpx.AsyncClient(
            headers=self._HEADERS, timeout=self.timeout, follow_redirects=True
        ) as client:
            for attempt in range(1, self.max_retries + 1):
                try:
                    response = await client.get(url)

                    if response.status_code == 200:
                        html = response.text
                        self._save_raw(html, url)
                        return BeautifulSoup(html, "lxml")

                    if response.status_code in (429, 503):
                        # Reason: exponential backoff for rate-limiting responses
                        wait = 2**attempt
                        logger.warning(
                            "[%s] HTTP %d on attempt %d/%d, retrying in %ds",
                            self.SOURCE,
                            response.status_code,
                            attempt,
                            self.max_retries,
                            wait,
                        )
                        await asyncio.sleep(wait)
                        continue

                    raise ScraperError(
                        self.SOURCE,
                        f"HTTP {response.status_code} fetching {url}",
                        status_code=response.status_code,
                    )

                except httpx.RequestError as exc:
                    last_error = exc
                    logger.warning(
                        "[%s] Request error on attempt %d/%d: %s",
                        self.SOURCE,
                        attempt,
                        self.max_retries,
                        exc,
                    )
                    if attempt < self.max_retries:
                        await asyncio.sleep(2**attempt)

        raise ScraperError(
            self.SOURCE,
            f"All {self.max_retries} attempts failed for {url}: {last_error}",
        )

    def _save_raw(self, html: str, url: str) -> None:
        """
        Persist raw HTML content to data/raw/<source>/<timestamp>.html.

        Args:
            html (str): Raw HTML string from the HTTP response.
            url (str): The URL that was fetched (written as a comment header).
        """
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        cache_path = RAW_CACHE_DIR / self.SOURCE / f"{ts}.html"
        # Reason: prefix with URL comment so cached files are self-documenting
        cache_path.write_text(f"<!-- scraped from: {url} -->\n{html}", encoding="utf-8")
        logger.debug("[%s] Cached raw HTML → %s", self.SOURCE, cache_path)
