#!/usr/bin/env python3
"""
ML-powered weekly prop predictions with calibrated confidence.

Outputs per player-prop:
1. Median projection
2. 80% confidence interval (10th-90th percentile)
3. Calibrated P(over line) when line is provided
4. Confidence level based on sample size and model uncertainty

Replaces the simple empirical Bayes approach with real gradient boosting models.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

try:
    from config import ROOT, DATA_DIR as DATA, PRED_DIR, EXT_DIR, GRADES_DIR
except ImportError:
    ROOT = Path(__file__).resolve().parents[1]
    DATA = ROOT / "data"
    PRED_DIR = DATA / "predictions"
    EXT_DIR = DATA / "external"
    GRADES_DIR = DATA / "grades"

from ml_data_pipeline import build_ml_dataset
from ml_features import engineer_all_features
from ml_train import load_model_bundle, MODEL_DIR, POS_STATS


def _now_labels() -> tuple[str, str]:
    utc = datetime.now(timezone.utc)
    pt = utc.astimezone(ZoneInfo("America/Los_Angeles"))
    return utc.isoformat(), pt.strftime("%Y-%m-%d %H:%M:%S %Z") + " (PT)"


def load_week_slate(df: pd.DataFrame, season: int, week: int) -> pd.DataFrame:
    """
    Get all players playing in a given week with their features.
    
    Returns DataFrame with one row per player.
    """
    # Load team schedule to find games
    try:
        import nflreadpy as nfl
        schedules_pl = nfl.load_schedules([season])
        schedules = schedules_pl.to_pandas()
        week_games = schedules[(schedules["season"] == season) & (schedules["week"] == week)]
        
        if week_games.empty:
            print(f"No games found for season {season} week {week}")
            return pd.DataFrame()
        
        # Get teams playing
        teams_playing = set()
        for _, game in week_games.iterrows():
            teams_playing.add(str(game["away_team"]).upper())
            teams_playing.add(str(game["home_team"]).upper())
        
        print(f"Week {week} teams: {sorted(teams_playing)}")
        
    except Exception as e:
        print(f"Error loading schedule: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame()
    
    # Get active roster
    try:
        roles = pd.read_parquet(DATA / "player_roles_current.parquet")
        roles = roles[roles["team"].isin(teams_playing)].copy()
        
        # Filter to skill positions
        skill_positions = ["QB", "RB", "WR", "TE", "FB", "HB"]
        roles = roles[roles["position"].isin(skill_positions)]
        
        # Starters and rotation by default (user can request bench with flag)
        roles = roles[roles["role_bucket"].isin(["starter", "rotation"])]
        
        print(f"Found {len(roles)} active players (starters + rotation)")
        
        return roles
        
    except Exception as e:
        print(f"Error loading roles: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame()


def predict_player_props(
    player_id: str,
    position: str,
    df_features: pd.DataFrame,
    season: int,
    week: int,
) -> list[dict]:
    """
    Generate predictions for all relevant props for a player.
    
    Returns list of dicts with:
    - prop: stat name
    - median: median prediction
    - lower_80: 10th percentile
    - upper_80: 90th percentile  
    - confidence: low/medium/high based on sample size
    """
    # Get player's historical features (row before this week)
    player_data = df_features[
        (df_features["player_id"] == player_id) &
        (df_features["season"] == season) &
        (df_features["week"] < week)
    ].copy()
    
    if player_data.empty:
        # Use prior season if no current season data
        player_data = df_features[
            (df_features["player_id"] == player_id) &
            (df_features["season"] == season - 1)
        ].copy()
    
    if player_data.empty:
        return []
    
    # Use most recent row
    player_row = player_data.sort_values(["season", "week"]).iloc[[-1]]
    
    # Get relevant stats for position
    stats = POS_STATS.get(position, [])
    
    predictions = []
    
    for stat in stats:
        bundle = load_model_bundle(stat)
        if bundle is None:
            continue
        
        models = bundle["models"]
        feature_cols = bundle["feature_cols"]
        
        # Check if we have the features
        missing_features = [f for f in feature_cols if f not in player_row.columns]
        if missing_features:
            # Skip if too many missing
            if len(missing_features) / len(feature_cols) > 0.5:
                continue
        
        X = player_row[feature_cols].fillna(0)
        
        # Predict quantiles
        median = models[0.5].predict(X)[0]
        lower_80 = models[0.1].predict(X)[0]
        upper_80 = models[0.9].predict(X)[0]
        
        # Confidence based on sample size
        games_played = player_row.get("games_played_last6", pd.Series([0])).iloc[0]
        if games_played >= 6:
            confidence = "high"
        elif games_played >= 3:
            confidence = "medium"
        else:
            confidence = "low"
        
        predictions.append({
            "prop": stat,
            "median": round(float(median), 2),
            "lower_80": round(float(lower_80), 2),
            "upper_80": round(float(upper_80), 2),
            "confidence": confidence,
            "interval_width": round(float(upper_80 - lower_80), 2),
        })
    
    return predictions


def compute_prob_over(
    models: dict,
    calibrator,
    X: pd.DataFrame,
    line: float,
) -> float:
    """
    Compute calibrated P(over line) from quantile models.
    """
    # Get quantile predictions
    preds_10 = models[0.1].predict(X)[0]
    preds_25 = models[0.25].predict(X)[0]
    preds_50 = models[0.5].predict(X)[0]
    preds_75 = models[0.75].predict(X)[0]
    preds_90 = models[0.9].predict(X)[0]
    
    q_vals = [preds_10, preds_25, preds_50, preds_75, preds_90]
    q_levels = [0.1, 0.25, 0.5, 0.75, 0.9]
    
    # Estimate P(Y > line)
    if line <= q_vals[0]:
        p_under = 0.1 * (line / max(q_vals[0], 0.1))
    elif line >= q_vals[-1]:
        p_under = 0.9
    else:
        p_under = np.interp(line, q_vals, q_levels)
    
    prob_over_uncal = 1 - p_under
    
    # Apply calibration
    if calibrator is not None:
        prob_over_cal = calibrator.predict([prob_over_uncal])[0]
    else:
        prob_over_cal = prob_over_uncal
    
    return float(np.clip(prob_over_cal, 0.01, 0.99))


def build_week_predictions(
    season: int,
    week: int,
    include_bench: bool = False,
) -> tuple[pd.DataFrame, dict]:
    """
    Build ML predictions for a full week slate.
    
    Returns:
        (predictions_df, metadata)
    """
    print(f"Building ML predictions for season {season} week {week}...")
    
    # Load historical data up to but not including this week
    print("Loading historical data...")
    seasons_to_load = list(range(max(2018, season - 3), season + 1))
    df = build_ml_dataset(seasons_to_load, use_pbp=False)
    
    print("Engineering features...")
    df = engineer_all_features(df)
    
    # Get week slate
    print("Loading week slate...")
    slate = load_week_slate(df, season, week)
    
    if slate.empty:
        raise ValueError(f"No players found for week {week}")
    
    # If include_bench, reload slate with bench
    if include_bench:
        print("Including bench players...")
        # Re-load with bench
        try:
            roles = pd.read_parquet(DATA / "player_roles_current.parquet")
            import nflreadpy as nfl
            schedules = nfl.load_schedules([season])
            week_games = schedules[(schedules["season"] == season) & (schedules["week"] == week)]
            teams_playing = set()
            for _, game in week_games.iterrows():
                teams_playing.add(str(game["away_team"]).upper())
                teams_playing.add(str(game["home_team"]).upper())
            roles = roles[roles["team"].isin(teams_playing)]
            skill_positions = ["QB", "RB", "WR", "TE", "FB", "HB"]
            slate = roles[roles["position"].isin(skill_positions)].copy()
        except Exception as e:
            print(f"Error including bench: {e}")
    
    # Generate predictions for each player
    predictions_list = []
    
    for _, player in slate.iterrows():
        player_id = player["gsis_id"]
        position = player["position"]
        
        props = predict_player_props(player_id, position, df, season, week)
        
        for prop in props:
            predictions_list.append({
                "season": season,
                "week": week,
                "player_id": player_id,
                "player_name": player.get("player_name", ""),
                "team": player["team"],
                "position": position,
                "role_bucket": player.get("role_bucket", ""),
                "prop": prop["prop"],
                "median": prop["median"],
                "lower_80": prop["lower_80"],
                "upper_80": prop["upper_80"],
                "confidence": prop["confidence"],
                "interval_width": prop["interval_width"],
            })
    
    pred_df = pd.DataFrame(predictions_list)
    
    metadata = {
        "season": season,
        "week": week,
        "generated_at_utc": _now_labels()[0],
        "generated_at_pt": _now_labels()[1],
        "predictions_locked": False,
        "locked_at": None,
        "model_type": "LightGBM_quantile_regression",
        "row_count": len(pred_df),
        "player_count": pred_df["player_id"].nunique() if len(pred_df) > 0 else 0,
        "include_bench": include_bench,
    }
    
    return pred_df, metadata


def save_predictions(pred: pd.DataFrame, meta: dict, lock: bool) -> Path:
    """Save predictions to parquet and JSON metadata."""
    PRED_DIR.mkdir(parents=True, exist_ok=True)
    season, week = meta["season"], meta["week"]
    stem = f"season{season}_week{week}"
    parquet = PRED_DIR / f"{stem}.parquet"
    lock_path = PRED_DIR / f"{stem}_ml.json"
    
    if lock_path.exists():
        try:
            existing = json.loads(lock_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
        if existing.get("predictions_locked") and not lock:
            print(f"WARNING: {lock_path.name} is locked; refusing overwrite")
            raise SystemExit(2)
    
    if lock:
        utc, pt = _now_labels()
        meta["predictions_locked"] = True
        meta["locked_at"] = utc
        meta["locked_at_pt"] = pt
    
    pred.to_parquet(parquet, index=False)
    pred.to_csv(PRED_DIR / f"{stem}_ml.csv", index=False)
    lock_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    
    return parquet


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate ML weekly predictions")
    parser.add_argument("--season", type=int, default=None)
    parser.add_argument("--week", type=int, default=None)
    parser.add_argument("--lock", action="store_true")
    parser.add_argument("--include-bench", action="store_true")
    args = parser.parse_args()
    
    # Get current week if not specified
    if args.season is None or args.week is None:
        try:
            import nflreadpy as nfl
            cs, cw = int(nfl.get_current_season()), int(nfl.get_current_week())
            season = args.season or cs
            week = args.week or cw
        except:
            season = args.season or 2026
            week = args.week or 4
    else:
        season, week = args.season, args.week
    
    pred, meta = build_week_predictions(season, week, include_bench=args.include_bench)
    path = save_predictions(pred, meta, lock=args.lock)
    
    print(f"\nWrote {path} ({meta['row_count']} prop rows, {meta['player_count']} players)")
    print(f"Lock file: {PRED_DIR / f'season{season}_week{week}_ml.json'} locked={meta['predictions_locked']}")
    
    # Sample output
    if not pred.empty:
        print("\nSample predictions:")
        sample = pred.head(10)
        for _, row in sample.iterrows():
            print(f"  {row['player_name']} ({row['position']} {row['team']}) {row['prop']}: "
                  f"{row['median']:.1f} [{row['lower_80']:.1f}, {row['upper_80']:.1f}] "
                  f"({row['confidence']} confidence)")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
