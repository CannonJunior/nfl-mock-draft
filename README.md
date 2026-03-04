# 2026 NFL Mock Draft

An analytics-driven web application predicting selections in the 2026 NFL Draft, covering all picks in rounds 1 through 3.

**Draft Location:** Pittsburgh, PA
**Draft Dates:** April 23–25, 2026

## Features

- Complete pick order for rounds 1–3 (~100 picks)
- NFL team logos with trade history visualization (smaller "via" logos for traded picks)
- Player data: biographical info, combine measurements, position, college
- Switchable stats views (Passing, Rushing, Receiving, Defense, Combine, etc.)
- Injury history expandable panel
- Media links: news articles, X/Twitter, Instagram, mock draft site coverage
- Scouting grade display
- Responsive NFL dark theme UI

## Setup

### Prerequisites
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager

### Installation

```bash
cd nfl-mock-draft
uv sync
```

### Running

```bash
uv run server.py
```

The app runs at **http://localhost:8988**

For development with auto-reload, set `DEBUG=true` in `.env`.

### Running Tests

```bash
uv run pytest tests/ -v
```

## Project Structure

```
nfl-mock-draft/
├── server.py              # FastAPI entry point (port 8988)
├── app/
│   ├── models.py          # Pydantic data models
│   ├── data_loader.py     # JSON data loading utilities
│   └── routes.py          # API + page route handlers
├── data/
│   ├── teams.json         # 32 NFL teams with logos and colors
│   ├── picks.json         # Draft pick order with trade history
│   └── players.json       # Player data (analytics-driven, TBD)
├── templates/
│   └── index.html         # Main Jinja2 UI template
├── static/
│   ├── css/style.css      # NFL dark theme stylesheet
│   └── js/app.js          # Frontend interactivity
└── tests/                 # Pytest unit tests
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Main UI page |
| `GET` | `/api/picks` | All picks (optional `?round=1\|2\|3`) |
| `GET` | `/api/picks/{n}` | Single pick by overall number |
| `GET` | `/api/teams` | All 32 NFL teams |
| `GET` | `/api/teams/{abbrev}` | Single team by ESPN abbreviation |
| `POST` | `/api/cache/clear` | Flush data cache |

## Configuration

All data is stored in `data/*.json` — no values are hardcoded in Python.

| File | Contents |
|------|---------|
| `data/teams.json` | Team names, cities, colors, ESPN logo URLs |
| `data/picks.json` | Pick order, round, trade history |
| `data/players.json` | Player data populated by analytics pipeline |

Port and host are configured in `.env`:
```
HOST=0.0.0.0
PORT=8988
DEBUG=false
```

## Adding Players

Populate `data/players.json` with player objects matching the `Player` schema:

```json
{
  "players": [
    {
      "player_id": "p001",
      "name": "Player Name",
      "position": "QB",
      "college": "University Name",
      "college_abbreviation": "espn_abbrev",
      "college_logo_url": "https://a.espncdn.com/i/teamlogos/ncaa/500/{id}.png",
      "bio": {
        "height_inches": 76,
        "weight_lbs": 218,
        "age": 21,
        "hometown": "City, State",
        "forty_yard_dash": 4.55
      },
      "grade": 9.2,
      "injury_history": [],
      "stat_views": [
        {
          "view_name": "Passing",
          "season": "2025",
          "stats": {"CMP%": "68.4", "YDS": 3842, "TD": 31, "INT": 7}
        }
      ],
      "media_links": [
        {
          "source_type": "news",
          "title": "Article headline",
          "url": "https://...",
          "source_name": "ESPN"
        }
      ]
    }
  ]
}
```

Then reference the player by setting `"player_id"` on the corresponding entry in `data/picks.json`.
