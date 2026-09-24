# NFL Props Stats

Real NFL player and team statistics for PrizePicks-style props analytics.

**Web App:** https://traplandlord.github.io/nfl-props-stats/ — Use the live app on any device (phone/laptop).

**Project by:** [@traplandlord](https://github.com/traplandlord) (Valentino)

**Rule: ZERO fabricated numbers.** Every row is downloaded from public nflverse releases (or locally aggregated from those rows). If a source fails, the error is recorded in `DATA_MANIFEST.md` / `data/ingest_errors.json` — data is never invented.

## Current generated data

- **Pull timestamp (PT):** 2026-09-22 22:16:51 PDT (PT)
- **Rows by generated file:**
  - `data/weekly_player_stats.parquet`: 59273 rows
  - `data/weekly_player_stats_full.parquet`: 59273 rows
  - `data/player_season_game_counts.parquet`: 7564 rows
  - `data/players.parquet`: 24830 rows
  - `data/players_with_photos.parquet`: 24830 rows
  - `data/team_logos.parquet`: 36 rows
  - `data/team_schedule.parquet`: 1127 rows
  - `data/snap_counts.parquet`: 82761 rows
  - `data/injuries.parquet`: 18315 rows
  - `data/player_usage_weekly.parquet`: 59273 rows
  - `data/player_usage_season.parquet`: 7564 rows
- **Errors:** none
- **Depth / roles (later pull):** `data/depth_charts.parquet` + `data/player_roles_current.parquet` (role_bucket counts on current snapshot: starter 774 / rotation 620 / bench_warmer 584; 1978 players)
- **Predictions:** `data/predictions/season2026_week3.*` locked; week2 graded under `data/grades/`

## Sources

| Dataset | Upstream | Access |
| --- | --- | --- |
| Weekly player stats | [nflverse-data `stats_player`](https://github.com/nflverse/nflverse-data/releases/tag/stats_player) | `nflreadpy.load_player_stats` |
| Players | [nflverse-data `players`](https://github.com/nflverse/nflverse-data/releases/tag/players) | `nflreadpy.load_players` |
| Players with photos | **Derived URL table** from nflverse players + ESPN CDN pattern from `espn_id` | local build in `refresh_nfl_stats.py` |
| Team logos | nflverse teams table | `nflreadpy.load_teams` |
| Team schedule | [nflverse-data `schedules`](https://github.com/nflverse/nflverse-data/releases/tag/schedules) (`games.parquet`) | `nflreadpy.load_schedules` |
| Snap counts | [nflverse-data `snap_counts`](https://github.com/nflverse/nflverse-data/releases/tag/snap_counts) | `nflreadpy.load_snap_counts` |
| Injuries | [nflverse-data `injuries`](https://github.com/nflverse/nflverse-data/releases/tag/injuries) | `nflreadpy.load_injuries` |
| Player usage (weekly/season) | **Derived** from weekly stats + snap counts (+ injuries) | local join in `refresh_nfl_stats.py` |
| Depth charts | [nflverse-data `depth_charts`](https://github.com/nflverse/nflverse-data/releases/tag/depth_charts) | `nflreadpy.load_depth_charts` |
| Player roles (current) | **Derived** from latest depth snapshot | role_bucket in `refresh_nfl_stats.py` |
| ESPN projections (optional) | User-supplied CSV only | `data/external/espn_projections.csv` — never invented |
| Vegas lines (optional) | User-supplied CSV only | `data/external/vegas_lines.csv` — never invented |

- Python package: [`nflreadpy`](https://nflreadpy.nflverse.com/) (nflfastR / nflverse compatible)
- Direct HTTP example: `https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2025.parquet`
- ESPN stats UI reference: https://www.espn.com/nfl/stats
- Photo URLs use nflverse player `headshot` values and `https://a.espncdn.com/i/headshots/nfl/players/full/{int espn_id}.png`; this project does not scrape ESPN HTML or download image binaries.
- Team logos come from `nflreadpy.load_teams()` (nflverse team metadata with ESPN logo URLs).
- Column dictionary: https://nflreadr.nflverse.com/articles/dictionary_player_stats.html
- Injuries dictionary: https://nflreadr.nflverse.com/articles/dictionary_injuries.html

> Note: `nfl_data_py` was **not** used here because it pins `numpy<2`, which does not ship wheels for Python 3.13 on this box. `nflreadpy` is the current official Python client and hits the same nflverse releases.

## Layout

```
nfl-props-stats/
  README.md                 # this file
  DATA_MANIFEST.md          # row counts, URLs, pull timestamp
  AUDIT_NOTES.md            # quality audit scores + flaws
  QUALITY_SCORECARD.md      # before/after scores after restructure
  requirements.txt
  tests/test_smoke.py       # smoke tests (real data only)
  .venv/                    # local virtualenv
  scripts/
    refresh_nfl_stats.py
    player_lookup_app.py          # Flask UI (optional local server)
    config.py                     # HOST/PORT/DATA_DIR
    run_ui.sh / ui_healthcheck.py # launcher + health
    active_games/                # multi-sport active games
    guide_lib.py / guide_improve.py
  data/
    players.parquet|csv
    players_with_photos.parquet|csv        # all player columns + nfl/ESPN photo URLs
    team_logos.parquet|csv               # nflverse team metadata and logo URLs
    weekly_player_stats.parquet|csv          # prop-relevant columns
    weekly_player_stats_full.parquet|csv     # full nflverse weekly schema
    team_schedule.parquet|csv
    snap_counts.parquet|csv
    injuries.parquet|csv                     # nflverse injury reports
    player_usage_weekly.parquet|csv          # derived: snaps + touches + shares
    player_usage_season.parquet|csv          # derived: season rollup + injury weeks
    player_season_game_counts.parquet|csv    # derived: distinct weeks per player-season
    depth_charts.parquet|csv                 # nflverse depth (legacy weeks + ESPN latest)
    player_roles_current.parquet|csv         # one row/player: role_bucket
    predictions/                             # MODEL ESTIMATE week locks
    grades/                                  # post-week MAE / hit-rate
    external/                                # ESPN/Vegas templates + optional loads
    entries/                                 # Build-my-card JSON saves
    guide/                                   # Guide improvement_log.jsonl
    sports_news.json                         # optional; created by refresh_sports_news.py (may be absent)
    ingest_errors.json
```

## Schemas (curated)

### `players`
Player identity / roster metadata keyed by `gsis_id` (matches weekly `player_id`).

Key fields: `gsis_id`, `display_name`, `position`, `position_group`, `latest_team`, `status`, `rookie_season`, `last_season`, external IDs (`espn_id`, `pfr_id`, …).

### `players_with_photos`
URL-only photo table retaining every column from `players.parquet`, plus `espn_headshot_url` and `photo_url`. `photo_url` is the first non-null value of the nflverse `headshot` and ESPN CDN URL; no image files are stored.

### `team_logos`
Team metadata from `nflreadpy.load_teams()`, including `team_abbr`, `team_name`, ESPN/Wikipedia/Squared logos, wordmark, colors, and available conference/division fields.

### `weekly_player_stats`
One row per player-week-game with prop-relevant counting stats:

- IDs: `player_id`, `player_display_name`, `position`, `season`, `week`, `season_type`, `game_id`, `team`, `opponent_team`
- Passing: `completions`, `attempts`, `passing_yards`, `passing_tds`, `passing_interceptions`
- Rushing: `carries`, `rushing_yards`, `rushing_tds`
- Receiving: `receptions`, `targets`, `receiving_yards`, `receiving_tds`
- Bonus: `fantasy_points`, `fantasy_points_ppr`

Full upstream columns are in `weekly_player_stats_full.*`.

### `team_schedule`
One row per game: `game_id`, `season`, `week`, `game_type`, `gameday`, `away_team`, `home_team`, scores, venue/weather when present.

### `snap_counts`
Weekly offensive/defensive/ST snap counts and percentages (PFR-derived via nflverse). Field-time proxy: `offense_snaps`, `offense_pct`.

### `injuries`
Official NFL injury reports (nflverse): `gsis_id`, `full_name`, `team`, `season`, `week`, `report_status`, `report_primary_injury`, practice status/injury fields, `date_modified`.

### `player_usage_weekly` (derived)
Left-join of weekly stats ↔ snap counts via `players.pfr_id` + `game_id`. Includes:

- Field time: `offense_snaps`, `offense_pct` (plus defense/ST when present)
- Ball involvement: `targets`, `receptions`, `receiving_yards`, `carries`, `rushing_yards`, `completions`, `attempts`, `passing_yards`
- **`touches = carries + receptions`** (both columns present in weekly stats; not targets+carries)
- **`target_share` / `carry_share`**: player total ÷ team-game totals from the same weekly table (NA when team total is 0)

### `player_usage_season` (derived)
Per (`season`, `player_id`, `team`): `games_played`, `avg_offense_snaps`, `avg_touches`, `avg_targets`, `avg_carries`, sums, and `injury_games_count` (distinct weeks on the injury report that season; 0 if never listed).

### `player_season_game_counts`
**Derived locally** from weekly rows: `games_played` = count of distinct `week` values per (`season`, `player_id`, `team`).

## Setup & refresh

```bash
cd /workspace/nfl-props-stats
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/refresh_nfl_stats.py
# optional:
python scripts/refresh_nfl_stats.py --seasons 2024 2025 2026
python scripts/refresh_nfl_stats.py --skip-snaps
python scripts/refresh_nfl_stats.py --skip-injuries
```

Default seasons: **2023, 2024, 2025, 2026** (2026 = season-to-date when available upstream).

After each pull, inspect `DATA_MANIFEST.md` for timestamps, row counts, and any errors.

## Player lookup (local)

Fuzzy name search over `data/players.parquet` with headshot, team logo, jersey, and season/weekly stats from local parquet only (never invented).

### CLI

```bash
cd /workspace/nfl-props-stats
./.venv/bin/python scripts/lookup_player.py "Patrick Mahomes"
./.venv/bin/python scripts/lookup_player.py CMC
./.venv/bin/python scripts/lookup_player.py "McCaffrey" --pick 1
```

If several names match, the CLI lists them; pass `--pick N` to choose. Clear top matches (e.g. `Mahomes`, `CMC`) auto-select.

### Web App (GitHub Pages)

**Live app:** https://traplandlord.github.io/nfl-props-stats/

The web app runs entirely in your browser (phone or laptop) with no server required. It includes:

- **Search** — Find players, see stats, team, position, and role
- **Weekly Predictions** — Model predictions based on recent performance  
- **Build My Card** — Create PrizePicks-style player cards (2-6 players)
- **Guide** — Upcoming games and tips based on real data

All data loads from JSON files. Your card selections save in your browser's local storage.

### Running Flask UI Locally (Optional)

You can also run the original Flask UI on your own computer:

```bash
cd /workspace/nfl-props-stats
./scripts/run_ui.sh
# health: ./.venv/bin/python scripts/ui_healthcheck.py
```

Then open `http://127.0.0.1:5056/` in your browser.

Config: `scripts/config.py` — env `NFL_PROPS_HOST` (default `127.0.0.1`), `NFL_PROPS_PORT` (default `5056`), `NFL_PROPS_DATA`.

Nav: **Search | Weekly Predictions | Build my card | Guide**.

#### Weekly Predictions (4 layers)

Per player-prop columns: **Actuals | ESPN | Vegas | Ours | Flags**

1. **Actuals** — nflverse trailing stats (last 4–6 games before the week)
2. **ESPN** — from `data/external/espn_projections.csv` if filled; else label **ESPN: not loaded** (see `espn_projections_template.csv`). Never invent ESPN numbers.
3. **Vegas** — from `data/external/vegas_lines.csv` if filled; else **Vegas: not loaded**. Never invent lines/odds.
4. **Ours** — MODEL ESTIMATE (empirical-Bayes shrink of trailing usage toward position/team prior); shows mean ± sd
5. **Flags** — disagreement vs ESPN/Vegas when loaded; calibration MAE tags when `data/grades/` exist

Players grouped by team (logo + abbr), sorted **starter → rotation → bench_warmer**.


#### Guide (active games + challenge)

Open **Guide** at `http://127.0.0.1:5056/guide`.

1. **Active games** — NFL from `data/team_schedule.parquet` (today / in-progress heuristic + 72h upcoming). Team logos from `team_logos`. Multi-sport scaffold: `scripts/active_games/` (`nfl` live; `nba` / `mlb` stubs labeled **feed not connected**). Schedule cached in memory (~2 min TTL).
2. **Challenge the card** — loads `data/entries/*.json` and locked `data/predictions/`. Per prop: ours mean±sd, ESPN/Vegas (**not loaded** unless external CSVs filled), live/actual from latest `weekly_player_stats` for that season/week (never fake PBP), challenge **z-score** `(actual − mean) / sd`.
3. **Improve with reasoning** — `scripts/guide_improve.py` (+ UI button). Suggests MODEL ESTIMATE revisions only on real signals (injury / depth role / usage drift / huge residual) via empirical-Bayes shrinkage. Logs to `data/guide/improvement_log.jsonl`; `grade_week.py` later attaches outcomes.
4. Hardened: paginated locked-week mode, API error JSON, no full 59k scan per request (weekly slice cached).

```bash
./.venv/bin/python scripts/guide_improve.py --season 2026 --week 3
./.venv/bin/python scripts/guide_improve.py --season 2026 --week 2 --record-grades
```

`grade_week.py` also calls `record_grade_outcomes` after writing grades. If you add Guide suggestions *after* grading, re-run `--record-grades` so `data/guide/improvement_log.jsonl` outcomes are not left `null`.

#### Build my card (PrizePicks-style)

- Entry size **N = 2, 3, 4, 5, or 6**
- Players may be from **any mix of NFL teams** (same-team allowed, never required)
- Add/remove via debounced search or paginated team browser; **Randomize** samples league-wide weighted by role (starters/rotation preferred) + trailing-usage confidence
- Card shows photo, team logo, jersey, role, and our predicted props
- Persists to Flask session + `data/entries/*.json`
- Hardened: no unbounded weekly loads; paginated teams; API error JSON; search debounce 300ms

### Depth role mapping

From `nflreadpy.load_depth_charts` (2023–2026):

- Legacy (≤2024): `depth_team` → `depth_order`
- ESPN (≥2025): latest snapshot; `pos_rank` → `depth_order`
- **starter** if `depth_order <= 1` (or label contains "starter")
- **rotation** if `depth_order == 2`
- **bench_warmer** if `depth_order >= 3` or practice

Current snapshot role counts (all positions): see `data/player_roles_current.parquet`.

### Predictions / lock / grade / news

```bash
# Current or next week MODEL ESTIMATES
./.venv/bin/python scripts/predict_week.py
./.venv/bin/python scripts/predict_week.py --season 2026 --week 3 --include-bench --lock

# After games: grade locked week vs nflverse actuals
./.venv/bin/python scripts/grade_week.py --season 2026 --week 2

# Lightweight live refresh: nflverse injuries/depth/schedule/weekly + Google News RSS
# (NOT brittle Google Sports HTML scrape)
./.venv/bin/python scripts/refresh_sports_news.py
./.venv/bin/python scripts/refresh_nfl_stats.py --skip-depth   # or full refresh incl. depth
```

Outputs:

- `data/predictions/season{Y}_week{W}.parquet` + `.json` (`locked_at`, `predictions_locked`)
- `data/grades/season{Y}_week{W}.*` + `*_critique.md`
- `data/sports_news.json`

Shared lookup logic: `scripts/player_lookup_lib.py`. Entry builder: `scripts/entry_builder_lib.py`. Guide: `scripts/guide_lib.py`, `scripts/guide_improve.py`, `scripts/active_games/`.
