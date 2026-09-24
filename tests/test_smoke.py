"""Smoke tests — real local data only; never invent ESPN/Vegas."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

DATA = ROOT / "data"


def test_players_with_photos_exists():
    pq = DATA / "players_with_photos.parquet"
    assert pq.is_file(), "players_with_photos.parquet missing — run refresh_nfl_stats.py"
    df = pd.read_parquet(pq)
    assert len(df) > 0
    assert "photo_url" in df.columns
    assert "gsis_id" in df.columns
    # majority should have a URL; never require inventing
    assert df["photo_url"].notna().mean() > 0.9


def test_depth_roles_buckets():
    pq = DATA / "player_roles_current.parquet"
    assert pq.is_file()
    df = pd.read_parquet(pq)
    assert "role_bucket" in df.columns
    buckets = set(df["role_bucket"].dropna().unique())
    assert buckets <= {"starter", "rotation", "bench_warmer"}
    assert {"starter", "rotation", "bench_warmer"} <= buckets
    assert len(df) > 100


def test_predict_week_rows_without_fabricating_espn_vegas():
    import predict_week as pw

    # Use a week that has schedule/roles; do NOT save (may be locked)
    pred, meta = pw.build_predictions(2026, 3, include_bench=False)
    assert len(pred) > 0
    assert meta.get("espn_loaded") is False
    assert meta.get("vegas_loaded") is False
    assert (pred["espn_status"] == "not_loaded").all()
    assert (pred["vegas_status"] == "not_loaded").all()
    # empty external CSVs must not invent numeric ESPN/Vegas
    assert pred["espn_projection"].isna().all()
    assert pred["vegas_line"].isna().all()
    assert pred["ours_mean"].notna().all()
    assert (pred["ours_label"] == "MODEL_ESTIMATE").all()


def test_entry_builder_allows_cross_team_n_2_to_6():
    import entry_builder_lib as entrylib

    for n in range(2, 7):
        players = entrylib.randomize_entry(2026, 3, n)
        assert len(players) == n
        teams = {p.get("team") for p in players}
        # cross-team allowed: with N>=3 expect possibility of >1 team (probabilistic).
        # Hard assert: never requires same team; card may mix.
        assert all(p.get("gsis_id") for p in players)
        # For N>=4, league-wide weighted sample should almost always span 2+ teams
        if n >= 4:
            assert len(teams) >= 2, f"expected cross-team mix for N={n}, got {teams}"


def test_guide_active_games_nfl_returns_list_without_inventing_scores():
    import active_games

    snap = active_games.list_active_games("nfl", include_upcoming_hours=72)
    assert snap.get("connected") is True
    assert isinstance(snap.get("active"), list)
    assert isinstance(snap.get("upcoming"), list)
    # Scores only when present in parquet — never invent live clocks
    for g in (snap.get("active") or []) + (snap.get("upcoming") or []):
        assert "away_team" in g and "home_team" in g
        # If scores present they must be numeric or None — not fabricated strings like "LIVE 24-17 fake"
        for key in ("away_score", "home_score"):
            if key in g and g[key] is not None:
                assert isinstance(g[key], (int, float))

    nba = active_games.list_active_games("nba")
    assert nba.get("connected") is False
    assert nba.get("active") == []
    assert nba.get("upcoming") == []
    assert "not connected" in (nba.get("note") or "").lower()


def test_config_port_data_dir():
    import config

    assert config.PORT == 5056 or isinstance(config.PORT, int)
    assert config.DATA_DIR == DATA.resolve() or config.DATA_DIR.is_dir()
    # Access message should reference local machine, not assistant/Grok
    msg = config.access_message().lower()
    assert "local" in msg or "machine" in msg
    assert "grok" not in msg and "assistant" not in msg
