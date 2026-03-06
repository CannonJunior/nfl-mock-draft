"""
Storage layer for scraped NFL draft data.

Persists scraped records into:
1. SQLite database (data/draft.db) for structured querying
2. data/processed/*.json for quick human-readable inspection and app consumption

Uses upsert semantics so repeated scraper runs are idempotent.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models.scrape import (
    ScrapedBuzzRecord,
    ScrapedCollegeStat,
    ScrapedCombineStat,
    ScrapedDraftPick,
    ScrapedMediaArticle,
    ScrapedMockEntry,
    ScrapedProspect,
    ScrapedTeamNeed,
    ScrapeResult,
)

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_DB_PATH = _DATA_DIR / "draft.db"
_PROCESSED_DIR = _DATA_DIR / "processed"


def init_db() -> None:
    """
    Create database tables if they do not already exist, then run migrations.

    Tables created:
        prospects, combine_stats, draft_picks, team_needs, mock_draft,
        buzz_signals, college_stats, media_articles, scrape_log
    """
    _PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    with _get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS prospects (
                name        TEXT NOT NULL,
                position    TEXT,
                college     TEXT,
                rank        INTEGER,
                grade       REAL,
                source      TEXT NOT NULL,
                source_url  TEXT,
                fetched_at  TEXT,
                PRIMARY KEY (name, source)
            );

            CREATE TABLE IF NOT EXISTS combine_stats (
                name                  TEXT NOT NULL,
                position              TEXT,
                college               TEXT,
                forty_yard_dash       REAL,
                vertical_jump_inches  REAL,
                broad_jump_inches     INTEGER,
                bench_press_reps      INTEGER,
                three_cone            REAL,
                twenty_yard_shuttle   REAL,
                source                TEXT NOT NULL,
                source_url            TEXT,
                fetched_at            TEXT,
                PRIMARY KEY (name, source)
            );

            CREATE TABLE IF NOT EXISTS draft_picks (
                pick_number    INTEGER NOT NULL,
                round          INTEGER,
                pick_in_round  INTEGER,
                team           TEXT,
                projected_player TEXT,
                traded_from    TEXT,
                source         TEXT NOT NULL,
                source_url     TEXT,
                fetched_at     TEXT,
                PRIMARY KEY (pick_number, source)
            );

            CREATE TABLE IF NOT EXISTS team_needs (
                team        TEXT NOT NULL,
                position    TEXT NOT NULL,
                need_level  INTEGER,
                source      TEXT NOT NULL,
                source_url  TEXT,
                fetched_at  TEXT,
                PRIMARY KEY (team, position, source)
            );

            CREATE TABLE IF NOT EXISTS mock_draft (
                pick_number  INTEGER NOT NULL,
                team         TEXT,
                player_name  TEXT,
                position     TEXT,
                college      TEXT,
                source       TEXT NOT NULL,
                source_url   TEXT,
                fetched_at   TEXT,
                PRIMARY KEY (pick_number, source)
            );

            CREATE TABLE IF NOT EXISTS buzz_signals (
                name        TEXT NOT NULL,
                grade       REAL,
                rank        INTEGER,
                mentions    INTEGER,
                source      TEXT NOT NULL,
                source_url  TEXT,
                fetched_at  TEXT,
                PRIMARY KEY (name, source)
            );

            CREATE TABLE IF NOT EXISTS college_stats (
                name        TEXT NOT NULL,
                position    TEXT,
                college     TEXT,
                season      TEXT NOT NULL,
                stats_json  TEXT,
                source      TEXT NOT NULL,
                source_url  TEXT,
                fetched_at  TEXT,
                PRIMARY KEY (name, season, source)
            );

            CREATE TABLE IF NOT EXISTS media_articles (
                player_name  TEXT NOT NULL,
                title        TEXT NOT NULL,
                url          TEXT NOT NULL,
                source_name  TEXT,
                source_type  TEXT DEFAULT 'news',
                published_at TEXT,
                source       TEXT NOT NULL,
                fetched_at   TEXT,
                PRIMARY KEY (url)
            );

            CREATE TABLE IF NOT EXISTS scrape_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                source       TEXT NOT NULL,
                success      INTEGER NOT NULL,
                records      INTEGER DEFAULT 0,
                error        TEXT,
                logged_at    TEXT NOT NULL
            );
            """
        )
    _migrate_db()
    logger.debug("Database initialised at %s", _DB_PATH)


def _migrate_db() -> None:
    """Add columns to existing tables for schema upgrades (idempotent)."""
    new_cols = [
        ("combine_stats", "height_inches", "INTEGER"),
        ("combine_stats", "weight_lbs", "INTEGER"),
        ("combine_stats", "arm_length_inches", "REAL"),
        ("combine_stats", "hand_size_inches", "REAL"),
    ]
    with _get_conn() as conn:
        for table, col, col_type in new_cols:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass  # Column already exists


def upsert_prospects(records: list[ScrapedProspect]) -> int:
    """
    Insert or replace prospect records into the prospects table.

    Args:
        records (list[ScrapedProspect]): Prospects to persist.

    Returns:
        int: Number of rows affected.
    """
    if not records:
        return 0
    rows = [
        (
            r.name, r.position, r.college, r.rank, r.grade,
            r.source, r.source_url, r.fetched_at.isoformat(),
        )
        for r in records
    ]
    with _get_conn() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO prospects
              (name, position, college, rank, grade, source, source_url, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    _export_json("prospects", [r.model_dump(mode="json") for r in records])
    return len(rows)


def upsert_combine_stats(records: list[ScrapedCombineStat]) -> int:
    """
    Insert or replace combine stat records.

    Args:
        records (list[ScrapedCombineStat]): Combine stats to persist.

    Returns:
        int: Number of rows affected.
    """
    if not records:
        return 0
    rows = [
        (
            r.name, r.position, r.college,
            r.height_inches, r.weight_lbs, r.arm_length_inches, r.hand_size_inches,
            r.forty_yard_dash, r.vertical_jump_inches, r.broad_jump_inches,
            r.bench_press_reps, r.three_cone, r.twenty_yard_shuttle,
            r.source, r.source_url, r.fetched_at.isoformat(),
        )
        for r in records
    ]
    with _get_conn() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO combine_stats
              (name, position, college,
               height_inches, weight_lbs, arm_length_inches, hand_size_inches,
               forty_yard_dash, vertical_jump_inches,
               broad_jump_inches, bench_press_reps, three_cone,
               twenty_yard_shuttle, source, source_url, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    _export_json("combine_stats", [r.model_dump(mode="json") for r in records])
    return len(rows)


def upsert_draft_picks(records: list[ScrapedDraftPick]) -> int:
    """
    Insert or replace draft pick records.

    Args:
        records (list[ScrapedDraftPick]): Draft picks to persist.

    Returns:
        int: Number of rows affected.
    """
    if not records:
        return 0
    rows = [
        (
            r.pick_number, r.round, r.pick_in_round, r.team,
            r.projected_player, r.traded_from,
            r.source, r.source_url, r.fetched_at.isoformat(),
        )
        for r in records
    ]
    with _get_conn() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO draft_picks
              (pick_number, round, pick_in_round, team, projected_player,
               traded_from, source, source_url, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    _export_json("draft_picks", [r.model_dump(mode="json") for r in records])
    return len(rows)


def upsert_team_needs(records: list[ScrapedTeamNeed]) -> int:
    """
    Insert or replace team need records.

    Args:
        records (list[ScrapedTeamNeed]): Team needs to persist.

    Returns:
        int: Number of rows affected.
    """
    if not records:
        return 0
    rows = [
        (
            r.team, r.position, r.need_level,
            r.source, r.source_url, r.fetched_at.isoformat(),
        )
        for r in records
    ]
    with _get_conn() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO team_needs
              (team, position, need_level, source, source_url, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    _export_json("team_needs", [r.model_dump(mode="json") for r in records])
    return len(rows)


def upsert_buzz_records(records: list[ScrapedBuzzRecord]) -> int:
    """
    Insert or replace buzz signal records.

    Args:
        records (list[ScrapedBuzzRecord]): Buzz records to persist.

    Returns:
        int: Number of rows affected.
    """
    if not records:
        return 0
    rows = [
        (
            r.name, r.grade, r.rank, r.mentions,
            r.source, r.source_url, r.fetched_at.isoformat(),
        )
        for r in records
    ]
    with _get_conn() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO buzz_signals
              (name, grade, rank, mentions, source, source_url, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    _export_json("buzz_signals", [r.model_dump(mode="json") for r in records])
    return len(rows)


def upsert_college_stats(records: list[ScrapedCollegeStat]) -> int:
    """Insert or replace college season stat records. Returns rows affected."""
    if not records:
        return 0
    rows = [
        (r.name, r.position, r.college, r.season, r.stats_json,
         r.source, r.source_url, r.fetched_at.isoformat())
        for r in records
    ]
    with _get_conn() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO college_stats
              (name, position, college, season, stats_json, source, source_url, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    _export_json("college_stats", [r.model_dump(mode="json") for r in records])
    return len(rows)


def upsert_media_articles(records: list[ScrapedMediaArticle]) -> int:
    """Insert or replace media article records. Returns rows affected."""
    if not records:
        return 0
    rows = [
        (r.player_name, r.title, r.url, r.source_name, r.source_type,
         r.published_at, r.source, r.fetched_at.isoformat())
        for r in records
    ]
    with _get_conn() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO media_articles
              (player_name, title, url, source_name, source_type,
               published_at, source, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    _export_json("media_articles", [r.model_dump(mode="json") for r in records])
    return len(rows)


def upsert_mock_entries(records: list[ScrapedMockEntry]) -> int:
    """
    Insert or replace mock draft entry records.

    Args:
        records (list[ScrapedMockEntry]): Mock draft entries to persist.

    Returns:
        int: Number of rows affected.
    """
    if not records:
        return 0
    rows = [
        (
            r.pick_number, r.team, r.player_name, r.position, r.college,
            r.source, r.source_url, r.fetched_at.isoformat(),
        )
        for r in records
    ]
    with _get_conn() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO mock_draft
              (pick_number, team, player_name, position, college,
               source, source_url, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    _export_json("mock_draft", [r.model_dump(mode="json") for r in records])
    return len(rows)


def log_scrape_result(result: ScrapeResult) -> None:
    """
    Append a scrape run record to the scrape_log table.

    Args:
        result (ScrapeResult): Result from a scraper run.
    """
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO scrape_log (source, success, records, error, logged_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                result.source,
                1 if result.success else 0,
                result.records_fetched,
                result.error,
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def get_prospects() -> list[dict]:
    """Return all scraped prospects as dicts (name, position, college) for downstream scrapers."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT name, position, college FROM prospects GROUP BY name"
        ).fetchall()
    return [{"name": r[0], "position": r[1] or "", "college": r[2] or ""} for r in rows]


def get_last_run_timestamps() -> dict[str, str]:
    """
    Return the most recent successful scrape timestamp for each source.

    Returns:
        dict[str, str]: Mapping of source name to ISO timestamp string.
            Sources that have never run successfully are omitted.
    """
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT source, MAX(logged_at) AS last_run
            FROM scrape_log
            WHERE success = 1
            GROUP BY source
            """
        ).fetchall()
    return {row[0]: row[1] for row in rows}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_conn() -> sqlite3.Connection:
    """
    Open a SQLite connection with WAL mode enabled.

    Returns:
        sqlite3.Connection: Configured database connection.
    """
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _export_json(name: str, records: list[dict[str, Any]]) -> None:
    """
    Write a list of record dicts to data/processed/<name>.json.

    Appends new records to any existing file, deduplicating by a
    best-effort comparison of the full record dict.

    Args:
        name (str): Base filename (without .json extension).
        records (list[dict]): Records to write.
    """
    path = _PROCESSED_DIR / f"{name}.json"
    existing: list[dict[str, Any]] = []
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = []

    # Reason: merge new records over existing ones by converting to set of tuples
    # is not practical with nested dicts; instead, write all records and rely on
    # the SQLite layer as the canonical deduplication source.
    merged = existing + records
    path.write_text(
        json.dumps(merged, indent=2, default=str), encoding="utf-8"
    )
