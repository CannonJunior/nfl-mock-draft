"""
Position value configuration loader for the NFL Mock Draft prediction engine.

Reads data/config/position_value.json to apply tier-based position weights
and need-level boosts to player scores during simulation.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent.parent / "data" / "config" / "position_value.json"

# Cache the loaded config so it is only read once per process lifetime
_CACHE: dict[str, Any] | None = None


def load_position_config() -> dict[str, Any]:
    """
    Load position value configuration from data/config/position_value.json.

    Returns the parsed JSON as a dict. Results are cached in-process.

    Returns:
        dict[str, Any]: Config dict with keys:
            - "position_tiers": {position: {tier, weight}}
            - "need_boost": {level_str: boost_float}
            - "supply_pressure": {threshold and max_boost keys}

    Raises:
        FileNotFoundError: If the config file does not exist.
        ValueError: If the JSON is malformed.
    """
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    if not _CONFIG_PATH.exists():
        raise FileNotFoundError(f"Position value config not found: {_CONFIG_PATH}")

    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        _CACHE = json.load(f)

    logger.debug("Loaded position_value.json from %s", _CONFIG_PATH)
    return _CACHE


def get_position_weight(position: str) -> float:
    """
    Return the tier weight for a given position code.

    Args:
        position (str): Normalised position code (e.g. "QB", "EDGE").

    Returns:
        float: Tier weight (e.g. 1.15 for QB). Defaults to 0.85 if
            the position is not found in the config.
    """
    config = load_position_config()
    tiers = config.get("position_tiers", {})
    entry = tiers.get(position, tiers.get(position.upper()))
    if entry:
        return float(entry["weight"])
    logger.debug("Position '%s' not in config; using default weight 0.85", position)
    return 0.85


def get_need_boost(need_level: int) -> float:
    """
    Return the additive boost factor for a given need level (1-5).

    Args:
        need_level (int): Team need level from 1 (minimal) to 5 (critical).

    Returns:
        float: Boost value (e.g. 0.30 for level 5, -0.05 for level 1).
            Returns 0.0 if the level is not in the config.
    """
    config = load_position_config()
    boosts = config.get("need_boost", {})
    return float(boosts.get(str(need_level), 0.0))


def get_supply_pressure_config() -> dict[str, float]:
    """
    Return the supply pressure threshold parameters.

    Returns:
        dict[str, float]: Keys: "talent_cliff_threshold",
            "early_drain_threshold", "max_boost".
    """
    config = load_position_config()
    sp = config.get("supply_pressure", {})
    return {
        "talent_cliff_threshold": float(sp.get("talent_cliff_threshold", 8.0)),
        "early_drain_threshold": float(sp.get("early_drain_threshold", 0.60)),
        "max_boost": float(sp.get("max_boost", 1.20)),
    }


def apply_position_weight(base_score: float, position: str) -> float:
    """
    Apply the tier weight for a position to a base score.

    Args:
        base_score (float): Raw base score 0-100.
        position (str): Normalised position code.

    Returns:
        float: Position-adjusted score.
    """
    weight = get_position_weight(position)
    return base_score * weight


def invalidate_cache() -> None:
    """
    Clear the in-process config cache.

    Useful in tests that need to reload the config with a different file.
    """
    global _CACHE
    _CACHE = None
