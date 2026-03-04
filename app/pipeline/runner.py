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
import sys
from typing import Optional

from app.models.scrape import ScrapeResult
from app.pipeline import storage
from app.scrapers.espn import ESPNScraper
from app.scrapers.nfl_com import NFLComScraper
from app.scrapers.sharp import SharpScraper
from app.scrapers.tankathon import TankathonScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

# All valid source identifiers
ALL_SOURCES = ["tankathon", "espn", "nfl", "sharp"]


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
