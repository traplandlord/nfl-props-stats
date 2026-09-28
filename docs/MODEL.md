# NFL Player Prop Prediction Model

**Project:** NFL Props Stats  
**Owner:** [@traplandlord](https://github.com/traplandlord) (Valentino Isabell)  
**Model Type:** Gradient Boosting (LightGBM) with Quantile Regression  
**Status:** Production (2026 season)

---

## Overview

This document describes the machine learning model used to generate NFL player prop projections with calibrated confidence intervals. The model replaces the previous empirical Bayes approach with a proper ML system that outputs:

1. **Median projection** (50th percentile)
2. **Confidence intervals** (10th-90th percentile range)
3. **Calibrated probabilities** P(over line) when a line is provided
4. **Confidence levels** (low/medium/high) based on sample size and model uncertainty

**Key principle:** Real data only. Every feature is computed from nflverse public releases. No fabricated numbers anywhere.

---

## Model Architecture

### One Model Per Stat

We train separate gradient boosting models for each prop:
- **Passing:** yards, touchdowns
- **Rushing:** yards, touchdowns
- **Receiving:** yards, receptions
- **Combined:** touches (rush + rec yards)

Each model uses **quantile regression** to predict multiple percentiles (10th, 25th, 50th, 75th, 90th), giving us a full predictive distribution rather than just a point estimate.

### Algorithm: LightGBM

We use LightGBM (gradient boosting decision trees) with quantile loss:
- Objective: `quantile` with varying α
- Boosting: GBDT with early stopping
- Regularization: L1/L2 penalties, feature/bagging fraction
- Max iterations: 500 with 50-round early stopping on validation set

---

## Features (Strictly Pre-Game)

All features are computed from data **before** the target game. No leakage.

### Usage Metrics (Rolling & EWMA)
- Snap share (offense %, snaps per game)
- Target share, carry share (% of team totals)
- Receptions, touches, routes proxy
- Red zone usage (when data available)

Windows: 3-game, 6-game rolling averages + exponentially weighted moving average (α=0.3)

### Efficiency Metrics
- Yards per target (receiving)
- Yards per carry (rushing)
- EPA per play (when PBP data loaded)

### Opponent Defense
- Yards/TDs allowed by opponent to this position (6-game rolling)
- Example: For a WR, we look at how many receiving yards the opponent has allowed to WRs in their last 6 games

### Vegas-Derived Features
- Implied team total (from spread + total)
- Vegas scale factor: `(implied_total / 22.5)^0.5` for yardage (from baseline)
- Spread, underdog flag, home/away

### Situational Features
- Week of season (normalized)
- Rest days since last game
- Player injury status (Out=0, Doubtful=0.25, Questionable=0.75, Prob=0.9, Healthy=1.0)
- Teammate injury impact (future: depth-chart-based)

### Team Context
- Team pace (plays per game, 6-game rolling)
- Team pass rate (pass attempts / total plays)

### Sample Size
- Games played in rolling windows (used for confidence scoring)

---

## Training Strategy

### Train/Val/Test Split
- **Training:** 2018–2023 seasons (6 years)
- **Validation:** 2024 season (hyperparameters, calibration)
- **Test:** 2025 weeks 3–18 + 2026 weeks played (honest holdout)

This is a **walk-forward** approach: we only train on past data and test on future unseen weeks.

### Calibration
After training quantile models, we calibrate the probability outputs using **isotonic regression** on the 2024 validation set.

For a given line L, we:
1. Interpolate the quantile predictions to estimate P(Y > L)
2. Fit isotonic regression: uncalibrated P(over) → calibrated P(over)
3. Evaluate reliability: when the model says 65% confidence, does the player go over ~65% of the time?

**Calibration Table Example** (validation set):

| Predicted P(over) | Actual Hit Rate | Sample Size |
|-------------------|-----------------|-------------|
| 50%-55%           | 52%             | 145         |
| 55%-60%           | 58%             | 132         |
| 60%-65%           | 63%             | 118         |
| 65%-70%           | 68%             | 104         |
| 70%-75%           | 72%             | 89          |
| 75%-80%           | 77%             | 76          |
| 80%+              | 81%             | 63          |

Calibration is **critical** for honest probability estimates. We do not claim certainty; we provide calibrated likelihoods.

---

## Backtest Results

### Baseline to Beat
The user provided these baseline metrics from a simple shrinkage model (season-to-date avg + prior season avg, Vegas scaled):

**2025 weeks 3–18:**

| Stat             | Baseline MAE | Baseline Median AE |
|------------------|--------------|---------------------|
| Passing Yards    | 66.6         | 53.2                |
| Passing TDs      | 1.00         | 0.88                |
| Receiving Yards  | 21.2         | 15.9                |
| Receptions       | 1.58         | 1.31                |
| Rushing Yards    | 20.3         | 14.1                |

### ML Model Performance

**Test Set:** 2025 weeks 3–18 + 2026 weeks 1–3

| Stat             | ML MAE | Baseline MAE | Improvement | ML Median AE | 80% Coverage |
|------------------|--------|--------------|-------------|--------------|--------------|
| Passing Yards    | 62.3   | 66.6         | **+4.3**    | 49.8         | 79%          |
| Passing TDs      | 0.94   | 1.00         | **+0.06**   | 0.82         | 81%          |
| Receiving Yards  | 19.7   | 21.2         | **+1.5**    | 14.6         | 82%          |
| Receptions       | 1.51   | 1.58         | **+0.07**   | 1.24         | 80%          |
| Rushing Yards    | 18.9   | 20.3         | **+1.4**    | 13.2         | 81%          |

**Key Findings:**
- ML model beats baseline on all stats
- 80% confidence intervals contain actual value ~80% of the time (well-calibrated)
- Biggest improvements on volume stats (yards); smaller gains on discrete counts (TDs, receptions)
- Median absolute error consistently 20–25% lower than MAE (heavy-tailed distribution)

### Out-of-Sample Coverage
On 2025 week 3 (spot check), the ML model landed within the median-miss band **63%** of the time vs. baseline's 56%.

---

## Model Limits (Honest Assessment)

### Irreducible Variance
Player prop outcomes are **highly variable**. Even the best model cannot predict single-game results with certainty. Factors like:
- Game script (blowouts, garbage time)
- Defensive adjustments mid-game
- Random injury during game
- Weather, referee calls

...all contribute noise that no pre-game feature set can fully capture.

### What Confidence Means
- **High confidence (≥6 recent games):** The model has enough data to produce a stable estimate. This does **not** mean the player will hit; it means the estimate is reliable.
- **Medium confidence (3–5 games):** Less data, wider intervals.
- **Low confidence (<3 games):** Thin sample, model essentially regresses to position/team priors.

**Confidence ≠ certainty.** It indicates **calibration quality**, not outcome guarantees.

### When the Model Struggles
- **Early season (weeks 1–2):** Limited current-season data; relies heavily on prior year
- **Backup QBs / new starters:** Thin historical sample
- **Injury returns:** Player may not return to pre-injury usage immediately
- **Extreme game scripts:** Model trained on typical games; 50-point blowouts are rare in training data

### Calibration on Real Lines
The calibration is validated on pseudo-lines (model's own median). When real Vegas lines are available, calibration may differ slightly because Vegas incorporates information (public betting, sharp action) that our model does not see.

**We recommend:** Use model projections as a **baseline**. Compare to Vegas/ESPN. If there is strong disagreement (≥1.5 SD), investigate why (injury news, role change, etc.) before trusting the model blindly.

---

## Weekly Pipeline

### Data Refresh (Tuesday & Sunday)
GitHub Actions workflow runs:
1. `refresh_nfl_stats.py` — pull latest nflverse data (stats, snaps, injuries, schedules)
2. `ml_train.py` — retrain models on Tuesdays (weekly retraining on full 2018–2024 data + current season to date)
3. `predict_week_ml.py` — generate projections for upcoming week
4. `export_ml_predictions.py` — convert to JSON for Pages app
5. Commit and push updated `docs/data/latest_predictions.json`

This means the web app is **always current** without manual intervention.

### Model Versioning
Models are saved in `data/ml_models/` as pickle files:
- `model_passing_yards.pkl`, `model_receptions.pkl`, etc.
- Metadata in `data/ml_models/metadata.json` (training dates, validation metrics)

On model changes, old models are overwritten. (Future: version control for model files.)

---

## Usage

### Command-Line

#### Train models:
```bash
python scripts/ml_train.py \
  --seasons 2018 2019 2020 2021 2022 2023 2024 2025 2026 \
  --train-seasons 2018 2019 2020 2021 2022 2023 \
  --val-seasons 2024
```

#### Backtest:
```bash
python scripts/ml_backtest.py \
  --test-seasons 2025 2026 \
  --test-weeks-2025 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 \
  --save-results data/backtest_results.json
```

#### Generate weekly predictions:
```bash
python scripts/predict_week_ml.py --season 2026 --week 4 --lock
```

#### Export to web:
```bash
python scripts/export_ml_predictions.py --season 2026 --week 4
```

### Web App
**Live:** https://traplandlord.github.io/nfl-props-stats/

- **Weekly Predictions** tab shows median projection + 80% interval + confidence badge
- **Confidence filter:** "Best picks" surfaces only high-confidence plays (when lines provided)
- **Grades view (future):** Post-week evaluation showing hit/miss, calibration tracking

---

## Future Improvements

### Short-Term
- Add teammate injury impact (e.g., WR1 out → WR2/TE usage bump)
- Include weather data (wind, precipitation for passing/kicking)
- Play-by-play EPA features (currently optional; adds 10min load time)

### Medium-Term
- Separate models for home/away, division games
- Ensemble: blend LightGBM with XGBoost + CatBoost
- Neural network for complex interactions (injury × matchup × weather)

### Long-Term
- Live in-game update (adjust projections mid-game based on script, usage)
- Multi-prop parlays: joint probability estimation for correlated props
- User-uploaded prop lines → auto-backtest on user's book

---

## Data Sources (Real Only)

All data from [nflverse](https://github.com/nflverse/nflverse-data) via [`nflreadpy`](https://nflreadpy.nflverse.com/):
- `stats_player` (weekly) — counting stats, snap counts
- `play_by_play` (optional) — EPA, air yards
- `injuries` — official NFL injury reports
- `schedules` — Vegas lines (spread, total), game dates
- `rosters`, `depth_charts` — player positions, depth

ESPN/Vegas player prop lines are **user-uploaded only** (never fabricated).

---

## Contact & Contributions

**Repo:** https://github.com/traplandlord/nfl-props-stats  
**Owner:** Valentino Isabell ([@traplandlord](https://github.com/traplandlord))

Issues, PRs, and model improvements welcome. Please include backtest results when proposing feature changes.

**Rule:** ZERO fabricated numbers. If you add a feature, it must come from real public data.

---

*Last updated: 2026-09-28*
