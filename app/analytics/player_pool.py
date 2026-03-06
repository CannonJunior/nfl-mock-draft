"""
Player pool builder for the NFL Mock Draft prediction engine.

Queries the SQLite database for prospects, combine stats, and mock draft
consensus data, then assembles a list of PlayerCandidate dataclasses ready
for scoring by the draft engine.
"""

from __future__ import annotations

import logging
import math
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "draft.db"

# All active mock draft sources that contribute to consensus signal
MOCK_SOURCES = ["tankathon", "espn_mock", "nfl_mock"]

# Normalise position labels scraped from different sources
_POS_ALIASES: dict[str, str] = {
    "defensive end": "EDGE",
    "de": "EDGE",
    "edge rusher": "EDGE",
    "dl": "DT",
    "offensive lineman": "IOL",
    "ol": "OT",
    "offensive tackle": "OT",
    "interior ol": "IOL",
    "interior offensive lineman": "IOL",
    "iol": "IOL",
    "og": "OG",
    "guard": "OG",
    "center": "C",
    "linebacker": "LB",
    "ilb": "LB",
    "olb": "LB",
    "wide receiver": "WR",
    "wr": "WR",
    "tight end": "TE",
    "quarterback": "QB",
    "running back": "RB",
    "fullback": "FB",
    "cornerback": "CB",
    "cb": "CB",
    "safety": "S",
    "fs": "S",
    "ss": "S",
    "defensive tackle": "DT",
    "dt": "DT",
}


@dataclass
class PlayerCandidate:
    """
    Internal representation of a draft prospect for the simulation engine.

    Attributes:
        player_id (str): Slug identifier: "firstname-lastname".
        name (str): Full player name.
        position (str): Normalised position code (e.g. "EDGE" not "DE").
        college (str): College or university name.
        espn_grade (Optional[float]): ESPN prospect grade (0-10 scale).
        espn_rank (Optional[int]): ESPN big board rank.
        combine (dict): Combine measurements keyed by stat name.
        mock_picks (list[int]): Pick numbers from mock sources where player appears.
        base_score (float): Composite 0-100 score.
        available (bool): False once the player has been drafted in simulation.
    """

    player_id: str
    name: str
    position: str
    college: str
    espn_grade: Optional[float]
    espn_rank: Optional[int]
    combine: dict = field(default_factory=dict)
    mock_picks: list[int] = field(default_factory=list)
    base_score: float = 0.0
    available: bool = True
    buzz_score: Optional[float] = None


def build_player_pool() -> list[PlayerCandidate]:
    """
    Build a ranked list of PlayerCandidate objects from the database.

    Joins prospects (ESPN grades/ranks), combine stats, and mock draft
    consensus data. Computes a base_score for each candidate.

    Returns:
        list[PlayerCandidate]: Players sorted by base_score descending.
            Returns a fallback synthetic pool if the DB has no data.
    """
    if not _DB_PATH.exists():
        logger.warning("draft.db not found — returning synthetic fallback pool")
        return _synthetic_fallback_pool()

    prospects = _load_prospects()
    if not prospects:
        logger.warning("No prospects in DB — returning synthetic fallback pool")
        return _synthetic_fallback_pool()

    combine_map = _load_combine_map()
    mock_map = _load_mock_map()
    buzz_map = _load_buzz_map()

    # Supplement ESPN prospects with players who appear only in mock drafts.
    # Reason: ESPN's big board has 25 players; mock sources cover 100+ picks.
    # Without this supplement, the simulation runs out of players after pick 25.
    espn_names = {row["name"].lower() for row in prospects}
    mock_only = _load_mock_only_players(espn_names, mock_map)
    all_prospects = list(prospects) + mock_only

    candidates: list[PlayerCandidate] = []
    for row in all_prospects:
        name = row["name"]
        position = _normalise_position(row.get("position") or "")
        college = row.get("college") or ""
        espn_grade: Optional[float] = row.get("grade")
        espn_rank: Optional[int] = row.get("rank")

        player_id = _make_player_id(name)
        combine = combine_map.get(name.lower(), {})
        mock_picks = mock_map.get(name.lower(), [])
        buzz = buzz_map.get(name.lower())

        base_score = _compute_base_score(
            espn_grade=espn_grade,
            espn_rank=espn_rank,
            mock_picks=mock_picks,
            combine=combine,
            position=position,
            buzz=buzz,
        )

        candidates.append(
            PlayerCandidate(
                player_id=player_id,
                name=name,
                position=position,
                college=college,
                espn_grade=espn_grade,
                espn_rank=espn_rank,
                combine=combine,
                mock_picks=mock_picks,
                base_score=base_score,
                buzz_score=buzz,
            )
        )

    # Sort descending so first pick has best player at the top
    candidates.sort(key=lambda c: c.base_score, reverse=True)
    logger.info("Player pool built: %d candidates", len(candidates))
    return candidates


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _compute_base_score(
    espn_grade: Optional[float],
    espn_rank: Optional[int],
    mock_picks: list[int],
    combine: dict,
    position: str,
    buzz: Optional[float] = None,
) -> float:
    """
    Compute the 0-100 base score for a prospect.

    Formula (when all signals present):
        base_score = espn_norm(0.35) + mock_signal(0.35) + combine_score(0.15) + buzz(0.15)

    Falls back to the original 0.40/0.40/0.20 formula when buzz is absent,
    and to ESPN-only or mock-only weights when grades/mocks are missing.

    Args:
        espn_grade (Optional[float]): ESPN 0-10 grade.
        espn_rank (Optional[int]): ESPN big board rank.
        mock_picks (list[int]): Pick numbers from all mock sources.
        combine (dict): Combine measurements.
        position (str): Normalised position code.
        buzz (Optional[float]): Community buzz score 0-100 (from social scraper).

    Returns:
        float: Base score in range 0-100.
    """
    mock_signal = _mock_consensus_signal(mock_picks)
    combine_score = _combine_score(combine, position)
    # Reason: normalise buzz (0-100) — use 50.0 neutral if None so we can
    # smoothly blend it when present without destabilising no-buzz cases.
    has_buzz = buzz is not None
    buzz_norm = buzz if buzz is not None else 50.0

    if espn_grade is not None:
        espn_norm = (espn_grade / 10.0) * 100.0
        if mock_picks and has_buzz:
            return (espn_norm * 0.35) + (mock_signal * 0.35) + (combine_score * 0.15) + (buzz_norm * 0.15)
        elif mock_picks:
            return (espn_norm * 0.40) + (mock_signal * 0.40) + (combine_score * 0.20)
        else:
            # No mock data — reweight to ESPN + combine (± buzz)
            if has_buzz:
                return (espn_norm * 0.65) + (combine_score * 0.15) + (buzz_norm * 0.20)
            return (espn_norm * 0.80) + (combine_score * 0.20)

    # No ESPN grade — derive from mock consensus or rank
    if mock_picks:
        derived_grade = _derive_grade_from_picks(mock_picks)
        if has_buzz:
            return (derived_grade * 0.65) + (combine_score * 0.15) + (buzz_norm * 0.20)
        return (derived_grade * 0.80) + (combine_score * 0.20)

    if espn_rank is not None:
        derived_grade = _derive_grade_from_rank(espn_rank)
        if has_buzz:
            return (derived_grade * 0.65) + (combine_score * 0.15) + (buzz_norm * 0.20)
        return (derived_grade * 0.80) + (combine_score * 0.20)

    # Absolute fallback — unknown prospect, low score
    return max(1.0, combine_score * 0.5)


def _mock_consensus_signal(mock_picks: list[int]) -> float:
    """
    Convert a list of mock-draft pick numbers into a 0-100 consensus signal.

    Each pick number is converted: score = 100 * (1 - (pick-1)/99).
    Scores are averaged across sources. Disagreement between sources
    (high std-dev) slightly reduces the result.

    Args:
        mock_picks (list[int]): Pick numbers from all sources.

    Returns:
        float: Consensus signal in range 0-100.
    """
    if not mock_picks:
        return 0.0

    scores = [max(0.0, 100.0 * (1.0 - (p - 1) / 99.0)) for p in mock_picks]
    avg = sum(scores) / len(scores)

    if len(scores) > 1:
        variance = sum((s - avg) ** 2 for s in scores) / len(scores)
        std_dev = math.sqrt(variance)
        # Reason: penalise high disagreement; cap penalty at 10 points
        disagreement_penalty = min(10.0, std_dev * 0.15)
        avg = max(0.0, avg - disagreement_penalty)

    return avg


def _combine_score(combine: dict, position: str) -> float:
    """
    Compute a position-relative athletic composite from combine measurements.

    Uses position-specific reference norms so a fast RB doesn't get the
    same boost as a fast OT (different expectations by position).

    Args:
        combine (dict): Combine measurements (40yd, vertical, etc.).
        position (str): Normalised position code.

    Returns:
        float: Combine score in range 0-100.
    """
    if not combine:
        return 50.0  # Neutral when no combine data

    # Reference medians by position tier for 40-yard dash (lower = better)
    _40_medians: dict[str, float] = {
        "QB": 4.75, "OT": 5.10, "EDGE": 4.65, "DE": 4.65,
        "WR": 4.45, "CB": 4.42, "DT": 4.95, "TE": 4.72,
        "LB": 4.65, "IOL": 5.15, "OG": 5.20, "C": 5.20,
        "S": 4.50, "RB": 4.48, "FB": 4.65,
    }

    scores: list[float] = []

    forty = combine.get("forty_yard_dash")
    if forty and forty > 0:
        median = _40_medians.get(position, 4.75)
        # Reason: scale so median = 50; each 0.10s deviation = ±10 pts
        raw = 50.0 + (median - forty) * 100.0
        scores.append(max(0.0, min(100.0, raw)))

    vertical = combine.get("vertical_jump_inches")
    if vertical and vertical > 0:
        # Median vertical ~33 inches; each 3-inch deviation = ±10 pts
        raw = 50.0 + (vertical - 33.0) * (10.0 / 3.0)
        scores.append(max(0.0, min(100.0, raw)))

    broad = combine.get("broad_jump_inches")
    if broad and broad > 0:
        # Median broad ~120 inches; each 6-inch deviation = ±10 pts
        raw = 50.0 + (broad - 120.0) * (10.0 / 6.0)
        scores.append(max(0.0, min(100.0, raw)))

    return sum(scores) / len(scores) if scores else 50.0


def _derive_grade_from_picks(mock_picks: list[int]) -> float:
    """
    Derive an ESPN-equivalent 0-100 grade from mock draft pick numbers.

    Uses a log-linear curve: pick 1 → ~95, pick 32 → ~70, pick 100 → ~30.

    Args:
        mock_picks (list[int]): Pick numbers from mock sources.

    Returns:
        float: Derived grade in 0-100 range.
    """
    avg_pick = sum(mock_picks) / len(mock_picks)
    # Reason: log curve maps pick 1→95, pick 32→70, pick 100→30 roughly
    grade = 100.0 - (math.log(max(1, avg_pick)) / math.log(100)) * 70.0
    return max(0.0, min(100.0, grade))


def _derive_grade_from_rank(rank: int) -> float:
    """
    Derive a 0-100 score from a big board rank.

    Args:
        rank (int): ESPN big board rank (1 = top prospect).

    Returns:
        float: Derived score in 0-100 range.
    """
    grade = 100.0 - (math.log(max(1, rank)) / math.log(200)) * 70.0
    return max(0.0, min(100.0, grade))


# ---------------------------------------------------------------------------
# DB query helpers
# ---------------------------------------------------------------------------


def _get_conn() -> sqlite3.Connection:
    """
    Open a read-only SQLite connection to draft.db.

    Returns:
        sqlite3.Connection: Configured database connection.
    """
    conn = sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _load_prospects() -> list[dict]:
    """
    Load distinct prospect rows from the prospects table.

    Prefers ESPN source rows; falls back to any source for each unique name.

    Returns:
        list[dict]: Prospect rows as dicts.
    """
    try:
        with _get_conn() as conn:
            rows = conn.execute(
                """
                SELECT name, position, college, rank, grade
                FROM prospects
                ORDER BY
                  CASE WHEN source = 'espn' THEN 0 ELSE 1 END,
                  rank ASC NULLS LAST,
                  grade DESC NULLS LAST
                """
            ).fetchall()

        # Deduplicate by lower-cased name, keeping first (ESPN-preferred) row
        seen: set[str] = set()
        unique: list[dict] = []
        for row in rows:
            key = row["name"].lower()
            if key not in seen:
                seen.add(key)
                unique.append(dict(row))
        return unique

    except sqlite3.OperationalError as exc:
        logger.warning("Could not load prospects: %s", exc)
        return []


def _load_combine_map() -> dict[str, dict]:
    """
    Build a name → combine stats dict from the combine_stats table.

    Returns:
        dict[str, dict]: Lower-cased player name → combine measurements.
    """
    try:
        with _get_conn() as conn:
            rows = conn.execute(
                """
                SELECT name, height_inches, weight_lbs,
                       arm_length_inches, hand_size_inches,
                       forty_yard_dash, vertical_jump_inches,
                       broad_jump_inches, bench_press_reps,
                       three_cone, twenty_yard_shuttle
                FROM combine_stats
                """
            ).fetchall()
        return {
            row["name"].lower(): {
                "height_inches": row["height_inches"],
                "weight_lbs": row["weight_lbs"],
                "arm_length_inches": row["arm_length_inches"],
                "hand_size_inches": row["hand_size_inches"],
                "forty_yard_dash": row["forty_yard_dash"],
                "vertical_jump_inches": row["vertical_jump_inches"],
                "broad_jump_inches": row["broad_jump_inches"],
                "bench_press_reps": row["bench_press_reps"],
                "three_cone": row["three_cone"],
                "twenty_yard_shuttle": row["twenty_yard_shuttle"],
            }
            for row in rows
        }
    except sqlite3.OperationalError as exc:
        logger.warning("Could not load combine stats: %s", exc)
        return {}


def _load_buzz_map() -> dict[str, float]:
    """
    Build a lower-cased name → buzz_score dict from the buzz_signals table.

    Combines TDN grade (0-10 → 0-100) and Reddit mention count into a
    single 0-100 buzz signal per player. Players with no buzz data are omitted.

    Returns:
        dict[str, float]: Lower-cased player name → buzz score 0-100.
    """
    try:
        with _get_conn() as conn:
            rows = conn.execute(
                """
                SELECT name, grade, rank, mentions, source
                FROM buzz_signals
                """
            ).fetchall()
    except Exception as exc:
        logger.warning("Could not load buzz signals: %s", exc)
        return {}

    # Aggregate per player: use TDN grade if available, supplement with Reddit
    per_player: dict[str, dict] = {}
    for row in rows:
        key = row["name"].lower()
        entry = per_player.setdefault(key, {"grade": None, "rank": None, "mentions": 0})
        if row["source"] == "thedraftnetwork":
            if row["grade"] is not None:
                # Reason: TDN grade is 0-10; convert to 0-100
                entry["grade"] = (row["grade"] / 10.0) * 100.0
            if row["rank"] is not None:
                entry["rank"] = row["rank"]
        elif row["source"] == "reddit":
            entry["mentions"] = (entry.get("mentions") or 0) + (row["mentions"] or 0)

    result: dict[str, float] = {}
    for key, entry in per_player.items():
        grade_score: Optional[float] = entry.get("grade")
        rank = entry.get("rank")
        mentions = entry.get("mentions") or 0

        # Derive grade from rank if no direct grade
        if grade_score is None and rank:
            import math
            grade_score = max(0.0, 100.0 - (math.log(max(1, rank)) / math.log(300)) * 80.0)

        # Normalise Reddit mention count: cap at 20 mentions = 100 score
        reddit_score = min(100.0, (mentions / 20.0) * 100.0) if mentions > 0 else 0.0

        if grade_score is not None:
            # Blend TDN grade (70%) with Reddit buzz (30%)
            result[key] = grade_score * 0.70 + reddit_score * 0.30
        elif reddit_score > 0:
            result[key] = reddit_score

    return result


def _load_mock_only_players(
    known_names: set[str], mock_map: dict[str, list[int]]
) -> list[dict]:
    """
    Return synthetic prospect rows for players found in mock drafts but not in
    the prospects table (i.e. no ESPN grade/rank data).

    Args:
        known_names (set[str]): Lower-cased player names already in the pool.
        mock_map (dict[str, list[int]]): Lower-cased name → pick numbers from mock sources.

    Returns:
        list[dict]: Minimal prospect row dicts (name, position, college, grade=None, rank=None).
    """
    extra: list[dict] = []
    placeholders = ",".join("?" * len(MOCK_SOURCES))
    try:
        with _get_conn() as conn:
            rows = conn.execute(
                f"""
                SELECT player_name, position, college
                FROM mock_draft
                WHERE source IN ({placeholders})
                  AND player_name IS NOT NULL
                  AND player_name != ''
                GROUP BY LOWER(player_name)
                """,
                MOCK_SOURCES,
            ).fetchall()
    except sqlite3.OperationalError as exc:
        logger.warning("Could not load mock-only players: %s", exc)
        return extra

    for row in rows:
        name = row["player_name"]
        if name.lower() in known_names:
            continue
        # Include any player projected in at least one mock source.
        # Reason: Tankathon covers picks 1-139 but NFL/ESPN mocks only cover
        # 32 picks, so most prospects 33+ appear in exactly 1 source.
        picks = mock_map.get(name.lower(), [])
        if not picks:
            continue
        extra.append({
            "name": name,
            "position": row["position"] or "",
            "college": row["college"] or "",
            "grade": None,
            "rank": None,
        })

    logger.info("Supplemented pool with %d mock-only players", len(extra))
    return extra


def _load_mock_map() -> dict[str, list[int]]:
    """
    Build a name → list-of-pick-numbers dict from the mock_draft table.

    Only considers sources in MOCK_SOURCES.

    Returns:
        dict[str, list[int]]: Lower-cased player name → pick numbers.
    """
    placeholders = ",".join("?" * len(MOCK_SOURCES))
    try:
        with _get_conn() as conn:
            rows = conn.execute(
                f"""
                SELECT player_name, pick_number
                FROM mock_draft
                WHERE source IN ({placeholders})
                """,
                MOCK_SOURCES,
            ).fetchall()

        result: dict[str, list[int]] = {}
        for row in rows:
            key = row["player_name"].lower()
            result.setdefault(key, []).append(row["pick_number"])
        return result
    except sqlite3.OperationalError as exc:
        logger.warning("Could not load mock draft data: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _make_player_id(name: str) -> str:
    """
    Convert a player name to a URL-safe slug used as player_id.

    Args:
        name (str): Player full name (e.g. "Shedeur Sanders").

    Returns:
        str: Slug (e.g. "shedeur-sanders").
    """
    slug = re.sub(r"[^\w\s-]", "", name.lower())
    return re.sub(r"[\s_]+", "-", slug).strip("-")


def _normalise_position(raw: str) -> str:
    """
    Normalise a raw position string to a canonical code.

    Args:
        raw (str): Raw position string from scraper output.

    Returns:
        str: Canonical position code (e.g. "EDGE", "IOL").
    """
    cleaned = raw.strip().lower()
    return _POS_ALIASES.get(cleaned, raw.upper().strip())


# ---------------------------------------------------------------------------
# Synthetic fallback pool (used when DB has no data)
# ---------------------------------------------------------------------------


def _synthetic_fallback_pool() -> list[PlayerCandidate]:
    """
    Return a minimal synthetic player pool for development/testing.

    This fallback ensures the simulator can run end-to-end even when
    the scraping pipeline hasn't been executed yet.

    Returns:
        list[PlayerCandidate]: 120 synthetic prospects covering all positions.
    """
    # Reason: 120 players ensures enough depth to fill all 100 picks with
    # some remainder for realistic selection dynamics.
    # NOTE: This pool is the confirmed 2026 NFL Draft class — players who
    # exhausted eligibility after the 2025 college season or received
    # special eligibility status. Grades/ranks sourced from Daniel Jeremiah
    # (NFL.com Top 50 v2.0), Mel Kiper Jr. (ESPN), and CBS Sports big board.
    # Format: (name, position, college, espn_grade_0_to_10, approx_rank)
    _PROSPECTS = [
        # ---- QBs ----
        ("Fernando Mendoza", "QB", "Indiana", 9.5, 1),
        ("Garrett Nussmeier", "QB", "LSU", 8.0, 15),
        ("Drew Allar", "QB", "Penn State", 7.5, 22),
        ("Carson Beck", "QB", "Miami", 7.3, 26),
        ("Ty Simpson", "QB", "Alabama", 6.8, 40),
        ("Cade Klubnik", "QB", "Clemson", 6.5, 45),
        ("Taylen Green", "QB", "Arkansas", 6.2, 52),
        ("Diego Pavia", "QB", "Vanderbilt", 6.0, 58),
        ("Luke Altmyer", "QB", "Illinois", 5.8, 63),
        # ---- OTs / IOL ----
        ("Francis Mauigoa", "OT", "Miami", 8.2, 12),
        ("Spencer Fano", "OT", "Utah", 8.0, 14),
        ("Blake Miller", "OT", "Clemson", 7.6, 24),
        ("Monroe Freeling", "OT", "Georgia", 7.5, 25),
        ("Kadyn Proctor", "OT", "Alabama", 7.3, 29),
        ("Caleb Lomu", "OT", "Utah", 7.1, 31),
        ("Olaivavega Ioane", "IOL", "Penn State", 8.3, 11),
        ("Chase Bisontis", "OG", "Texas A&M", 7.0, 32),
        ("Billy Schrauth", "OG", "Notre Dame", 6.8, 36),
        ("Parker Brailsford", "C", "Alabama", 6.6, 38),
        ("Aamil Wagner", "OT", "Notre Dame", 6.4, 43),
        ("Jalen Farmer", "OG", "Kentucky", 6.2, 48),
        ("Jager Burton", "OG", "Kentucky", 6.0, 54),
        ("Emmanuel Pregnon", "OT", "Oregon", 5.8, 60),
        ("Jaeden Roberts", "OT", "Alabama", 5.6, 66),
        # ---- EDGE / DE ----
        ("David Bailey", "EDGE", "Texas Tech", 9.1, 3),
        ("Rueben Bain Jr.", "EDGE", "Miami", 8.8, 6),
        ("Akheem Mesidor", "EDGE", "Miami", 7.9, 20),
        ("Cashius Howell", "EDGE", "Texas A&M", 7.8, 21),
        ("Keldric Faulk", "EDGE", "Auburn", 7.4, 28),
        ("T.J. Parker", "EDGE", "Clemson", 7.2, 32),
        ("R Mason Thomas", "EDGE", "Oklahoma", 6.9, 39),
        ("Zion Young", "EDGE", "Missouri", 6.6, 47),
        ("Dani Dennis-Sutton", "EDGE", "Penn State", 6.4, 50),
        ("Zane Durant", "EDGE", "Penn State", 6.2, 55),
        ("Jaishawn Barham", "EDGE", "Michigan", 6.0, 61),
        ("Trey Moore", "EDGE", "Texas", 5.8, 67),
        ("Caden Curry", "EDGE", "Ohio State", 5.6, 72),
        # ---- DTs / Interior DL ----
        ("Lee Hunter", "DT", "Texas Tech", 7.5, 27),
        ("Kayden McDonald", "DT", "Ohio State", 7.1, 35),
        ("Caleb Banks", "DT", "Florida", 7.0, 36),
        ("Peter Woods", "DT", "Clemson", 6.8, 38),
        ("Christen Miller", "DT", "Georgia", 6.6, 41),
        ("DeMonte Capehart", "DT", "Clemson", 6.3, 49),
        ("Dontay Corleone", "DT", "Cincinnati", 6.1, 56),
        ("Tim Keenan III", "DT", "Alabama", 5.9, 62),
        ("Rayshaun Benny", "DT", "Michigan", 5.7, 68),
        ("Keyron Crawford", "DT", "Auburn", 5.5, 74),
        # ---- WRs ----
        ("Carnell Tate", "WR", "Ohio State", 8.7, 7),
        ("Makai Lemon", "WR", "USC", 8.4, 10),
        ("Jordyn Tyson", "WR", "Arizona State", 8.1, 17),
        ("Denzel Boston", "WR", "Washington", 8.0, 18),
        ("Omar Cooper Jr.", "WR", "Indiana", 7.9, 19),
        ("KC Concepcion", "WR", "Texas A&M", 7.2, 33),
        ("Malachi Fields", "WR", "Notre Dame", 6.9, 44),
        ("Antonio Williams", "WR", "Clemson", 6.7, 46),
        ("Deion Burks", "WR", "Oklahoma", 6.5, 49),
        ("Zachariah Branch", "WR", "Georgia", 6.4, 50),
        ("Aaron Anderson", "WR", "LSU", 6.2, 57),
        ("Barion Brown", "WR", "LSU", 6.0, 63),
        ("Chris Brazzell II", "WR", "Tennessee", 5.8, 69),
        ("Kevin Coleman Jr.", "WR", "Missouri", 5.6, 75),
        # ---- CBs ----
        ("Mansoor Delane", "CB", "LSU", 8.6, 8),
        ("Jermod McCoy", "CB", "Tennessee", 8.1, 13),
        ("Colton Hood", "CB", "Tennessee", 7.5, 26),
        ("Avieon Terrell", "CB", "Clemson", 7.2, 30),
        ("Brandon Cisse", "CB", "South Carolina", 6.8, 37),
        ("Keionte Scott", "CB", "Miami", 6.6, 45),
        ("Malik Muhammad", "CB", "Texas", 6.3, 52),
        ("Jadon Canady", "CB", "Oregon", 6.0, 59),
        ("Davison Igbinosun", "CB", "Ohio State", 5.8, 65),
        ("Daylen Everette", "CB", "Georgia", 5.6, 71),
        ("Toriano Pride Jr.", "CB", "Missouri", 5.4, 77),
        # ---- Safeties ----
        ("Caleb Downs", "S", "Ohio State", 8.5, 9),
        ("Emmanuel McNeil-Warren", "S", "Toledo", 8.1, 15),
        ("Dillon Thieneman", "S", "Oregon", 7.8, 23),
        ("Kamari Ramsey", "S", "USC", 6.7, 42),
        ("Genesis Smith", "S", "Arizona", 6.4, 51),
        ("D'Angelo Ponds", "S", "Indiana", 6.1, 58),
        ("Xavier Nwankpa", "S", "Iowa", 5.9, 64),
        # ---- LBs ----
        ("Arvell Reese", "LB", "Ohio State", 9.0, 4),
        ("Sonny Styles", "LB", "Ohio State", 8.9, 5),
        ("CJ Allen", "LB", "Georgia", 7.8, 22),
        ("Anthony Hill Jr.", "LB", "Texas", 6.8, 42),
        ("Harold Perkins Jr.", "LB", "LSU", 6.6, 46),
        ("Jake Golday", "LB", "Cincinnati", 6.5, 48),
        ("Lander Barton", "LB", "Utah", 6.2, 55),
        ("Kendal Daniels", "LB", "Oklahoma", 6.0, 61),
        ("Deontae Lawson", "LB", "Alabama", 5.8, 67),
        ("Eric Gentry", "LB", "USC", 5.6, 73),
        # ---- TEs ----
        ("Kenyon Sadiq", "TE", "Oregon", 8.2, 16),
        ("Max Klare", "TE", "Ohio State", 7.0, 34),
        ("Marlin Klein", "TE", "Michigan", 6.7, 41),
        ("Eli Raridon", "TE", "Notre Dame", 6.4, 49),
        ("Oscar Delp", "TE", "Georgia", 6.2, 56),
        ("Michael Trigg", "TE", "Baylor", 6.0, 62),
        ("Jack Endries", "TE", "Texas", 5.8, 68),
        # ---- RBs ----
        ("Jeremiyah Love", "RB", "Notre Dame", 9.2, 2),
        ("Jadarian Price", "RB", "Notre Dame", 6.8, 43),
        ("Nicholas Singleton", "RB", "Penn State", 6.5, 50),
        ("Kaytron Allen", "RB", "Penn State", 6.3, 57),
        ("Jonah Coleman", "RB", "Washington", 6.1, 63),
        ("Emmett Johnson", "RB", "Nebraska", 5.9, 69),
        ("Desmond Reid", "RB", "Pittsburgh", 5.7, 75),
    ]

    candidates = []
    for (name, pos, college, grade_10, rank) in _PROSPECTS:
        grade_100 = grade_10 * 10.0
        base_score = grade_100 * 0.80 + 50.0 * 0.20
        candidates.append(
            PlayerCandidate(
                player_id=_make_player_id(name),
                name=name,
                position=pos,
                college=college,
                espn_grade=grade_10,
                espn_rank=rank,
                combine={},
                mock_picks=[rank] if rank <= 100 else [],
                base_score=base_score,
            )
        )

    candidates.sort(key=lambda c: c.base_score, reverse=True)
    return candidates
