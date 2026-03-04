# NFL Mock Draft 2026 - Context Engineering Prompt

## Project Overview
This is a web application predicting selections in the 2026 NFL Draft (rounds 1-3). The application displays mock draft predictions enriched with player analytics, biographical data, statistics, injury history, and media aggregation.

## Architecture Summary
- **Backend**: FastAPI (Python), port 8988
- **Frontend**: Vanilla HTML/CSS/JS with Jinja2 templating
- **Data Layer**: JSON config files (`data/`) — no database in v1
- **Package Manager**: `uv` (never use pip)
- **Virtual Environment**: `venv_linux`

## Key Files
| File | Purpose |
|------|---------|
| `server.py` | FastAPI entry point, port 8988 |
| `app/models.py` | Pydantic data models |
| `app/data_loader.py` | JSON data loading and caching |
| `app/routes.py` | API and page route handlers |
| `data/teams.json` | 32 NFL teams with logos, colors |
| `data/picks.json` | Draft pick order, rounds 1-3, trade history |
| `data/players.json` | Player data (analytics-driven, TBD) |
| `templates/index.html` | Main Jinja2 UI template |
| `static/css/style.css` | NFL dark theme styles |
| `static/js/app.js` | Frontend interactivity |

## Draft Data Source
2026 NFL Draft picks sourced from ESPN/NFL.com (as of March 2026):
- Round 1: 32 picks (4 traded: picks 13, 16, 20, 24)
- Round 2: 32 picks (+ potential compensatory)
- Round 3: 36+ picks (includes compensatory)
- Official compensatory picks announced ~March 3-7, 2026

## Key Trade History (Round 1)
| Pick | Current Team | Original Team | Trade Context |
|------|-------------|--------------|---------------|
| 13 | Rams | Falcons | Micah Parsons trade package |
| 16 | Jets | Colts | Sauce Gardner trade package |
| 20 | Cowboys | Packers | Micah Parsons trade package |
| 24 | Browns | Jaguars | TBD |

## Data Model Hierarchy
```
Pick
  ├── current_team → Team
  ├── traded_from → [Team, ...]  (pick trade chain)
  └── player → Player (nullable, set by analytics)
              ├── BiographicalInfo
              ├── [InjuryRecord, ...]
              ├── stats: {view_name: {stat_key: value}}
              └── [MediaLink, ...]
```

## UI Design Principles
- NFL dark theme: dark navy (#0d1117) background, white text
- Table-first layout with sticky round navigation tabs
- Logo display: current team large (48px), traded-from teams small (20px) with tooltip
- Player info expandable inline per row
- Stats views switchable (tabs): Overview, Passing, Rushing, Receiving, Defense, Combine
- Media links categorized: News, X/Twitter, Instagram, Mock Draft Sites
- Mobile-responsive

## Logo URLs
- NFL teams: `https://a.espncdn.com/i/teamlogos/nfl/500/{espn_abbrev}.png`
- College teams: `https://a.espncdn.com/i/teamlogos/ncaa/500/{espn_id}.png`

## Development Rules
- Never hardcode values — use JSON config files
- Port 8988 always
- All Python: PEP8, type hints, Google docstrings, pydantic validation
- Tests for every feature in `tests/` directory
- 500 line max per file — refactor if approaching limit

## Player Analytics Integration (Future)
Player selections (who gets picked where) will be driven by analytics algorithms.
The `data/players.json` file and `Player` model are designed to receive this data.
Fields with `null` values indicate TBD analytics input.
