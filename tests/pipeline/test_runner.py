"""
Unit tests for app.pipeline.runner and app.pipeline.storage.

Uses a temporary SQLite database to avoid touching the real data/draft.db.
All scraper network calls are mocked.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.models.scrape import (
    ScrapedDraftPick,
    ScrapedProspect,
    ScrapeResult,
)


# ---------------------------------------------------------------------------
# Storage tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect all storage paths to a temporary directory."""
    monkeypatch.setattr("app.pipeline.storage._DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(
        "app.pipeline.storage._PROCESSED_DIR", tmp_path / "processed"
    )
    (tmp_path / "processed").mkdir()
    from app.pipeline import storage
    storage.init_db()
    return tmp_path


def test_init_db_creates_tables(tmp_db: Path):
    """Expected: init_db creates all required tables."""
    from app.pipeline.storage import _DB_PATH
    conn = sqlite3.connect(str(_DB_PATH))
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()
    assert "prospects" in tables
    assert "draft_picks" in tables
    assert "team_needs" in tables
    assert "mock_draft" in tables
    assert "scrape_log" in tables


def test_upsert_prospects_basic(tmp_db: Path):
    """Expected: prospects are inserted and retrievable."""
    from app.pipeline import storage

    records = [
        ScrapedProspect(
            name="Cam Ward",
            position="QB",
            college="Miami",
            rank=1,
            grade=8.5,
            source="espn",
            source_url="https://espn.com",
        )
    ]
    count = storage.upsert_prospects(records)
    assert count == 1

    from app.pipeline.storage import _DB_PATH
    conn = sqlite3.connect(str(_DB_PATH))
    row = conn.execute("SELECT name, rank FROM prospects").fetchone()
    conn.close()
    assert row[0] == "Cam Ward"
    assert row[1] == 1


def test_upsert_prospects_idempotent(tmp_db: Path):
    """Edge case: upserting the same prospect twice does not duplicate it."""
    from app.pipeline import storage

    record = ScrapedProspect(
        name="Cam Ward",
        position="QB",
        college="Miami",
        rank=1,
        source="espn",
        source_url="https://espn.com",
    )
    storage.upsert_prospects([record])
    storage.upsert_prospects([record])

    from app.pipeline.storage import _DB_PATH
    conn = sqlite3.connect(str(_DB_PATH))
    count = conn.execute("SELECT COUNT(*) FROM prospects").fetchone()[0]
    conn.close()
    assert count == 1


def test_upsert_draft_picks_basic(tmp_db: Path):
    """Expected: draft picks inserted and retrievable by pick_number."""
    from app.pipeline import storage

    picks = [
        ScrapedDraftPick(
            pick_number=1,
            round=1,
            pick_in_round=1,
            team="TEN",
            source="tankathon",
            source_url="https://tankathon.com",
        )
    ]
    count = storage.upsert_draft_picks(picks)
    assert count == 1


def test_log_scrape_result(tmp_db: Path):
    """Expected: scrape results are logged with correct source and status."""
    from app.pipeline import storage

    result = ScrapeResult(source="espn", success=True, records_fetched=42)
    storage.log_scrape_result(result)

    timestamps = storage.get_last_run_timestamps()
    assert "espn" in timestamps
    assert timestamps["espn"] is not None


def test_upsert_empty_list_is_noop(tmp_db: Path):
    """Edge case: upserting an empty list returns 0 and does not error."""
    from app.pipeline import storage

    count = storage.upsert_prospects([])
    assert count == 0


# ---------------------------------------------------------------------------
# Runner tests (mocked scrapers)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_pipeline_unknown_source(tmp_db: Path, monkeypatch: pytest.MonkeyPatch):
    """Failure case: unknown source is silently skipped, returns no results."""
    from app.pipeline.runner import run_pipeline

    results = await run_pipeline(sources=["nonexistent_source"])
    assert results == []


@pytest.mark.asyncio
async def test_run_pipeline_espn_mocked(tmp_db: Path, monkeypatch: pytest.MonkeyPatch):
    """Expected: ESPN scraper results are persisted and returned."""
    from app.pipeline import runner

    mock_prospect = ScrapedProspect(
        name="Cam Ward",
        position="QB",
        college="Miami",
        rank=1,
        source="espn",
        source_url="https://espn.com",
    )
    mock_result = ScrapeResult(source="espn", success=True, records_fetched=1)

    with patch(
        "app.pipeline.runner.ESPNScraper.fetch_prospects",
        new=AsyncMock(return_value=([mock_prospect], mock_result)),
    ):
        results = await runner.run_pipeline(sources=["espn"])

    assert len(results) == 1
    assert results[0].source == "espn"
    assert results[0].success is True
    assert results[0].records_fetched == 1
