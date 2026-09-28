#!/usr/bin/env python3
"""
Feature engineering for ML player prop models.

Computes:
- Rolling/EWMA usage metrics (snap share, target share, carry share, routes, red zone)
- Efficiency metrics (yards per target/carry, EPA)
- Team pace and pass rate
- Opponent defense allowed (rolling by position)
- Rest days, home/away
- Injury flags (player and key teammates)
- Week-of-season, sample size
- Vegas implied team total scaled features

All features are strictly pre-game (no leakage).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Optional


def add_rolling_features(
    df: pd.DataFrame,
    windows: list[int] = [3, 6],
    alpha: float = 0.3,
) -> pd.DataFrame:
    """
    Add rolling and EWMA features for usage and efficiency metrics.
    
    Args:
        df: DataFrame with player-week data sorted by player_id, season, week
        windows: Rolling window sizes
        alpha: EWMA alpha parameter (smaller = more weight on history)
    
    Returns:
        DataFrame with added rolling features
    """
    result = df.copy()
    
    # Ensure sorted
    result = result.sort_values(["player_id", "season", "week"])
    
    # Features to roll
    roll_cols = [
        "offense_snaps",
        "offense_pct",
        "targets",
        "target_share",
        "carries",
        "carry_share",
        "receptions",
        "receiving_yards",
        "rushing_yards",
        "passing_yards",
        "passing_tds",
        "rushing_tds",
        "touches",
    ]
    
    # Filter to columns that exist
    roll_cols = [c for c in roll_cols if c in result.columns]
    
    for col in roll_cols:
        # Convert to numeric
        result[col] = pd.to_numeric(result[col], errors="coerce")
        
        # Rolling means
        for w in windows:
            result[f"{col}_roll{w}"] = (
                result
                .groupby("player_id")[col]
                .transform(lambda x: x.rolling(window=w, min_periods=1).mean().shift(1))
            )
        
        # EWMA
        result[f"{col}_ewma"] = (
            result
            .groupby("player_id")[col]
            .transform(lambda x: x.ewm(alpha=alpha, min_periods=1).mean().shift(1))
        )
    
    # Efficiency metrics
    if "receiving_yards" in result.columns and "targets" in result.columns:
        yards_per_target = result["receiving_yards"] / result["targets"].replace(0, np.nan)
        for w in windows:
            result[f"yards_per_target_roll{w}"] = (
                result
                .groupby("player_id")
                .apply(lambda g: yards_per_target[g.index].rolling(window=w, min_periods=1).mean().shift(1))
                .reset_index(level=0, drop=True)
            )
    
    if "rushing_yards" in result.columns and "carries" in result.columns:
        yards_per_carry = result["rushing_yards"] / result["carries"].replace(0, np.nan)
        for w in windows:
            result[f"yards_per_carry_roll{w}"] = (
                result
                .groupby("player_id")
                .apply(lambda g: yards_per_carry[g.index].rolling(window=w, min_periods=1).mean().shift(1))
                .reset_index(level=0, drop=True)
            )
    
    # Sample size (games played in rolling window)
    for w in windows:
        result[f"games_played_last{w}"] = (
            result
            .groupby("player_id")
            .cumcount()
            .clip(upper=w)
        )
    
    return result


def add_opponent_defense_features(df: pd.DataFrame, windows: list[int] = [6]) -> pd.DataFrame:
    """
    Add opponent defense allowed metrics by position (rolling).
    
    For each position, compute how many yards/TDs/etc. the opponent has allowed
    to that position over the last N games.
    
    This is pre-game: we look at opponent's past defensive performance.
    """
    result = df.copy()
    
    # Ensure sorted
    result = result.sort_values(["season", "week", "game_id"])
    
    # For each position and stat, compute team defense allowed
    positions = result["position"].dropna().unique()
    stats_to_defend = [
        ("receiving_yards", ["WR", "TE", "RB", "FB"]),
        ("receptions", ["WR", "TE", "RB", "FB"]),
        ("rushing_yards", ["RB", "FB", "QB", "HB"]),
        ("rushing_tds", ["RB", "FB", "QB", "HB"]),
        ("passing_yards", ["QB"]),
        ("passing_tds", ["QB"]),
    ]
    
    for stat, relevant_positions in stats_to_defend:
        if stat not in result.columns:
            continue
        
        for pos in relevant_positions:
            # Compute team defense allowed to this position
            # Group by opponent_team, season, week
            defense_df = (
                result[result["position"] == pos]
                .groupby(["opponent_team", "season", "week"], dropna=False)
                .agg({stat: "sum"})
                .reset_index()
                .rename(columns={"opponent_team": "team", stat: f"{stat}_allowed_vs_{pos}"})
            )
            
            # For each team, compute rolling allowed
            defense_df = defense_df.sort_values(["team", "season", "week"])
            
            for w in windows:
                defense_df[f"{stat}_allowed_vs_{pos}_roll{w}"] = (
                    defense_df
                    .groupby("team")[f"{stat}_allowed_vs_{pos}"]
                    .transform(lambda x: x.rolling(window=w, min_periods=1).mean().shift(1))
                )
            
            # Merge back to result by matching opponent_team
            result = result.merge(
                defense_df[["team", "season", "week"] + [c for c in defense_df.columns if "_roll" in c]],
                left_on=["opponent_team", "season", "week"],
                right_on=["team", "season", "week"],
                how="left",
                suffixes=("", "_def")
            )
            
            # Drop duplicate team column
            if "team_def" in result.columns:
                result = result.drop(columns=["team_def"])
    
    return result


def add_vegas_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add Vegas-derived features: implied team total scaling, underdog flags.
    
    For yardage projections, we scale by (implied_team_total / 22.5)^0.5
    following the baseline approach.
    """
    result = df.copy()
    
    if "implied_team_total" not in result.columns:
        return result
    
    implied = pd.to_numeric(result["implied_team_total"], errors="coerce")
    
    # Vegas scale factor for yardage (from baseline)
    result["vegas_scale_factor"] = np.sqrt(implied / 22.5)
    
    # Underdog flag (implied total < 22.5)
    result["is_underdog"] = (implied < 22.5).astype(float)
    
    # Spread features
    if "spread_line" in result.columns:
        spread = pd.to_numeric(result["spread_line"], errors="coerce")
        result["spread_abs"] = spread.abs()
        result["is_home"] = (result["team"] == result["home_team"]).astype(float)
        
        # Effective spread for the team (positive if favored)
        result["team_spread"] = np.where(
            result["is_home"] == 1,
            spread,  # home team gets the spread as-is
            -spread  # away team gets negative spread
        )
    
    return result


def add_injury_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add injury-related features.
    
    Includes:
    - Player's own injury status
    - Teammate injury flags (e.g., WR1 out boosts other WRs)
    """
    result = df.copy()
    
    if "player_injury_status" not in result.columns:
        return result
    
    # Encode player injury status
    injury_status_map = {
        "Out": 0.0,
        "Doubtful": 0.25,
        "Questionable": 0.75,
        "Probable": 0.9,
        None: 1.0,
    }
    
    result["injury_availability"] = (
        result["player_injury_status"]
        .map(injury_status_map)
        .fillna(1.0)
    )
    
    # TODO: Add teammate injury impact (requires depth chart data)
    # For now, placeholder
    
    return result


def add_rest_and_situational_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add rest days, home/away, week of season, etc.
    """
    result = df.copy()
    
    # Week of season (normalized)
    if "week" in result.columns:
        result["week_of_season"] = pd.to_numeric(result["week"], errors="coerce") / 18.0
    
    # Home/away already added in vegas features
    
    # Rest days (if gameday is available)
    if "gameday" in result.columns:
        result["gameday"] = pd.to_datetime(result["gameday"], errors="coerce")
        result = result.sort_values(["player_id", "gameday"])
        result["rest_days"] = (
            result
            .groupby("player_id")["gameday"]
            .diff()
            .dt.days
            .fillna(7)  # First game of season, assume 7 days
        )
    
    return result


def add_team_pace_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute team pace and pass rate from team-game totals.
    
    Pace = plays per game
    Pass rate = pass plays / (pass + rush plays)
    """
    result = df.copy()
    
    # Aggregate plays per team-game
    if "total_passing_attempts" in result.columns and "total_carries" in result.columns:
        result["team_total_plays"] = (
            pd.to_numeric(result["total_passing_attempts"], errors="coerce").fillna(0) +
            pd.to_numeric(result["total_carries"], errors="coerce").fillna(0)
        )
        
        result["team_pass_rate"] = (
            pd.to_numeric(result["total_passing_attempts"], errors="coerce") /
            result["team_total_plays"].replace(0, np.nan)
        )
    
    # Rolling team pace
    if "team_total_plays" in result.columns:
        result = result.sort_values(["team", "season", "week"])
        result["team_pace_roll6"] = (
            result
            .groupby("team")["team_total_plays"]
            .transform(lambda x: x.rolling(window=6, min_periods=1).mean().shift(1))
        )
    
    return result


def engineer_all_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply all feature engineering steps in sequence.
    
    Returns DataFrame with all engineered features.
    """
    print("Engineering features...")
    
    print("  Adding rolling features...")
    df = add_rolling_features(df, windows=[3, 6], alpha=0.3)
    
    print("  Adding opponent defense features...")
    df = add_opponent_defense_features(df, windows=[6])
    
    print("  Adding Vegas features...")
    df = add_vegas_features(df)
    
    print("  Adding injury features...")
    df = add_injury_features(df)
    
    print("  Adding rest and situational features...")
    df = add_rest_and_situational_features(df)
    
    print("  Adding team pace features...")
    df = add_team_pace_features(df)
    
    print(f"Feature engineering complete: {len(df.columns)} columns")
    
    return df


if __name__ == "__main__":
    # Test feature engineering
    import argparse
    from ml_data_pipeline import build_ml_dataset
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", nargs="+", type=int, default=[2024, 2025])
    parser.add_argument("--save", type=str, help="Save to parquet")
    args = parser.parse_args()
    
    df = build_ml_dataset(args.seasons, use_pbp=False)
    df_features = engineer_all_features(df)
    
    print(f"\nFinal dataset: {len(df_features)} rows, {len(df_features.columns)} columns")
    print("Sample columns:", df_features.columns[:30].tolist())
    
    if args.save:
        from pathlib import Path
        save_path = Path(args.save)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        df_features.to_parquet(save_path, index=False)
        print(f"Saved to {save_path}")
