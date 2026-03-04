# NFL Mock Draft 2026 - Architecture & Planning

## Project Goal
A web application predicting selections in the 2026 NFL Draft (rounds 1-3), featuring rich player data, analytics, and media aggregation.

## Tech Stack
- **Backend**: FastAPI (Python 3.11+)
- **Frontend**: Vanilla HTML/CSS/JS with Jinja2 templating
- **Data**: JSON config files (no database for initial version)
- **Package Manager**: uv
- **Port**: 8988

## Directory Structure
```
nfl-mock-draft/
├── CLAUDE.md                          # Project instructions
├── PLANNING.md                        # This file
├── TASK.md                            # Task tracker
├── README.md                          # Setup and usage guide
├── NFL-MOCK-DRAFT-CONTEXT-ENGINEERING-PROMPT.md  # Context doc
├── pyproject.toml                     # uv/Python project config
├── server.py                          # FastAPI app entry point
├── .env                               # Environment variables (gitignored)
├── app/
│   ├── __init__.py
│   ├── models.py                      # Pydantic data models
│   ├── routes.py                      # FastAPI route handlers
│   └── data_loader.py                 # JSON data loading utilities
├── data/
│   ├── teams.json                     # 32 NFL teams + logo URLs
│   ├── picks.json                     # All draft picks (rounds 1-3)
│   └── players.json                   # Player data (TBD by analytics)
├── static/
│   ├── css/
│   │   └── style.css                  # Main stylesheet
│   └── js/
│       └── app.js                     # Frontend interactivity
├── templates/
│   └── index.html                     # Main UI template
└── tests/
    ├── test_models.py
    ├── test_routes.py
    └── test_data_loader.py
```

## Data Models

### Team
- `abbreviation`: ESPN CDN abbreviation (e.g., "lv", "nyj")
- `name`: Full team name
- `city`: City/region
- `nickname`: Team nickname
- `primary_color`: Hex color for UI theming
- `secondary_color`: Hex color
- `logo_url`: ESPN CDN URL pattern

### Pick
- `pick_number`: Overall pick number (1-100+)
- `round`: Round number (1-3)
- `pick_in_round`: Pick within the round
- `current_team`: Team abbreviation making the pick
- `traded_from`: List of team abbreviations (pick history chain)
- `player`: Optional Player reference

### Player
- `name`: Player full name
- `position`: QB, RB, WR, TE, OT, OG, C, DE, DT, LB, CB, S
- `college`: College/university name
- `college_abbreviation`: For logo lookup
- `height_inches`: Height in inches
- `weight_lbs`: Weight in pounds
- `age`: Age at draft time
- `hometown`: Hometown, State
- `injury_history`: List of InjuryRecord
- `stats`: Dict of stat views
- `media_links`: List of MediaLink

## API Routes
- `GET /` - Serve main UI
- `GET /api/picks` - All picks (optional ?round= filter)
- `GET /api/picks/{pick_number}` - Single pick detail
- `GET /api/teams` - All team data
- `GET /api/teams/{abbreviation}` - Single team

## Logo Sources
- NFL Teams: `https://a.espncdn.com/i/teamlogos/nfl/500/{abbrev}.png`
- College Teams: `https://a.espncdn.com/i/teamlogos/ncaa/500/{id}.png`
- Fallback: `/static/images/logos/placeholder.png`

## UI Design
- NFL dark theme (dark navy/charcoal background)
- Responsive table layout with sticky header
- Round tabs (Round 1, Round 2, Round 3)
- Per-row expandable detail panel with:
  - Stats tabs (Overview, Passing, Rushing, Receiving, Defense)
  - Injury history collapsible
  - Media links grid

## Configuration
All configurable values live in JSON files, not hardcoded in Python.
Port 8988 is the only exception (defined in server.py via .env).
