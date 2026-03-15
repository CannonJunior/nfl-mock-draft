"""
Live draft order sync module for the NFL Mock Draft 2026 prediction pipeline.

Fetches Tankathon's current full draft order and compares against picks.json,
auto-detecting and applying pick-ownership changes (trades, rescissions, etc.)
without requiring manual updates to known_trades.json.

Called during Phase 0 of POST /api/predictions/run so that pick ownership is
always current before the simulation executes.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_PICKS_PATH = _DATA_DIR / "picks.json"
_TEAM_NAME_MAP_PATH = _DATA_DIR / "config" / "team_name_map.json"

# Picks above this number are compensatory or provisional — skip them because
# Tankathon may not list them consistently until officially announced.
_MAX_SYNC_PICK = 96


def _load_team_name_map() -> dict[str, str]:
    """
    Load the full-name → abbreviation mapping from team_name_map.json.

    Returns:
        dict[str, str]: Maps team name variants to 2-3 letter abbreviations
            (e.g. "Baltimore Ravens" → "bal", "Baltimore" → "bal").
            Returns empty dict on load failure.
    """
    if not _TEAM_NAME_MAP_PATH.exists():
        logger.warning("team_name_map.json not found at %s", _TEAM_NAME_MAP_PATH)
        return {}
    try:
        with open(_TEAM_NAME_MAP_PATH, "r", encoding="utf-8") as f:
            raw: dict[str, str] = json.load(f)
        # Normalise all keys to lowercase for case-insensitive lookup
        return {k.lower(): v.lower() for k, v in raw.items()}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load team_name_map.json: %s", exc)
        return {}


def _resolve_team_abbrev(team_name: str, name_map: dict[str, str]) -> Optional[str]:
    """
    Convert a Tankathon team name to our 2-3 letter abbreviation.

    Tries full name first, then city/nickname only, then abbreviation passthrough.

    Args:
        team_name (str): Team name as returned by Tankathon (e.g. "Baltimore Ravens").
        name_map (dict[str, str]): Lowercased name → abbreviation map.

    Returns:
        Optional[str]: Lowercase abbreviation (e.g. "bal"), or None if not found.
    """
    if not team_name:
        return None
    key = team_name.strip().lower()
    if key in name_map:
        return name_map[key]
    # Try just the first word (city name, e.g. "Baltimore")
    first_word = key.split()[0] if key else ""
    if first_word in name_map:
        return name_map[first_word]
    # Short abbreviations are already 2-3 chars (e.g. "LV" from mock-row img alt)
    if len(key) <= 3:
        return key
    return None


def apply_draft_order_changes(
    tankathon_picks: list[dict],
    picks_data: dict,
    name_map: dict[str, str],
) -> int:
    """
    Compare Tankathon pick ownership against picks.json and apply any changes.

    For each pick in tankathon_picks (up to _MAX_SYNC_PICK):
    - Resolve the Tankathon team name to an abbreviation.
    - If the abbreviation differs from the current owner in picks.json, update
      current_team and append the old owner to the traded_from chain.

    Args:
        tankathon_picks (list[dict]): Raw ScrapedDraftPick-like dicts with
            "pick_number" and "team" keys.
        picks_data (dict): Parsed picks.json contents (mutated in place).
        name_map (dict[str, str]): Lowercased name → abbreviation map.

    Returns:
        int: Number of pick rows changed.
    """
    picks_by_number: dict[int, dict] = {
        p["pick_number"]: p for p in picks_data.get("picks", [])
    }

    modified = 0
    for scraped in tankathon_picks:
        pick_num: int = scraped.get("pick_number", 0)
        if pick_num < 1 or pick_num > _MAX_SYNC_PICK:
            continue

        team_name: str = scraped.get("team", "")
        new_team = _resolve_team_abbrev(team_name, name_map)
        if not new_team:
            logger.debug(
                "Pick #%d: could not resolve team name %r — skipping", pick_num, team_name
            )
            continue

        pick = picks_by_number.get(pick_num)
        if pick is None:
            logger.debug("Pick #%d not found in picks.json — skipping", pick_num)
            continue

        old_team = pick.get("current_team", "")
        if old_team == new_team:
            continue  # No change needed

        # Ownership has changed — update and record the chain
        pick["current_team"] = new_team
        traded_from: list = pick.setdefault("traded_from", [])
        if old_team and old_team not in traded_from:
            traded_from.append(old_team)

        pick["trade_notes"] = (
            f"Auto-detected: {old_team.upper()} → {new_team.upper()} "
            f"(synced from Tankathon on refresh)"
        )
        logger.info(
            "Pick #%d ownership synced: %s → %s", pick_num, old_team, new_team
        )
        modified += 1

    return modified


async def sync_draft_order() -> int:
    """
    Fetch Tankathon's live draft order and apply any ownership changes to picks.json.

    This is the main entry point called from Phase 0 of the predictions pipeline.
    Failures are caught and logged; a failed sync returns 0 so the pipeline
    continues normally on the existing picks.json data.

    Returns:
        int: Number of pick ownership changes applied; 0 on failure or no changes.
    """
    from app.scrapers.tankathon import TankathonScraper

    name_map = _load_team_name_map()
    if not name_map:
        logger.warning("Team name map empty — draft order sync skipped")
        return 0

    scraper = TankathonScraper()
    try:
        scraped_picks, result = await scraper.fetch_draft_order()
    except Exception as exc:
        logger.warning("Draft order fetch failed (non-fatal): %s", exc)
        return 0

    if not result.success or not scraped_picks:
        logger.info(
            "Draft order sync: no picks returned (success=%s)", result.success
        )
        return 0

    if not _PICKS_PATH.exists():
        logger.warning("picks.json not found — cannot sync draft order")
        return 0

    with open(_PICKS_PATH, "r", encoding="utf-8") as f:
        picks_data = json.load(f)

    # Convert ScrapedDraftPick objects to dicts for apply_draft_order_changes
    tankathon_dicts = [
        {"pick_number": p.pick_number, "team": p.team} for p in scraped_picks
    ]

    modified = apply_draft_order_changes(tankathon_dicts, picks_data, name_map)

    if modified:
        _PICKS_PATH.write_text(
            json.dumps(picks_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(
            "Draft order sync complete: %d pick(s) updated from Tankathon", modified
        )
    else:
        logger.debug("Draft order sync: no changes detected")

    return modified
