#!/usr/bin/env python3
"""Export parquet data to JSON files for the GitHub Pages web app.

Only exports what's needed for the browser:
- Players with photos (filtered to recent players)
- Team logos
- Latest predictions and grades
- Player roles
- Current week schedule

Never invents data. If a file is missing, it's skipped.
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
WEB_DATA_DIR = ROOT / "docs" / "data"

WEB_DATA_DIR.mkdir(parents=True, exist_ok=True)


def export_players():
    """Export active players (last_season >= 2023) with photos and key fields."""
    parquet_path = DATA_DIR / "players_with_photos.parquet"
    if not parquet_path.exists():
        print(f"Skipping players: {parquet_path} not found")
        return

    df = pd.read_parquet(parquet_path)
    
    # Filter to recent players (last_season >= 2023)
    df = df[df["last_season"] >= 2023].copy()
    
    # Select only needed columns
    columns = [
        "gsis_id",
        "display_name",
        "position",
        "position_group",
        "latest_team",
        "status",
        "jersey_number",
        "photo_url",
        "espn_id",
    ]
    df = df[[col for col in columns if col in df.columns]]
    
    # Convert to JSON-friendly format
    data = df.to_dict(orient="records")
    
    output_path = WEB_DATA_DIR / "players.json"
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
    
    print(f"✓ Exported {len(data)} players to {output_path}")


def export_team_logos():
    """Export team logos."""
    parquet_path = DATA_DIR / "team_logos.parquet"
    if not parquet_path.exists():
        print(f"Skipping team logos: {parquet_path} not found")
        return

    df = pd.read_parquet(parquet_path)
    
    # Select needed columns
    columns = [
        "team_abbr",
        "team_name",
        "team_logo_espn",
        "team_color",
        "team_color2",
    ]
    df = df[[col for col in columns if col in df.columns]]
    
    data = df.to_dict(orient="records")
    
    output_path = WEB_DATA_DIR / "teams.json"
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
    
    print(f"✓ Exported {len(data)} teams to {output_path}")


def export_player_roles():
    """Export current player roles (starter/rotation/bench)."""
    parquet_path = DATA_DIR / "player_roles_current.parquet"
    if not parquet_path.exists():
        print(f"Skipping player roles: {parquet_path} not found")
        return

    df = pd.read_parquet(parquet_path)
    
    data = df.to_dict(orient="records")
    
    output_path = WEB_DATA_DIR / "player_roles.json"
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
    
    print(f"✓ Exported {len(data)} player roles to {output_path}")


def export_predictions():
    """Export latest prediction file."""
    pred_dir = DATA_DIR / "predictions"
    if not pred_dir.exists():
        print(f"Skipping predictions: {pred_dir} not found")
        return

    # Find the latest prediction JSON file
    json_files = sorted(pred_dir.glob("season*.json"), reverse=True)
    if not json_files:
        print("No prediction JSON files found")
        return

    latest_json = json_files[0]
    
    # Copy the JSON file
    with open(latest_json) as f:
        metadata = json.load(f)
    
    output_path = WEB_DATA_DIR / "latest_predictions_meta.json"
    with open(output_path, "w") as f:
        json.dump(metadata, f, indent=2)
    
    # Load and export prediction data (just a sample for now to keep size down)
    parquet_file = latest_json.with_suffix(".parquet")
    if parquet_file.exists():
        df = pd.read_parquet(parquet_file)
        
        # Keep only key columns and limit to 500 rows for demo
        columns = [
            "player_id",
            "player_display_name",
            "position",
            "team",
            "role_bucket",
            "prop",
            "mean",
            "sd",
        ]
        df = df[[col for col in columns if col in df.columns]]
        
        # Sort by role_bucket priority and take top players
        role_priority = {"starter": 0, "rotation": 1, "bench_warmer": 2}
        if "role_bucket" in df.columns:
            df["_sort"] = df["role_bucket"].map(role_priority).fillna(3)
            df = df.sort_values("_sort").drop("_sort", axis=1)
        
        df = df.head(500)
        
        data = df.to_dict(orient="records")
        
        output_path = WEB_DATA_DIR / "latest_predictions.json"
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2)
        
        print(f"✓ Exported {len(data)} predictions (sample) to {output_path}")
    else:
        print(f"Parquet file not found: {parquet_file}")


def export_grades():
    """Export latest grade file."""
    grades_dir = DATA_DIR / "grades"
    if not grades_dir.exists():
        print(f"Skipping grades: {grades_dir} not found")
        return

    # Find the latest grade JSON file
    json_files = sorted(grades_dir.glob("season*.json"), reverse=True)
    if not json_files:
        print("No grade JSON files found")
        return

    latest_json = json_files[0]
    
    # Copy the JSON file
    with open(latest_json) as f:
        grade_data = json.load(f)
    
    output_path = WEB_DATA_DIR / "latest_grades.json"
    with open(output_path, "w") as f:
        json.dump(grade_data, f, indent=2)
    
    print(f"✓ Exported grades to {output_path}")


def export_schedule():
    """Export upcoming games from schedule."""
    parquet_path = DATA_DIR / "team_schedule.parquet"
    if not parquet_path.exists():
        print(f"Skipping schedule: {parquet_path} not found")
        return

    df = pd.read_parquet(parquet_path)
    
    # Filter to recent/upcoming games (within 7 days)
    today = datetime.now().date()
    df["gameday_dt"] = pd.to_datetime(df["gameday"]).dt.date
    
    mask = (df["gameday_dt"] >= today - timedelta(days=3)) & (df["gameday_dt"] <= today + timedelta(days=7))
    df = df[mask].copy()
    
    # Select needed columns
    columns = [
        "game_id",
        "season",
        "week",
        "game_type",
        "gameday",
        "away_team",
        "home_team",
        "away_score",
        "home_score",
    ]
    df = df[[col for col in columns if col in df.columns]]
    
    data = df.to_dict(orient="records")
    
    output_path = WEB_DATA_DIR / "schedule.json"
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
    
    print(f"✓ Exported {len(data)} games to {output_path}")


def export_player_stats_sample():
    """Export recent player stats for search functionality."""
    parquet_path = DATA_DIR / "weekly_player_stats.parquet"
    if not parquet_path.exists():
        print(f"Skipping player stats: {parquet_path} not found")
        return

    df = pd.read_parquet(parquet_path)
    
    # Filter to 2026 season for current stats
    df = df[df["season"] == 2026].copy()
    
    # Group by player and aggregate recent stats
    grouped = df.groupby(["player_id", "player_display_name", "position", "team"]).agg({
        "passing_yards": "mean",
        "rushing_yards": "mean",
        "receiving_yards": "mean",
        "receptions": "mean",
        "targets": "mean",
        "carries": "mean",
        "week": "count",  # games played
    }).reset_index()
    
    grouped = grouped.rename(columns={"week": "games_played"})
    
    # Round numeric columns
    for col in ["passing_yards", "rushing_yards", "receiving_yards", "receptions", "targets", "carries"]:
        if col in grouped.columns:
            grouped[col] = grouped[col].round(1)
    
    data = grouped.to_dict(orient="records")
    
    output_path = WEB_DATA_DIR / "player_stats_2026.json"
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
    
    print(f"✓ Exported stats for {len(data)} players to {output_path}")


def main():
    print("Exporting data for GitHub Pages web app...")
    print(f"Output directory: {WEB_DATA_DIR}")
    print()
    
    export_players()
    export_team_logos()
    export_player_roles()
    export_predictions()
    export_grades()
    export_schedule()
    export_player_stats_sample()
    
    print()
    print("✓ Export complete!")


if __name__ == "__main__":
    main()
