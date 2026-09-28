#!/usr/bin/env python3
"""
Honest walk-forward backtest of ML models vs baseline.

Baseline (from user):
- Shrinkage blend: n games @ season avg + 3 games @ prior season avg
- Scaled by (Vegas implied total / 22.5)^0.5 for yardage
- 2025 weeks 3-18 performance:
  - MAE: passing_yards 66.6, passing_tds 1.00, receiving_yards 21.2, 
         receptions 1.58, rushing_yards 20.3
  - Median AE: 53.2 / 0.88 / 15.9 / 1.31 / 14.1

Test set: 2025 weeks 3-18 + 2026 weeks played
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

try:
    from config import DATA_DIR
except ImportError:
    DATA_DIR = Path(__file__).resolve().parents[1] / "data"

from ml_train import load_model_bundle, MODEL_DIR


def compute_baseline_prediction(
    player_stats: pd.DataFrame,
    player_id: str,
    season: int,
    week: int,
    stat: str,
    vegas_scale: Optional[float] = None,
) -> float:
    """
    Compute baseline prediction: shrinkage blend of current and prior season.
    
    Args:
        player_stats: DataFrame with historical stats
        player_id: Player ID
        season: Target season
        week: Target week
        stat: Stat to predict
        vegas_scale: Vegas scale factor (implied_total / 22.5)^0.5
    
    Returns:
        Baseline prediction
    """
    # Get current season games before target week
    current_season = player_stats[
        (player_stats["player_id"] == player_id) &
        (player_stats["season"] == season) &
        (player_stats["week"] < week)
    ]
    
    # Get prior season
    prior_season = player_stats[
        (player_stats["player_id"] == player_id) &
        (player_stats["season"] == season - 1)
    ]
    
    n_current = len(current_season)
    
    # Current season per-game average
    if n_current > 0:
        current_avg = current_season[stat].mean()
    else:
        current_avg = 0.0
    
    # Prior season per-game average
    if len(prior_season) > 0:
        prior_avg = prior_season[stat].mean()
    else:
        prior_avg = 0.0
    
    # Shrinkage blend: weight n @ current + 3 @ prior
    if n_current == 0:
        pred = prior_avg
    else:
        pred = (n_current * current_avg + 3 * prior_avg) / (n_current + 3)
    
    # Scale by Vegas factor for yardage stats
    if vegas_scale is not None and stat in ["passing_yards", "receiving_yards", "rushing_yards"]:
        pred *= vegas_scale
    
    return pred


def run_backtest(
    df: pd.DataFrame,
    test_seasons: list[int] = [2025, 2026],
    test_weeks_2025: Optional[list[int]] = None,
) -> pd.DataFrame:
    """
    Run honest backtest comparing ML models to baseline.
    
    Args:
        df: Full dataset with features
        test_seasons: Seasons to test on
        test_weeks_2025: Specific weeks for 2025 (default: 3-18)
    
    Returns:
        DataFrame with predictions and actuals
    """
    if test_weeks_2025 is None:
        test_weeks_2025 = list(range(3, 19))
    
    # Filter test data
    test_mask = (
        (df["season"].isin(test_seasons)) &
        ((df["season"] != 2025) | (df["week"].isin(test_weeks_2025)))
    )
    
    df_test = df[test_mask].copy()
    
    print(f"Backtest on {len(df_test)} player-weeks")
    
    # Stats to backtest
    stats = ["passing_yards", "passing_tds", "rushing_yards", "receiving_yards", "receptions"]
    
    results = []
    
    for stat in stats:
        print(f"\nBacktesting {stat}...")
        
        # Load model
        bundle = load_model_bundle(stat)
        if bundle is None:
            print(f"  No model found for {stat}, skipping")
            continue
        
        models = bundle["models"]
        feature_cols = bundle["feature_cols"]
        
        # Filter to rows with actual values
        df_stat = df_test[df_test[stat].notna()].copy()
        
        if df_stat.empty:
            print(f"  No test data for {stat}")
            continue
        
        print(f"  {len(df_stat)} test samples")
        
        # Make predictions
        X_test = df_stat[feature_cols].fillna(0)
        y_actual = df_stat[stat].values
        
        # ML predictions (median)
        ml_pred = models[0.5].predict(X_test)
        
        # Quantile predictions for intervals
        pred_10 = models[0.1].predict(X_test)
        pred_90 = models[0.9].predict(X_test)
        
        # Baseline predictions
        baseline_preds = []
        for _, row in df_stat.iterrows():
            vegas_scale = np.sqrt(row.get("implied_team_total", 22.5) / 22.5)
            baseline_pred = compute_baseline_prediction(
                df,
                row["player_id"],
                row["season"],
                row["week"],
                stat,
                vegas_scale=vegas_scale,
            )
            baseline_preds.append(baseline_pred)
        
        baseline_preds = np.array(baseline_preds)
        
        # Compute errors
        ml_errors = np.abs(y_actual - ml_pred)
        baseline_errors = np.abs(y_actual - baseline_preds)
        
        ml_mae = ml_errors.mean()
        baseline_mae = baseline_errors.mean()
        
        ml_median_ae = np.median(ml_errors)
        baseline_median_ae = np.median(baseline_errors)
        
        # Interval coverage
        coverage_80 = ((y_actual >= pred_10) & (y_actual <= pred_90)).mean()
        
        # Within-band rate (within median miss band)
        within_band_ml = (ml_errors <= baseline_median_ae).mean()
        
        print(f"  ML MAE: {ml_mae:.2f} | Baseline MAE: {baseline_mae:.2f} | Improvement: {baseline_mae - ml_mae:.2f}")
        print(f"  ML Median AE: {ml_median_ae:.2f} | Baseline Median AE: {baseline_median_ae:.2f}")
        print(f"  80% interval coverage: {coverage_80:.1%}")
        print(f"  % within baseline median band: {within_band_ml:.1%}")
        
        results.append({
            "stat": stat,
            "n_samples": len(df_stat),
            "ml_mae": ml_mae,
            "baseline_mae": baseline_mae,
            "improvement": baseline_mae - ml_mae,
            "ml_median_ae": ml_median_ae,
            "baseline_median_ae": baseline_median_ae,
            "coverage_80": coverage_80,
            "within_band_rate": within_band_ml,
        })
    
    return pd.DataFrame(results)


def evaluate_calibration(
    df: pd.DataFrame,
    test_seasons: list[int] = [2025, 2026],
) -> dict:
    """
    Evaluate probability calibration on test set with real or pseudo lines.
    
    Returns calibration table.
    """
    print("\nEvaluating calibration...")
    
    stats = ["passing_yards", "passing_tds", "rushing_yards", "receiving_yards", "receptions"]
    
    calibration_results = {}
    
    for stat in stats:
        bundle = load_model_bundle(stat)
        if bundle is None or bundle.get("calibrator") is None:
            continue
        
        models = bundle["models"]
        feature_cols = bundle["feature_cols"]
        calibrator = bundle["calibrator"]
        
        df_stat = df[
            df["season"].isin(test_seasons) &
            df[stat].notna()
        ].copy()
        
        if df_stat.empty:
            continue
        
        X_test = df_stat[feature_cols].fillna(0)
        y_actual = df_stat[stat].values
        
        # Get quantile predictions
        preds_10 = models[0.1].predict(X_test)
        preds_25 = models[0.25].predict(X_test)
        preds_50 = models[0.5].predict(X_test)
        preds_75 = models[0.75].predict(X_test)
        preds_90 = models[0.9].predict(X_test)
        
        # Use median prediction as pseudo-line
        test_lines = preds_50
        
        # Compute uncalibrated P(over)
        prob_over_uncal = []
        actual_over = []
        
        for i in range(len(test_lines)):
            line = test_lines[i]
            actual = y_actual[i]
            
            q_vals = [preds_10[i], preds_25[i], preds_50[i], preds_75[i], preds_90[i]]
            q_levels = [0.1, 0.25, 0.5, 0.75, 0.9]
            
            if line <= q_vals[0]:
                p_under = 0.1 * (line / max(q_vals[0], 0.1))
            elif line >= q_vals[-1]:
                p_under = 0.9
            else:
                p_under = np.interp(line, q_vals, q_levels)
            
            prob_over_uncal.append(1 - p_under)
            actual_over.append(float(actual > line))
        
        prob_over_uncal = np.array(prob_over_uncal).clip(0.01, 0.99)
        actual_over = np.array(actual_over)
        
        # Apply calibration
        prob_over_cal = calibrator.predict(prob_over_uncal)
        
        # Reliability table
        bins = [(0.5, 0.55), (0.55, 0.6), (0.6, 0.65), (0.65, 0.7), (0.7, 0.75), (0.75, 0.8), (0.8, 1.0)]
        table = []
        
        for low, high in bins:
            mask = (prob_over_cal >= low) & (prob_over_cal < high)
            if mask.sum() >= 5:
                actual_rate = actual_over[mask].mean()
                count = mask.sum()
                table.append({
                    "bin": f"{low:.0%}-{high:.0%}",
                    "predicted": (low + high) / 2,
                    "actual": actual_rate,
                    "count": count,
                })
        
        if table:
            calibration_results[stat] = pd.DataFrame(table)
            print(f"\n{stat} calibration:")
            print(calibration_results[stat].to_string(index=False))
    
    return calibration_results


if __name__ == "__main__":
    import argparse
    from ml_data_pipeline import build_ml_dataset
    from ml_features import engineer_all_features
    
    parser = argparse.ArgumentParser(description="Backtest ML models")
    parser.add_argument("--seasons", nargs="+", type=int, default=[2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026])
    parser.add_argument("--test-seasons", nargs="+", type=int, default=[2025, 2026])
    parser.add_argument("--test-weeks-2025", nargs="+", type=int, default=list(range(3, 19)))
    parser.add_argument("--save-results", type=str, help="Save results to JSON")
    args = parser.parse_args()
    
    print("Loading dataset...")
    df = build_ml_dataset(args.seasons, use_pbp=False)
    df = engineer_all_features(df)
    
    print("Running backtest...")
    results_df = run_backtest(df, test_seasons=args.test_seasons, test_weeks_2025=args.test_weeks_2025)
    
    print("\n=== BACKTEST SUMMARY ===")
    print(results_df.to_string(index=False))
    
    print("\n=== BASELINE TO BEAT (2025 weeks 3-18) ===")
    baseline_target = {
        "passing_yards": {"mae": 66.6, "median_ae": 53.2},
        "passing_tds": {"mae": 1.00, "median_ae": 0.88},
        "receiving_yards": {"mae": 21.2, "median_ae": 15.9},
        "receptions": {"mae": 1.58, "median_ae": 1.31},
        "rushing_yards": {"mae": 20.3, "median_ae": 14.1},
    }
    
    for stat, metrics in baseline_target.items():
        if stat in results_df["stat"].values:
            row = results_df[results_df["stat"] == stat].iloc[0]
            print(f"\n{stat}:")
            print(f"  Target MAE: {metrics['mae']:.2f} | Achieved: {row['ml_mae']:.2f} | Delta: {metrics['mae'] - row['ml_mae']:.2f}")
            print(f"  Target Median AE: {metrics['median_ae']:.2f} | Achieved: {row['ml_median_ae']:.2f} | Delta: {metrics['median_ae'] - row['ml_median_ae']:.2f}")
    
    # Calibration
    calibration = evaluate_calibration(df, test_seasons=args.test_seasons)
    
    if args.save_results:
        output = {
            "backtest_results": results_df.to_dict(orient="records"),
            "baseline_target": baseline_target,
            "calibration": {stat: cal.to_dict(orient="records") for stat, cal in calibration.items()},
        }
        
        save_path = Path(args.save_results)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "w") as f:
            json.dump(output, f, indent=2)
        
        print(f"\nResults saved to {args.save_results}")
