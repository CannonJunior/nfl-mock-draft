"""
Unit tests for app/routes.py FastAPI endpoints.

Uses FastAPI TestClient to test HTTP behavior.
Covers:
  - Expected responses for happy paths
  - Edge cases (round filtering)
  - Failure cases (404 for unknown pick/team)
"""

from fastapi.testclient import TestClient

from server import app

client = TestClient(app)


# -----------------------------------------------------------------------
# GET / (index page)
# -----------------------------------------------------------------------


class TestIndexPage:
    """Tests for the main page route."""

    def test_returns_200(self):
        """GET / returns HTTP 200."""
        response = client.get("/")
        assert response.status_code == 200

    def test_returns_html(self):
        """GET / returns HTML content-type."""
        response = client.get("/")
        assert "text/html" in response.headers["content-type"]

    def test_contains_round_tabs(self):
        """GET / HTML contains round tab markup."""
        response = client.get("/")
        assert "round-tab" in response.text

    def test_contains_pick_rows(self):
        """GET / HTML contains at least one pick-row."""
        response = client.get("/")
        assert "pick-row" in response.text


# -----------------------------------------------------------------------
# GET /api/picks
# -----------------------------------------------------------------------


class TestGetAllPicks:
    """Tests for GET /api/picks."""

    def test_returns_200(self):
        """GET /api/picks returns HTTP 200."""
        response = client.get("/api/picks")
        assert response.status_code == 200

    def test_returns_100_picks(self):
        """GET /api/picks returns all 100 picks."""
        response = client.get("/api/picks")
        data = response.json()
        assert len(data) == 100

    def test_filter_round_1(self):
        """GET /api/picks?round=1 returns exactly 32 picks."""
        response = client.get("/api/picks?round=1")
        data = response.json()
        assert len(data) == 32
        assert all(item["pick"]["round"] == 1 for item in data)

    def test_filter_invalid_round(self):
        """GET /api/picks?round=5 returns 422 validation error."""
        response = client.get("/api/picks?round=5")
        assert response.status_code == 422

    def test_pick_structure(self):
        """Each pick item has expected top-level keys."""
        response = client.get("/api/picks?round=1")
        item = response.json()[0]
        assert "pick" in item
        assert "team" in item
        assert "traded_from_teams" in item


# -----------------------------------------------------------------------
# GET /api/picks/{pick_number}
# -----------------------------------------------------------------------


class TestGetSinglePick:
    """Tests for GET /api/picks/{pick_number}."""

    def test_pick_1_returns_raiders(self):
        """GET /api/picks/1 returns Las Vegas Raiders as current team."""
        response = client.get("/api/picks/1")
        assert response.status_code == 200
        data = response.json()
        assert data["team"]["abbreviation"] == "lv"

    def test_pick_13_has_traded_from(self):
        """GET /api/picks/13 shows Rams holding pick originally from Falcons."""
        response = client.get("/api/picks/13")
        assert response.status_code == 200
        data = response.json()
        assert data["team"]["abbreviation"] == "lar"
        traded = [t["abbreviation"] for t in data["traded_from_teams"]]
        assert "atl" in traded

    def test_nonexistent_pick_returns_404(self):
        """GET /api/picks/999 returns HTTP 404."""
        response = client.get("/api/picks/999")
        assert response.status_code == 404

    def test_pick_1_has_valid_player_or_null(self):
        """GET /api/picks/1 returns a pick with either a player object or null."""
        response = client.get("/api/picks/1")
        assert response.status_code == 200
        data = response.json()
        # player is None before predictions run; a dict with required keys after
        player = data["player"]
        if player is not None:
            assert "name" in player
            assert "position" in player
            assert "college" in player


# -----------------------------------------------------------------------
# GET /api/teams
# -----------------------------------------------------------------------


class TestGetAllTeams:
    """Tests for GET /api/teams."""

    def test_returns_200(self):
        """GET /api/teams returns HTTP 200."""
        response = client.get("/api/teams")
        assert response.status_code == 200

    def test_returns_32_teams(self):
        """GET /api/teams returns all 32 teams."""
        response = client.get("/api/teams")
        assert len(response.json()) == 32

    def test_teams_sorted_by_name(self):
        """GET /api/teams returns teams sorted alphabetically by name."""
        response = client.get("/api/teams")
        names = [t["name"] for t in response.json()]
        assert names == sorted(names)


# -----------------------------------------------------------------------
# GET /api/teams/{abbreviation}
# -----------------------------------------------------------------------


class TestGetSingleTeam:
    """Tests for GET /api/teams/{abbreviation}."""

    def test_raiders_lookup(self):
        """GET /api/teams/lv returns Las Vegas Raiders."""
        response = client.get("/api/teams/lv")
        assert response.status_code == 200
        assert response.json()["name"] == "Las Vegas Raiders"

    def test_case_insensitive(self):
        """GET /api/teams/LV (uppercase) still finds the team."""
        response = client.get("/api/teams/LV")
        assert response.status_code == 200

    def test_unknown_team_returns_404(self):
        """GET /api/teams/xyz returns HTTP 404."""
        response = client.get("/api/teams/xyz")
        assert response.status_code == 404


# -----------------------------------------------------------------------
# POST /api/cache/clear
# -----------------------------------------------------------------------


class TestCacheClear:
    """Tests for POST /api/cache/clear."""

    def test_returns_200(self):
        """POST /api/cache/clear returns HTTP 200."""
        response = client.post("/api/cache/clear")
        assert response.status_code == 200

    def test_returns_message(self):
        """POST /api/cache/clear returns a message key."""
        response = client.post("/api/cache/clear")
        assert "message" in response.json()
