#!/usr/bin/env python3
"""
Refresh NFL player/team stats from nflverse (via nflreadpy).

Pulls real public data only — never fabricates numbers.
On source failure, records the error and continues with other datasets.

Usage (from repo root, with venv active):
  python scripts/refresh_nfl_stats.py
  python scripts/refresh_nfl_stats.py --seasons 2023 2024 2025 2026
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MANIFEST_PATH = ROOT / "DATA_MANIFEST.md"
ERRORS_PATH = DATA / "ingest_errors.json"
README_PATH = ROOT / "README.md"

# Prop-relevant columns kept in the curated weekly export (subset of full nflverse schema).
WEEKLY_PROP_COLS = [
    "player_id",
    "player_name",
    "player_display_name",
    "position",
    "position_group",
    "season",
    "week",
    "season_type",
    "game_id",
    "team",
    "opponent_team",
    # passing
    "completions",
    "attempts",
    "passing_yards",
    "passing_tds",
    "passing_interceptions",
    # rushing
    "carries",
    "rushing_yards",
    "rushing_tds",
    # receiving
    "receptions",
    "targets",
    "receiving_yards",
    "receiving_tds",
    # fantasy (handy for props work)
    "fantasy_points",
    "fantasy_points_ppr",
]

PLAYERS_KEEP = [
    "gsis_id",
    "display_name",
    "common_first_name",
    "first_name",
    "last_name",
    "short_name",
    "football_name",
    "position_group",
    "position",
    "height",
    "weight",
    "college_name",
    "jersey_number",
    "rookie_season",
    "last_season",
    "latest_team",
    "status",
    "birth_date",
    "espn_id",
    "pfr_id",
    "pff_id",
    "nfl_id",
    "headshot",
]

SCHEDULE_KEEP = [
    "game_id",
    "season",
    "game_type",
    "week",
    "gameday",
    "weekday",
    "gametime",
    "away_team",
    "home_team",
    "away_score",
    "home_score",
    "location",
    "result",
    "total",
    "overtime",
    "away_rest",
    "home_rest",
    "stadium",
    "roof",
    "surface",
    "temp",
    "wind",
]

INJURIES_KEEP = [
    "season",
    "game_type",
    "team",
    "week",
    "gsis_id",
    "position",
    "full_name",
    "first_name",
    "last_name",
    "report_primary_injury",
    "report_secondary_injury",
    "report_status",
    "practice_primary_injury",
    "practice_secondary_injury",
    "practice_status",
    "date_modified",
    "season_type",
]

# touches definition used throughout derived usage tables
TOUCHES_NOTE = (
    "touches = carries + receptions (both columns present in nflverse weekly stats; "
    "not targets+carries)"
)


def _now_labels() -> tuple[str, str]:
    """Return (UTC ISO, America/Los_Angeles labeled string)."""
    utc = datetime.now(timezone.utc)
    pt = utc.astimezone(ZoneInfo("America/Los_Angeles"))
    return utc.isoformat(), pt.strftime("%Y-%m-%d %H:%M:%S %Z") + " (PT)"


def _to_pandas(obj) -> pd.DataFrame:
    if isinstance(obj, pd.DataFrame):
        return obj
    # polars
    if hasattr(obj, "to_pandas"):
        return obj.to_pandas()
    raise TypeError(f"Unsupported frame type: {type(obj)}")


def _save_df(df: pd.DataFrame, stem: str) -> dict:
    DATA.mkdir(parents=True, exist_ok=True)
    parquet_path = DATA / f"{stem}.parquet"
    csv_path = DATA / f"{stem}.csv"
    df.to_parquet(parquet_path, index=False)
    df.to_csv(csv_path, index=False)
    return {
        "stem": stem,
        "rows": int(len(df)),
        "cols": int(df.shape[1]),
        "parquet": str(parquet_path.relative_to(ROOT)),
        "csv": str(csv_path.relative_to(ROOT)),
        "parquet_bytes": parquet_path.stat().st_size,
        "csv_bytes": csv_path.stat().st_size,
        "columns": list(df.columns),
    }


def _pick_cols(df: pd.DataFrame, wanted: list[str]) -> pd.DataFrame:
    present = [c for c in wanted if c in df.columns]
    missing = [c for c in wanted if c not in df.columns]
    if missing:
        print(f"  note: missing columns (skipped): {missing}", file=sys.stderr)
    return df[present].copy()


def pull_weekly(seasons: list[int], errors: list[dict]) -> dict | None:
    import nflreadpy as nfl

    print(f"Loading weekly player stats for seasons={seasons} ...")
    try:
        raw = _to_pandas(nfl.load_player_stats(seasons=seasons, summary_level="week"))
    except Exception as e:
        errors.append({"dataset": "weekly_player_stats", "error": repr(e)})
        print(f"  ERROR weekly_player_stats: {e}", file=sys.stderr)
        return None

    # Full dump for provenance / future props
    full_meta = _save_df(raw, "weekly_player_stats_full")
    curated = _pick_cols(raw, WEEKLY_PROP_COLS)
    curated_meta = _save_df(curated, "weekly_player_stats")

    # Game counts per player-season (derived from real weekly rows only)
    game_counts = (
        curated.groupby(
            ["season", "player_id", "player_display_name", "position", "team"],
            dropna=False,
        )
        .agg(games_played=("week", "nunique"), weeks=("week", "count"))
        .reset_index()
    )
    gc_meta = _save_df(game_counts, "player_season_game_counts")

    seasons_found = sorted(int(s) for s in curated["season"].dropna().unique())
    return {
        "name": "weekly_player_stats",
        "source": "nflreadpy.load_player_stats / nflverse-data release tag stats_player",
        "source_urls": [
            f"https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{s}.parquet"
            for s in seasons_found
        ],
        "package": "nflreadpy",
        "seasons": seasons_found,
        "files": [curated_meta, full_meta, gc_meta],
        "row_count_curated": curated_meta["rows"],
        "_df_weekly": curated,
    }


def _build_player_photos(players: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Add real nflverse/ESPN URL references without downloading image binaries."""
    out = players.copy()

    def espn_url(value) -> str | None:
        if pd.isna(value):
            return None
        try:
            number = float(value)
            if not number.is_integer():
                return None
            return f"https://a.espncdn.com/i/headshots/nfl/players/full/{int(number)}.png"
        except (TypeError, ValueError, OverflowError):
            return None

    out["espn_headshot_url"] = out["espn_id"].map(espn_url)
    nfl_headshot = out["headshot"].where(
        out["headshot"].notna()
        & out["headshot"].astype("string").str.strip().ne(""),
        pd.NA,
    )
    out["photo_url"] = nfl_headshot.combine_first(out["espn_headshot_url"])

    recent = (
        pd.to_numeric(out["last_season"], errors="coerce").ge(2023)
        if "last_season" in out
        else pd.Series(False, index=out.index)
    )
    coverage = {
        "rows": int(len(out)),
        "nfl_headshot_count": int(nfl_headshot.notna().sum()),
        "espn_headshot_count": int(out["espn_headshot_url"].notna().sum()),
        "both_headshot_count": int((nfl_headshot.notna() & out["espn_headshot_url"].notna()).sum()),
        "photo_url_count": int(out["photo_url"].notna().sum()),
        "last_season_ge_2023_rows": int(recent.sum()),
        "last_season_ge_2023_photo_url_count": int(out.loc[recent, "photo_url"].notna().sum()),
    }
    denom = coverage["last_season_ge_2023_rows"]
    coverage["last_season_ge_2023_photo_url_pct"] = (
        round(100.0 * coverage["last_season_ge_2023_photo_url_count"] / denom, 2)
        if denom
        else None
    )
    return out, coverage


def pull_players(errors: list[dict]) -> dict | None:
    import nflreadpy as nfl

    print("Loading players ...")
    try:
        raw = _to_pandas(nfl.load_players())
    except Exception as e:
        errors.append({"dataset": "players", "error": repr(e)})
        print(f"  ERROR players: {e}", file=sys.stderr)
        return None

    curated = _pick_cols(raw, PLAYERS_KEEP)
    meta = _save_df(curated, "players")
    try:
        # Read the just-written canonical table so the derived export is explicitly
        # built from data/players.parquet and retains every existing column.
        players_from_disk = pd.read_parquet(DATA / "players.parquet")
        photos, coverage = _build_player_photos(players_from_disk)
        photos_meta = _save_df(photos, "players_with_photos")
        both = photos[photos["headshot"].notna() & photos["espn_headshot_url"].notna()]
        print("Spot-check players with both headshot URLs:")
        for _, row in both[["display_name", "headshot", "espn_headshot_url"]].head(2).iterrows():
            print(f"  {row['display_name']}: nfl={row['headshot']} | espn={row['espn_headshot_url']}")
    except Exception as e:
        errors.append({"dataset": "players_with_photos", "error": repr(e)})
        print(f"  ERROR players_with_photos: {e}", file=sys.stderr)
        photos_meta = None
        coverage = {}

    result = {
        "name": "players",
        "source": "nflreadpy.load_players / nflverse-data release tag players",
        "source_urls": [
            "https://github.com/nflverse/nflverse-data/releases/download/players/players.parquet"
        ],
        "package": "nflreadpy",
        "files": [meta],
        "row_count": meta["rows"],
        "_df_players": curated,
    }
    if photos_meta:
        result["files"].append(photos_meta)
        result["photo_coverage"] = coverage
        result["notes"] = [
            "players_with_photos keeps every players.parquet column and adds "
            "espn_headshot_url plus photo_url = coalesce(headshot, espn_headshot_url).",
            "nfl headshots are sourced from nflverse players; ESPN URLs use the CDN pattern "
            "with the source espn_id. No image binaries are downloaded.",
            (
                f"Coverage: {coverage['photo_url_count']}/{coverage['rows']} rows have photo_url; "
                f"{coverage['nfl_headshot_count']} nfl headshots; "
                f"{coverage['espn_headshot_count']} ESPN headshot URLs; "
                f"{coverage['both_headshot_count']} have both; "
                f"last_season>=2023 coverage {coverage['last_season_ge_2023_photo_url_pct']}% "
                f"({coverage['last_season_ge_2023_photo_url_count']}/{coverage['last_season_ge_2023_rows']})."
            ),
        ]
    return result


def pull_teams(errors: list[dict]) -> dict | None:
    import nflreadpy as nfl

    print("Loading teams ...")
    try:
        raw = _to_pandas(nfl.load_teams())
        # Keep the complete load_teams table, including all currently available
        # conference/division and logo fields; this avoids dropping future fields.
        required = [
            "team_abbr", "team_name", "team_logo_espn", "team_logo_wikipedia",
            "team_logo_squared", "team_wordmark", "team_color", "team_color2",
            "team_conf", "team_division",
        ]
        missing = [c for c in required if c not in raw.columns]
        if missing:
            errors.append({"dataset": "team_logos", "error": f"required columns missing: {missing}"})
            print(f"  ERROR team_logos: required columns missing: {missing}", file=sys.stderr)
            return None
        # Explicit stable ordering for required fields, followed by any available
        # nflreadpy fields not yet documented here.
        ordered = required + [c for c in raw.columns if c not in required]
        teams = raw[ordered].copy()
        meta = _save_df(teams, "team_logos")
        print("Spot-check team ESPN logo URLs:")
        for _, row in teams[["team_abbr", "team_logo_espn"]].dropna(subset=["team_logo_espn"]).head(2).iterrows():
            print(f"  {row['team_abbr']}: {row['team_logo_espn']}")
        return {
            "name": "team_logos",
            "source": "nflreadpy.load_teams / nflverse teams table (ESPN logo URLs)",
            "source_urls": [
                "https://github.com/nflverse/nflverse-data/releases/tag/teams"
            ],
            "package": "nflreadpy",
            "files": [meta],
            "row_count": meta["rows"],
            "notes": [
                "Includes team_abbr, team_name, team_logo_espn, team_logo_wikipedia, "
                "team_logo_squared, team_wordmark, team_color, team_color2, and available "
                "conference/division fields from nflreadpy.load_teams."
            ],
        }
    except Exception as e:
        errors.append({"dataset": "team_logos", "error": repr(e)})
        print(f"  ERROR team_logos: {e}", file=sys.stderr)
        return None


def pull_schedule(seasons: list[int], errors: list[dict]) -> dict | None:
    import nflreadpy as nfl

    print(f"Loading schedules for seasons={seasons} ...")
    try:
        raw = _to_pandas(nfl.load_schedules(seasons=seasons))
    except Exception as e:
        errors.append({"dataset": "team_schedule", "error": repr(e)})
        print(f"  ERROR team_schedule: {e}", file=sys.stderr)
        return None

    curated = _pick_cols(raw, SCHEDULE_KEEP)
    meta = _save_df(curated, "team_schedule")
    seasons_found = sorted(int(s) for s in curated["season"].dropna().unique())
    return {
        "name": "team_schedule",
        "source": "nflreadpy.load_schedules / nflverse-data release tag schedules (games.parquet)",
        "source_urls": [
            "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.parquet"
        ],
        "package": "nflreadpy",
        "seasons": seasons_found,
        "files": [meta],
        "row_count": meta["rows"],
    }


def pull_snap_counts(seasons: list[int], errors: list[dict]) -> dict | None:
    import nflreadpy as nfl

    print(f"Loading snap counts for seasons={seasons} ...")
    try:
        raw = _to_pandas(nfl.load_snap_counts(seasons=seasons))
    except Exception as e:
        errors.append({"dataset": "snap_counts", "error": repr(e)})
        print(f"  ERROR snap_counts: {e}", file=sys.stderr)
        return None

    meta = _save_df(raw, "snap_counts")
    seasons_found = (
        sorted(int(s) for s in raw["season"].dropna().unique())
        if "season" in raw.columns
        else []
    )
    return {
        "name": "snap_counts",
        "source": "nflreadpy.load_snap_counts / nflverse-data (PFR-derived snaps)",
        "source_urls": [
            "https://github.com/nflverse/nflverse-data/releases/tag/snap_counts"
        ],
        "package": "nflreadpy",
        "seasons": seasons_found,
        "files": [meta],
        "row_count": meta["rows"],
        "_df_snaps": raw,
    }


def pull_injuries(seasons: list[int], errors: list[dict]) -> dict | None:
    import nflreadpy as nfl

    print(f"Loading injuries for seasons={seasons} ...")
    try:
        raw = _to_pandas(nfl.load_injuries(seasons=seasons))
    except Exception as e:
        errors.append({"dataset": "injuries", "error": repr(e)})
        print(f"  ERROR injuries: {e}", file=sys.stderr)
        return None

    curated = _pick_cols(raw, INJURIES_KEEP)
    meta = _save_df(curated, "injuries")
    seasons_found = (
        sorted(int(s) for s in curated["season"].dropna().unique())
        if "season" in curated.columns
        else []
    )
    return {
        "name": "injuries",
        "source": "nflreadpy.load_injuries / nflverse-data release tag injuries",
        "source_urls": [
            f"https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{s}.parquet"
            for s in seasons_found
        ]
        or ["https://github.com/nflverse/nflverse-data/releases/tag/injuries"],
        "package": "nflreadpy",
        "seasons": seasons_found,
        "files": [meta],
        "row_count": meta["rows"],
        "_df_injuries": curated,
        "notes": [
            "Official NFL injury reports via nflverse; one row per player-team-week report.",
            "Dictionary: https://nflreadr.nflverse.com/articles/dictionary_injuries.html",
        ],
    }



DEPTH_ROLE_NOTE = (
    "role_bucket from depth_order: starter if depth_order<=1 (or label contains "
    "'starter'); rotation if depth_order==2; bench_warmer if depth_order>=3 or "
    "practice. depth_order = legacy depth_team or ESPN pos_rank."
)

SKILL_POS = {"QB", "RB", "WR", "TE", "FB", "HB"}


def _role_bucket(depth_order, label: str | None = None) -> str:
    lab = (label or "").strip().lower()
    if "practice" in lab:
        return "bench_warmer"
    if "starter" in lab and "non" not in lab:
        return "starter"
    try:
        d = int(depth_order)
    except (TypeError, ValueError):
        return "bench_warmer"
    if d <= 1:
        return "starter"
    if d == 2:
        return "rotation"
    return "bench_warmer"


def _normalize_depth_legacy(raw: pd.DataFrame, season: int) -> pd.DataFrame:
    """Normalize 2023–2024 nflverse depth chart schema."""
    out = pd.DataFrame(
        {
            "season": pd.to_numeric(raw.get("season", season), errors="coerce").fillna(season).astype(int),
            "week": pd.to_numeric(raw["week"], errors="coerce") if "week" in raw.columns else pd.NA,
            "team": raw["club_code"].astype(str).str.upper() if "club_code" in raw.columns else pd.NA,
            "player_name": raw["full_name"] if "full_name" in raw.columns else pd.NA,
            "gsis_id": raw["gsis_id"] if "gsis_id" in raw.columns else pd.NA,
            "espn_id": pd.NA,
            "position": raw["position"] if "position" in raw.columns else pd.NA,
            "depth_position": raw["depth_position"] if "depth_position" in raw.columns else pd.NA,
            "depth_order": pd.to_numeric(raw["depth_team"], errors="coerce") if "depth_team" in raw.columns else pd.NA,
            "formation": raw["formation"] if "formation" in raw.columns else pd.NA,
            "game_type": raw["game_type"] if "game_type" in raw.columns else pd.NA,
            "jersey_number": raw["jersey_number"] if "jersey_number" in raw.columns else pd.NA,
            "snapshot_dt": pd.NA,
            "schema_version": "legacy_weekly",
            "source_season": season,
        }
    )
    return out


def _normalize_depth_espn(raw: pd.DataFrame, season: int) -> pd.DataFrame:
    """Normalize 2025+ ESPN-style depth chart schema; keep latest snapshot only."""
    if raw.empty or "dt" not in raw.columns:
        return pd.DataFrame()
    latest = raw["dt"].max()
    snap = raw[raw["dt"] == latest].copy()
    out = pd.DataFrame(
        {
            "season": int(season),
            "week": pd.NA,
            "team": snap["team"].astype(str).str.upper() if "team" in snap.columns else pd.NA,
            "player_name": snap["player_name"] if "player_name" in snap.columns else pd.NA,
            "gsis_id": snap["gsis_id"] if "gsis_id" in snap.columns else pd.NA,
            "espn_id": snap["espn_id"] if "espn_id" in snap.columns else pd.NA,
            "position": snap["pos_abb"] if "pos_abb" in snap.columns else pd.NA,
            "depth_position": snap["pos_name"] if "pos_name" in snap.columns else pd.NA,
            "depth_order": pd.to_numeric(snap["pos_rank"], errors="coerce") if "pos_rank" in snap.columns else pd.NA,
            "formation": snap["pos_grp"] if "pos_grp" in snap.columns else pd.NA,
            "game_type": pd.NA,
            "jersey_number": pd.NA,
            "snapshot_dt": snap["dt"],
            "schema_version": "espn_snapshot",
            "source_season": season,
        }
    )
    return out


def build_player_roles_current(depth: pd.DataFrame) -> pd.DataFrame:
    """One row per player on the current (latest-season) depth chart with role_bucket."""
    if depth.empty:
        return depth
    d = depth.copy()
    d = d[d["gsis_id"].notna() & (d["gsis_id"].astype(str).str.strip() != "")]
    max_season = int(pd.to_numeric(d["season"], errors="coerce").max())
    cur = d[pd.to_numeric(d["season"], errors="coerce") == max_season].copy()
    if "snapshot_dt" in cur.columns and cur["snapshot_dt"].notna().any():
        latest = cur["snapshot_dt"].dropna().max()
        cur = cur[(cur["snapshot_dt"] == latest) | cur["snapshot_dt"].isna()].copy()
    elif "week" in cur.columns and cur["week"].notna().any():
        max_week = pd.to_numeric(cur["week"], errors="coerce").max()
        cur = cur[pd.to_numeric(cur["week"], errors="coerce") == max_week].copy()

    # Prefer offensive skill listings when a player appears multiple times
    cur["_pos_u"] = cur["position"].astype(str).str.upper()
    cur["_skill"] = cur["_pos_u"].isin(SKILL_POS).astype(int)
    cur["_depth"] = pd.to_numeric(cur["depth_order"], errors="coerce")
    # offense formations preferred
    form = cur["formation"].astype(str).str.lower()
    cur["_off"] = (
        form.str.contains("wr|te|offense|3wr", regex=True, na=False)
        | cur["_pos_u"].isin(SKILL_POS)
    ).astype(int)
    cur = cur.sort_values(
        ["gsis_id", "_skill", "_off", "_depth"],
        ascending=[True, False, False, True],
    )
    one = cur.drop_duplicates(subset=["gsis_id"], keep="first").copy()

    labels = (
        one["depth_position"].astype(str).fillna("")
        + " "
        + one["formation"].astype(str).fillna("")
    )
    one["role_bucket"] = [
        _role_bucket(d, lab) for d, lab in zip(one["_depth"], labels)
    ]
    one["depth_order"] = one["_depth"]
    keep = [
        "season",
        "week",
        "team",
        "player_name",
        "gsis_id",
        "espn_id",
        "position",
        "depth_position",
        "depth_order",
        "role_bucket",
        "formation",
        "jersey_number",
        "snapshot_dt",
        "schema_version",
    ]
    out = one[[c for c in keep if c in one.columns]].copy()
    out = out.sort_values(["team", "role_bucket", "position", "depth_order", "player_name"])
    return out.reset_index(drop=True)


def pull_depth_charts(seasons: list[int], errors: list[dict]) -> dict | None:
    """Pull nflverse depth charts (legacy weekly + ESPN snapshots) and current roles."""
    import nflreadpy as nfl

    print(f"Loading depth charts for seasons={seasons} ...")
    frames: list[pd.DataFrame] = []
    source_urls: list[str] = []
    for season in seasons:
        try:
            raw = _to_pandas(nfl.load_depth_charts(seasons=season))
        except Exception as e:
            errors.append({"dataset": f"depth_charts_{season}", "error": repr(e)})
            print(f"  ERROR depth_charts season={season}: {e}", file=sys.stderr)
            continue
        if raw is None or raw.empty:
            errors.append({"dataset": f"depth_charts_{season}", "error": "empty frame"})
            continue
        if "depth_team" in raw.columns or "club_code" in raw.columns:
            norm = _normalize_depth_legacy(raw, season)
        elif "pos_rank" in raw.columns or "dt" in raw.columns:
            norm = _normalize_depth_espn(raw, season)
        else:
            errors.append(
                {
                    "dataset": f"depth_charts_{season}",
                    "error": f"unrecognized schema columns={list(raw.columns)}",
                }
            )
            continue
        frames.append(norm)
        source_urls.append(
            f"https://github.com/nflverse/nflverse-data/releases/download/depth_charts/depth_charts_{season}.parquet"
        )
        print(f"  season {season}: {len(norm)} normalized rows (schema={norm['schema_version'].iloc[0] if len(norm) else '?'})")

    if not frames:
        errors.append({"dataset": "depth_charts", "error": "no seasons loaded"})
        return None

    depth = pd.concat(frames, ignore_index=True)
    # role labels on full table for convenience
    depth_labels = (
        depth["depth_position"].astype(str).fillna("")
        + " "
        + depth["formation"].astype(str).fillna("")
    )
    depth["role_bucket"] = [
        _role_bucket(d, lab)
        for d, lab in zip(pd.to_numeric(depth["depth_order"], errors="coerce"), depth_labels)
    ]
    meta = _save_df(depth, "depth_charts")

    roles = build_player_roles_current(depth)
    roles_meta = _save_df(roles, "player_roles_current")
    counts = roles["role_bucket"].value_counts(dropna=False).to_dict() if len(roles) else {}
    print(f"  player_roles_current: {len(roles)} players; role counts={counts}")

    return {
        "name": "depth_charts",
        "source": "nflreadpy.load_depth_charts / nflverse-data release tag depth_charts",
        "source_urls": source_urls
        or ["https://github.com/nflverse/nflverse-data/releases/tag/depth_charts"],
        "package": "nflreadpy",
        "seasons": seasons,
        "files": [meta, roles_meta],
        "row_count": meta["rows"],
        "role_counts": {str(k): int(v) for k, v in counts.items()},
        "notes": [
            DEPTH_ROLE_NOTE,
            "Legacy seasons (≤2024): weekly club_code/depth_team schema kept for all weeks.",
            "ESPN seasons (≥2025): latest snapshot only retained per season (pos_rank → depth_order).",
            "player_roles_current: one row per gsis_id on the latest-season snapshot; skill/offense rows preferred.",
        ],
        "_df_depth": depth,
        "_df_roles": roles,
    }


def build_player_usage(
    weekly: pd.DataFrame,
    snaps: pd.DataFrame | None,
    players: pd.DataFrame | None,
    injuries: pd.DataFrame | None,
    errors: list[dict],
) -> dict | None:
    """
    Derive weekly + season player usage from real weekly stats + snap counts.

    touches = carries + receptions (documented; receptions always present in curated weekly).
    target_share / carry_share = player total / team-week total from same weekly table.
    """
    print("Building player_usage_weekly / player_usage_season ...")
    try:
        usage = weekly.copy()

        # Numeric fills only for share math; leave NaN where source was null (don't invent)
        for col in ("carries", "receptions", "targets", "completions", "attempts"):
            if col not in usage.columns:
                errors.append(
                    {
                        "dataset": "player_usage",
                        "error": f"required column missing from weekly: {col}",
                    }
                )
                return None

        # touches = carries + receptions (both present)
        usage["touches"] = usage["carries"].fillna(0) + usage["receptions"].fillna(0)
        # Preserve nullness when BOTH source cols were null
        both_null = usage["carries"].isna() & usage["receptions"].isna()
        usage.loc[both_null, "touches"] = pd.NA

        # Team-week totals for shares (from same real weekly rows)
        team_week = (
            usage.groupby(["season", "week", "season_type", "team", "game_id"], dropna=False)
            .agg(
                team_targets=("targets", "sum"),
                team_carries=("carries", "sum"),
            )
            .reset_index()
        )
        usage = usage.merge(
            team_week,
            on=["season", "week", "season_type", "team", "game_id"],
            how="left",
        )
        usage["target_share"] = usage["targets"] / usage["team_targets"].replace(0, pd.NA)
        usage["carry_share"] = usage["carries"] / usage["team_carries"].replace(0, pd.NA)

        # Join snaps via players.pfr_id <-> snap_counts.pfr_player_id + game_id
        snap_matched = 0
        snap_cols_added = [
            "offense_snaps",
            "offense_pct",
            "defense_snaps",
            "defense_pct",
            "st_snaps",
            "st_pct",
            "pfr_player_id",
        ]
        for c in snap_cols_added:
            usage[c] = pd.NA

        join_note = "snap join skipped (snaps or players unavailable)"
        if snaps is not None and players is not None and "pfr_id" in players.columns:
            id_map = players[["gsis_id", "pfr_id"]].dropna(subset=["gsis_id"]).drop_duplicates(
                "gsis_id"
            )
            usage = usage.merge(
                id_map, left_on="player_id", right_on="gsis_id", how="left"
            )
            if "gsis_id" in usage.columns:
                usage = usage.drop(columns=["gsis_id"])

            snap_keep = [
                c
                for c in [
                    "game_id",
                    "pfr_player_id",
                    "offense_snaps",
                    "offense_pct",
                    "defense_snaps",
                    "defense_pct",
                    "st_snaps",
                    "st_pct",
                ]
                if c in snaps.columns
            ]
            snap_sub = snaps[snap_keep].drop_duplicates(["game_id", "pfr_player_id"])
            # drop placeholder cols before merge
            usage = usage.drop(
                columns=[c for c in snap_cols_added if c in usage.columns],
                errors="ignore",
            )
            usage = usage.merge(
                snap_sub,
                left_on=["game_id", "pfr_id"],
                right_on=["game_id", "pfr_player_id"],
                how="left",
            )
            if "pfr_id" in usage.columns and "pfr_player_id" in usage.columns:
                # keep pfr_player_id from snaps; drop helper pfr_id if redundant
                usage = usage.drop(columns=["pfr_id"])
            snap_matched = int(usage["offense_snaps"].notna().sum()) if "offense_snaps" in usage.columns else 0
            join_note = (
                f"snaps joined via players.pfr_id == snap_counts.pfr_player_id + game_id; "
                f"{snap_matched}/{len(usage)} weekly rows matched offense_snaps"
            )
        else:
            errors.append(
                {
                    "dataset": "player_usage",
                    "error": "snaps and/or players missing — usage built without snap columns",
                }
            )

        # Column order for weekly usage
        weekly_cols = [
            "player_id",
            "player_name",
            "player_display_name",
            "position",
            "position_group",
            "season",
            "week",
            "season_type",
            "game_id",
            "team",
            "opponent_team",
            "offense_snaps",
            "offense_pct",
            "defense_snaps",
            "defense_pct",
            "st_snaps",
            "st_pct",
            "pfr_player_id",
            "targets",
            "receptions",
            "receiving_yards",
            "carries",
            "rushing_yards",
            "completions",
            "attempts",
            "passing_yards",
            "touches",
            "team_targets",
            "team_carries",
            "target_share",
            "carry_share",
        ]
        weekly_out = _pick_cols(usage, weekly_cols)
        weekly_meta = _save_df(weekly_out, "player_usage_weekly")

        # Season rollup
        agg_map = {
            "games_played": ("week", "nunique"),
            "avg_offense_snaps": ("offense_snaps", "mean"),
            "avg_offense_pct": ("offense_pct", "mean"),
            "avg_touches": ("touches", "mean"),
            "avg_targets": ("targets", "mean"),
            "avg_carries": ("carries", "mean"),
            "avg_receptions": ("receptions", "mean"),
            "sum_touches": ("touches", "sum"),
            "sum_targets": ("targets", "sum"),
            "sum_carries": ("carries", "sum"),
            "sum_offense_snaps": ("offense_snaps", "sum"),
        }
        # only agg columns that exist
        present_aggs = {k: v for k, v in agg_map.items() if v[0] in usage.columns}
        season = (
            usage.groupby(
                ["season", "player_id", "player_display_name", "position", "team"],
                dropna=False,
            )
            .agg(**present_aggs)
            .reset_index()
        )

        # injury_games_count: distinct weeks player appears on injury report that season
        if injuries is not None and "gsis_id" in injuries.columns:
            inj = injuries.dropna(subset=["gsis_id"]).copy()
            # Count distinct weeks with any injury report row (practice or game report)
            inj_counts = (
                inj.groupby(["season", "gsis_id"], dropna=False)
                .agg(injury_games_count=("week", "nunique"))
                .reset_index()
            )
            season = season.merge(
                inj_counts,
                left_on=["season", "player_id"],
                right_on=["season", "gsis_id"],
                how="left",
            )
            if "gsis_id" in season.columns:
                season = season.drop(columns=["gsis_id"])
            season["injury_games_count"] = (
                season["injury_games_count"].fillna(0).astype("int64")
            )
            inj_note = (
                "injury_games_count = distinct weeks player appears in nflverse injuries "
                "for that season (any report/practice row); 0 if never listed"
            )
        else:
            season["injury_games_count"] = pd.NA
            inj_note = "injury_games_count not joined (injuries unavailable)"

        season_meta = _save_df(season, "player_usage_season")
        seasons_found = sorted(int(s) for s in weekly_out["season"].dropna().unique())

        return {
            "name": "player_usage",
            "source": (
                "DERIVED locally from weekly_player_stats + snap_counts (+ players pfr_id map) "
                "+ injuries; ZERO fabricated rows"
            ),
            "source_urls": [
                "https://github.com/nflverse/nflverse-data/releases/tag/stats_player",
                "https://github.com/nflverse/nflverse-data/releases/tag/snap_counts",
                "https://github.com/nflverse/nflverse-data/releases/tag/injuries",
                "https://github.com/nflverse/nflverse-data/releases/tag/players",
            ],
            "package": "nflreadpy (derived)",
            "seasons": seasons_found,
            "files": [weekly_meta, season_meta],
            "notes": [
                TOUCHES_NOTE,
                "target_share = targets / sum(targets) for same team-game_id week; "
                "carry_share = carries / sum(carries) for same team-game_id week "
                "(team totals from weekly stats; skipped only if team total is 0 → NA)",
                join_note,
                inj_note,
            ],
        }
    except Exception as e:
        errors.append({"dataset": "player_usage", "error": repr(e)})
        print(f"  ERROR player_usage: {e}", file=sys.stderr)
        return None


def write_manifest(
    pull_ts_utc: str,
    pull_ts_pt: str,
    seasons_requested: list[int],
    results: list[dict],
    errors: list[dict],
    nflreadpy_version: str,
    current_season: int | None,
    current_week: int | None,
) -> None:
    lines: list[str] = []
    lines.append("# NFL Props Stats — Data Manifest")
    lines.append("")
    lines.append(
        "**ZERO fabricated numbers.** All rows come from nflverse public releases via "
        "`nflreadpy` (or local aggregations of those rows)."
    )
    lines.append("")
    lines.append("## Pull metadata")
    lines.append("")
    lines.append(f"- **Pull timestamp (UTC):** `{pull_ts_utc}`")
    lines.append(f"- **Pull timestamp (PT):** {pull_ts_pt}")
    lines.append(f"- **Seasons requested:** {seasons_requested}")
    lines.append(f"- **nflreadpy version:** `{nflreadpy_version}`")
    lines.append(
        f"- **nflverse current season / week (at pull):** {current_season} / {current_week}"
    )
    lines.append(f"- **Primary package docs:** https://nflreadpy.nflverse.com/")
    lines.append(
        f"- **Upstream releases:** https://github.com/nflverse/nflverse-data/releases"
    )
    lines.append(
        f"- **Player stats dictionary:** "
        f"https://nflreadr.nflverse.com/articles/dictionary_player_stats.html"
    )
    lines.append(
        f"- **Injuries dictionary:** "
        f"https://nflreadr.nflverse.com/articles/dictionary_injuries.html"
    )
    lines.append("- **ESPN stats UI reference:** https://www.espn.com/nfl/stats")
    lines.append(
        "- **Photo URL sources:** nflverse players `headshot` plus the ESPN CDN pattern "
        "`https://a.espncdn.com/i/headshots/nfl/players/full/{int espn_id}.png`; "
        "actual assets are URL references, not scraped ESPN HTML."
    )
    lines.append(
        "- **Team logo source:** `nflreadpy.load_teams()` / nflverse teams table, including ESPN logo URLs."
    )
    lines.append("")

    if errors:
        lines.append("## Errors (sources that failed)")
        lines.append("")
        for err in errors:
            lines.append(f"- **{err['dataset']}:** `{err['error']}`")
        lines.append("")
    else:
        lines.append("## Errors")
        lines.append("")
        lines.append("None — all requested pulls succeeded.")
        lines.append("")

    lines.append("## Files")
    lines.append("")
    for res in results:
        if not res:
            continue
        lines.append(f"### `{res['name']}`")
        lines.append("")
        lines.append(f"- **Source:** {res['source']}")
        lines.append(f"- **Package:** `{res.get('package', 'nflreadpy')}`")
        if res.get("seasons") is not None:
            lines.append(f"- **Seasons present:** {res['seasons']}")
        if res.get("source_urls"):
            lines.append("- **Source URLs:**")
            for u in res["source_urls"]:
                lines.append(f"  - {u}")
        if res.get("notes"):
            lines.append("- **Notes:**")
            for n in res["notes"]:
                lines.append(f"  - {n}")
        lines.append("")
        lines.append("| file | rows | cols | bytes |")
        lines.append("| --- | ---: | ---: | ---: |")
        for f in res.get("files", []):
            lines.append(
                f"| `{f['parquet']}` | {f['rows']} | {f['cols']} | {f['parquet_bytes']} |"
            )
            lines.append(
                f"| `{f['csv']}` | {f['rows']} | {f['cols']} | {f['csv_bytes']} |"
            )
        if res.get("files"):
            primary = res["files"][0]
            lines.append("")
            lines.append(
                f"**Columns ({primary['stem']}):** "
                + ", ".join(f"`{c}`" for c in primary["columns"])
            )
            if len(res["files"]) > 1:
                for f in res["files"][1:]:
                    lines.append("")
                    lines.append(
                        f"**Columns ({f['stem']}):** "
                        + ", ".join(f"`{c}`" for c in f["columns"])
                    )
        lines.append("")

    lines.append("## Provenance notes")
    lines.append("")
    lines.append(
        "- Weekly player stats are produced by nflverse with "
        "`nflfastR::calculate_stats()` and published under the `stats_player` release tag."
    )
    lines.append("- Schedules come from the `schedules` release (`games.parquet`).")
    lines.append("- Players ID map comes from the `players` release.")
    lines.append(
        "- Snap counts are PFR-derived via nflverse `snap_counts`; if a season is missing "
        "upstream, that is recorded under Errors."
    )
    lines.append(
        "- Injuries come from the nflverse `injuries` release "
        "(`nflreadpy.load_injuries`)."
    )
    lines.append(
        "- `player_season_game_counts` is a **local aggregation** of weekly rows "
        "(count of distinct weeks), not a separate upstream file."
    )
    lines.append(
        f"- `player_usage_weekly` / `player_usage_season` are **local joins/aggregations** "
        f"of weekly stats + snap counts (+ injuries). {TOUCHES_NOTE}."
    )
    lines.append("- **No fabricated rows** — missing upstream data yields nulls / omitted files, never invented stats.")
    lines.append("")

    MANIFEST_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {MANIFEST_PATH}")


def write_readme(
    pull_ts_pt: str | None = None,
    results: list[dict] | None = None,
    errors: list[dict] | None = None,
) -> None:
    """Refresh README layout/sources and current generated-file metadata."""
    text = """# NFL Props Stats

Real NFL player and team statistics for PrizePicks-style props analytics.

**Rule: ZERO fabricated numbers.** Every row is downloaded from public nflverse releases (or locally aggregated from those rows). If a source fails, the error is recorded in `DATA_MANIFEST.md` / `data/ingest_errors.json` — data is never invented.

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
| Player roles (current) | **Derived** from latest depth snapshot | `role_bucket` mapping in `refresh_nfl_stats.py` |

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
  requirements.txt
  .venv/                    # local virtualenv
  scripts/refresh_nfl_stats.py
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
    player_roles_current.parquet|csv         # one row/player: role_bucket on current depth
    predictions/                             # MODEL ESTIMATE week locks (predict_week.py)
    grades/                                  # post-week MAE / hit-rate (grade_week.py)
    sports_news.json                         # optional Google News RSS headlines
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

### `depth_charts` / `player_roles_current`
From `nflreadpy.load_depth_charts` (seasons 2023–2026):

- **Legacy (≤2024):** weekly `club_code` / `depth_team` / `position` rows kept for all weeks.
- **ESPN (≥2025):** latest snapshot only; `pos_rank` → `depth_order`, `pos_abb` → `position`.
- **`role_bucket` mapping:** `starter` if `depth_order<=1` (or label contains "starter"); `rotation` if `depth_order==2`; `bench_warmer` if `depth_order>=3` or practice. Documented in code as `DEPTH_ROLE_NOTE`.
- **`player_roles_current`:** one row per `gsis_id` on the latest-season snapshot (skill/offense preferred when duplicated).

## Weekly predictions (MODEL ESTIMATES)

Predictions are **Bayesian/heuristic posteriors from trailing usage**, clearly labeled **MODEL ESTIMATES** — never invented past results.

```bash
# Generate (and optionally lock) predictions for a week
./.venv/bin/python scripts/predict_week.py                  # current nflverse week
./.venv/bin/python scripts/predict_week.py --season 2026 --week 3
./.venv/bin/python scripts/predict_week.py --season 2026 --week 4 --lock

# After games: grade locked predictions vs actuals
./.venv/bin/python scripts/grade_week.py --season 2026 --week 2

# Lightweight live refresh: nflverse pieces + optional News RSS (no Google Sports HTML scrape)
./.venv/bin/python scripts/refresh_sports_news.py
```

Outputs: `data/predictions/season{Y}_week{W}.parquet` + `.json` lock (`locked_at`, `predictions_locked`), `data/grades/season{Y}_week{W}.*` + markdown critique.

### Web UI

```bash
./.venv/bin/python scripts/player_lookup_app.py
# http://127.0.0.1:5056/  (5056 if 5055 busy; Search | Weekly Predictions)
```

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
python scripts/refresh_nfl_stats.py --skip-depth
```

Default seasons: **2023, 2024, 2025, 2026** (2026 = season-to-date when available upstream).

After each pull, inspect `DATA_MANIFEST.md` for timestamps, row counts, and any errors.
"""
    metadata_lines = ["## Current generated data", ""]
    if pull_ts_pt:
        metadata_lines.append(f"- **Pull timestamp (PT):** {pull_ts_pt}")
    if results:
        metadata_lines.append("- **Rows by generated file:**")
        for res in results:
            for f in res.get("files", []):
                metadata_lines.append(f"  - `{f['parquet']}`: {f['rows']} rows")
    if errors:
        metadata_lines.append(f"- **Errors:** {len(errors)} (see `DATA_MANIFEST.md` and `data/ingest_errors.json`)")
    else:
        metadata_lines.append("- **Errors:** none")
    metadata_lines.append("")
    text = text.replace("## Sources", "\n".join(metadata_lines) + "\n## Sources", 1)
    README_PATH.write_text(text, encoding="utf-8")
    print(f"Wrote {README_PATH}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh NFL props stats from nflverse")
    parser.add_argument(
        "--seasons",
        nargs="+",
        type=int,
        default=[2023, 2024, 2025, 2026],
        help="Seasons to pull (default: 2023 2024 2025 2026)",
    )
    parser.add_argument(
        "--skip-snaps",
        action="store_true",
        help="Skip snap_counts pull",
    )
    parser.add_argument(
        "--skip-injuries",
        action="store_true",
        help="Skip injuries pull",
    )
    parser.add_argument(
        "--skip-depth",
        action="store_true",
        help="Skip depth charts / player_roles_current pull",
    )
    args = parser.parse_args()
    seasons = list(args.seasons)

    DATA.mkdir(parents=True, exist_ok=True)
    pull_ts_utc, pull_ts_pt = _now_labels()
    errors: list[dict] = []
    results: list[dict] = []

    try:
        import nflreadpy as nfl

        nflreadpy_version = getattr(nfl, "version", None) or getattr(
            __import__("importlib.metadata", fromlist=["version"]), "version"
        )("nflreadpy")
        if not isinstance(nflreadpy_version, str):
            try:
                from importlib.metadata import version as pkg_version

                nflreadpy_version = pkg_version("nflreadpy")
            except Exception:
                nflreadpy_version = str(nflreadpy_version)
        try:
            current_season = int(nfl.get_current_season())
            current_week = int(nfl.get_current_week())
        except Exception as e:
            current_season, current_week = None, None
            errors.append({"dataset": "get_current_season/week", "error": repr(e)})
    except Exception as e:
        print(f"FATAL: cannot import nflreadpy: {e}", file=sys.stderr)
        ERRORS_PATH.write_text(
            json.dumps([{"dataset": "nflreadpy", "error": repr(e)}], indent=2)
        )
        return 1

    weekly_df = None
    players_df = None
    snaps_df = None
    injuries_df = None

    res = pull_weekly(seasons=seasons, errors=errors)
    if res:
        weekly_df = res.pop("_df_weekly", None)
        results.append(res)

    res = pull_players(errors=errors)
    if res:
        players_df = res.pop("_df_players", None)
        results.append(res)

    res = pull_teams(errors=errors)
    if res:
        results.append(res)

    res = pull_schedule(seasons=seasons, errors=errors)
    if res:
        results.append(res)

    if not args.skip_snaps:
        res = pull_snap_counts(seasons=seasons, errors=errors)
        if res:
            snaps_df = res.pop("_df_snaps", None)
            results.append(res)

    if not args.skip_injuries:
        res = pull_injuries(seasons=seasons, errors=errors)
        if res:
            injuries_df = res.pop("_df_injuries", None)
            results.append(res)

    if not args.skip_depth:
        res = pull_depth_charts(seasons=seasons, errors=errors)
        if res:
            res.pop("_df_depth", None)
            res.pop("_df_roles", None)
            results.append(res)

    # Derived usage tables (need weekly at minimum)
    if weekly_df is not None:
        # Fall back to on-disk if a pull was skipped but file exists
        if snaps_df is None and (DATA / "snap_counts.parquet").exists() and not args.skip_snaps:
            try:
                snaps_df = pd.read_parquet(DATA / "snap_counts.parquet")
            except Exception as e:
                errors.append({"dataset": "player_usage_snaps_fallback", "error": repr(e)})
        if players_df is None and (DATA / "players.parquet").exists():
            try:
                players_df = pd.read_parquet(DATA / "players.parquet")
            except Exception as e:
                errors.append({"dataset": "player_usage_players_fallback", "error": repr(e)})
        if injuries_df is None and (DATA / "injuries.parquet").exists() and not args.skip_injuries:
            try:
                injuries_df = pd.read_parquet(DATA / "injuries.parquet")
            except Exception as e:
                errors.append({"dataset": "player_usage_injuries_fallback", "error": repr(e)})

        res = build_player_usage(
            weekly=weekly_df,
            snaps=snaps_df,
            players=players_df,
            injuries=injuries_df,
            errors=errors,
        )
        if res:
            results.append(res)
    else:
        errors.append(
            {
                "dataset": "player_usage",
                "error": "skipped — weekly_player_stats unavailable",
            }
        )

    ERRORS_PATH.write_text(json.dumps(errors, indent=2), encoding="utf-8")
    write_manifest(
        pull_ts_utc=pull_ts_utc,
        pull_ts_pt=pull_ts_pt,
        seasons_requested=seasons,
        results=results,
        errors=errors,
        nflreadpy_version=str(nflreadpy_version),
        current_season=current_season,
        current_week=current_week,
    )
    write_readme(pull_ts_pt=pull_ts_pt, results=results, errors=errors)

    ok = any(r and r.get("files") for r in results)
    if not ok:
        print("No datasets written.", file=sys.stderr)
        return 1

    print("Done.")
    for r in results:
        for f in r.get("files", []):
            print(f"  {f['parquet']}: {f['rows']} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
