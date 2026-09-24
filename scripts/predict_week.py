#!/usr/bin/env python3
"""Weekly prop MODEL ESTIMATES from nflverse trailing usage (empirical Bayes).

Never invents past results or ESPN/Vegas numbers.
Layers written per player-prop:
  1. actuals_*  — trailing nflverse stats (last N games)
  2. espn_*     — loaded from data/external/espn_projections.csv if present
  3. vegas_*    — loaded from data/external/vegas_lines.csv if present
  4. ours_*     — Bayesian/heuristic shrink toward position/team prior (mean + sd)
  5. flags      — disagreement vs ESPN/Vegas + calibration notes when grades exist

Usage:
  ./.venv/bin/python scripts/predict_week.py
  ./.venv/bin/python scripts/predict_week.py --season 2026 --week 3 --lock
  ./.venv/bin/python scripts/predict_week.py --include-bench
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
except ImportError:  # pragma: no cover
    ROOT = Path(__file__).resolve().parents[1]
    DATA = ROOT / "data"
    PRED_DIR = DATA / "predictions"
    EXT_DIR = DATA / "external"
    GRADES_DIR = DATA / "grades"

TRAIL_N = 6
PRIOR_K = 3.0  # prior strength for empirical-Bayes shrink
SKILL_POS = {"QB", "RB", "WR", "TE", "FB", "HB"}
ROLE_ORDER = {"starter": 0, "rotation": 1, "bench_warmer": 2}

# Position → props we estimate
POS_PROPS: dict[str, list[str]] = {
    "QB": ["passing_yards", "passing_tds", "rushing_yards", "touches"],
    "RB": ["rushing_yards", "rushing_tds", "receiving_yards", "receptions", "touches"],
    "FB": ["rushing_yards", "receiving_yards", "receptions", "touches"],
    "HB": ["rushing_yards", "rushing_tds", "receiving_yards", "receptions", "touches"],
    "WR": ["receiving_yards", "receptions", "touches", "rushing_yards"],
    "TE": ["receiving_yards", "receptions", "touches"],
}

PROP_SOURCE_COLS = {
    "passing_yards": "passing_yards",
    "passing_tds": "passing_tds",
    "rushing_yards": "rushing_yards",
    "rushing_tds": "rushing_tds",
    "receiving_yards": "receiving_yards",
    "receptions": "receptions",
    "touches": "touches",
}


def _now_labels() -> tuple[str, str]:
    utc = datetime.now(timezone.utc)
    pt = utc.astimezone(ZoneInfo("America/Los_Angeles"))
    return utc.isoformat(), pt.strftime("%Y-%m-%d %H:%M:%S %Z") + " (PT)"


def _read_csv_skip_comments(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.lstrip().startswith("#"):
                continue
            rows.append(line)
    if not rows:
        return pd.DataFrame()
    from io import StringIO

    df = pd.read_csv(StringIO("".join(rows)))
    # drop fully empty rows
    if df.empty:
        return df
    return df.dropna(how="all")


def load_external_espn(season: int, week: int) -> pd.DataFrame:
    """Load real ESPN projections if user filled data/external/espn_projections.csv.

    Never fabricates values. Empty → UI shows 'ESPN: not loaded'.
    """
    path = EXT_DIR / "espn_projections.csv"
    df = _read_csv_skip_comments(path)
    if df.empty:
        return df
    for c in ("season", "week"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "season" in df.columns:
        df = df[df["season"] == season]
    if "week" in df.columns:
        df = df[df["week"] == week]
    if "projection" in df.columns:
        df = df[df["projection"].notna()]
    return df.reset_index(drop=True)


def load_external_vegas(season: int, week: int) -> pd.DataFrame:
    """Load real Vegas lines if user filled data/external/vegas_lines.csv."""
    path = EXT_DIR / "vegas_lines.csv"
    df = _read_csv_skip_comments(path)
    if df.empty:
        return df
    for c in ("season", "week"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "season" in df.columns:
        df = df[df["season"] == season]
    if "week" in df.columns:
        df = df[df["week"] == week]
    if "line" in df.columns:
        df = df[df["line"].notna()]
    return df.reset_index(drop=True)


def load_calibration_notes() -> dict:
    """Summarize graded weeks for competency / calibration flags (if any)."""
    if not GRADES_DIR.is_dir():
        return {}
    notes: dict[str, dict] = {}
    for p in sorted(GRADES_DIR.glob("season*_week*.json")):
        try:
            meta = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        summary = meta.get("summary") or meta.get("metrics") or {}
        notes[p.stem] = summary
    return notes


def _current_season_week() -> tuple[int, int]:
    import nflreadpy as nfl

    return int(nfl.get_current_season()), int(nfl.get_current_week())


def _teams_for_week(sched: pd.DataFrame, season: int, week: int) -> pd.DataFrame:
    g = sched[(sched["season"] == season) & (sched["week"] == week)].copy()
    if g.empty:
        return g
    rows = []
    for _, r in g.iterrows():
        rows.append(
            {
                "game_id": r["game_id"],
                "team": str(r["away_team"]).upper(),
                "opponent": str(r["home_team"]).upper(),
                "home_away": "away",
                "gameday": r.get("gameday"),
            }
        )
        rows.append(
            {
                "game_id": r["game_id"],
                "team": str(r["home_team"]).upper(),
                "opponent": str(r["away_team"]).upper(),
                "home_away": "home",
                "gameday": r.get("gameday"),
            }
        )
    return pd.DataFrame(rows)


def _ensure_touches(weekly: pd.DataFrame) -> pd.DataFrame:
    w = weekly.copy()
    if "touches" not in w.columns:
        carries = pd.to_numeric(w.get("carries"), errors="coerce").fillna(0)
        rec = pd.to_numeric(w.get("receptions"), errors="coerce").fillna(0)
        # Only invent touches formula from real columns (documented), not fake yards
        w["touches"] = carries + rec
    return w


def _trailing_slice(weekly: pd.DataFrame, player_id: str, season: int, week: int, n: int) -> pd.DataFrame:
    """Games strictly before (season, week), preferring same season then prior."""
    w = weekly[weekly["player_id"] == player_id].copy()
    if w.empty:
        return w
    w["_ord"] = w["season"].astype(int) * 100 + w["week"].astype(int)
    cutoff = season * 100 + week
    w = w[w["_ord"] < cutoff].sort_values("_ord")
    return w.tail(n)


def _empirical_bayes(player_vals: np.ndarray, prior_mean: float, prior_sd: float, k: float) -> tuple[float, float, int]:
    """Shrink sample mean toward prior; return (posterior_mean, posterior_sd, n)."""
    vals = player_vals[~np.isnan(player_vals)]
    n = len(vals)
    if n == 0:
        return float(prior_mean), float(prior_sd), 0
    m = float(np.mean(vals))
    s = float(np.std(vals, ddof=1)) if n > 1 else float(prior_sd)
    weight = n / (n + k)
    post_mean = weight * m + (1 - weight) * prior_mean
    # conservative sd: blend sample sd with prior sd
    post_sd = np.sqrt(weight * (s**2) + (1 - weight) * (prior_sd**2) + (prior_sd**2) / (n + k))
    return float(post_mean), float(post_sd), n


def _position_priors(weekly: pd.DataFrame, season: int, week: int) -> dict[tuple[str, str], tuple[float, float]]:
    """(position, prop) -> (mean, sd) from games before this week in season (+ prior season fallback)."""
    w = _ensure_touches(weekly)
    cutoff = season * 100 + week
    w = w.copy()
    w["_ord"] = w["season"].astype(int) * 100 + w["week"].astype(int)
    hist = w[w["_ord"] < cutoff]
    # prefer current season when enough rows
    cur = hist[hist["season"] == season]
    base = cur if len(cur) >= 200 else hist
    priors: dict[tuple[str, str], tuple[float, float]] = {}
    for pos, props in POS_PROPS.items():
        sub = base[base["position"].astype(str).str.upper() == pos]
        for prop in props:
            col = PROP_SOURCE_COLS[prop]
            if col not in sub.columns or sub.empty:
                priors[(pos, prop)] = (0.0, 1.0)
                continue
            series = pd.to_numeric(sub[col], errors="coerce").dropna()
            if series.empty:
                priors[(pos, prop)] = (0.0, 1.0)
            else:
                sd = float(series.std(ddof=1)) if len(series) > 1 else max(float(series.mean()) * 0.5, 1.0)
                priors[(pos, prop)] = (float(series.mean()), max(sd, 0.5))
    return priors


def _team_pos_prior(
    weekly: pd.DataFrame, team: str, pos: str, prop: str, season: int, week: int
) -> tuple[float, float] | None:
    w = _ensure_touches(weekly)
    cutoff = season * 100 + week
    w = w.copy()
    w["_ord"] = w["season"].astype(int) * 100 + w["week"].astype(int)
    sub = w[
        (w["_ord"] < cutoff)
        & (w["team"].astype(str).str.upper() == team.upper())
        & (w["position"].astype(str).str.upper() == pos.upper())
    ]
    col = PROP_SOURCE_COLS[prop]
    if col not in sub.columns or sub.empty:
        return None
    series = pd.to_numeric(sub[col], errors="coerce").dropna()
    if len(series) < 3:
        return None
    sd = float(series.std(ddof=1)) if len(series) > 1 else max(float(series.mean()) * 0.5, 1.0)
    return float(series.mean()), max(sd, 0.5)


def build_predictions(
    season: int,
    week: int,
    include_bench: bool = False,
) -> tuple[pd.DataFrame, dict]:
    roles = pd.read_parquet(DATA / "player_roles_current.parquet")
    weekly = pd.read_parquet(DATA / "weekly_player_stats.parquet")
    weekly = _ensure_touches(weekly)
    sched = pd.read_parquet(DATA / "team_schedule.parquet")
    players = pd.read_parquet(
        DATA / "players_with_photos.parquet"
        if (DATA / "players_with_photos.parquet").exists()
        else DATA / "players.parquet"
    )

    team_week = _teams_for_week(sched, season, week)
    if team_week.empty:
        raise SystemExit(f"No schedule games for season={season} week={week}")

    roles = roles.copy()
    roles["position"] = roles["position"].astype(str).str.upper()
    roles = roles[roles["position"].isin(SKILL_POS)]
    roles = roles[roles["team"].astype(str).str.upper().isin(set(team_week["team"]))]
    if not include_bench:
        roles = roles[roles["role_bucket"].isin(["starter", "rotation"])]
    else:
        # include bench but mark low confidence later
        pass

    roles = roles.merge(team_week, on="team", how="inner")

    # jersey / photo from players
    pcols = ["gsis_id"]
    for c in ("jersey_number", "photo_url", "headshot", "display_name", "espn_id"):
        if c in players.columns:
            pcols.append(c)
    roles = roles.merge(players[pcols].drop_duplicates("gsis_id"), on="gsis_id", how="left")

    espn = load_external_espn(season, week)
    vegas = load_external_vegas(season, week)
    espn_loaded = not espn.empty
    vegas_loaded = not vegas.empty
    espn_idx = {}
    if espn_loaded:
        for _, r in espn.iterrows():
            key = (str(r.get("gsis_id") or ""), str(r.get("prop") or ""))
            espn_idx[key] = r
    vegas_idx = {}
    if vegas_loaded:
        for _, r in vegas.iterrows():
            key = (str(r.get("gsis_id") or ""), str(r.get("prop") or ""))
            vegas_idx[key] = r

    calib = load_calibration_notes()
    # aggregate MAE by prop if present in any grade summary
    prop_mae: dict[str, float] = {}
    for summ in calib.values():
        by_prop = summ.get("mae_by_prop") or summ.get("by_prop") or {}
        for prop, mae in by_prop.items():
            try:
                prop_mae[prop] = float(mae)
            except (TypeError, ValueError):
                pass

    priors = _position_priors(weekly, season, week)
    rows: list[dict] = []

    for _, pl in roles.iterrows():
        gsis = str(pl["gsis_id"])
        pos = str(pl["position"]).upper()
        team = str(pl["team"]).upper()
        role = str(pl.get("role_bucket") or "bench_warmer")
        props = POS_PROPS.get(pos, ["touches"])
        trail = _trailing_slice(weekly, gsis, season, week, TRAIL_N)
        name = pl.get("player_name") or pl.get("display_name") or ""

        for prop in props:
            col = PROP_SOURCE_COLS[prop]
            vals = (
                pd.to_numeric(trail[col], errors="coerce").to_numpy(dtype=float)
                if col in trail.columns and not trail.empty
                else np.array([], dtype=float)
            )
            vals = vals[~np.isnan(vals)]
            actual_mean = float(np.mean(vals)) if len(vals) else None
            actual_median = float(np.median(vals)) if len(vals) else None
            actual_n = int(len(vals))
            # last game actual
            last_actual = float(vals[-1]) if len(vals) else None

            team_prior = _team_pos_prior(weekly, team, pos, prop, season, week)
            pos_mean, pos_sd = priors.get((pos, prop), (0.0, 1.0))
            if team_prior is not None:
                # blend team and position prior 50/50
                prior_mean = 0.5 * team_prior[0] + 0.5 * pos_mean
                prior_sd = 0.5 * team_prior[1] + 0.5 * pos_sd
            else:
                prior_mean, prior_sd = pos_mean, pos_sd

            ours_mean, ours_sd, n_used = _empirical_bayes(vals, prior_mean, prior_sd, PRIOR_K)
            confidence = "low" if role == "bench_warmer" or n_used < 2 else ("medium" if n_used < 4 else "high")

            # ESPN layer
            er = espn_idx.get((gsis, prop))
            if er is not None:
                espn_val = float(er["projection"]) if pd.notna(er.get("projection")) else None
                espn_reason = er.get("reasoning") if pd.notna(er.get("reasoning")) else None
                espn_status = "loaded"
            else:
                espn_val = None
                espn_reason = None
                espn_status = "not_loaded" if not espn_loaded else "missing_player"

            # Vegas layer
            vr = vegas_idx.get((gsis, prop))
            if vr is not None:
                vegas_line = float(vr["line"]) if pd.notna(vr.get("line")) else None
                vegas_over = vr.get("over_odds") if pd.notna(vr.get("over_odds")) else None
                vegas_under = vr.get("under_odds") if pd.notna(vr.get("under_odds")) else None
                vegas_book = vr.get("book") if pd.notna(vr.get("book")) else None
                vegas_status = "loaded"
            else:
                vegas_line = vegas_over = vegas_under = vegas_book = None
                vegas_status = "not_loaded" if not vegas_loaded else "missing_player"

            flags: list[str] = []
            if role == "bench_warmer":
                flags.append("low_confidence_bench")
            if n_used == 0:
                flags.append("no_trailing_actuals")
            # disagreement vs ESPN / Vegas (only when those layers exist — never invent)
            if espn_val is not None and ours_sd > 0:
                z = abs(ours_mean - espn_val) / max(ours_sd, 1e-6)
                if z >= 1.5:
                    flags.append(f"disagree_espn_z{z:.1f}")
            if vegas_line is not None and ours_sd > 0:
                z = abs(ours_mean - vegas_line) / max(ours_sd, 1e-6)
                if z >= 1.5:
                    flags.append(f"disagree_vegas_z{z:.1f}")
            if prop in prop_mae:
                flags.append(f"calib_mae_{prop}={prop_mae[prop]:.1f}")

            photo = pl.get("photo_url") or pl.get("headshot")
            rows.append(
                {
                    "season": season,
                    "week": week,
                    "game_id": pl.get("game_id"),
                    "gameday": str(pl.get("gameday") or ""),
                    "team": team,
                    "opponent": pl.get("opponent"),
                    "home_away": pl.get("home_away"),
                    "gsis_id": gsis,
                    "player_name": name,
                    "position": pos,
                    "jersey_number": pl.get("jersey_number"),
                    "photo_url": photo if pd.notna(photo) else None,
                    "depth_order": pl.get("depth_order"),
                    "role_bucket": role,
                    "prop": prop,
                    # 1 Actuals
                    "actuals_n": actual_n,
                    "actuals_mean": actual_mean,
                    "actuals_median": actual_median,
                    "actuals_last": last_actual,
                    "actuals_window": f"last_{TRAIL_N}_games_before_s{season}w{week}",
                    # 2 ESPN
                    "espn_status": espn_status,
                    "espn_projection": espn_val,
                    "espn_reasoning": espn_reason,
                    # 3 Vegas
                    "vegas_status": vegas_status,
                    "vegas_line": vegas_line,
                    "vegas_over_odds": vegas_over,
                    "vegas_under_odds": vegas_under,
                    "vegas_book": vegas_book,
                    # 4 Ours (MODEL ESTIMATE)
                    "ours_label": "MODEL_ESTIMATE",
                    "ours_mean": round(ours_mean, 3),
                    "ours_sd": round(ours_sd, 3),
                    "ours_method": "empirical_bayes_shrink_trailing_to_pos_team_prior",
                    "ours_prior_mean": round(prior_mean, 3),
                    "ours_n_games": n_used,
                    "ours_confidence": confidence,
                    # 5 Flags
                    "flags": "|".join(flags) if flags else "",
                }
            )

    pred = pd.DataFrame(rows)
    if not pred.empty:
        pred["_role_ord"] = pred["role_bucket"].map(ROLE_ORDER).fillna(9)
        pred = pred.sort_values(
            ["team", "_role_ord", "position", "depth_order", "player_name", "prop"]
        ).drop(columns=["_role_ord"])

    meta = {
        "season": season,
        "week": week,
        "generated_at_utc": _now_labels()[0],
        "generated_at_pt": _now_labels()[1],
        "predictions_locked": False,
        "locked_at": None,
        "row_count": int(len(pred)),
        "player_count": int(pred["gsis_id"].nunique()) if len(pred) else 0,
        "espn_loaded": espn_loaded,
        "vegas_loaded": vegas_loaded,
        "espn_note": (
            "ESPN projections loaded from data/external/espn_projections.csv"
            if espn_loaded
            else "ESPN: not loaded — fill data/external/espn_projections.csv (see espn_projections_template.csv); never invent"
        ),
        "vegas_note": (
            "Vegas lines loaded from data/external/vegas_lines.csv"
            if vegas_loaded
            else "Vegas: not loaded — fill data/external/vegas_lines.csv (see vegas_lines_template.csv); never invent"
        ),
        "ours_note": "MODEL ESTIMATES only — empirical-Bayes from nflverse trailing usage; not past results",
        "trail_n": TRAIL_N,
        "prior_k": PRIOR_K,
        "include_bench": include_bench,
        "calibration_weeks": list(calib.keys()),
    }
    return pred, meta


def save_predictions(pred: pd.DataFrame, meta: dict, lock: bool) -> Path:
    PRED_DIR.mkdir(parents=True, exist_ok=True)
    season, week = meta["season"], meta["week"]
    stem = f"season{season}_week{week}"
    parquet = PRED_DIR / f"{stem}.parquet"
    lock_path = PRED_DIR / f"{stem}.json"

    if lock_path.exists():
        try:
            existing = json.loads(lock_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
        if existing.get("predictions_locked") and not lock:
            print(
                f"WARNING: {lock_path.name} is locked; refusing overwrite without --lock "
                f"(locked_at={existing.get('locked_at')})",
                file=sys.stderr,
            )
            raise SystemExit(2)
        if existing.get("predictions_locked") and lock:
            print(
                f"WARNING: re-locking over existing lock at {existing.get('locked_at')}",
                file=sys.stderr,
            )

    if lock:
        utc, pt = _now_labels()
        meta["predictions_locked"] = True
        meta["locked_at"] = utc
        meta["locked_at_pt"] = pt

    pred.to_parquet(parquet, index=False)
    # also csv for inspection
    pred.to_csv(PRED_DIR / f"{stem}.csv", index=False)
    lock_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return parquet


def spot_check(pred: pd.DataFrame, team: str = "KC") -> None:
    sub = pred[pred["team"] == team]
    if sub.empty:
        teams = sorted(pred["team"].unique())
        team = teams[0] if teams else team
        sub = pred[pred["team"] == team]
    print(f"\n=== Spot-check {team} (starters vs bench) ===")
    for role in ("starter", "rotation", "bench_warmer"):
        r = sub[sub["role_bucket"] == role]
        if r.empty:
            continue
        print(f"\n-- {role} --")
        for pid, grp in r.groupby("gsis_id", sort=False):
            name = grp["player_name"].iloc[0]
            pos = grp["position"].iloc[0]
            props = ", ".join(
                f"{row.prop}: ours={row.ours_mean:.1f}±{row.ours_sd:.1f} "
                f"(act_mean={row.actuals_mean if row.actuals_mean is not None else '—'}; "
                f"ESPN={row.espn_projection if row.espn_projection is not None else row.espn_status}; "
                f"Vegas={row.vegas_line if row.vegas_line is not None else row.vegas_status})"
                for _, row in grp.iterrows()
            )
            print(f"  {name} ({pos}): {props}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate weekly MODEL ESTIMATE prop predictions")
    parser.add_argument("--season", type=int, default=None)
    parser.add_argument("--week", type=int, default=None)
    parser.add_argument("--lock", action="store_true", help="Freeze this week's predictions")
    parser.add_argument("--include-bench", action="store_true", help="Include bench_warmer (low confidence)")
    parser.add_argument("--spot-team", default="KC", help="Team abbr for console spot-check")
    args = parser.parse_args()

    if args.season is None or args.week is None:
        cs, cw = _current_season_week()
        season = args.season or cs
        week = args.week or cw
    else:
        season, week = args.season, args.week

    print(f"Building MODEL ESTIMATES for season={season} week={week} ...")
    pred, meta = build_predictions(season, week, include_bench=args.include_bench)
    path = save_predictions(pred, meta, lock=args.lock)
    print(f"Wrote {path} ({meta['row_count']} prop rows, {meta['player_count']} players)")
    print(f"Lock file: {PRED_DIR / f'season{season}_week{week}.json'} locked={meta['predictions_locked']}")
    print(meta["espn_note"])
    print(meta["vegas_note"])
    print(meta["ours_note"])
    spot_check(pred, team=args.spot_team.upper())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
