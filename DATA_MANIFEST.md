# NFL Props Stats — Data Manifest

**ZERO fabricated numbers.** All rows come from nflverse public releases via `nflreadpy` (or local aggregations of those rows).

## Pull metadata

- **Pull timestamp (UTC):** `2026-09-23T05:16:51.337787+00:00`
- **Pull timestamp (PT):** 2026-09-22 22:16:51 PDT (PT)
- **Seasons requested:** [2023, 2024, 2025, 2026]
- **nflreadpy version:** `0.1.5`
- **nflverse current season / week (at pull):** 2026 / 3
- **Primary package docs:** https://nflreadpy.nflverse.com/
- **Upstream releases:** https://github.com/nflverse/nflverse-data/releases
- **Player stats dictionary:** https://nflreadr.nflverse.com/articles/dictionary_player_stats.html
- **Injuries dictionary:** https://nflreadr.nflverse.com/articles/dictionary_injuries.html
- **ESPN stats UI reference:** https://www.espn.com/nfl/stats
- **Photo URL sources:** nflverse players `headshot` plus the ESPN CDN pattern `https://a.espncdn.com/i/headshots/nfl/players/full/{int espn_id}.png`; actual assets are URL references, not scraped ESPN HTML.
- **Team logo source:** `nflreadpy.load_teams()` / nflverse teams table, including ESPN logo URLs.

## Errors

None — all requested pulls succeeded.

## Files

### `weekly_player_stats`

- **Source:** nflreadpy.load_player_stats / nflverse-data release tag stats_player
- **Package:** `nflreadpy`
- **Seasons present:** [2023, 2024, 2025, 2026]
- **Source URLs:**
  - https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2023.parquet
  - https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2024.parquet
  - https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2025.parquet
  - https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2026.parquet

| file | rows | cols | bytes |
| --- | ---: | ---: | ---: |
| `data/weekly_player_stats.parquet` | 59273 | 25 | 842674 |
| `data/weekly_player_stats.csv` | 59273 | 25 | 6522128 |
| `data/weekly_player_stats_full.parquet` | 59273 | 150 | 2351139 |
| `data/weekly_player_stats_full.csv` | 59273 | 150 | 27383248 |
| `data/player_season_game_counts.parquet` | 7564 | 7 | 95596 |
| `data/player_season_game_counts.csv` | 7564 | 7 | 313629 |

**Columns (weekly_player_stats):** `player_id`, `player_name`, `player_display_name`, `position`, `position_group`, `season`, `week`, `season_type`, `game_id`, `team`, `opponent_team`, `completions`, `attempts`, `passing_yards`, `passing_tds`, `passing_interceptions`, `carries`, `rushing_yards`, `rushing_tds`, `receptions`, `targets`, `receiving_yards`, `receiving_tds`, `fantasy_points`, `fantasy_points_ppr`

**Columns (weekly_player_stats_full):** `player_id`, `player_name`, `player_display_name`, `position`, `position_group`, `headshot_url`, `season`, `week`, `season_type`, `game_id`, `team`, `opponent_team`, `completions`, `attempts`, `passing_yards`, `passing_tds`, `passing_interceptions`, `sacks_suffered`, `sack_yards_lost`, `sack_fumbles`, `sack_fumbles_lost`, `passing_air_yards`, `passing_yards_after_catch`, `passing_first_downs`, `passing_epa`, `passing_cpoe`, `passing_2pt_conversions`, `pacr`, `passing_10`, `passing_16`, `passing_20`, `passing_40`, `carries`, `rushing_yards`, `rushing_tds`, `rushing_fumbles`, `rushing_fumbles_lost`, `rushing_first_downs`, `rushing_epa`, `rushing_2pt_conversions`, `rushing_10`, `rushing_12`, `rushing_20`, `rushing_40`, `receptions`, `targets`, `receiving_yards`, `receiving_tds`, `receiving_fumbles`, `receiving_fumbles_lost`, `receiving_air_yards`, `receiving_yards_after_catch`, `receiving_first_downs`, `receiving_epa`, `receiving_2pt_conversions`, `receiving_10`, `receiving_16`, `receiving_20`, `receiving_40`, `racr`, `target_share`, `air_yards_share`, `wopr`, `special_teams_tds`, `def_tackles_solo`, `def_tackles_with_assist`, `def_tackle_assists`, `def_tackles_for_loss`, `def_tackles_for_loss_yards`, `def_fumbles_forced`, `def_sacks`, `def_sack_yards`, `def_qb_hits`, `def_interceptions`, `def_interception_yards`, `def_pass_defended`, `def_tds`, `def_fumbles`, `def_safeties`, `def_punt_blocks`, `def_pat_blocks`, `def_fg_blocks`, `def_2pt_atts`, `def_2pt_made`, `misc_yards`, `fumble_recovery_own`, `fumble_recovery_yards_own`, `fumble_recovery_opp`, `fumble_recovery_yards_opp`, `fumble_recovery_tds`, `penalties`, `penalty_yards`, `fumbles_forced_by_opp`, `fumbles_not_forced`, `fumbles_out_of_bounds`, `fumbles_total`, `fumbles_lost_total`, `punt_returns`, `punt_return_yards`, `kickoff_returns`, `kickoff_return_yards`, `fg_made`, `fg_att`, `fg_missed`, `fg_blocked`, `fg_long`, `fg_pct`, `fg_made_0_19`, `fg_made_20_29`, `fg_made_30_39`, `fg_made_40_49`, `fg_made_50_59`, `fg_made_60_`, `fg_missed_0_19`, `fg_missed_20_29`, `fg_missed_30_39`, `fg_missed_40_49`, `fg_missed_50_59`, `fg_missed_60_`, `fg_made_list`, `fg_missed_list`, `fg_blocked_list`, `fg_made_distance`, `fg_missed_distance`, `fg_blocked_distance`, `pat_made`, `pat_att`, `pat_missed`, `pat_blocked`, `pat_pct`, `gwfg_made`, `gwfg_att`, `gwfg_missed`, `gwfg_blocked`, `gwfg_distance`, `pt_att`, `pt_blocked`, `pt_long`, `pt_yards`, `pt_inside_20`, `pt_out_of_bounds`, `pt_downed`, `pt_touchback`, `pt_fair_caught`, `pt_returned`, `pt_return_yards`, `pt_return_tds`, `pt_net_yards`, `fantasy_points`, `fantasy_points_ppr`

**Columns (player_season_game_counts):** `season`, `player_id`, `player_display_name`, `position`, `team`, `games_played`, `weeks`

### `players`

- **Source:** nflreadpy.load_players / nflverse-data release tag players
- **Package:** `nflreadpy`
- **Source URLs:**
  - https://github.com/nflverse/nflverse-data/releases/download/players/players.parquet
- **Notes:**
  - players_with_photos keeps every players.parquet column and adds espn_headshot_url plus photo_url = coalesce(headshot, espn_headshot_url).
  - nfl headshots are sourced from nflverse players; ESPN URLs use the CDN pattern with the source espn_id. No image binaries are downloaded.
  - Coverage: 24825/24830 rows have photo_url; 24659 nfl headshots; 16565 ESPN headshot URLs; 16399 have both; last_season>=2023 coverage 99.91% (4349/4353).

| file | rows | cols | bytes |
| --- | ---: | ---: | ---: |
| `data/players.parquet` | 24830 | 23 | 2251818 |
| `data/players.csv` | 24830 | 23 | 5375264 |
| `data/players_with_photos.parquet` | 24830 | 25 | 3080700 |
| `data/players_with_photos.csv` | 24830 | 25 | 8504061 |

**Columns (players):** `gsis_id`, `display_name`, `common_first_name`, `first_name`, `last_name`, `short_name`, `football_name`, `position_group`, `position`, `height`, `weight`, `college_name`, `jersey_number`, `rookie_season`, `last_season`, `latest_team`, `status`, `birth_date`, `espn_id`, `pfr_id`, `pff_id`, `nfl_id`, `headshot`

**Columns (players_with_photos):** `gsis_id`, `display_name`, `common_first_name`, `first_name`, `last_name`, `short_name`, `football_name`, `position_group`, `position`, `height`, `weight`, `college_name`, `jersey_number`, `rookie_season`, `last_season`, `latest_team`, `status`, `birth_date`, `espn_id`, `pfr_id`, `pff_id`, `nfl_id`, `headshot`, `espn_headshot_url`, `photo_url`

### `team_logos`

- **Source:** nflreadpy.load_teams / nflverse teams table (ESPN logo URLs)
- **Package:** `nflreadpy`
- **Source URLs:**
  - https://github.com/nflverse/nflverse-data/releases/tag/teams
- **Notes:**
  - Includes team_abbr, team_name, team_logo_espn, team_logo_wikipedia, team_logo_squared, team_wordmark, team_color, team_color2, and available conference/division fields from nflreadpy.load_teams.

| file | rows | cols | bytes |
| --- | ---: | ---: | ---: |
| `data/team_logos.parquet` | 36 | 16 | 15660 |
| `data/team_logos.csv` | 36 | 16 | 18919 |

**Columns (team_logos):** `team_abbr`, `team_name`, `team_logo_espn`, `team_logo_wikipedia`, `team_logo_squared`, `team_wordmark`, `team_color`, `team_color2`, `team_conf`, `team_division`, `team_id`, `team_nick`, `team_color3`, `team_color4`, `team_conference_logo`, `team_league_logo`

### `team_schedule`

- **Source:** nflreadpy.load_schedules / nflverse-data release tag schedules (games.parquet)
- **Package:** `nflreadpy`
- **Seasons present:** [2023, 2024, 2025, 2026]
- **Source URLs:**
  - https://github.com/nflverse/nflverse-data/releases/download/schedules/games.parquet

| file | rows | cols | bytes |
| --- | ---: | ---: | ---: |
| `data/team_schedule.parquet` | 1127 | 22 | 35865 |
| `data/team_schedule.csv` | 1127 | 22 | 142460 |

**Columns (team_schedule):** `game_id`, `season`, `game_type`, `week`, `gameday`, `weekday`, `gametime`, `away_team`, `home_team`, `away_score`, `home_score`, `location`, `result`, `total`, `overtime`, `away_rest`, `home_rest`, `stadium`, `roof`, `surface`, `temp`, `wind`

### `snap_counts`

- **Source:** nflreadpy.load_snap_counts / nflverse-data (PFR-derived snaps)
- **Package:** `nflreadpy`
- **Seasons present:** [2023, 2024, 2025, 2026]
- **Source URLs:**
  - https://github.com/nflverse/nflverse-data/releases/tag/snap_counts

| file | rows | cols | bytes |
| --- | ---: | ---: | ---: |
| `data/snap_counts.parquet` | 82761 | 16 | 667210 |
| `data/snap_counts.csv` | 82761 | 16 | 8235500 |

**Columns (snap_counts):** `game_id`, `pfr_game_id`, `season`, `game_type`, `week`, `player`, `pfr_player_id`, `position`, `team`, `opponent`, `offense_snaps`, `offense_pct`, `defense_snaps`, `defense_pct`, `st_snaps`, `st_pct`

### `injuries`

- **Source:** nflreadpy.load_injuries / nflverse-data release tag injuries
- **Package:** `nflreadpy`
- **Seasons present:** [2023, 2024, 2025, 2026]
- **Source URLs:**
  - https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_2023.parquet
  - https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_2024.parquet
  - https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_2025.parquet
  - https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_2026.parquet
- **Notes:**
  - Official NFL injury reports via nflverse; one row per player-team-week report.
  - Dictionary: https://nflreadr.nflverse.com/articles/dictionary_injuries.html

| file | rows | cols | bytes |
| --- | ---: | ---: | ---: |
| `data/injuries.parquet` | 18315 | 17 | 309600 |
| `data/injuries.csv` | 18315 | 17 | 2377776 |

**Columns (injuries):** `season`, `game_type`, `team`, `week`, `gsis_id`, `position`, `full_name`, `first_name`, `last_name`, `report_primary_injury`, `report_secondary_injury`, `report_status`, `practice_primary_injury`, `practice_secondary_injury`, `practice_status`, `date_modified`, `season_type`

### `player_usage`

- **Source:** DERIVED locally from weekly_player_stats + snap_counts (+ players pfr_id map) + injuries; ZERO fabricated rows
- **Package:** `nflreadpy (derived)`
- **Seasons present:** [2023, 2024, 2025, 2026]
- **Source URLs:**
  - https://github.com/nflverse/nflverse-data/releases/tag/stats_player
  - https://github.com/nflverse/nflverse-data/releases/tag/snap_counts
  - https://github.com/nflverse/nflverse-data/releases/tag/injuries
  - https://github.com/nflverse/nflverse-data/releases/tag/players
- **Notes:**
  - touches = carries + receptions (both columns present in nflverse weekly stats; not targets+carries)
  - target_share = targets / sum(targets) for same team-game_id week; carry_share = carries / sum(carries) for same team-game_id week (team totals from weekly stats; skipped only if team total is 0 → NA)
  - snaps joined via players.pfr_id == snap_counts.pfr_player_id + game_id; 59145/59273 weekly rows matched offense_snaps
  - injury_games_count = distinct weeks player appears in nflverse injuries for that season (any report/practice row); 0 if never listed

| file | rows | cols | bytes |
| --- | ---: | ---: | ---: |
| `data/player_usage_weekly.parquet` | 59273 | 31 | 1299539 |
| `data/player_usage_weekly.csv` | 59273 | 31 | 8875315 |
| `data/player_usage_season.parquet` | 7564 | 17 | 194675 |
| `data/player_usage_season.csv` | 7564 | 17 | 680169 |

**Columns (player_usage_weekly):** `player_id`, `player_name`, `player_display_name`, `position`, `position_group`, `season`, `week`, `season_type`, `game_id`, `team`, `opponent_team`, `offense_snaps`, `offense_pct`, `defense_snaps`, `defense_pct`, `st_snaps`, `st_pct`, `pfr_player_id`, `targets`, `receptions`, `receiving_yards`, `carries`, `rushing_yards`, `completions`, `attempts`, `passing_yards`, `touches`, `team_targets`, `team_carries`, `target_share`, `carry_share`

**Columns (player_usage_season):** `season`, `player_id`, `player_display_name`, `position`, `team`, `games_played`, `avg_offense_snaps`, `avg_offense_pct`, `avg_touches`, `avg_targets`, `avg_carries`, `avg_receptions`, `sum_touches`, `sum_targets`, `sum_carries`, `sum_offense_snaps`, `injury_games_count`

## Provenance notes

- Weekly player stats are produced by nflverse with `nflfastR::calculate_stats()` and published under the `stats_player` release tag.
- Schedules come from the `schedules` release (`games.parquet`).
- Players ID map comes from the `players` release.
- Snap counts are PFR-derived via nflverse `snap_counts`; if a season is missing upstream, that is recorded under Errors.
- Injuries come from the nflverse `injuries` release (`nflreadpy.load_injuries`).
- `player_season_game_counts` is a **local aggregation** of weekly rows (count of distinct weeks), not a separate upstream file.
- `player_usage_weekly` / `player_usage_season` are **local joins/aggregations** of weekly stats + snap counts (+ injuries). touches = carries + receptions (both columns present in nflverse weekly stats; not targets+carries).
- **No fabricated rows** — missing upstream data yields nulls / omitted files, never invented stats.


## Depth / roles / predictions / external (audit addendum 2026-09-23 PT)

These files exist on disk; provenance rules unchanged (nflverse or derived; ESPN/Vegas user-supplied only).

### `depth_charts` / `player_roles_current`

- **Source:** `nflreadpy.load_depth_charts` (+ derived `role_bucket`)
- **Files:** `data/depth_charts.parquet|csv`, `data/player_roles_current.parquet|csv`
- **role_bucket:** `starter` | `rotation` | `bench_warmer` (current snapshot counts at last refresh: see README)

### `predictions` / `grades`

- **Source:** MODEL ESTIMATES from `scripts/predict_week.py` (empirical-Bayes on nflverse trailing usage); grades from `scripts/grade_week.py` vs nflverse weekly actuals
- **Files:** `data/predictions/season{Y}_week{W}.*`, `data/grades/season{Y}_week{W}.*`
- **Lock:** `predictions_locked` in companion `.json` — do not overwrite without `--lock` / backup

### `external` (ESPN / Vegas)

- **Status at audit:** header-only CSVs → **not loaded** (never invent numbers)
- **Files:** `data/external/espn_projections.csv`, `vegas_lines.csv` (+ `*_template.csv`)

### `entries` / `guide`

- Build-my-card JSON under `data/entries/`; Guide log `data/guide/improvement_log.jsonl`
- `data/sports_news.json` is **optional** — created only after `scripts/refresh_sports_news.py`
