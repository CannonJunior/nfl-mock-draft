"""
Pydantic models for web-scraped NFL draft data.

These models represent the raw output of each scraper before being
merged into the canonical data files (data/players.json, data/picks.json).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class ScrapedProspect(BaseModel):
    """
    A draft prospect as returned by a scraper.

    Attributes:
        name (str): Full player name.
        position (str): Position code (e.g. "QB", "WR").
        college (str): College or university name.
        rank (Optional[int]): Big board rank from this source.
        grade (Optional[float]): Numeric prospect grade if available.
        source (str): Which scraper produced this record (e.g. "espn", "tankathon").
        source_url (str): URL that was scraped.
        fetched_at (datetime): Timestamp of the fetch.
    """

    name: str
    position: str
    college: str
    rank: Optional[int] = None
    grade: Optional[float] = None
    source: str
    source_url: str
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ScrapedCombineStat(BaseModel):
    """
    NFL Combine measurements for a single player.

    Attributes:
        name (str): Player name (used to match to ScrapedProspect).
        position (str): Position code.
        college (str): College name.
        forty_yard_dash (Optional[float]): 40-yard dash time in seconds.
        vertical_jump_inches (Optional[float]): Vertical jump in inches.
        broad_jump_inches (Optional[int]): Broad jump in inches.
        bench_press_reps (Optional[int]): 225 lb bench press reps.
        three_cone (Optional[float]): 3-cone drill time in seconds.
        twenty_yard_shuttle (Optional[float]): 20-yard shuttle time.
        source (str): Scraper source identifier.
        source_url (str): URL that was scraped.
        fetched_at (datetime): Timestamp of the fetch.
    """

    name: str
    position: str
    college: str
    forty_yard_dash: Optional[float] = None
    vertical_jump_inches: Optional[float] = None
    broad_jump_inches: Optional[int] = None
    bench_press_reps: Optional[int] = None
    three_cone: Optional[float] = None
    twenty_yard_shuttle: Optional[float] = None
    source: str
    source_url: str
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ScrapedDraftPick(BaseModel):
    """
    A draft pick slot as scraped from Tankathon or NFL.com.

    Attributes:
        pick_number (int): Overall pick number.
        round (int): Round number.
        pick_in_round (int): Pick number within the round.
        team (str): Team abbreviation or name holding the pick.
        projected_player (Optional[str]): Player name projected at this slot.
        traded_from (Optional[str]): Original team if traded.
        source (str): Scraper source identifier.
        source_url (str): URL that was scraped.
        fetched_at (datetime): Timestamp of the fetch.
    """

    pick_number: int
    round: int
    pick_in_round: int
    team: str
    projected_player: Optional[str] = None
    traded_from: Optional[str] = None
    source: str
    source_url: str
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ScrapedTeamNeed(BaseModel):
    """
    A team's positional need rating from Tankathon.

    Attributes:
        team (str): Team abbreviation or name.
        position (str): Position code (e.g. "QB", "OT").
        need_level (int): Need rating 1-5 (5 = critical need).
        source (str): Scraper source identifier.
        source_url (str): URL that was scraped.
        fetched_at (datetime): Timestamp of the fetch.
    """

    team: str
    position: str
    need_level: int
    source: str
    source_url: str
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ScrapedMockEntry(BaseModel):
    """
    A single pick in a consensus mock draft.

    Attributes:
        pick_number (int): Overall pick number.
        team (str): Team name or abbreviation.
        player_name (str): Projected player name.
        position (str): Player position.
        college (str): Player college.
        source (str): Scraper source identifier.
        source_url (str): URL that was scraped.
        fetched_at (datetime): Timestamp of the fetch.
    """

    pick_number: int
    team: str
    player_name: str
    position: str
    college: str
    source: str
    source_url: str
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ScrapeResult(BaseModel):
    """
    Summary result returned by a scraper run.

    Attributes:
        source (str): Scraper identifier.
        success (bool): Whether the scrape completed without errors.
        records_fetched (int): Number of records returned.
        error (Optional[str]): Error message if success=False.
        fetched_at (datetime): Timestamp of the run.
    """

    source: str
    success: bool
    records_fetched: int = 0
    error: Optional[str] = None
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
