#!/usr/bin/env python3
"""
Apples-to-apples comparison: ML model vs user baseline vs naive baseline.

Role filtering to match user's baseline:
- QB: >=15 attempts per game (season average)
- RB: carries + targets >= 8 per game
- WR/TE: targets >= 3 per game

All three models scored on EXACTLY the same test rows.
"""

import numpy as np
import pandas as pd
from pathlib import Path
from ml_train import load_model_bundle, POS_STATS
import sys
sys.path.insert(0, '/workspace/scripts')
from ml_data_pipeline import build_ml_dataset
from ml_features import engineer_all_features

def compute_user_baseline(df: pd.DataFrame, player_id: str, season: int, week: int, 
                          stat: str, vegas_scale: float = None) -> float:
    """
    User's baseline: shrinkage blend of current + prior season.
    
    Formula: (n * current_avg + 3 * prior_avg) / (n + 3)
    Scaled by sqrt(implied_total/22.5) for yardage stats.
    """
    # Current season games before target week
    current = df[
        (df['player_id'] == player_id) &
        (df['season'] == season) &
        (df['week'] < week)
    ]
    
    # Prior season (must have >=4 games)
    prior = df[
        (df['player_id'] == player_id) &
        (df['season'] == season - 1)
    ]
    
    n_current = len(current)
    n_prior = len(prior)
    
    if n_current == 0:
        return np.nan
    
    current_avg = current[stat].mean() if n_current > 0 else 0.0
    
    if n_prior >= 4:
        prior_avg = prior[stat].mean()
        pred = (n_current * current_avg + 3 * prior_avg) / (n_current + 3)
    else:
        pred = current_avg
    
    # Scale yardage stats by Vegas factor
    if vegas_scale is not None and stat in ['passing_yards', 'receiving_yards', 'rushing_yards']:
        pred *= vegas_scale
    
    return pred


def compute_naive_baseline(df: pd.DataFrame, player_id: str, season: int, week: int, stat: str) -> float:
    """Naive baseline: just season-to-date average."""
    current = df[
        (df['player_id'] == player_id) &
        (df['season'] == season) &
        (df['week'] < week)
    ]
    
    if len(current) == 0:
        return np.nan
    
    return current[stat].mean()


def apply_role_filters(df: pd.DataFrame, stat: str) -> pd.DataFrame:
    """
    Apply user's role filters to match their baseline measurement:
    - QB: >=15 attempts per game
    - RB: carries + targets >= 8 per game  
    - WR/TE: targets >= 3 per game
    """
    filtered = df.copy()
    
    # Compute per-game averages for filtering
    if stat in ['passing_yards', 'passing_tds']:
        # QB filter: >=15 attempts per game (season average before this week)
        for idx in filtered.index:
            player_id = filtered.loc[idx, 'player_id']
            season = filtered.loc[idx, 'season']
            week = filtered.loc[idx, 'week']
            
            prior_games = df[
                (df['player_id'] == player_id) &
                (df['season'] == season) &
                (df['week'] < week)
            ]
            
            if len(prior_games) > 0:
                avg_attempts = prior_games['attempts'].mean()
                filtered.loc[idx, 'avg_attempts'] = avg_attempts
            else:
                filtered.loc[idx, 'avg_attempts'] = 0
        
        filtered = filtered[filtered['avg_attempts'] >= 15]
    
    elif stat in ['rushing_yards', 'rushing_tds']:
        # RB filter: carries + targets >= 8 per game
        for idx in filtered.index:
            if filtered.loc[idx, 'position'] not in ['RB', 'HB', 'FB']:
                continue
            
            player_id = filtered.loc[idx, 'player_id']
            season = filtered.loc[idx, 'season']
            week = filtered.loc[idx, 'week']
            
            prior_games = df[
                (df['player_id'] == player_id) &
                (df['season'] == season) &
                (df['week'] < week)
            ]
            
            if len(prior_games) > 0:
                avg_usage = (prior_games['carries'].fillna(0) + prior_games['targets'].fillna(0)).mean()
                filtered.loc[idx, 'avg_usage'] = avg_usage
            else:
                filtered.loc[idx, 'avg_usage'] = 0
        
        filtered = filtered[
            (filtered['position'].isin(['RB', 'HB', 'FB'])) &
            (filtered['avg_usage'] >= 8)
        ]
    
    elif stat in ['receiving_yards', 'receptions']:
        # WR/TE filter: targets >= 3 per game
        for idx in filtered.index:
            player_id = filtered.loc[idx, 'player_id']
            season = filtered.loc[idx, 'season']
            week = filtered.loc[idx, 'week']
            
            prior_games = df[
                (df['player_id'] == player_id) &
                (df['season'] == season) &
                (df['week'] < week)
            ]
            
            if len(prior_games) > 0:
                avg_targets = prior_games['targets'].fillna(0).mean()
                filtered.loc[idx, 'avg_targets'] = avg_targets
            else:
                filtered.loc[idx, 'avg_targets'] = 0
        
        filtered = filtered[filtered['avg_targets'] >= 3]
    
    return filtered


def compute_calibration_table(y_actual, y_pred_baseline, models, X, calibrator):
    """
    Compute P(over) calibration table using baseline prediction as the line.
    
    Returns: DataFrame with bins, predicted prob, actual rate, counts
    """
    results = []
    
    for i in range(len(y_actual)):
        actual = y_actual[i]
        line = round(y_pred_baseline[i] * 2) / 2  # Round to nearest 0.5
        
        # Get ML quantile predictions
        preds = []
        for q in [0.1, 0.25, 0.5, 0.75, 0.9]:
            preds.append(models[q].predict(X[i:i+1])[0])
        
        q_vals = preds
        q_levels = [0.1, 0.25, 0.5, 0.75, 0.9]
        
        # Estimate P(over line)
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
        
        results.append({
            'prob_over': prob_over_cal,
            'actual_over': float(actual > line),
        })
    
    results_df = pd.DataFrame(results)
    
    # Bin by probability
    bins = [(0.5, 0.55), (0.55, 0.6), (0.6, 0.65), (0.65, 0.7), (0.7, 0.75), (0.75, 0.8), (0.8, 1.0)]
    
    table = []
    for low, high in bins:
        mask = (results_df['prob_over'] >= low) & (results_df['prob_over'] < high)
        if mask.sum() >= 5:
            actual_rate = results_df.loc[mask, 'actual_over'].mean()
            count = mask.sum()
            table.append({
                'bin': f'{low:.0%}-{high:.0%}',
                'predicted_prob': (low + high) / 2,
                'actual_rate': actual_rate,
                'count': count,
            })
    
    return pd.DataFrame(table)


print("Loading data...")
df = build_ml_dataset([2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025], use_pbp=False)
df = engineer_all_features(df)

# Filter to test set
test_df = df[(df['season'] == 2025) & (df['week'] >= 3) & (df['week'] <= 18)].copy()
print(f"Test set: {len(test_df)} rows\n")

stats = ['passing_yards', 'passing_tds', 'receiving_yards', 'receptions', 'rushing_yards']

all_results = []
calibration_tables = {}

for stat in stats:
    print(f"\n{'='*60}")
    print(f"STAT: {stat}")
    print('='*60)
    
    # Load ML model
    bundle = load_model_bundle(stat)
    if bundle is None:
        print(f"  No model for {stat}")
        continue
    
    models = bundle['models']
    feature_cols = bundle['feature_cols']
    calibrator = bundle.get('calibrator')
    
    # Filter to relevant positions
    relevant_positions = [pos for pos, stats_list in POS_STATS.items() if stat in stats_list]
    stat_df = test_df[
        test_df['position'].isin(relevant_positions) &
        test_df[stat].notna() &
        (test_df[stat] > 0)
    ].copy()
    
    # Apply role filters (user's baseline filters)
    print(f"Before role filtering: {len(stat_df)} rows")
    stat_df = apply_role_filters(stat_df, stat)
    print(f"After role filtering: {len(stat_df)} rows")
    
    if stat_df.empty:
        print("  No data after filtering")
        continue
    
    # Get actuals
    y_actual = stat_df[stat].values
    
    # ML predictions
    X = stat_df[feature_cols].fillna(0)
    ml_pred = models[0.5].predict(X)
    pred_10 = models[0.1].predict(X)
    pred_90 = models[0.9].predict(X)
    
    # User baseline predictions
    user_baseline_preds = []
    for _, row in stat_df.iterrows():
        vegas_scale = np.sqrt(row.get('implied_team_total', 22.5) / 22.5)
        pred = compute_user_baseline(df, row['player_id'], row['season'], row['week'], 
                                     stat, vegas_scale=vegas_scale)
        user_baseline_preds.append(pred)
    user_baseline_preds = np.array(user_baseline_preds)
    
    # Naive baseline predictions
    naive_baseline_preds = []
    for _, row in stat_df.iterrows():
        pred = compute_naive_baseline(df, row['player_id'], row['season'], row['week'], stat)
        naive_baseline_preds.append(pred)
    naive_baseline_preds = np.array(naive_baseline_preds)
    
    # Remove NaN predictions
    valid_mask = ~np.isnan(user_baseline_preds) & ~np.isnan(naive_baseline_preds)
    y_actual = y_actual[valid_mask]
    ml_pred = ml_pred[valid_mask]
    pred_10 = pred_10[valid_mask]
    pred_90 = pred_90[valid_mask]
    user_baseline_preds = user_baseline_preds[valid_mask]
    naive_baseline_preds = naive_baseline_preds[valid_mask]
    X_valid = X[valid_mask]
    
    print(f"Valid predictions: {len(y_actual)} rows\n")
    
    # Compute errors
    ml_errors = np.abs(y_actual - ml_pred)
    user_errors = np.abs(y_actual - user_baseline_preds)
    naive_errors = np.abs(y_actual - naive_baseline_preds)
    
    ml_mae = ml_errors.mean()
    user_mae = user_errors.mean()
    naive_mae = naive_errors.mean()
    
    ml_median_ae = np.median(ml_errors)
    user_median_ae = np.median(user_errors)
    naive_median_ae = np.median(naive_errors)
    
    # Coverage
    coverage_80 = ((y_actual >= pred_10) & (y_actual <= pred_90)).mean()
    
    # Improvement
    ml_vs_user = user_mae - ml_mae
    ml_vs_naive = naive_mae - ml_mae
    
    print(f"ML Model:")
    print(f"  MAE: {ml_mae:.2f}")
    print(f"  Median AE: {ml_median_ae:.2f}")
    print(f"  80% coverage: {coverage_80:.1%}")
    
    print(f"\nUser Baseline (shrinkage + Vegas scale):")
    print(f"  MAE: {user_mae:.2f}")
    print(f"  Median AE: {user_median_ae:.2f}")
    
    print(f"\nNaive Baseline (season average):")
    print(f"  MAE: {naive_mae:.2f}")
    print(f"  Median AE: {naive_median_ae:.2f}")
    
    print(f"\nML vs User Baseline: {ml_vs_user:+.2f} ({(ml_vs_user/user_mae)*100:+.1f}%)")
    print(f"ML vs Naive Baseline: {ml_vs_naive:+.2f} ({(ml_vs_naive/naive_mae)*100:+.1f}%)")
    
    # Calibration table
    if calibrator is not None:
        print(f"\nCalibration (using user baseline as line):")
        cal_table = compute_calibration_table(y_actual, user_baseline_preds, models, X_valid, calibrator)
        if not cal_table.empty:
            print(cal_table.to_string(index=False))
            calibration_tables[stat] = cal_table
    
    all_results.append({
        'stat': stat,
        'n_samples': len(y_actual),
        'ml_mae': ml_mae,
        'ml_median_ae': ml_median_ae,
        'user_mae': user_mae,
        'user_median_ae': user_median_ae,
        'naive_mae': naive_mae,
        'naive_median_ae': naive_median_ae,
        'ml_vs_user': ml_vs_user,
        'ml_vs_naive': ml_vs_naive,
        'coverage_80': coverage_80,
    })

print(f"\n\n{'='*80}")
print("SUMMARY TABLE")
print('='*80)

results_df = pd.DataFrame(all_results)
print(results_df.to_string(index=False))

print(f"\n{'='*80}")
print("CALIBRATION TABLES (P(over) using user baseline as line)")
print('='*80)

for stat, table in calibration_tables.items():
    print(f"\n{stat}:")
    print(table.to_string(index=False))

# Save results
results_df.to_csv('/workspace/data/apples_to_apples_comparison.csv', index=False)
print(f"\n\nResults saved to /workspace/data/apples_to_apples_comparison.csv")
