"""
Sequential draft simulator for the NFL Mock Draft prediction engine.

Simulates all 100 picks in order, selecting the best-fit available player
for each team based on team value scores. Writes results to:
  - data/players.json   (player profiles)
  - data/picks.json     (player_id fields populated)
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

from app.analytics.draft_engine import rank_players_for_team
from app.analytics.player_pool import PlayerCandidate, build_player_pool
from app.analytics.team_context import (
    TeamNeedState,
    build_team_need_states,
    update_team_need,
)

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_PICKS_PATH = _DATA_DIR / "picks.json"
_PLAYERS_PATH = _DATA_DIR / "players.json"
_COLLEGE_LOGO_MAP_PATH = _DATA_DIR / "config" / "college_logo_map.json"
_COLLEGE_LOGOS_URL_BASE = "/static/img/colleges"

# Load college logo map once at module import
_college_logo_map: dict[str, int] = {}
try:
    with open(_COLLEGE_LOGO_MAP_PATH, encoding="utf-8") as _f:
        _college_logo_map = json.load(_f).get("colleges", {})
except FileNotFoundError:
    pass


def run_simulation(
    player_pool: Optional[list[PlayerCandidate]] = None,
) -> tuple[dict[int, PlayerCandidate], dict[int, dict]]:
    """
    Simulate all 100 draft picks sequentially and return pick-to-player mapping
    along with a per-pick team need snapshot captured before each selection.

    For each pick:
    1. Snapshot the team's current need state (pre-pick).
    2. Score all available players for that team.
    3. Select the highest-scoring available player.
    4. Mark the player as unavailable.
    5. Update the team's need state.

    Args:
        player_pool (Optional[list[PlayerCandidate]]): Pre-built pool.
            If None, will call build_player_pool() to construct from DB.

    Returns:
        tuple:
            - dict[int, PlayerCandidate]: pick_number → selected player.
            - dict[int, dict]: pick_number → team need snapshot (pre-pick).
    """
    picks_data = _load_picks_json()
    picks = picks_data.get("picks", [])

    if not picks:
        logger.error("No picks found in picks.json — aborting simulation")
        return {}, {}

    if player_pool is None:
        player_pool = build_player_pool()

    if not player_pool:
        logger.error("Player pool is empty — aborting simulation")
        return {}, {}

    # Extract unique teams from picks to build need states
    team_abbrevs = list({p["current_team"] for p in picks})
    team_states: dict[str, TeamNeedState] = build_team_need_states(team_abbrevs)

    # Working copy of the pool (available flag is mutated per pick)
    pool = list(player_pool)

    results: dict[int, PlayerCandidate] = {}
    need_snapshots: dict[int, dict] = {}

    for pick_row in picks:
        pick_number = pick_row["pick_number"]
        team = pick_row["current_team"]

        available = [p for p in pool if p.available]
        if not available:
            logger.warning("Pick %d: No available players remaining!", pick_number)
            break

        team_state = team_states.get(team)
        if team_state is None:
            # Reason: unknown team (shouldn't happen) — create empty state
            logger.warning("Pick %d: Unknown team '%s', creating empty state", pick_number, team)
            team_state = TeamNeedState(team=team)
            team_states[team] = team_state

        # Capture pre-pick need snapshot so the UI can show what the team needed
        need_snapshots[pick_number] = {
            "team": team,
            "needs_ranked": _build_needs_ranked(team_state),
            "picks_made": list(team_state.picks_made),
        }

        ranked = rank_players_for_team(available, team_state)
        if not ranked:
            logger.warning("Pick %d: ranking returned empty for team %s", pick_number, team)
            continue

        _, selected = ranked[0]
        selected.available = False
        results[pick_number] = selected
        update_team_need(team_state, selected.position)

        logger.debug(
            "Pick %3d | %-4s | %-25s | %-5s | score=%.1f",
            pick_number,
            team.upper(),
            selected.name,
            selected.position,
            _score_of(ranked[0]),
        )

    logger.info("Simulation complete: %d/%d picks assigned", len(results), len(picks))
    return results, need_snapshots


def _build_needs_ranked(state: TeamNeedState) -> list[dict]:
    """
    Return the team's positional needs sorted by need level descending.

    Excludes positions with need level 0 (fully satisfied or irrelevant).

    Args:
        state (TeamNeedState): Current team need state.

    Returns:
        list[dict]: Ordered list of {"position": str, "need_level": int} dicts,
            highest need first.
    """
    sorted_needs = sorted(
        state.needs.items(),
        key=lambda kv: kv[1],
        reverse=True,
    )
    return [
        {"position": pos, "need_level": level}
        for pos, level in sorted_needs
        if level > 0
    ]


def write_results(
    results: dict[int, PlayerCandidate],
    need_snapshots: Optional[dict[int, dict]] = None,
) -> tuple[int, int]:
    """
    Write simulation results to data/players.json and data/picks.json.

    Players are serialised as Player-compatible JSON objects.
    Picks are updated in-place with the assigned player_id and, when provided,
    a ``team_needs_snapshot`` dict recording what the team needed pre-pick.

    Args:
        results (dict[int, PlayerCandidate]): pick_number → PlayerCandidate.
        need_snapshots (Optional[dict[int, dict]]): pick_number → need snapshot
            dict as produced by run_simulation(). Written to picks.json when given.

    Returns:
        tuple[int, int]: (picks_assigned, players_created) counts.
    """
    # Load enrichment data from DB once for all players
    college_stats_map = _load_college_stats_map()
    media_articles_map = _load_media_articles_map()

    # Build player JSON records
    players_list = [
        _candidate_to_player_dict(
            player,
            college_stats=college_stats_map.get(player.name.lower(), []),
            articles=media_articles_map.get(player.name.lower(), []),
        )
        for player in results.values()
    ]
    _PLAYERS_PATH.write_text(
        json.dumps({"players": players_list}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Wrote %d player records to %s", len(players_list), _PLAYERS_PATH)

    # Update picks.json with player_ids and team need snapshots
    picks_data = _load_picks_json()
    player_id_map: dict[int, str] = {
        pick_num: candidate.player_id for pick_num, candidate in results.items()
    }

    updated_count = 0
    for pick_row in picks_data.get("picks", []):
        pick_num = pick_row["pick_number"]
        if pick_num in player_id_map:
            pick_row["player_id"] = player_id_map[pick_num]
            updated_count += 1
        if need_snapshots and pick_num in need_snapshots:
            pick_row["team_needs_snapshot"] = need_snapshots[pick_num]

    _PICKS_PATH.write_text(
        json.dumps(picks_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Updated %d pick player_id fields in %s", updated_count, _PICKS_PATH)

    return updated_count, len(players_list)


def simulate_and_write(
    player_pool: Optional[list[PlayerCandidate]] = None,
) -> tuple[int, int]:
    """
    Run simulation then write results. Convenience wrapper.

    Args:
        player_pool (Optional[list[PlayerCandidate]]): Pre-built pool; auto-built
            from DB if None.

    Returns:
        tuple[int, int]: (picks_assigned, players_created).
    """
    results, need_snapshots = run_simulation(player_pool=player_pool)
    if not results:
        return 0, 0
    return write_results(results, need_snapshots=need_snapshots)


# ---------------------------------------------------------------------------
# JSON serialisation helpers
# ---------------------------------------------------------------------------


_DB_PATH = _DATA_DIR / "draft.db"


def _load_college_stats_map() -> dict[str, list[dict]]:
    """
    Load all college_stats rows from the DB grouped by lower-cased player name.

    Returns:
        dict[str, list[dict]]: name.lower() → list of {season, stats_json} dicts.
    """
    result: dict[str, list[dict]] = {}
    if not _DB_PATH.exists():
        return result
    try:
        conn = sqlite3.connect(str(_DB_PATH))
        rows = conn.execute(
            "SELECT name, season, stats_json FROM college_stats ORDER BY season DESC"
        ).fetchall()
        conn.close()
    except sqlite3.Error as exc:
        logger.warning("college_stats load failed: %s", exc)
        return result
    for name, season, stats_json in rows:
        result.setdefault(name.lower(), []).append(
            {"season": season, "stats_json": stats_json}
        )
    return result


def _load_media_articles_map() -> dict[str, list[dict]]:
    """
    Load all media_articles rows from the DB grouped by lower-cased player name.

    Returns:
        dict[str, list[dict]]: name.lower() → list of article dicts.
    """
    result: dict[str, list[dict]] = {}
    if not _DB_PATH.exists():
        return result
    try:
        conn = sqlite3.connect(str(_DB_PATH))
        rows = conn.execute(
            "SELECT player_name, title, url, source_name, source_type, published_at, fetched_at "
            "FROM media_articles ORDER BY published_at DESC"
        ).fetchall()
        conn.close()
    except sqlite3.Error as exc:
        logger.warning("media_articles load failed: %s", exc)
        return result
    for player_name, title, url, source_name, source_type, published_at, fetched_at in rows:
        result.setdefault(player_name.lower(), []).append({
            "title": title,
            "url": url,
            "source_name": source_name,
            "source_type": source_type or "news",
            "published_at": published_at,
            "fetched_at": fetched_at,  # ISO string; used by frontend for "new" badge
        })
    return result


# Normalisation constants for model-derived display grades.
# Top-100 picks have base_scores roughly in [15, 100]. We map that range onto
# the [6.5, 9.9] band that professional scouts use for draftable prospects,
# so model grades look consistent with ESPN/consensus scouting grades.
_GRADE_SCORE_MIN = 15.0   # base_score that anchors the lowest displayed grade
_GRADE_SCORE_MAX = 100.0  # base_score that anchors the highest displayed grade
_GRADE_DISPLAY_MIN = 6.5  # displayed grade floor (comparable to a late-3rd pick)
_GRADE_DISPLAY_MAX = 9.9  # displayed grade ceiling (comparable to #1 overall)


def _compute_display_grade(candidate: PlayerCandidate) -> float:
    """
    Compute the displayed 0-10 scouting grade for a player. Never returns None.

    Priority:
    1. ESPN scouting grade (professional, calibrated 0-10 scale).
    2. Model-derived: linearly rescales base_score from [_GRADE_SCORE_MIN,
       _GRADE_SCORE_MAX] onto [_GRADE_DISPLAY_MIN, _GRADE_DISPLAY_MAX].

    Reason: base_score for top-100 picks spans ~15-100. A raw ``/10`` mapping
    puts mid-round picks at 5.0 or below, far outside the 6.5-9.9 band that
    professional scouts assign to all draftable prospects. The rescaled formula
    ensures model grades are directly comparable to real scouting grades.

    Args:
        candidate (PlayerCandidate): Scored prospect.

    Returns:
        float: Grade in [_GRADE_DISPLAY_MIN, _GRADE_DISPLAY_MAX], always set.
    """
    if candidate.espn_grade is not None:
        return round(candidate.espn_grade, 1)
    # Reason: linearly map the draftable base_score range onto the scout grade
    # range so model grades sit in the same band as ESPN/consensus grades.
    ratio = (candidate.base_score - _GRADE_SCORE_MIN) / (
        _GRADE_SCORE_MAX - _GRADE_SCORE_MIN
    )
    derived = _GRADE_DISPLAY_MIN + ratio * (_GRADE_DISPLAY_MAX - _GRADE_DISPLAY_MIN)
    return round(max(_GRADE_DISPLAY_MIN, min(_GRADE_DISPLAY_MAX, derived)), 1)


def _build_grade_breakdown(candidate: PlayerCandidate) -> dict:
    """
    Build a grade explanation dict for display in the expanded pick panel.

    Computes the same signals used by ``_compute_base_score`` and formats
    them as human-readable strings for the template.

    Args:
        candidate (PlayerCandidate): Scored prospect.

    Returns:
        dict: Keys ``grade_source``, ``base_score``, ``formula``, ``components``.
    """
    import math

    combine = candidate.combine or {}
    mock_picks = candidate.mock_picks or []

    # --- Mock consensus signal ---
    mock_signal: Optional[float] = None
    if mock_picks:
        scores = [max(0.0, 100.0 * (1.0 - (p - 1) / 99.0)) for p in mock_picks]
        avg = sum(scores) / len(scores)
        if len(scores) > 1:
            variance = sum((s - avg) ** 2 for s in scores) / len(scores)
            std_dev = math.sqrt(variance)
            avg = max(0.0, avg - min(10.0, std_dev * 0.15))
        mock_signal = avg

    # --- Combine athletic score ---
    _40_medians: dict[str, float] = {
        "QB": 4.75, "OT": 5.10, "EDGE": 4.65, "DE": 4.65,
        "WR": 4.45, "CB": 4.42, "DT": 4.95, "TE": 4.72,
        "LB": 4.65, "IOL": 5.15, "OG": 5.20, "C": 5.20,
        "S": 4.50, "RB": 4.48, "FB": 4.65,
    }
    combine_scores: list[float] = []
    forty = combine.get("forty_yard_dash")
    if forty and forty > 0:
        median = _40_medians.get(candidate.position, 4.75)
        combine_scores.append(max(0.0, min(100.0, 50.0 + (median - forty) * 100.0)))
    vert = combine.get("vertical_jump_inches")
    if vert and vert > 0:
        combine_scores.append(max(0.0, min(100.0, 50.0 + (vert - 33.0) * (10.0 / 3.0))))
    broad = combine.get("broad_jump_inches")
    if broad and broad > 0:
        combine_scores.append(max(0.0, min(100.0, 50.0 + (broad - 120.0) * (10.0 / 6.0))))
    combine_score = sum(combine_scores) / len(combine_scores) if combine_scores else 50.0
    drills_measured = len(combine_scores)

    # --- Determine grade source and weights used ---
    has_espn = candidate.espn_grade is not None
    has_mock = bool(mock_picks)
    has_buzz = candidate.buzz_score is not None
    has_combine = bool(combine)

    if has_espn:
        grade_source = "ESPN Scouting Grade"
        if has_mock and has_buzz:
            formula = "ESPN 35% + Mock 35% + Combine 15% + Buzz 15%"
        elif has_mock:
            formula = "ESPN 40% + Mock 40% + Combine 20%"
        elif has_buzz:
            formula = "ESPN 65% + Combine 15% + Buzz 20%"
        else:
            formula = "ESPN 80% + Combine 20%"
    elif has_mock:
        grade_source = "Model-Derived (Mock + Combine)"
        formula = "Mock 80% + Combine 20%" + (" + Buzz 20%" if has_buzz else "")
    else:
        grade_source = "Model-Derived (Combine only)"
        formula = "Combine fallback"

    # --- Build components dict ---
    components: dict[str, str] = {}
    if has_espn:
        components["ESPN Grade"] = f"{candidate.espn_grade:.1f}/10"
    if candidate.espn_rank:
        components["Big Board Rank"] = f"#{candidate.espn_rank}"
    if mock_signal is not None:
        avg_pick = sum(mock_picks) / len(mock_picks)
        components[f"Mock Consensus ({len(mock_picks)} src)"] = (
            f"#{avg_pick:.0f} avg → {mock_signal:.0f}/100"
        )
    if has_combine:
        drill_label = f"{drills_measured} drill(s)" if drills_measured else "no drills"
        components["Combine Athletic"] = f"{combine_score:.0f}/100 ({drill_label})"
    if has_buzz:
        components["Social Buzz"] = f"{candidate.buzz_score:.0f}/100"

    return {
        "grade_source": grade_source,
        "formula": formula,
        "base_score": round(candidate.base_score, 1),
        "components": components,
    }


def _resolve_college_logo_url(college: str) -> Optional[str]:
    """
    Return local static URL for a college logo, or None if unknown.

    Args:
        college (str): College name (any casing).

    Returns:
        Optional[str]: URL like "/static/img/colleges/333.png", or None.
    """
    logo_id = _college_logo_map.get(college.lower().strip())
    if logo_id is None:
        return None
    local_path = Path(__file__).parent.parent.parent / "static" / "img" / "colleges" / f"{logo_id}.png"
    if not local_path.exists():
        return None
    return f"{_COLLEGE_LOGOS_URL_BASE}/{logo_id}.png"


def _candidate_to_player_dict(
    candidate: PlayerCandidate,
    college_stats: Optional[list[dict]] = None,
    articles: Optional[list[dict]] = None,
) -> dict:
    """
    Convert a PlayerCandidate to a Player-compatible JSON dict.

    Includes combine stats in the bio field, college season stats in stat_views,
    and news articles in media_links.

    Args:
        candidate (PlayerCandidate): Simulated draft selection.
        college_stats (Optional[list[dict]]): Rows from college_stats table for this player.
        articles (Optional[list[dict]]): Rows from media_articles table for this player.

    Returns:
        dict: JSON-serialisable player record matching the Player Pydantic model.
    """
    bio: dict = {}
    combine = candidate.combine or {}
    # Physical measurements
    for field in ("height_inches", "weight_lbs"):
        if combine.get(field):
            bio[field] = combine[field]
    for field in ("arm_length_inches", "hand_size_inches"):
        if combine.get(field):
            bio[field] = combine[field]
    # Athletic testing
    for field in (
        "forty_yard_dash", "vertical_jump_inches",
        "broad_jump_inches", "bench_press_reps",
        "three_cone", "twenty_yard_shuttle",
    ):
        if combine.get(field):
            bio[field] = combine[field]

    # Build stat_views from scraped college season stats
    stat_views: list[dict] = []
    for row in (college_stats or []):
        try:
            stats = json.loads(row.get("stats_json", "{}"))
        except (json.JSONDecodeError, TypeError):
            stats = {}
        if stats:
            stat_views.append({
                "view_name": row.get("season", "Season"),
                "season": row.get("season", ""),
                "stats": stats,
            })

    # Split articles into news/media links and tweets
    media_links: list[dict] = []
    tweets: list[dict] = []
    for art in (articles or []):
        entry = {
            "source_type": art.get("source_type", "news"),
            "title": art.get("title", ""),
            "url": art.get("url", ""),
            "source_name": art.get("source_name", ""),
            "published_at": art.get("published_at"),
            "fetched_at": art.get("fetched_at"),  # used by frontend "new" badge
            "thumbnail_url": None,
        }
        if art.get("source_type") == "twitter":
            tweets.append(entry)
        else:
            media_links.append(entry)

    # --- Combine stat view (always add when combine data exists) ---
    if combine:
        combine_stats: dict[str, str | int | float] = {}
        ht = combine.get("height_inches")
        if ht:
            combine_stats["Height"] = f"{ht // 12}'{ht % 12}\""
        if combine.get("weight_lbs"):
            combine_stats["Weight"] = f"{combine['weight_lbs']} lbs"
        if combine.get("arm_length_inches"):
            combine_stats["Arm Length"] = f"{combine['arm_length_inches']:.2f}\""
        if combine.get("hand_size_inches"):
            combine_stats["Hand Size"] = f"{combine['hand_size_inches']:.2f}\""
        if combine.get("forty_yard_dash"):
            combine_stats["40-Yard Dash"] = f"{combine['forty_yard_dash']}s"
        if combine.get("vertical_jump_inches"):
            combine_stats["Vertical Jump"] = f"{combine['vertical_jump_inches']}\""
        if combine.get("broad_jump_inches"):
            combine_stats["Broad Jump"] = f"{combine['broad_jump_inches']}\""
        if combine.get("bench_press_reps"):
            combine_stats["Bench Press"] = f"{combine['bench_press_reps']} reps"
        if combine.get("twenty_yard_shuttle"):
            combine_stats["20-Yd Shuttle"] = f"{combine['twenty_yard_shuttle']}s"
        if combine.get("three_cone"):
            combine_stats["3-Cone Drill"] = f"{combine['three_cone']}s"
        if combine_stats:
            # Reason: insert Combine tab first so it's the default view
            stat_views.insert(0, {
                "view_name": "Combine",
                "season": "2026",
                "stats": combine_stats,
            })

    # --- Projection stat view ---
    # Always append so the Statistics tab always has at least one view.
    grade_bd = _build_grade_breakdown(candidate)
    proj: dict[str, str | int | float] = {}
    if candidate.espn_grade is not None:
        proj["ESPN Grade"] = f"{candidate.espn_grade:.1f}/10"
    if candidate.espn_rank:
        proj["Big Board Rank"] = f"#{candidate.espn_rank}"
    if candidate.mock_picks:
        avg_p = sum(candidate.mock_picks) / len(candidate.mock_picks)
        proj["Mock Consensus"] = f"#{avg_p:.0f} avg ({len(candidate.mock_picks)} src)"
    proj["Model Score"] = f"{grade_bd['base_score']}/100"
    if candidate.buzz_score is not None:
        proj["Buzz Score"] = f"{candidate.buzz_score:.0f}/100"
    stat_views.append({
        "view_name": "Projection",
        "season": "2026",
        "stats": proj,
    })

    # --- Compute final display grade (never None) ---
    grade = _compute_display_grade(candidate)

    # --- Mock consensus note ---
    mock_note = ""
    if candidate.mock_picks:
        avg_mock = sum(candidate.mock_picks) / len(candidate.mock_picks)
        mock_note = (
            f"Mock consensus avg pick: {avg_mock:.1f} "
            f"({len(candidate.mock_picks)} source(s)). "
        )

    return {
        "player_id": candidate.player_id,
        "name": candidate.name,
        "position": candidate.position,
        "college": candidate.college,
        "college_abbreviation": None,
        "college_logo_url": _resolve_college_logo_url(candidate.college),
        "bio": bio,
        "injury_history": [],
        "stat_views": stat_views,
        "media_links": media_links,
        "tweets": tweets,
        "grade": grade,
        "grade_breakdown": grade_bd,
        "notes": (
            f"{mock_note}Model score: {grade_bd['base_score']}/100 "
            f"({grade_bd['grade_source']})."
        ),
    }


def _load_picks_json() -> dict:
    """
    Load picks.json from disk.

    Returns:
        dict: Parsed picks JSON with a "picks" key.
    """
    if not _PICKS_PATH.exists():
        return {"picks": []}
    with open(_PICKS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _score_of(scored_pair: tuple[float, PlayerCandidate]) -> float:
    """
    Extract the score float from a (score, player) tuple.

    Args:
        scored_pair (tuple[float, PlayerCandidate]): Ranked pair.

    Returns:
        float: The score value.
    """
    return scored_pair[0]
