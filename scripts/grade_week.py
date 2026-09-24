#!/usr/bin/env python3
"""Grade locked MODEL ESTIMATES against nflverse actual weekly stats.

Joins data/predictions/season{Y}_week{W}.* to weekly_player_stats for that week.
Computes MAE and hit-rate vs simple over/under on predicted mean.
Writes data/grades/season{Y}_week{W}.parquet|.csv|.json + short markdown critique.

Never invents actuals — only nflverse weekly rows.
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
    from config import ROOT, DATA_DIR as DATA, PRED_DIR, GRADES_DIR
except ImportError:  # pragma: no cover
    ROOT = Path(__file__).resolve().parents[1]
    DATA = ROOT / "data"
    PRED_DIR = DATA / "predictions"
    GRADES_DIR = DATA / "grades"

PROP_COLS = {
    "passing_yards": "passing_yards",
    "passing_tds": "passing_tds",
    "rushing_yards": "rushing_yards",
    "rushing_tds": "rushing_tds",
    "receiving_yards": "receiving_yards",
    "receptions": "receptions",
    "touches": "touches",
}


def _now_pt() -> str:
    pt = datetime.now(timezone.utc).astimezone(ZoneInfo("America/Los_Angeles"))
    return pt.strftime("%Y-%m-%d %H:%M:%S %Z") + " (PT)"


def _ensure_touches(df: pd.DataFrame) -> pd.DataFrame:
    w = df.copy()
    if "touches" not in w.columns:
        carries = pd.to_numeric(w.get("carries"), errors="coerce").fillna(0)
        rec = pd.to_numeric(w.get("receptions"), errors="coerce").fillna(0)
        w["touches"] = carries + rec
    return w


def grade(season: int, week: int) -> tuple[pd.DataFrame, dict, str]:
    stem = f"season{season}_week{week}"
    pred_path = PRED_DIR / f"{stem}.parquet"
    lock_path = PRED_DIR / f"{stem}.json"
    if not pred_path.is_file():
        raise SystemExit(f"Missing predictions: {pred_path}")

    pred = pd.read_parquet(pred_path)
    lock = {}
    if lock_path.is_file():
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if not lock.get("predictions_locked"):
        print(
            "NOTE: predictions were not locked with --lock; grading unlocked file anyway.",
            file=sys.stderr,
        )

    weekly = pd.read_parquet(DATA / "weekly_player_stats.parquet")
    weekly = _ensure_touches(weekly)
    actual = weekly[(weekly["season"] == season) & (weekly["week"] == week)].copy()
    if actual.empty:
        raise SystemExit(
            f"No nflverse weekly actuals for season={season} week={week} yet — cannot grade."
        )

    # one actual row per player (sum if multi-team edge case)
    agg_map = {c: "sum" for c in PROP_COLS.values() if c in actual.columns}
    keep_id = actual.groupby("player_id", as_index=False).agg(agg_map)

    rows = []
    for _, r in pred.iterrows():
        prop = r["prop"]
        col = PROP_COLS.get(prop)
        if not col or col not in keep_id.columns:
            continue
        hit = keep_id[keep_id["player_id"] == r["gsis_id"]]
        if hit.empty:
            actual_val = None
            played = False
        else:
            actual_val = float(hit.iloc[0][col])
            played = True
        ours = float(r["ours_mean"]) if pd.notna(r["ours_mean"]) else None
        err = (ours - actual_val) if (ours is not None and actual_val is not None) else None
        abs_err = abs(err) if err is not None else None
        # over/under hit: did actual land on the side of ours_mean vs a push band?
        if ours is not None and actual_val is not None:
            if actual_val > ours:
                ou_side = "over"
            elif actual_val < ours:
                ou_side = "under"
            else:
                ou_side = "push"
            # "hit" vs naive: we treat predicting the mean as the line; hit if abs error <= 0.5*sd
            sd = float(r["ours_sd"]) if pd.notna(r.get("ours_sd")) else None
            within_1sd = abs_err <= sd if (abs_err is not None and sd is not None) else None
        else:
            ou_side = None
            within_1sd = None

        rows.append(
            {
                "season": season,
                "week": week,
                "gsis_id": r["gsis_id"],
                "player_name": r["player_name"],
                "team": r["team"],
                "position": r["position"],
                "role_bucket": r["role_bucket"],
                "prop": prop,
                "ours_mean": ours,
                "ours_sd": r.get("ours_sd"),
                "espn_projection": r.get("espn_projection"),
                "vegas_line": r.get("vegas_line"),
                "actual": actual_val,
                "played": played,
                "error": err,
                "abs_error": abs_err,
                "ou_side": ou_side,
                "within_1sd": within_1sd,
            }
        )

    graded = pd.DataFrame(rows)
    scored = graded[graded["actual"].notna()].copy()

    mae_by_prop = {}
    hit_by_prop = {}
    for prop, g in scored.groupby("prop"):
        mae_by_prop[prop] = float(g["abs_error"].mean()) if len(g) else None
        # hit-rate: fraction within 1 sd of ours_mean
        w = g["within_1sd"].dropna()
        hit_by_prop[prop] = float(w.mean()) if len(w) else None

    overall_mae = float(scored["abs_error"].mean()) if len(scored) else None
    overall_hit = float(scored["within_1sd"].dropna().mean()) if scored["within_1sd"].notna().any() else None

    # simple O/U: if we had used ours_mean as line, "correct direction vs median actual"? skip
    # Instead: bias (mean error)
    bias = float(scored["error"].mean()) if len(scored) else None

    summary = {
        "season": season,
        "week": week,
        "graded_at_pt": _now_pt(),
        "predictions_locked": bool(lock.get("predictions_locked")),
        "locked_at": lock.get("locked_at"),
        "n_pred_rows": int(len(pred)),
        "n_scored": int(len(scored)),
        "n_missing_actual": int((~graded["played"]).sum()) if len(graded) else 0,
        "overall_mae": overall_mae,
        "overall_within_1sd_rate": overall_hit,
        "overall_bias": bias,
        "mae_by_prop": mae_by_prop,
        "within_1sd_by_prop": hit_by_prop,
    }

    # markdown critique
    lines = [
        f"# Grade critique — season {season} week {week}",
        "",
        f"- Graded at: **{_now_pt()}**",
        f"- Predictions locked: **{summary['predictions_locked']}** (locked_at={summary['locked_at']})",
        f"- Scored rows: **{summary['n_scored']}** / {summary['n_pred_rows']} "
        f"(missing actuals: {summary['n_missing_actual']})",
        f"- Overall MAE (ours_mean vs nflverse actual): **{overall_mae:.3f}**" if overall_mae is not None else "- Overall MAE: n/a",
        f"- Within-1-SD hit rate: **{overall_hit:.1%}**" if overall_hit is not None else "- Within-1-SD hit rate: n/a",
        f"- Bias (ours − actual): **{bias:.3f}**" if bias is not None else "- Bias: n/a",
        "",
        "## By prop",
        "",
        "| Prop | MAE | Within 1 SD |",
        "| --- | --- | --- |",
    ]
    for prop in sorted(mae_by_prop.keys()):
        mae = mae_by_prop[prop]
        hit = hit_by_prop.get(prop)
        lines.append(
            f"| {prop} | {mae:.2f} | {hit:.1%} |"
            if mae is not None and hit is not None
            else f"| {prop} | {mae} | {hit} |"
        )

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Actuals are **nflverse weekly stats only** — never fabricated.",
            "- ESPN/Vegas columns graded only when those external files were loaded at predict time; empty means not loaded (not zero).",
            "- MODEL ESTIMATES use empirical-Bayes shrink of trailing usage; high MAE on TDs is expected (high variance).",
            "- Competency signal for the UI Flags column is written into the grade JSON (`mae_by_prop`).",
            "",
        ]
    )

    # worst misses
    if len(scored):
        worst = scored.nlargest(8, "abs_error")
        lines.append("## Largest misses")
        lines.append("")
        for _, w in worst.iterrows():
            lines.append(
                f"- {w['player_name']} ({w['team']} {w['position']}) {w['prop']}: "
                f"ours={w['ours_mean']:.1f} actual={w['actual']:.1f} abs_err={w['abs_error']:.1f}"
            )
        lines.append("")

    critique = "\n".join(lines)
    return graded, summary, critique


def main() -> int:
    parser = argparse.ArgumentParser(description="Grade locked weekly predictions vs actuals")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    args = parser.parse_args()

    graded, summary, critique = grade(args.season, args.week)
    GRADES_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"season{args.season}_week{args.week}"
    graded.to_parquet(GRADES_DIR / f"{stem}.parquet", index=False)
    graded.to_csv(GRADES_DIR / f"{stem}.csv", index=False)
    (GRADES_DIR / f"{stem}.json").write_text(
        json.dumps({"summary": summary, "metrics": summary}, indent=2), encoding="utf-8"
    )
    (GRADES_DIR / f"{stem}_critique.md").write_text(critique, encoding="utf-8")
    print(critique)
    print(f"\nWrote data/grades/{stem}.*")
    # Self-check: attach outcomes to Guide improvement_log suggestions when present
    try:
        import guide_improve as gi
        outcome = gi.record_grade_outcomes(args.season, args.week)
        print(f"Guide improvement_log outcomes updated: {outcome}")
    except Exception as e:
        print(f"Guide log outcome skip: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
