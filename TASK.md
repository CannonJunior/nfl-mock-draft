# NFL Mock Draft 2026 - Task Tracker

## Completed Tasks

### [DONE] Initial Project Build
**Date Added:** 2026-03-04
**Date Completed:** 2026-03-04
**Description:** Built the complete web application from scratch.

**Subtasks:**
- [x] Search for 2026 NFL draft pick order (rounds 1-3)
- [x] Create project structure and pyproject.toml
- [x] Create PLANNING.md architecture doc
- [x] Create data/teams.json (32 teams with ESPN logos + colors)
- [x] Create data/picks.json (100 picks, rounds 1-3, with trade history)
- [x] Create data/players.json (placeholder, empty — awaiting analytics)
- [x] Create app/models_core.py (Pydantic models — renamed to avoid package conflict)
- [x] Create app/models/__init__.py (re-exports from models_core)
- [x] Create app/data_loader.py (JSON loading with LRU cache)
- [x] Create app/routes.py (FastAPI page + API routes)
- [x] Create server.py (port 8988)
- [x] Create templates/index.html (NFL dark theme, round tabs, expandable rows)
- [x] Create static/css/style.css (full NFL dark theme)
- [x] Create static/js/app.js (tabs, expand/collapse, stats views)
- [x] Create tests/ — 92 tests, all passing
- [x] Create README.md
- [x] Create NFL-MOCK-DRAFT-CONTEXT-ENGINEERING-PROMPT.md
- [x] Install dependencies with uv sync
- [x] Verified 92/92 tests pass

## Discovered During Work (2026-03-04 analytics build)
- Synthetic player pool (103 confirmed 2026 prospects) added as fallback when DB is empty
- `POST /api/predictions/run?scrape=false` runs simulation only on existing DB data
- 154 tests passing after analytics engine added
- [DONE] Fixed scoring model: position weights tightened to 0.92–1.02 range so high-grade players at any position rank correctly
- [DONE] Created app/scrapers/college_stats.py — scrapes NFL.com prospect pages for season stats
- [DONE] Created app/scrapers/news.py — scrapes Google News RSS for 5 articles per player
- [DONE] Wired college_stats and news into runner.py pipeline (sources: "college_stats", "news")
- [DONE] simulator.py now populates bio (height/weight/arm/hand + combine), stat_views, and media_links from DB

## Discovered During Work
- Pick 13 (Round 1): Rams acquired from Falcons (Micah Parsons trade)
- Pick 16 (Round 1): Jets acquired from Colts (Sauce Gardner trade)
- Pick 20 (Round 1): Cowboys acquired from Packers (Micah Parsons trade)
- Pick 24 (Round 1): Browns acquired from Jaguars
- Picks 97-100 (Round 3): Marked as compensatory (official picks not released until ~March 7, 2026)
- College team logo IDs need ESPN numeric IDs — to be added with player data
- `app/models/` directory conflict: models.py renamed to models_core.py; models/__init__.py re-exports all classes
- Extra directories exist: app/api/, app/pipeline/, app/scrapers/ — contain scaffolding for future scraping pipeline

## Discovered During Work (2026-03-04 scraper fixes)
- [DONE] Fixed scoring model (all position weights = 1.0, need_boost max 3%) so grade dominates over position/need
- [DONE] Fixed all broken scraper URLs and HTML parsers for 2026 season:
  - tankathon.py: /nfl/full_draft + /nfl/mock_draft, CSS-class parsers (mock-row, full-draft-round-nfl)
  - espn.py: Kiper big board article, h2 regex parser for "N.Name, POS, College*" format
  - nfl_mock.py: Zierlein/Jeremiah 2.0 article URLs, nfl-o-ranked-item component parser
  - espn_mock.py: Kiper/Reid/Yates mock URLs, h2-team parser for "N.Team\n<p>Player, POS, College</p>" format
  - sharp.py: /rankings/nfl URL; nfl_com.py: /combine/ URL (JS-rendered, returns 0 gracefully)
- [DONE] Fixed player pool — supplements ESPN's 25 with mock-only players for 100+ prospect coverage
- [DONE] End-to-end simulation now assigns 100/100 picks with real scraped data
- nfl_com combine and nfl_prospects are JS-rendered — return 0 gracefully, not fixable with httpx

## Discovered During Work (2026-03-05 combine scraper)
- [DONE] Created app/scrapers/draft_countdown.py — scrapes draftcountdown.com (wpDataTable, 300+ prospects, server-rendered) with bigboardlab.com fallback (COMBINE_DATA JS array, 450+ prospects)
- [DONE] Added "draft_countdown" to ALL_SOURCES in runner.py
- [DONE] 35 new unit tests added; 189/189 total passing
- draftcountdown.com encoding: HGT=FIID (feet+inches+tenth), HAND/ARM=WW..N8 (whole+eighths), BJ=FII (feet+last2=inches)
- nfl_com combine scraper (existing) returns 0 records gracefully — JS-rendered; draft_countdown is now the primary combine source

## Discovered During Work (2026-03-05 grade + combine fixes)
- [DONE] Grade display revamped: never N/A; ESPN grade if available, else base_score/10 (min 3.5)
- [DONE] `_compute_display_grade()` and `_build_grade_breakdown()` added to simulator.py
- [DONE] `grade_breakdown` field added to Player model; written to players.json per player
- [DONE] Grade Analysis section added to expanded pick panel (formula, all signal components, base score)
- [DONE] Combine stat_view added to Statistics tab when combine data is present in DB
- [DONE] `grade-derived-label` "model" badge shown under grade circle when grade is model-derived
- [DONE] CSS added: .grade-analysis-box, .grade-source-pill, .grade-components-grid, .grade-derived-label
- Combine data will display once `draft_countdown` scraper runs (via POST /api/predictions/run)

## Discovered During Work (2026-03-06 college logos)
- [DONE] Created data/config/college_logo_map.json — maps ~90 lowercased college names to ESPN CDN numeric IDs
- [DONE] Downloaded 129 unique college logo PNGs to static/img/colleges/ (local, no CDN hits at runtime)
- [DONE] Added `_resolve_college_logo_url()` to simulator.py — resolves college name → /static/img/colleges/{id}.png
- [DONE] UAB ID corrected to 5 (was incorrectly 2439 which is UNLV); UNLV retains 2439; Old Dominion removed (ESPN 404)
- [DONE] 2 new tests in test_simulator.py; 191/191 total passing

## Discovered During Work (2026-03-06 Twitter/Social Buzz + NEW badges)
- [DONE] Created data/config/twitter_accounts.json — top 5 general experts + 3 per NFL team (32 teams)
- [DONE] Created app/scrapers/twitter_nitter.py — nitter-based Twitter scraper with 5 fallback instances; graceful on all-fail
- [DONE] Added "twitter" to ALL_SOURCES in runner.py; dispatches TwitterNitterScraper
- [DONE] Added `sources` query param to POST /api/predictions/run — limits scraping scope (e.g. ?sources=news,twitter)
- [DONE] Refresh Predictions button now calls ?scrape=true&sources=news,twitter; sets localStorage.nflMockLastRefresh
- [DONE] simulator.py splits articles into media_links (news/video) and tweets (twitter); both include fetched_at
- [DONE] Player model gains `tweets: Optional[list]` field; players.json updated
- [DONE] NEW badge on pick rows (disappears when row expanded); NEW badge on individual media/tweet items
- [DONE] Tweets section added to expanded pick card (Social Buzz, full-width below detail grid)
- [DONE] localStorage tracks lastRefresh + seenPicks for persistent badge state across reloads
- [DONE] 17 new tests in test_twitter_nitter.py; 208/208 total passing

## Discovered During Work (2026-03-15 grade normalization + scoring fixes)
- [DONE] Grade normalization: `_compute_display_grade()` rescales base_score [15,100] → display grade [6.5,9.9]
- [DONE] ESPN grade sanity check tightened: `expected_max = min(9.9, 10.0 - rank * 0.08)` (steeper ceiling rejects rank-17 grade 9.5 artifacts)
- [DONE] `_combine_score()` now returns `Optional[float]` (None when no drills); `_compute_base_score()` uses additive delta instead of neutral 50
- [DONE] `_count_combine_drills()` helper added; combine confidence scales with drill count (1/3, 2/3, 1.0)
- [DONE] models_core.py: `Pick.team_needs_snapshot: Optional[dict]` added
- [DONE] routes.py: `pick_team_histories` pre-computed for Team Needs section in UI
- [DONE] team_context.py: `_load_team_needs_from_config()` fallback + `_TEAM_NEEDS_CONFIG_PATH`
- [DONE] Restored all files reverted by git stash disaster; 255/255 tests passing

## Upcoming Tasks
- [x] Add web data ingestion pipeline (T-001 — completed 2026-03-04)
- [x] Add player analytics pipeline to populate data/players.json (completed 2026-03-04)
- [x] Source ESPN numeric IDs for college team logos (completed 2026-03-06)
- [ ] Update compensatory picks once NFL announces official 2026 comp picks (est. March 7, 2026)
- [ ] Add search/filter functionality to the UI (by team, position, round)
- [ ] Add a "my mock draft" mode where users can make their own picks
