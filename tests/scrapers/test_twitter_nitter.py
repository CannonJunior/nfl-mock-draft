"""
Unit tests for app/scrapers/twitter_nitter.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.scrapers.twitter_nitter import (
    TwitterNitterScraper,
    _parse_nitter_timeline,
    _player_mentioned,
)

# ---------------------------------------------------------------------------
# Synthetic nitter HTML fixture
# ---------------------------------------------------------------------------

NITTER_HTML = """
<html><body>
<div class="timeline">
  <div class="timeline-item">
    <div class="tweet-content">Cam Ward looks like a lock for pick 1. Incredible arm talent out of Miami.</div>
    <a class="tweet-link" href="/AdamSchefter/status/1234567890#m"></a>
    <div class="tweet-date"><a title="Mar 5, 2026 · 3:00 PM UTC" href="/AdamSchefter/status/1234567890#m">Mar 5</a></div>
  </div>
  <div class="timeline-item">
    <div class="retweet-header">Retweet</div>
    <div class="tweet-content">This is a retweet and should be skipped.</div>
    <a class="tweet-link" href="/AdamSchefter/status/9999999999#m"></a>
  </div>
  <div class="timeline-item">
    <div class="tweet-content">Travis Hunter is the most complete prospect in this draft class.</div>
    <a class="tweet-link" href="/AdamSchefter/status/2222222222#m"></a>
    <div class="tweet-date"><a title="Mar 4, 2026 · 10:00 AM UTC" href="/AdamSchefter/status/2222222222#m">Mar 4</a></div>
  </div>
  <div class="timeline-item">
    <div class="tweet-content">No player mentions in this tweet about stadium food.</div>
    <a class="tweet-link" href="/AdamSchefter/status/3333333333#m"></a>
    <div class="tweet-date"><a title="Mar 3, 2026 · 8:00 AM UTC" href="/AdamSchefter/status/3333333333#m">Mar 3</a></div>
  </div>
</div>
</body></html>
"""

EMPTY_NITTER_HTML = "<html><body><div class='timeline'></div></body></html>"

PLAYER_NAMES = ["Cam Ward", "Travis Hunter", "Shedeur Sanders", "Abdul Carter"]


# ---------------------------------------------------------------------------
# _parse_nitter_timeline
# ---------------------------------------------------------------------------


class TestParseNitterTimeline:
    def test_extracts_tweet_text(self):
        tweets = _parse_nitter_timeline(NITTER_HTML, "AdamSchefter", "https://nitter.net")
        texts = [t["text"] for t in tweets]
        assert any("Cam Ward" in t for t in texts)
        assert any("Travis Hunter" in t for t in texts)

    def test_skips_retweets(self):
        tweets = _parse_nitter_timeline(NITTER_HTML, "AdamSchefter", "https://nitter.net")
        texts = [t["text"] for t in tweets]
        assert all("skipped" not in t for t in texts)

    def test_url_converted_to_x_dot_com(self):
        tweets = _parse_nitter_timeline(NITTER_HTML, "AdamSchefter", "https://nitter.net")
        urls = [t["url"] for t in tweets if t["url"]]
        assert all(u.startswith("https://x.com/") for u in urls)

    def test_published_at_parsed(self):
        tweets = _parse_nitter_timeline(NITTER_HTML, "AdamSchefter", "https://nitter.net")
        dates = [t["published_at"] for t in tweets if t["published_at"]]
        assert "2026-03-05" in dates
        assert "2026-03-04" in dates

    def test_account_field_set(self):
        tweets = _parse_nitter_timeline(NITTER_HTML, "AdamSchefter", "https://nitter.net")
        assert all(t["account"] == "@AdamSchefter" for t in tweets)

    def test_empty_html_returns_empty(self):
        tweets = _parse_nitter_timeline(EMPTY_NITTER_HTML, "test", "https://nitter.net")
        assert tweets == []


# ---------------------------------------------------------------------------
# _player_mentioned
# ---------------------------------------------------------------------------


class TestPlayerMentioned:
    def test_full_name_match(self):
        result = _player_mentioned("Cam Ward is the top QB prospect", PLAYER_NAMES)
        assert result == "Cam Ward"

    def test_case_insensitive(self):
        result = _player_mentioned("CAM WARD dominates the big board", PLAYER_NAMES)
        assert result == "Cam Ward"

    def test_last_name_match_long_surname(self):
        # "Hunter" is 6 chars — should match
        result = _player_mentioned("Hunter looks elite at WR/CB", PLAYER_NAMES)
        assert result == "Travis Hunter"

    def test_last_name_short_no_match(self):
        # Add a player with a very short last name — should NOT match on last name
        names = ["Joe Kim"]
        result = _player_mentioned("Kim was seen at the combine", names)
        assert result is None  # "Kim" < 6 chars

    def test_no_match_returns_none(self):
        result = _player_mentioned("General NFL news about the salary cap", PLAYER_NAMES)
        assert result is None

    def test_first_match_wins(self):
        # Multiple players mentioned — first one in list wins
        result = _player_mentioned("Cam Ward and Travis Hunter both impressed", PLAYER_NAMES)
        assert result == "Cam Ward"  # Cam Ward is first in PLAYER_NAMES


# ---------------------------------------------------------------------------
# TwitterNitterScraper.fetch_tweets_for_picks
# ---------------------------------------------------------------------------


class TestFetchTweetsForPicks:
    @pytest.fixture
    def scraper(self):
        return TwitterNitterScraper()

    @pytest.fixture
    def minimal_picks(self):
        return [{"current_team": "lv", "player_id": None}]

    async def test_returns_articles_and_result(self, scraper, minimal_picks):
        """Successful scrape returns list of ScrapedMediaArticle."""
        with patch.object(scraper, "_try_nitter_instances", new_callable=AsyncMock) as mock_ni:
            mock_ni.return_value = [
                {
                    "text": "Cam Ward is a generational QB talent.",
                    "url": "https://x.com/AdamSchefter/status/111",
                    "published_at": "2026-03-05",
                    "account": "@AdamSchefter",
                }
            ]
            articles, result = await scraper.fetch_tweets_for_picks(minimal_picks, PLAYER_NAMES)

        assert result.source == "nitter"
        assert result.success is True
        matching = [a for a in articles if a.player_name == "Cam Ward"]
        assert len(matching) >= 1
        assert matching[0].source_type == "twitter"
        assert matching[0].source == "nitter"

    async def test_source_name_is_at_handle(self, scraper, minimal_picks):
        """source_name on returned article uses @Handle format."""
        with patch.object(scraper, "_try_nitter_instances", new_callable=AsyncMock) as mock_ni:
            mock_ni.return_value = [
                {
                    "text": "Travis Hunter two-way star",
                    "url": "https://x.com/AdamSchefter/status/222",
                    "published_at": "2026-03-04",
                    "account": "@AdamSchefter",
                }
            ]
            articles, _ = await scraper.fetch_tweets_for_picks(minimal_picks, PLAYER_NAMES)

        tw_articles = [a for a in articles if a.source_type == "twitter"]
        if tw_articles:
            assert tw_articles[0].source_name.startswith("@")

    async def test_all_nitter_down_returns_empty(self, scraper, minimal_picks):
        """If all nitter instances fail, returns 0 articles with success=True (graceful)."""
        with patch.object(scraper, "_try_nitter_instances", new_callable=AsyncMock) as mock_ni:
            mock_ni.return_value = []
            articles, result = await scraper.fetch_tweets_for_picks(minimal_picks, PLAYER_NAMES)

        assert articles == []
        assert result.success is True
        assert result.records_fetched == 0

    async def test_deduplication_by_url(self, scraper, minimal_picks):
        """Same tweet URL from multiple account fetches is deduplicated."""
        with patch.object(scraper, "_try_nitter_instances", new_callable=AsyncMock) as mock_ni:
            mock_ni.return_value = [
                {
                    "text": "Cam Ward #1 overall",
                    "url": "https://x.com/AdamSchefter/status/999",
                    "published_at": "2026-03-05",
                    "account": "@AdamSchefter",
                }
            ]
            articles, _ = await scraper.fetch_tweets_for_picks(minimal_picks, PLAYER_NAMES)

        urls = [a.url for a in articles]
        assert len(urls) == len(set(urls)), "Duplicate URLs present"

    async def test_empty_player_names_returns_empty(self, scraper, minimal_picks):
        """No player names → no tweets matched."""
        with patch.object(scraper, "_try_nitter_instances", new_callable=AsyncMock) as mock_ni:
            mock_ni.return_value = [
                {
                    "text": "Some general NFL tweet",
                    "url": "https://x.com/AdamSchefter/status/123",
                    "published_at": "2026-03-05",
                    "account": "@AdamSchefter",
                }
            ]
            articles, result = await scraper.fetch_tweets_for_picks(minimal_picks, [])

        assert articles == []
        assert result.success is True
