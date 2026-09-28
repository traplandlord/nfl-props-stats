#!/usr/bin/env python3
"""Quick backtest script - position-filtered."""

import numpy as np
import pandas as pd
from pathlib import Path
from ml_train import load_model_bundle, POS_STATS

# Load data
print("Loading data...")
import sys
sys.path.insert(0, '/workspace/scripts')
from ml_data_pipeline import build_ml_dataset
from ml_features import engineer_all_features

df = build_ml_dataset([2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025], use_pbp=False)
df = engineer_all_features(df)

# Filter to test set
test_df = df[(df['season'] == 2025) & (df['week'] >= 3) & (df['week'] <= 18)].copy()
print(f"Test set: {len(test_df)} rows")

stats = ['passing_yards', 'passing_tds', 'receiving_yards', 'receptions', 'rushing_yards']

results = []

for stat in stats:
    print(f"\nBacktesting {stat}...")
    
    bundle = load_model_bundle(stat)
    if bundle is None:
        print(f"  No model for {stat}")
        continue
    
    models = bundle['models']
    feature_cols = bundle['feature_cols']
    
    # Filter to relevant positions
    relevant_positions = [pos for pos, stats_list in POS_STATS.items() if stat in stats_list]
    stat_df = test_df[
        test_df['position'].isin(relevant_positions) &
        test_df[stat].notna() &
        (test_df[stat] > 0)  # Only non-zero values
    ].copy()
    
    if stat_df.empty:
        print(f"  No data")
        continue
    
    print(f"  {len(stat_df)} samples (positions: {relevant_positions})")
    
    # ML predictions
    X = stat_df[feature_cols].fillna(0)
    y_actual = stat_df[stat].values
    
    ml_pred = models[0.5].predict(X)
    pred_10 = models[0.1].predict(X)
    pred_90 = models[0.9].predict(X)
    
    # Errors
    ml_errors = np.abs(y_actual - ml_pred)
    ml_mae = ml_errors.mean()
    ml_median_ae = np.median(ml_errors)
    
    # Coverage
    coverage_80 = ((y_actual >= pred_10) & (y_actual <= pred_90)).mean()
    
    print(f"  ML MAE: {ml_mae:.2f}")
    print(f"  ML Median AE: {ml_median_ae:.2f}")
    print(f"  80% coverage: {coverage_80:.1%}")
    
    results.append({
        'stat': stat,
        'n_samples': len(stat_df),
        'ml_mae': ml_mae,
        'ml_median_ae': ml_median_ae,
        'coverage_80': coverage_80,
    })

# Print results
print("\n=== BACKTEST RESULTS ===")
results_df = pd.DataFrame(results)
print(results_df.to_string(index=False))

# Baseline numbers
print("\n=== BASELINE TO BEAT (user-provided, 2025 weeks 3-18) ===")
baseline = {
    'passing_yards': (66.6, 53.2),
    'passing_tds': (1.00, 0.88),
    'receiving_yards': (21.2, 15.9),
    'receptions': (1.58, 1.31),
    'rushing_yards': (20.3, 14.1),
}

for stat, (baseline_mae, baseline_median) in baseline.items():
    row = results_df[results_df['stat'] == stat]
    if len(row) > 0:
        ml_mae = row.iloc[0]['ml_mae']
        ml_median = row.iloc[0]['ml_median_ae']
        improvement = baseline_mae - ml_mae
        median_improvement = baseline_median - ml_median
        pct = (improvement / baseline_mae) * 100
        print(f"{stat}:")
        print(f"  MAE: ML {ml_mae:.2f} vs Baseline {baseline_mae:.2f} → {improvement:+.2f} ({pct:+.1f}%)")
        print(f"  Median AE: ML {ml_median:.2f} vs Baseline {baseline_median:.2f} → {median_improvement:+.2f}")
