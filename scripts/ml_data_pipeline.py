#!/usr/bin/env python3
"""
ML data pipeline: load and merge nflverse data for feature engineering.

Real data only from nflverse releases:
- weekly player stats
- snap counts
- play-by-play (for EPA, air yards, etc.)
- injuries
- depth charts
- schedule/games (spread_line, total_line, moneylines)
- rosters

Never fabricates numbers.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

try:
    from config import DATA_DIR
except ImportError:
    DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def load_weekly_stats(seasons: list[int]) -> pd.DataFrame:
    """Load nflverse weekly player stats for multiple seasons."""
    try:
        import nflreadpy as nfl
        
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df_pl = nfl.load_player_stats(seasons, summary_level="week")
        
        # Convert polars to pandas
        df = df_pl.to_pandas()
        
        if df.empty:
            return pd.DataFrame()
        
        # Ensure touches column
        if "touches" not in df.columns:
            carries = pd.to_numeric(df.get("carries"), errors="coerce").fillna(0)
            receptions = pd.to_numeric(df.get("receptions"), errors="coerce").fillna(0)
            df["touches"] = carries + receptions
        
        return df
    except Exception as e:
        print(f"Warning: Could not load weekly stats: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame()


def load_snap_counts(seasons: list[int]) -> pd.DataFrame:
    """Load nflverse snap counts."""
    try:
        import nflreadpy as nfl
        
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df_pl = nfl.load_snap_counts(seasons)
        
        df = df_pl.to_pandas()
        return df
    except Exception as e:
        print(f"Warning: Could not load snap counts: {e}")
        return pd.DataFrame()


def load_pbp(seasons: list[int]) -> pd.DataFrame:
    """Load play-by-play data for EPA and advanced metrics."""
    try:
        import nflreadpy as nfl
        
        print(f"  Loading PBP for {seasons}...")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df_pl = nfl.load_pbp(seasons)
        
        df = df_pl.to_pandas()
        return df
    except Exception as e:
        print(f"Warning: Could not load PBP: {e}")
        return pd.DataFrame()


def load_injuries(seasons: list[int]) -> pd.DataFrame:
    """Load nflverse injury reports."""
    try:
        import nflreadpy as nfl
        
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df_pl = nfl.load_injuries(seasons)
        
        df = df_pl.to_pandas()
        return df
    except Exception as e:
        print(f"Warning: Could not load injuries: {e}")
        return pd.DataFrame()


def load_schedules(seasons: list[int]) -> pd.DataFrame:
    """Load game schedule with Vegas lines (spread_line, total_line)."""
    try:
        import nflreadpy as nfl
        
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df_pl = nfl.load_schedules(seasons)
        
        df = df_pl.to_pandas()
        return df
    except Exception as e:
        print(f"Warning: Could not load schedules: {e}")
        return pd.DataFrame()


def load_depth_charts(seasons: list[int]) -> pd.DataFrame:
    """Load depth charts."""
    try:
        import nflreadpy as nfl
        
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df_pl = nfl.load_depth_charts(seasons)
        
        df = df_pl.to_pandas()
        return df
    except Exception as e:
        print(f"Warning: Could not load depth charts: {e}")
        return pd.DataFrame()


def load_rosters(seasons: list[int]) -> pd.DataFrame:
    """Load player rosters."""
    try:
        import nflreadpy as nfl
        
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df_pl = nfl.load_rosters(seasons)
        
        df = df_pl.to_pandas()
        return df
    except Exception as e:
        print(f"Warning: Could not load rosters: {e}")
        return pd.DataFrame()


def compute_team_game_totals(weekly: pd.DataFrame) -> pd.DataFrame:
    """
    Compute team-game totals for share calculations.
    Returns DataFrame with columns: season, week, game_id, team, total_targets, total_carries, etc.
    """
    if weekly.empty:
        return pd.DataFrame()
    
    agg_cols = {}
    if "targets" in weekly.columns:
        agg_cols["total_targets"] = pd.NamedAgg(column="targets", aggfunc="sum")
    if "carries" in weekly.columns:
        agg_cols["total_carries"] = pd.NamedAgg(column="carries", aggfunc="sum")
    if "receptions" in weekly.columns:
        agg_cols["total_receptions"] = pd.NamedAgg(column="receptions", aggfunc="sum")
    if "passing_attempts" in weekly.columns:
        agg_cols["total_passing_attempts"] = pd.NamedAgg(column="attempts", aggfunc="sum")
    
    if not agg_cols:
        return pd.DataFrame()
    
    team_totals = (
        weekly
        .groupby(["season", "week", "game_id", "team"], dropna=False)
        .agg(**agg_cols)
        .reset_index()
    )
    
    # Replace 0 with NaN to avoid division issues
    for col in team_totals.columns:
        if col.startswith("total_"):
            team_totals[col] = team_totals[col].replace(0, np.nan)
    
    return team_totals


def merge_snap_counts(weekly: pd.DataFrame, snaps: pd.DataFrame) -> pd.DataFrame:
    """Merge snap counts into weekly stats."""
    if snaps.empty:
        return weekly
    
    # Snap counts join via pfr_id + game_id
    # Weekly has player_id (gsis_id), need to map via rosters
    snap_cols = [
        "pfr_player_id", "game_id", "offense_snaps", "offense_pct",
        "defense_snaps", "defense_pct", "st_snaps", "st_pct"
    ]
    snap_cols = [c for c in snap_cols if c in snaps.columns]
    
    snaps_clean = snaps[snap_cols].copy()
    
    # Load rosters to map gsis_id to pfr_id
    try:
        seasons = sorted(weekly["season"].dropna().unique().astype(int))
        rosters = load_rosters(seasons)
        
        if not rosters.empty and "gsis_id" in rosters.columns and "pfr_id" in rosters.columns:
            id_map = rosters[["gsis_id", "pfr_id"]].drop_duplicates()
            weekly_with_pfr = weekly.merge(
                id_map,
                left_on="player_id",
                right_on="gsis_id",
                how="left"
            )
            
            merged = weekly_with_pfr.merge(
                snaps_clean,
                left_on=["pfr_id", "game_id"],
                right_on=["pfr_player_id", "game_id"],
                how="left"
            )
            
            # Drop temporary columns
            merged = merged.drop(columns=["pfr_id", "pfr_player_id"], errors="ignore")
            return merged
        else:
            print("Warning: Could not map gsis_id to pfr_id for snap counts")
            return weekly
    except Exception as e:
        print(f"Warning: Error merging snap counts: {e}")
        return weekly


def add_vegas_lines(weekly: pd.DataFrame, schedules: pd.DataFrame) -> pd.DataFrame:
    """
    Add Vegas spread and total lines to weekly stats.
    
    Note: spread_line in nfldata is positive when home team is favored.
    total_line is the over/under.
    """
    if schedules.empty:
        return weekly
    
    # Extract relevant columns from schedules
    schedule_cols = ["game_id", "spread_line", "total_line", "home_moneyline", "away_moneyline", "home_team", "away_team"]
    schedule_cols = [c for c in schedule_cols if c in schedules.columns]
    
    if "game_id" not in schedule_cols:
        return weekly
    
    sched_clean = schedules[schedule_cols].drop_duplicates("game_id")
    
    merged = weekly.merge(sched_clean, on="game_id", how="left", suffixes=("", "_sched"))
    
    # If team column doesn't exist in weekly, can't compute implied total
    if "team" not in merged.columns:
        return merged
    
    # Compute implied team total
    # For a given team, if they are home and spread_line is positive (favored), 
    # implied_team_total ≈ (total_line / 2) + (spread_line / 2)
    # If away, implied_team_total ≈ (total_line / 2) - (spread_line / 2)
    
    if "total_line" in merged.columns and "spread_line" in merged.columns:
        total = pd.to_numeric(merged["total_line"], errors="coerce")
        spread = pd.to_numeric(merged["spread_line"], errors="coerce")
        
        # Determine if team is home
        # Need to check which team column exists
        home_team_col = "home_team" if "home_team" in merged.columns else "home_team_sched"
        away_team_col = "away_team" if "away_team" in merged.columns else "away_team_sched"
        
        if home_team_col not in merged.columns:
            return merged
        
        is_home = merged["team"] == merged[home_team_col]
        
        # spread_line positive means home favored, so home gets +spread/2, away gets -spread/2
        merged["implied_team_total"] = np.where(
            is_home,
            (total / 2.0) + (spread / 2.0),
            (total / 2.0) - (spread / 2.0)
        )
    
    # Drop duplicate columns from merge
    for col in merged.columns:
        if col.endswith("_sched") and col[:-6] in merged.columns:
            merged = merged.drop(columns=[col])
    
    return merged


def add_injury_flags(weekly: pd.DataFrame, injuries: pd.DataFrame) -> pd.DataFrame:
    """
    Add injury status flags to weekly data.
    
    Returns weekly with additional columns:
    - player_injury_status: player's own injury status for that week
    """
    if injuries.empty:
        return weekly
    
    # Injuries have: gsis_id, season, week, report_status, report_primary_injury
    injury_cols = ["gsis_id", "season", "week", "report_status", "report_primary_injury"]
    injury_cols = [c for c in injury_cols if c in injuries.columns]
    
    if len(injury_cols) < 3:
        return weekly
    
    injuries_clean = injuries[injury_cols].copy()
    
    # Merge on player_id, season, week
    merged = weekly.merge(
        injuries_clean,
        left_on=["player_id", "season", "week"],
        right_on=["gsis_id", "season", "week"],
        how="left",
        suffixes=("", "_inj")
    )
    
    # Rename for clarity
    if "report_status" in merged.columns:
        merged = merged.rename(columns={"report_status": "player_injury_status"})
    if "report_primary_injury" in merged.columns:
        merged = merged.rename(columns={"report_primary_injury": "player_injury_type"})
    
    # Drop duplicate gsis_id column if present
    if "gsis_id_inj" in merged.columns:
        merged = merged.drop(columns=["gsis_id_inj"])
    
    return merged


def build_ml_dataset(seasons: list[int], use_pbp: bool = False) -> pd.DataFrame:
    """
    Build complete ML dataset with all features.
    
    Args:
        seasons: List of seasons to load
        use_pbp: If True, load PBP data for EPA features (slow)
    
    Returns:
        DataFrame with weekly stats and all engineered features
    """
    print(f"Loading data for seasons {seasons}...")
    
    # Load base datasets
    print("  Loading weekly stats...")
    weekly = load_weekly_stats(seasons)
    if weekly.empty:
        raise ValueError("No weekly stats loaded")
    
    print("  Loading snap counts...")
    snaps = load_snap_counts(seasons)
    
    print("  Loading schedules...")
    schedules = load_schedules(seasons)
    
    print("  Loading injuries...")
    injuries = load_injuries(seasons)
    
    # Merge snap counts
    if not snaps.empty:
        print("  Merging snap counts...")
        weekly = merge_snap_counts(weekly, snaps)
    
    # Add Vegas lines
    if not schedules.empty:
        print("  Adding Vegas lines...")
        weekly = add_vegas_lines(weekly, schedules)
    
    # Add injury flags
    if not injuries.empty:
        print("  Adding injury flags...")
        weekly = add_injury_flags(weekly, injuries)
    
    # Compute team-game totals for shares
    print("  Computing team totals for shares...")
    team_totals = compute_team_game_totals(weekly)
    
    if not team_totals.empty:
        weekly = weekly.merge(
            team_totals,
            on=["season", "week", "game_id", "team"],
            how="left"
        )
        
        # Compute shares
        if "targets" in weekly.columns and "total_targets" in weekly.columns:
            weekly["target_share"] = (
                pd.to_numeric(weekly["targets"], errors="coerce") / 
                pd.to_numeric(weekly["total_targets"], errors="coerce")
            )
        
        if "carries" in weekly.columns and "total_carries" in weekly.columns:
            weekly["carry_share"] = (
                pd.to_numeric(weekly["carries"], errors="coerce") / 
                pd.to_numeric(weekly["total_carries"], errors="coerce")
            )
        
        if "receptions" in weekly.columns and "total_receptions" in weekly.columns:
            weekly["reception_share"] = (
                pd.to_numeric(weekly["receptions"], errors="coerce") / 
                pd.to_numeric(weekly["total_receptions"], errors="coerce")
            )
    
    # Load PBP if requested (for EPA features)
    if use_pbp:
        print("  Loading PBP (this may take a while)...")
        pbp = load_pbp(seasons)
        if not pbp.empty:
            print("  Adding PBP features...")
            weekly = add_pbp_features(weekly, pbp)
    
    print(f"Dataset complete: {len(weekly)} player-week rows")
    return weekly


def add_pbp_features(weekly: pd.DataFrame, pbp: pd.DataFrame) -> pd.DataFrame:
    """
    Add play-by-play derived features (EPA, air yards, etc.) to weekly data.
    
    This is expensive but provides valuable signal.
    """
    # Aggregate EPA per player per game
    # For pass plays: passer_player_id gets passing EPA
    # For rush plays: rusher_player_id gets rushing EPA
    # For pass completions: receiver_player_id gets receiving EPA
    
    pass_plays = pbp[pbp["play_type"] == "pass"].copy()
    rush_plays = pbp[pbp["play_type"] == "run"].copy()
    
    agg_features = {}
    
    # Passing EPA
    if not pass_plays.empty and "passer_player_id" in pass_plays.columns and "epa" in pass_plays.columns:
        pass_epa = (
            pass_plays
            .groupby(["game_id", "passer_player_id"], dropna=False)
            .agg(
                passing_epa=pd.NamedAgg(column="epa", aggfunc="sum"),
                passing_epa_per_play=pd.NamedAgg(column="epa", aggfunc="mean"),
            )
            .reset_index()
            .rename(columns={"passer_player_id": "player_id"})
        )
        agg_features["passing_epa"] = pass_epa
    
    # Rushing EPA
    if not rush_plays.empty and "rusher_player_id" in rush_plays.columns and "epa" in rush_plays.columns:
        rush_epa = (
            rush_plays
            .groupby(["game_id", "rusher_player_id"], dropna=False)
            .agg(
                rushing_epa=pd.NamedAgg(column="epa", aggfunc="sum"),
                rushing_epa_per_play=pd.NamedAgg(column="epa", aggfunc="mean"),
            )
            .reset_index()
            .rename(columns={"rusher_player_id": "player_id"})
        )
        agg_features["rushing_epa"] = rush_epa
    
    # Receiving EPA and air yards
    if not pass_plays.empty and "receiver_player_id" in pass_plays.columns:
        rec_cols = {
            "receiving_epa": pd.NamedAgg(column="epa", aggfunc="sum"),
            "receiving_epa_per_target": pd.NamedAgg(column="epa", aggfunc="mean"),
        }
        if "air_yards" in pass_plays.columns:
            rec_cols["air_yards_total"] = pd.NamedAgg(column="air_yards", aggfunc="sum")
            rec_cols["air_yards_per_target"] = pd.NamedAgg(column="air_yards", aggfunc="mean")
        
        rec_epa = (
            pass_plays[pass_plays["receiver_player_id"].notna()]
            .groupby(["game_id", "receiver_player_id"], dropna=False)
            .agg(**rec_cols)
            .reset_index()
            .rename(columns={"receiver_player_id": "player_id"})
        )
        agg_features["receiving_epa"] = rec_epa
    
    # Merge all PBP features
    result = weekly
    for name, df in agg_features.items():
        result = result.merge(df, on=["game_id", "player_id"], how="left")
    
    return result


if __name__ == "__main__":
    # Test loading
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", nargs="+", type=int, default=[2024, 2025])
    parser.add_argument("--use-pbp", action="store_true")
    parser.add_argument("--save", type=str, help="Save to parquet file")
    args = parser.parse_args()
    
    df = build_ml_dataset(args.seasons, use_pbp=args.use_pbp)
    print(f"\nLoaded {len(df)} rows with {len(df.columns)} columns")
    print(f"Columns: {', '.join(df.columns[:20])}...")
    
    if args.save:
        save_path = Path(args.save)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(save_path, index=False)
        print(f"Saved to {save_path}")
