"""
Pipeline runner for NFL mock draft web data ingestion.

Orchestrates all scrapers and persists results to SQLite and JSON.
Can be invoked as a CLI:

    uv run -m app.pipeline.runner --source all
    uv run -m app.pipeline.runner --source tankathon
    uv run -m app.pipeline.runner --source espn,nfl

Or called programmatically from the FastAPI route:

    from app.pipeline.runner import run_pipeline
    results = await run_pipeline(sources=["tankathon", "espn"])
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from typing import Optional

from app.models.scrape import ScrapeResult
from app.pipeline import storage
from app.scrapers.college_stats import CollegeStatsScraper
from app.scrapers.draft_countdown import DraftCountdownScraper
from app.scrapers.espn import ESPNScraper
from app.scrapers.espn_mock import ESPNMockScraper
from app.scrapers.news import NewsScraper
from app.scrapers.nfl_com import NFLComScraper
from app.scrapers.nfl_mock import NFLMockScraper
from app.scrapers.sharp import SharpScraper
from app.scrapers.social import SocialScraper
from app.scrapers.tankathon import TankathonScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

# All valid source identifiers
ALL_SOURCES = [
    "tankathon", "espn", "nfl", "sharp",
    "nfl_mock", "espn_mock", "social",
    "college_stats", "news", "draft_countdown",
]


async def run_pipeline(
    sources: Optional[list[str]] = None,
) -> list[ScrapeResult]:
    """
    Run the data ingestion pipeline for the specified sources.

    Scrapers run sequentially to avoid hammering target sites.
    The database is initialised before any scraping begins.

    Args:
        sources (Optional[list[str]]): Source identifiers to run.
            Defaults to all sources if None or ["all"].

    Returns:
        list[ScrapeResult]: One result object per scraper operation
            (a source that runs multiple operations returns multiple results).
    """
    storage.init_db()

    if not sources or sources == ["all"]:
        sources = ALL_SOURCES

    # Validate source names
    unknown = [s for s in sources if s not in ALL_SOURCES]
    if unknown:
        logger.warning("Unknown sources (ignored): %s", unknown)
        sources = [s for s in sources if s in ALL_SOURCES]

    results: list[ScrapeResult] = []

    for source in sources:
        logger.info("=== Running scraper: %s ===", source)
        source_results = await _run_source(source)
        results.extend(source_results)
        for r in source_results:
            storage.log_scrape_result(r)
            status = "OK" if r.success else "FAILED"
            logger.info(
                "[%s] %s — %d records%s",
                r.source,
                status,
                r.records_fetched,
                f" — {r.error}" if r.error else "",
            )

    return results


async def _run_source(source: str) -> list[ScrapeResult]:
    """
    Dispatch a single named source to its scraper and persist results.

    Args:
        source (str): Source identifier from ALL_SOURCES.

    Returns:
        list[ScrapeResult]: Results from all operations for this source.
    """
    results: list[ScrapeResult] = []

    if source == "tankathon":
        scraper = TankathonScraper()

        picks, r1 = await scraper.fetch_draft_order()
        if picks:
            storage.upsert_draft_picks(picks)
        results.append(r1)

        needs, r2 = await scraper.fetch_team_needs()
        if needs:
            storage.upsert_team_needs(needs)
        results.append(r2)

        mock, r3 = await scraper.fetch_mock_draft()
        if mock:
            storage.upsert_mock_entries(mock)
        results.append(r3)

    elif source == "espn":
        scraper = ESPNScraper()
        prospects, r = await scraper.fetch_prospects()
        if prospects:
            storage.upsert_prospects(prospects)
        results.append(r)

    elif source == "nfl":
        scraper = NFLComScraper()
        combine_stats, r = await scraper.fetch_combine_stats()
        if combine_stats:
            storage.upsert_combine_stats(combine_stats)
        results.append(r)

    elif source == "sharp":
        scraper = SharpScraper()
        analytics, r = await scraper.fetch_team_analytics()
        # Reason: TeamAnalytics is stored only in processed JSON for now;
        # a dedicated table can be added if querying is needed later.
        if analytics:
            from app.pipeline.storage import _export_json
            _export_json("team_analytics", [a.model_dump(mode="json") for a in analytics])
        results.append(r)

    elif source == "nfl_mock":
        scraper = NFLMockScraper()
        mock, r = await scraper.fetch_mock_draft()
        if mock:
            storage.upsert_mock_entries(mock)
        results.append(r)

    elif source == "espn_mock":
        scraper = ESPNMockScraper()
        mock, r = await scraper.fetch_mock_draft()
        if mock:
            storage.upsert_mock_entries(mock)
        results.append(r)

    elif source == "social":
        scraper = SocialScraper()

        tdn_records, r1 = await scraper.fetch_tdn_board()
        if tdn_records:
            storage.upsert_buzz_records(tdn_records)
        results.append(r1)

        reddit_records, r2 = await scraper.fetch_reddit_buzz()
        if reddit_records:
            storage.upsert_buzz_records(reddit_records)
        results.append(r2)

    elif source == "college_stats":
        players = storage.get_prospects()
        if not players:
            logger.warning("[college_stats] No prospects in DB — run espn source first")
            results.append(ScrapeResult(
                source="nfl_prospects", success=False,
                error="No prospects in DB to scrape stats for",
            ))
        else:
            # Derive player_id (URL slug) from name
            for p in players:
                slug = re.sub(r"[^\w\s-]", "", p["name"].lower())
                p["player_id"] = re.sub(r"[\s_]+", "-", slug).strip("-")
            scraper = CollegeStatsScraper()
            stats, r = await scraper.fetch_stats_for_pool(players)
            if stats:
                storage.upsert_college_stats(stats)
            results.append(r)

    elif source == "draft_countdown":
        scraper = DraftCountdownScraper()
        combine_stats, r = await scraper.fetch_combine_stats()
        if combine_stats:
            storage.upsert_combine_stats(combine_stats)
        results.append(r)

    elif source == "news":
        players = storage.get_prospects()
        if not players:
            logger.warning("[news] No prospects in DB — run espn source first")
            results.append(ScrapeResult(
                source="google_news", success=False,
                error="No prospects in DB to fetch news for",
            ))
        else:
            scraper = NewsScraper()
            articles, r = await scraper.fetch_articles_for_pool(players)
            if articles:
                storage.upsert_media_articles(articles)
            results.append(r)

    return results


def _parse_args() -> argparse.Namespace:
    """
    Parse CLI arguments for the pipeline runner.

    Returns:
        argparse.Namespace: Parsed arguments with a `source` attribute.
    """
    parser = argparse.ArgumentParser(
        description="NFL Mock Draft data ingestion pipeline"
    )
    parser.add_argument(
        "--source",
        default="all",
        help=(
            "Comma-separated list of sources to run, or 'all'. "
            f"Valid sources: {', '.join(ALL_SOURCES)}"
        ),
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    requested = [s.strip() for s in args.source.split(",")]
    final_results = asyncio.run(run_pipeline(sources=requested))

    # Print summary table
    print("\n--- Pipeline Summary ---")
    for r in final_results:
        status_icon = "✓" if r.success else "✗"
        print(
            f"{status_icon} {r.source:<12} "
            f"{r.records_fetched:>4} records  "
            f"{r.fetched_at.strftime('%H:%M:%S') if r.fetched_at else ''}"
            + (f"  ERROR: {r.error}" if r.error else "")
        )

    # Exit with non-zero code if any scraper failed
    failed = [r for r in final_results if not r.success]
    sys.exit(1 if failed else 0)
