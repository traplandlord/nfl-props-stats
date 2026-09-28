# ML Model Quick Start

## Installation

```bash
pip install -r requirements.txt
```

New dependencies added:
- `lightgbm>=4.0` - Gradient boosting framework
- `scikit-learn>=1.3` - Calibration and metrics
- `scipy>=1.11` - Statistical functions

## Training Pipeline

### 1. Load Data and Engineer Features

```bash
# Load historical seasons
python3 scripts/ml_data_pipeline.py --seasons 2018 2019 2020 2021 2022 2023 2024 2025 2026

# Add features
python3 scripts/ml_features.py --seasons 2018 2019 2020 2021 2022 2023 2024 2025 2026 \
  --save data/ml_features.parquet
```

### 2. Train Models

```bash
# Train on 2018-2023, validate on 2024
python3 scripts/ml_train.py \
  --seasons 2018 2019 2020 2021 2022 2023 2024 2025 2026 \
  --train-seasons 2018 2019 2020 2021 2022 2023 \
  --val-seasons 2024
```

This will:
- Train one model per stat (passing_yards, passing_tds, rushing_yards, etc.)
- Output quantile predictions (10th, 25th, 50th, 75th, 90th percentiles)
- Calibrate probabilities using isotonic regression
- Save models to `data/ml_models/*.pkl`
- Save metadata to `data/ml_models/metadata.json`

### 3. Run Backtest

```bash
# Honest walk-forward test on 2025-2026
python3 scripts/ml_backtest.py \
  --test-seasons 2025 2026 \
  --test-weeks-2025 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 \
  --save-results data/backtest_results.json
```

This compares ML model vs baseline on held-out data and outputs actual measured metrics.

### 4. Generate Weekly Predictions

```bash
# Generate predictions for upcoming week
python3 scripts/predict_week_ml.py --season 2026 --week 4 --lock

# Export to web format
python3 scripts/export_ml_predictions.py --season 2026 --week 4
```

Output saved to:
- `data/predictions/season2026_week4.parquet` - Full predictions
- `data/predictions/season2026_week4_ml.json` - Metadata
- `docs/data/latest_predictions.json` - Web app format

## Model Files

After training, you'll have:

```
data/ml_models/
├── model_passing_yards.pkl
├── model_passing_tds.pkl
├── model_rushing_yards.pkl
├── model_rushing_tds.pkl
├── model_receiving_yards.pkl
├── model_receptions.pkl
├── model_touches.pkl
└── metadata.json
```

Each `.pkl` file contains:
- `models`: dict of quantile → LightGBM booster
- `calibrator`: IsotonicRegression for P(over) calibration
- `feature_cols`: list of feature names used
- `val_mae`, `val_median_ae`, `coverage_80`: validation metrics

## GitHub Actions

The workflow `.github/workflows/weekly_predictions.yml` runs:
- **Tuesday 9 AM PT**: Full refresh (data + model retrain + predictions)
- **Sunday 9 AM PT**: Quick refresh (data + predictions, reuse models)

Manual trigger: Go to Actions tab → "Weekly Predictions Update" → "Run workflow"

## Quick Validation

To verify everything works without waiting for full training:

```bash
# Quick data load test (2025 only)
python3 scripts/ml_data_pipeline.py --seasons 2025

# Quick feature test (2024-2025)
python3 scripts/ml_features.py --seasons 2024 2025
```

## Troubleshooting

### "No module named 'lightgbm'"
```bash
pip install lightgbm scikit-learn scipy polars
```

### "Season must be between 1920 and 2026"
nflverse data for future seasons is only available during the season. Use past seasons for testing.

### "No games found for season X week Y"
The week hasn't been played yet. Use a past week for testing.

### Models not found
Run `ml_train.py` first to create the model files.

## Documentation

- `docs/MODEL.md` - Complete model documentation with measured backtest results
- `scripts/ml_*.py` - Inline docstrings for every function
- This README - Quick start guide
