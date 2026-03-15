"""
Trade detection module for the NFL Mock Draft 2026 prediction pipeline.

Reads data/config/known_trades.json and applies confirmed trade changes to
data/picks.json before the simulation runs. This ensures pick ownership and
traded_from chains stay accurate without relying on brittle news scraping.

To record a new trade, add an entry to data/config/known_trades.json:
    {
        "pick_number": 5,
        "new_current_team": "dal",
        "traded_from_append": "nyg",
        "trade_notes": "Pick acquired in exchange for ...",
        "confirmed_date": "2026-03-01"
    }

apply_trades_to_picks() is idempotent: re-running after a pick is already
updated will not duplicate entries in the traded_from chain.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_PICKS_PATH = _DATA_DIR / "picks.json"
_TRADES_PATH = _DATA_DIR / "config" / "known_trades.json"


class TradeUpdate:
    """
    Represents a single confirmed pick-ownership change.

    Attributes:
        pick_number (int): The overall pick number affected.
        new_current_team (str): Team abbreviation now holding the pick.
        traded_from_append (Optional[str]): Abbreviation of the previous owner
            to push into the traded_from chain. Defaults to the current owner
            read from picks.json if not explicitly specified.
        trade_notes (Optional[str]): Human-readable trade description for the UI.
        confirmed_date (Optional[str]): ISO date string when the trade was confirmed.
    """

    def __init__(
        self,
        pick_number: int,
        new_current_team: str,
        traded_from_append: Optional[str] = None,
        trade_notes: Optional[str] = None,
        confirmed_date: Optional[str] = None,
    ) -> None:
        self.pick_number = pick_number
        self.new_current_team = new_current_team.strip().lower()
        self.traded_from_append = traded_from_append.strip().lower() if traded_from_append else None
        self.trade_notes = trade_notes
        self.confirmed_date = confirmed_date


def load_known_trades() -> list[TradeUpdate]:
    """
    Load and parse the known_trades.json configuration file.

    Skips malformed entries with a warning rather than failing completely.

    Returns:
        list[TradeUpdate]: All configured trade updates; empty list if the
            file does not exist or contains no trades.
    """
    if not _TRADES_PATH.exists():
        logger.debug("known_trades.json not found — no trades to apply")
        return []

    try:
        with open(_TRADES_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load known_trades.json: %s", exc)
        return []

    trades: list[TradeUpdate] = []
    for entry in raw.get("trades", []):
        try:
            trades.append(
                TradeUpdate(
                    pick_number=int(entry["pick_number"]),
                    new_current_team=str(entry["new_current_team"]),
                    traded_from_append=entry.get("traded_from_append"),
                    trade_notes=entry.get("trade_notes"),
                    confirmed_date=entry.get("confirmed_date"),
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("Skipping malformed trade entry %r: %s", entry, exc)

    logger.info("Loaded %d trade entry(ies) from known_trades.json", len(trades))
    return trades


def apply_trades_to_picks(trades: list[TradeUpdate]) -> int:
    """
    Apply trade updates to data/picks.json in place.

    For each trade:
    - Updates ``current_team`` to the new owner.
    - Appends ``traded_from_append`` (or the old owner) to the pick's
      ``traded_from`` list, avoiding duplicates on re-runs.
    - Writes ``trade_notes`` onto the pick when provided.

    Only modifies picks whose ``current_team`` actually differs from the
    configured ``new_current_team``, making this safe to re-run repeatedly.

    Args:
        trades (list[TradeUpdate]): Trade updates to apply.

    Returns:
        int: Number of pick rows actually changed and written.
    """
    if not trades:
        return 0

    if not _PICKS_PATH.exists():
        logger.warning("picks.json not found — cannot apply trades")
        return 0

    with open(_PICKS_PATH, "r", encoding="utf-8") as f:
        picks_data = json.load(f)

    picks_by_number: dict[int, dict] = {
        p["pick_number"]: p for p in picks_data.get("picks", [])
    }

    modified = 0
    for trade in trades:
        pick = picks_by_number.get(trade.pick_number)
        if pick is None:
            logger.warning(
                "Trade references pick #%d — not found in picks.json", trade.pick_number
            )
            continue

        # Reason: only apply when ownership has actually changed — prevents
        # re-running from accumulating duplicate traded_from entries.
        if pick.get("current_team") == trade.new_current_team:
            logger.debug("Pick #%d already owned by %s — skipping", trade.pick_number, trade.new_current_team)
            continue

        old_team = pick["current_team"]
        pick["current_team"] = trade.new_current_team

        # Append the prior owner to the trade chain
        append_team = trade.traded_from_append or old_team
        traded_from = pick.setdefault("traded_from", [])
        if append_team not in traded_from:
            traded_from.append(append_team)

        if trade.trade_notes:
            pick["trade_notes"] = trade.trade_notes

        logger.info(
            "Pick #%d: %s → %s%s",
            trade.pick_number,
            old_team,
            trade.new_current_team,
            f" ({trade.trade_notes})" if trade.trade_notes else "",
        )
        modified += 1

    if modified:
        _PICKS_PATH.write_text(
            json.dumps(picks_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Applied %d trade(s) to picks.json", modified)
    else:
        logger.debug("No picks required trade updates (all already current)")

    return modified


def detect_and_apply_trades() -> int:
    """
    Convenience wrapper: load known trades and apply them to picks.json.

    Called at the start of POST /api/predictions/run (Phase 0) so that
    pick ownership is correct before the simulation executes.

    Returns:
        int: Number of picks modified by trade application.
    """
    trades = load_known_trades()
    return apply_trades_to_picks(trades)
