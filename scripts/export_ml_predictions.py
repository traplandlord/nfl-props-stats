#!/usr/bin/env python3
"""
Export ML predictions to JSON format for GitHub Pages web app.

Converts ML model outputs (median, intervals, confidence) to the format
expected by docs/index.html.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

try:
    from config import DATA_DIR
except ImportError:
    DATA_DIR = Path(__file__).resolve().parents[1] / "data"

DOCS_DIR = Path(__file__).resolve().parents[1] / "docs"
PRED_DIR = DATA_DIR / "predictions"


def export_ml_predictions(season: int, week: int):
    """
    Export ML predictions for web app consumption.
    
    Output format:
    [
      {
        "player_id": "...",
        "player_name": "...",
        "team": "...",
        "position": "...",
        "role_bucket": "...",
        "prop": "passing_yards",
        "median": 275.3,
        "lower_80": 225.1,
        "upper_80": 325.5,
        "confidence": "high",
        "interval_width": 100.4
      },
      ...
    ]
    """
    pred_file = PRED_DIR / f"season{season}_week{week}.parquet"
    
    if not pred_file.exists():
        print(f"No predictions found: {pred_file}")
        return
    
    pred_df = pd.read_parquet(pred_file)
    
    # Convert to JSON format
    records = pred_df.to_dict(orient="records")
    
    # Clean up for JSON
    for r in records:
        for k, v in r.items():
            if pd.isna(v):
                r[k] = None
            elif isinstance(v, (float, int)):
                r[k] = float(v) if isinstance(v, float) else int(v)
    
    # Save to docs/data/
    output_file = DOCS_DIR / "data" / "latest_predictions.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, "w") as f:
        json.dump(records, f, indent=2)
    
    print(f"Exported {len(records)} predictions to {output_file}")
    
    # Also save metadata
    meta_file = PRED_DIR / f"season{season}_week{week}_ml.json"
    if meta_file.exists():
        meta = json.loads(meta_file.read_text())
        
        output_meta = DOCS_DIR / "data" / "latest_predictions_meta.json"
        with open(output_meta, "w") as f:
            json.dump(meta, f, indent=2)
        
        print(f"Exported metadata to {output_meta}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    args = parser.parse_args()
    
    export_ml_predictions(args.season, args.week)
