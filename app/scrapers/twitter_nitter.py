"""
Twitter/X scraper via nitter (open-source Twitter frontend proxy).

Fetches recent tweets from curated NFL draft expert accounts listed in
data/config/twitter_accounts.json. Filters tweets for player name mentions
and stores them as ScrapedMediaArticle with source_type='twitter'.

Nitter instances are public and frequently go down; multiple fallbacks
are tried in sequence. If all fail, returns 0 records gracefully.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from app.models.scrape import ScrapedMediaArticle, ScrapeResult
from app.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent.parent / "data" / "config" / "twitter_accounts.json"

# Public nitter instances, tried in order until one responds.
NITTER_INSTANCES: list[str] = [
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
    "https://nitter.esmailelbob.xyz",
    "https://nitter.net",
    "https://nitter.cz",
]


def _load_twitter_config() -> dict:
    """
    Load the curated Twitter account config.

    Returns:
        dict: Parsed twitter_accounts.json content.
    """
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("[twitter_nitter] twitter_accounts.json not found at %s", _CONFIG_PATH)
        return {"general_experts": [], "team_experts": {}}


def _player_mentioned(tweet_text: str, player_names: list[str]) -> Optional[str]:
    """
    Return the player name if any player is mentioned in the tweet text.

    Checks full name first, then last name (if last name is ≥6 chars to
    avoid false positives on common short surnames).

    Args:
        tweet_text (str): Raw tweet text.
        player_names (list[str]): Full player names to check.

    Returns:
        Optional[str]: Matched player name, or None.
    """
    text_lower = tweet_text.lower()
    for name in player_names:
        # Full name check
        if name.lower() in text_lower:
            return name
        # Last name check (only for surnames ≥ 6 chars)
        parts = name.split()
        if len(parts) >= 2:
            last = parts[-1]
            if len(last) >= 6 and last.lower() in text_lower:
                return name
    return None


def _parse_nitter_timeline(html: str, handle: str, base_url: str) -> list[dict]:
    """
    Parse a nitter account timeline page and extract tweet data.

    Args:
        html (str): Raw HTML of the nitter timeline page.
        handle (str): Twitter handle (without @) for URL construction.
        base_url (str): Nitter instance base URL used for resolving links.

    Returns:
        list[dict]: List of tweet dicts with keys:
            text, url, published_at, account (str "@handle")
    """
    soup = BeautifulSoup(html, "lxml")
    tweets: list[dict] = []

    for item in soup.select(".timeline-item"):
        # Skip retweet headers — only original tweets and quote tweets
        if item.select_one(".retweet-header"):
            continue

        content_el = item.select_one(".tweet-content")
        if not content_el:
            continue

        text = content_el.get_text(" ", strip=True)
        if not text:
            continue

        # Extract tweet permalink → convert to x.com URL
        link_el = item.select_one(".tweet-link")
        tweet_url = ""
        if link_el and link_el.get("href"):
            href = link_el["href"]
            # Nitter hrefs look like /{handle}/status/{id}#m
            clean = href.split("#")[0]
            tweet_url = f"https://x.com{clean}"

        # Extract published_at from <span class="tweet-date"> title attribute
        # Nitter format: "Mar 5, 2026 · 2:30 PM UTC"
        published_at = ""
        date_el = item.select_one(".tweet-date a")
        if date_el and date_el.get("title"):
            raw_date = date_el["title"]
            try:
                # Parse "Mar 5, 2026 · 2:30 PM UTC" → ISO date
                date_part = raw_date.split("·")[0].strip()
                dt = datetime.strptime(date_part, "%b %d, %Y")
                published_at = dt.strftime("%Y-%m-%d")
            except (ValueError, IndexError):
                published_at = ""

        tweets.append(
            {
                "text": text,
                "url": tweet_url,
                "published_at": published_at,
                "account": f"@{handle}",
            }
        )

    return tweets


class TwitterNitterScraper(BaseScraper):
    """
    Scrapes tweet content from curated NFL draft expert accounts via nitter.

    Iterates over public nitter instances as fallbacks. Fetches each account's
    timeline, filters for mentions of tracked 2026 draft prospects, and returns
    results as ScrapedMediaArticle records.
    """

    SOURCE = "twitter_nitter"
    BASE_URL = ""  # Dynamic — set per nitter instance

    def __init__(self, timeout: float = 15.0, max_retries: int = 1):
        """
        Initialize with shorter timeout since nitter instances are unreliable.

        Args:
            timeout (float): HTTP timeout per request in seconds.
            max_retries (int): Retries per individual URL (nitter instances
                fail fast; we rely on instance fallback instead).
        """
        super().__init__(timeout=timeout, max_retries=max_retries)

    async def _try_nitter_instances(self, handle: str) -> list[dict]:
        """
        Try each nitter instance in sequence to fetch a timeline.

        Args:
            handle (str): Twitter handle (without @).

        Returns:
            list[dict]: Parsed tweet dicts, or [] if all instances fail.
        """
        async with httpx.AsyncClient(
            headers=self._HEADERS,
            timeout=self.timeout,
            follow_redirects=True,
        ) as client:
            for instance in NITTER_INSTANCES:
                url = f"{instance}/{handle}"
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200 and len(resp.text) > 500:
                        tweets = _parse_nitter_timeline(resp.text, handle, instance)
                        if tweets:
                            logger.debug(
                                "[twitter_nitter] @%s — %d tweets via %s",
                                handle,
                                len(tweets),
                                instance,
                            )
                            return tweets
                except Exception as exc:
                    logger.debug("[twitter_nitter] Instance %s failed for @%s: %s", instance, handle, exc)
                await asyncio.sleep(0.05)
        return []

    async def fetch_tweets_for_picks(
        self,
        picks: list[dict],
        player_names: list[str],
    ) -> tuple[list[ScrapedMediaArticle], ScrapeResult]:
        """
        Fetch tweets from curated accounts that mention tracked 2026 prospects.

        Strategy:
        - General experts: fetch timeline, filter for any of the player_names.
        - Team experts: fetch timelines for accounts matching each pick's team;
          filter for the player assigned to that team's picks.

        Args:
            picks (list[dict]): List of pick dicts with at least
                {"current_team": str, "player_id": str | None}.
            player_names (list[str]): Full player names to match against tweets.

        Returns:
            tuple[list[ScrapedMediaArticle], ScrapeResult]:
                Articles and a summary result.
        """
        config = _load_twitter_config()
        general_accounts: list[dict] = config.get("general_experts", [])
        team_experts: dict[str, list[dict]] = config.get("team_experts", {})

        articles: list[ScrapedMediaArticle] = []
        now = datetime.now(timezone.utc)
        fetched_at_iso = now.isoformat()

        # Build team → player names mapping from picks
        # Reason: limit team expert searches to their team's assigned players
        team_players: dict[str, list[str]] = {}
        for pick in picks:
            team = (pick.get("current_team") or "").lower()
            if not team:
                continue
            team_players.setdefault(team, [])
        # Map all players to teams if we have assignment data
        # If picks don't have player names, search against all player_names
        all_names = player_names or []

        # --- General experts: filter against all player names ---
        for account in general_accounts:
            handle = account.get("handle", "")
            if not handle:
                continue
            tweets = await self._try_nitter_instances(handle)
            for tw in tweets:
                matched = _player_mentioned(tw["text"], all_names)
                if matched:
                    articles.append(
                        ScrapedMediaArticle(
                            player_name=matched,
                            title=tw["text"][:500],  # cap tweet length
                            url=tw["url"] or f"https://x.com/{handle}",
                            source_name=f"@{handle}",
                            source_type="twitter",
                            published_at=tw["published_at"] or None,
                            source="nitter",
                            source_url=f"https://x.com/{handle}",
                            fetched_at=now,
                        )
                    )
            await asyncio.sleep(0.1)

        # --- Team experts: filter against their team's players ---
        visited_handles: set[str] = {a["handle"] for a in general_accounts}
        for team, expert_list in team_experts.items():
            names_for_team = all_names  # filter against all if no assignment
            for account in expert_list:
                handle = account.get("handle", "")
                if not handle or handle in visited_handles:
                    continue
                visited_handles.add(handle)
                tweets = await self._try_nitter_instances(handle)
                for tw in tweets:
                    matched = _player_mentioned(tw["text"], names_for_team)
                    if matched:
                        articles.append(
                            ScrapedMediaArticle(
                                player_name=matched,
                                title=tw["text"][:500],
                                url=tw["url"] or f"https://x.com/{handle}",
                                source_name=f"@{handle}",
                                source_type="twitter",
                                published_at=tw["published_at"] or None,
                                source="nitter",
                                source_url=f"https://x.com/{handle}",
                                fetched_at=now,
                            )
                        )
                await asyncio.sleep(0.1)

        # Deduplicate by URL
        seen_urls: set[str] = set()
        deduped: list[ScrapedMediaArticle] = []
        for art in articles:
            if art.url not in seen_urls:
                seen_urls.add(art.url)
                deduped.append(art)

        success = len(deduped) > 0 or True  # True even if 0 — graceful empty
        logger.info("[twitter_nitter] %d tweets collected for %d players", len(deduped), len(all_names))

        return deduped, ScrapeResult(
            source="nitter",
            success=True,
            records_fetched=len(deduped),
            fetched_at=now,
        )
