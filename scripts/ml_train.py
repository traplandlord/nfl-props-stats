#!/usr/bin/env python3
"""
Train gradient boosting models for player props with quantile regression and calibration.

One model per stat:
- passing_yards, passing_tds
- rushing_yards, rushing_tds  
- receiving_yards, receptions
- touches (rush + rec)

Each model outputs:
- Median prediction (quantile=0.5)
- Predictive distribution (quantiles: 0.1, 0.25, 0.5, 0.75, 0.9)
- Calibrated P(over line) via isotonic regression

Training strategy:
- Train on 2018-2023
- Validate on 2024 (for calibration and hyperparams)
- Test on 2025+2026
"""

from __future__ import annotations

import json
import pickle
import warnings
from pathlib import Path
from typing import Optional

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.model_selection import train_test_split

try:
    from config import DATA_DIR
except ImportError:
    DATA_DIR = Path(__file__).resolve().parents[1] / "data"

MODEL_DIR = DATA_DIR / "ml_models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)


# Position -> relevant stats mapping
POS_STATS = {
    "QB": ["passing_yards", "passing_tds", "rushing_yards", "touches"],
    "RB": ["rushing_yards", "rushing_tds", "receiving_yards", "receptions", "touches"],
    "WR": ["receiving_yards", "receptions", "rushing_yards", "touches"],
    "TE": ["receiving_yards", "receptions", "touches"],
    "FB": ["receiving_yards", "receptions", "rushing_yards", "touches"],
    "HB": ["rushing_yards", "rushing_tds", "receiving_yards", "receptions", "touches"],
}


def get_feature_columns(df: pd.DataFrame, stat: str) -> list[str]:
    """
    Select relevant feature columns for a given stat.
    
    Returns list of column names to use as features.
    """
    # Start with rolling/ewma features
    base_features = []
    
    # Position-specific usage features
    if stat in ["passing_yards", "passing_tds"]:
        patterns = ["passing", "attempts", "completions", "offense_pct"]
    elif stat in ["rushing_yards", "rushing_tds"]:
        patterns = ["rushing", "carries", "carry_share", "offense_pct"]
    elif stat in ["receiving_yards", "receptions"]:
        patterns = ["receiving", "targets", "target_share", "receptions", "offense_pct"]
    elif stat == "touches":
        patterns = ["touches", "carries", "carry_share", "targets", "target_share", "offense_pct"]
    else:
        patterns = ["offense_pct", "targets", "carries"]
    
    # Find all rolling/ewma columns matching patterns
    for col in df.columns:
        if any(p in col for p in patterns) and ("_roll" in col or "_ewma" in col):
            base_features.append(col)
    
    # Add situational features
    situational = [
        "week_of_season",
        "is_home",
        "vegas_scale_factor",
        "is_underdog",
        "spread_abs",
        "team_spread",
        "injury_availability",
        "rest_days",
        "team_pace_roll6",
        "team_pass_rate",
        "games_played_last3",
        "games_played_last6",
    ]
    
    for col in situational:
        if col in df.columns:
            base_features.append(col)
    
    # Add opponent defense features
    for col in df.columns:
        if "_allowed_vs_" in col and "_roll" in col:
            base_features.append(col)
    
    # Add efficiency features
    if stat in ["receiving_yards", "receptions"]:
        for col in df.columns:
            if "yards_per_target" in col:
                base_features.append(col)
    
    if stat in ["rushing_yards", "rushing_tds"]:
        for col in df.columns:
            if "yards_per_carry" in col:
                base_features.append(col)
    
    # Remove duplicates and ensure they exist
    base_features = [c for c in sorted(set(base_features)) if c in df.columns]
    
    return base_features


def train_quantile_model(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    quantile: float = 0.5,
) -> lgb.Booster:
    """
    Train a LightGBM quantile regression model.
    
    Args:
        X_train, y_train: Training data
        X_val, y_val: Validation data
        quantile: Target quantile (0.5 for median)
    
    Returns:
        Trained LightGBM booster
    """
    train_data = lgb.Dataset(X_train, label=y_train)
    val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
    
    params = {
        "objective": "quantile",
        "alpha": quantile,
        "metric": "quantile",
        "boosting_type": "gbdt",
        "num_leaves": 31,
        "learning_rate": 0.05,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "verbose": -1,
        "min_data_in_leaf": 20,
        "lambda_l1": 0.1,
        "lambda_l2": 0.1,
    }
    
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = lgb.train(
            params,
            train_data,
            num_boost_round=500,
            valid_sets=[val_data],
            callbacks=[lgb.early_stopping(stopping_rounds=50, verbose=False)],
        )
    
    return model


def train_stat_models(
    df: pd.DataFrame,
    stat: str,
    train_seasons: list[int],
    val_seasons: list[int],
) -> dict:
    """
    Train quantile models for a single stat.
    
    Returns dict with:
    - models: dict of quantile -> LightGBM model
    - feature_cols: list of feature column names
    - train_metrics: training performance
    - val_metrics: validation performance
    """
    print(f"\nTraining models for {stat}...")
    
    # Filter to relevant positions
    relevant_positions = [pos for pos, stats in POS_STATS.items() if stat in stats]
    df_stat = df[df["position"].isin(relevant_positions)].copy()
    
    if df_stat.empty:
        print(f"  No data for {stat}")
        return None
    
    # Filter to rows with non-null target
    df_stat = df_stat[df_stat[stat].notna()].copy()
    df_stat[stat] = pd.to_numeric(df_stat[stat], errors="coerce")
    df_stat = df_stat[df_stat[stat].notna()]
    
    if len(df_stat) < 100:
        print(f"  Insufficient data for {stat}: {len(df_stat)} rows")
        return None
    
    # Get features
    feature_cols = get_feature_columns(df_stat, stat)
    
    if not feature_cols:
        print(f"  No features found for {stat}")
        return None
    
    print(f"  Using {len(feature_cols)} features")
    
    # Split train/val
    train_mask = df_stat["season"].isin(train_seasons)
    val_mask = df_stat["season"].isin(val_seasons)
    
    df_train = df_stat[train_mask].copy()
    df_val = df_stat[val_mask].copy()
    
    print(f"  Train: {len(df_train)} rows ({train_seasons})")
    print(f"  Val: {len(df_val)} rows ({val_seasons})")
    
    if len(df_train) < 100 or len(df_val) < 20:
        print(f"  Insufficient train/val data")
        return None
    
    # Prepare data
    X_train = df_train[feature_cols].fillna(0)
    y_train = df_train[stat]
    X_val = df_val[feature_cols].fillna(0)
    y_val = df_val[stat]
    
    # Train quantile models
    quantiles = [0.1, 0.25, 0.5, 0.75, 0.9]
    models = {}
    
    for q in quantiles:
        print(f"  Training q={q}...")
        models[q] = train_quantile_model(X_train, y_train, X_val, y_val, quantile=q)
    
    # Compute validation metrics
    preds_median = models[0.5].predict(X_val)
    val_mae = np.mean(np.abs(y_val - preds_median))
    val_median_ae = np.median(np.abs(y_val - preds_median))
    
    print(f"  Validation MAE: {val_mae:.2f}")
    print(f"  Validation Median AE: {val_median_ae:.2f}")
    
    # Check interval coverage
    preds_10 = models[0.1].predict(X_val)
    preds_90 = models[0.9].predict(X_val)
    coverage_80 = np.mean((y_val >= preds_10) & (y_val <= preds_90))
    print(f"  80% interval coverage: {coverage_80:.1%}")
    
    return {
        "stat": stat,
        "models": models,
        "feature_cols": feature_cols,
        "train_size": len(df_train),
        "val_size": len(df_val),
        "val_mae": float(val_mae),
        "val_median_ae": float(val_median_ae),
        "coverage_80": float(coverage_80),
    }


def calibrate_probabilities(
    df: pd.DataFrame,
    stat: str,
    models: dict,
    feature_cols: list[str],
    val_seasons: list[int],
    lines: Optional[pd.DataFrame] = None,
) -> IsotonicRegression:
    """
    Calibrate over/under probabilities using isotonic regression.
    
    Args:
        df: Full dataset
        stat: Stat name
        models: Dict of quantile models
        feature_cols: Feature column names
        val_seasons: Validation seasons for calibration
        lines: Optional DataFrame with (player_id, week, line) for real lines
    
    Returns:
        Fitted IsotonicRegression calibrator
    """
    print(f"  Calibrating probabilities for {stat}...")
    
    # Get validation data
    relevant_positions = [pos for pos, stats in POS_STATS.items() if stat in stats]
    df_stat = df[
        df["position"].isin(relevant_positions) &
        df["season"].isin(val_seasons) &
        df[stat].notna()
    ].copy()
    
    if df_stat.empty:
        print("    No validation data for calibration")
        return None
    
    X_val = df_stat[feature_cols].fillna(0)
    y_val = df_stat[stat].values
    
    # Get predictions at multiple quantiles
    preds_10 = models[0.1].predict(X_val)
    preds_25 = models[0.25].predict(X_val)
    preds_50 = models[0.5].predict(X_val)
    preds_75 = models[0.75].predict(X_val)
    preds_90 = models[0.9].predict(X_val)
    
    # If real lines are provided, use them; otherwise use predictions as pseudo-lines
    if lines is not None and not lines.empty:
        # Merge lines
        df_with_lines = df_stat.merge(
            lines[["player_id", "season", "week", "line"]],
            on=["player_id", "season", "week"],
            how="inner"
        )
        
        if len(df_with_lines) < 20:
            print("    Insufficient lines for calibration, using pseudo-lines")
            test_lines = preds_50
        else:
            test_lines = df_with_lines["line"].values
            y_val = df_with_lines[stat].values
            # Need to re-predict for the filtered data
            X_filtered = df_with_lines[feature_cols].fillna(0)
            preds_50 = models[0.5].predict(X_filtered)
    else:
        # Use predictions as pseudo-lines (spread around median)
        test_lines = preds_50
    
    # Compute P(over) from predictive distribution
    # Approximate CDF from quantiles
    # For a given line L, estimate P(Y > L) from the quantile predictions
    
    prob_over = []
    actual_over = []
    
    for i in range(len(test_lines)):
        line = test_lines[i]
        actual = y_val[i]
        
        # Estimate P(Y > line) from quantiles
        # We have quantiles 0.1, 0.25, 0.5, 0.75, 0.9
        q_vals = [preds_10[i], preds_25[i], preds_50[i], preds_75[i], preds_90[i]]
        q_levels = [0.1, 0.25, 0.5, 0.75, 0.9]
        
        # Interpolate to find CDF(line)
        if line <= q_vals[0]:
            p_under = 0.1 * (line / q_vals[0]) if q_vals[0] > 0 else 0.05
        elif line >= q_vals[-1]:
            p_under = 0.9 + 0.1 * min((line - q_vals[-1]) / max(q_vals[-1] * 0.1, 1), 1)
        else:
            # Linear interpolation between quantiles
            p_under = np.interp(line, q_vals, q_levels)
        
        prob_over.append(1 - p_under)
        actual_over.append(float(actual > line))
    
    prob_over = np.array(prob_over).clip(0.01, 0.99)
    actual_over = np.array(actual_over)
    
    # Fit isotonic regression
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(prob_over, actual_over)
    
    # Evaluate calibration
    calibrated_probs = calibrator.predict(prob_over)
    
    # Reliability table
    bins = [(0.5, 0.55), (0.55, 0.6), (0.6, 0.65), (0.65, 0.7), (0.7, 0.75), (0.75, 0.8), (0.8, 1.0)]
    print("    Calibration table:")
    print("    Predicted P(over) | Actual rate | Count")
    for low, high in bins:
        mask = (prob_over >= low) & (prob_over < high)
        if mask.sum() > 0:
            actual_rate = actual_over[mask].mean()
            count = mask.sum()
            print(f"    {low:.0%}-{high:.0%}      | {actual_rate:.1%}      | {count}")
    
    return calibrator


def save_model_bundle(bundle: dict, stat: str, output_dir: Path = MODEL_DIR) -> Path:
    """
    Save model bundle (models + metadata) to disk.
    
    Bundle includes:
    - models: dict of quantile -> LightGBM booster
    - calibrator: IsotonicRegression or None
    - feature_cols: list of feature names
    - metadata: performance metrics
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"model_{stat}.pkl"
    
    with open(path, "wb") as f:
        pickle.dump(bundle, f)
    
    print(f"  Saved model to {path}")
    return path


def load_model_bundle(stat: str, model_dir: Path = MODEL_DIR) -> Optional[dict]:
    """Load model bundle from disk."""
    path = model_dir / f"model_{stat}.pkl"
    
    if not path.exists():
        return None
    
    with open(path, "rb") as f:
        bundle = pickle.load(f)
    
    return bundle


def train_all_models(
    df: pd.DataFrame,
    train_seasons: list[int] = [2018, 2019, 2020, 2021, 2022, 2023],
    val_seasons: list[int] = [2024],
    calibrate: bool = True,
) -> dict:
    """
    Train models for all stats and save them.
    
    Returns:
        Dict of stat -> model bundle
    """
    all_stats = set()
    for stats in POS_STATS.values():
        all_stats.update(stats)
    
    all_stats = sorted(all_stats)
    
    print(f"Training models for {len(all_stats)} stats: {all_stats}")
    print(f"Train seasons: {train_seasons}")
    print(f"Val seasons: {val_seasons}")
    
    results = {}
    
    for stat in all_stats:
        if stat not in df.columns:
            print(f"Skipping {stat} (not in dataset)")
            continue
        
        bundle = train_stat_models(df, stat, train_seasons, val_seasons)
        
        if bundle is None:
            continue
        
        # Calibrate if requested
        if calibrate:
            calibrator = calibrate_probabilities(
                df, stat, bundle["models"], bundle["feature_cols"], val_seasons
            )
            bundle["calibrator"] = calibrator
        else:
            bundle["calibrator"] = None
        
        # Save
        save_model_bundle(bundle, stat)
        
        results[stat] = bundle
    
    # Save metadata
    metadata = {
        "train_seasons": train_seasons,
        "val_seasons": val_seasons,
        "stats": {
            stat: {
                "val_mae": bundle["val_mae"],
                "val_median_ae": bundle["val_median_ae"],
                "coverage_80": bundle["coverage_80"],
                "train_size": bundle["train_size"],
                "val_size": bundle["val_size"],
                "n_features": len(bundle["feature_cols"]),
            }
            for stat, bundle in results.items()
        },
    }
    
    metadata_path = MODEL_DIR / "metadata.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)
    
    print(f"\nSaved metadata to {metadata_path}")
    
    return results


if __name__ == "__main__":
    import argparse
    from ml_data_pipeline import build_ml_dataset
    from ml_features import engineer_all_features
    
    parser = argparse.ArgumentParser(description="Train ML models for player props")
    parser.add_argument(
        "--seasons",
        nargs="+",
        type=int,
        default=[2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026],
    )
    parser.add_argument("--train-seasons", nargs="+", type=int, default=[2018, 2019, 2020, 2021, 2022, 2023])
    parser.add_argument("--val-seasons", nargs="+", type=int, default=[2024])
    parser.add_argument("--no-calibrate", action="store_true")
    parser.add_argument("--use-pbp", action="store_true")
    args = parser.parse_args()
    
    print("Building ML dataset...")
    df = build_ml_dataset(args.seasons, use_pbp=args.use_pbp)
    
    print("Engineering features...")
    df = engineer_all_features(df)
    
    print("Training models...")
    results = train_all_models(
        df,
        train_seasons=args.train_seasons,
        val_seasons=args.val_seasons,
        calibrate=not args.no_calibrate,
    )
    
    print(f"\nTraining complete! Trained {len(results)} models.")
