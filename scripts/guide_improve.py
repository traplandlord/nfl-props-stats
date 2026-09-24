#!/usr/bin/env python3
"""Propose MODEL ESTIMATE revisions when justified by real signals.

Signals (must cite columns/files):
  - injury status change (data/injuries.parquet)
  - depth / role_bucket change (data/player_roles_current.parquet vs prediction)
  - snap/usage drift from recent weeks (data/player_usage_weekly.parquet)
  - huge residual vs locked mean when weekly actuals exist

Updates use empirical-Bayes / shrinkage — documented as MODEL ESTIMATES.
Never invents ESPN/Vegas or exponential fake math.

Also maintains data/guide/improvement_log.jsonl for later grade_week outcomes.

Usage:
  ./.venv/bin/python scripts/guide_improve.py --season 2026 --week 3
  ./.venv/bin/python scripts/guide_improve.py --entry-id <uuid>
  ./.venv/bin/python scripts/guide_improve.py --season 2026 --week 2 --record-grades
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

try:
    from config import ROOT, DATA_DIR as DATA, PRED_DIR, GUIDE_DIR, GRADES_DIR
except ImportError:  # pragma: no cover
    ROOT = Path(__file__).resolve().parents[1]
    DATA = ROOT / "data"
    PRED_DIR = DATA / "predictions"
    GUIDE_DIR = DATA / "guide"
    GRADES_DIR = DATA / "grades"
LOG_PATH = GUIDE_DIR / "improvement_log.jsonl"
INJ_PATH = DATA / "injuries.parquet"
ROLES_PATH = DATA / "player_roles_current.parquet"
USAGE_WEEKLY_PATH = DATA / "player_usage_weekly.parquet"

PRIOR_K = 3.0  # same shrink strength family as predict_week
RESIDUAL_Z_TRIGGER = 1.75
USAGE_DRIFT_PCT = 0.35  # 35% relative drift in offense_pct / touches
MAX_SUGGESTIONS = 40

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _now_pt() -> str:
    pt = datetime.now(timezone.utc).astimezone(ZoneInfo("America/Los_Angeles"))
    return pt.strftime("%Y-%m-%d %H:%M:%S %Z") + " (PT)"


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_parquet(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    try:
        if columns:
            try:
                return pd.read_parquet(path, columns=columns)
            except Exception:
                df = pd.read_parquet(path)
                keep = [c for c in columns if c in df.columns]
                return df[keep].copy() if keep else df
        return pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()


def _eb_update(mean: float, sd: float, evidence_mean: float, n_eff: float, prior_k: float = PRIOR_K) -> dict:
    """Empirical-Bayes shrink of locked mean toward new evidence.

    posterior_mean = (prior_k * mean + n_eff * evidence_mean) / (prior_k + n_eff)
    Expected lift = posterior_mean - mean (MODEL ESTIMATE, not a guarantee).
    """
    k = max(float(prior_k), 0.1)
    n = max(float(n_eff), 0.1)
    post = (k * mean + n * evidence_mean) / (k + n)
    # shrink sd slightly toward evidence uncertainty (heuristic, documented)
    post_sd = float(sd) * np.sqrt(k / (k + n)) if sd and sd > 0 else sd
    return {
        "revised_mean": round(float(post), 3),
        "revised_sd": round(float(post_sd), 3) if post_sd is not None else None,
        "expected_lift": round(float(post - mean), 3),
        "method": "empirical_bayes_shrink",
        "prior_k": k,
        "n_eff": n,
        "label": "MODEL ESTIMATE",
    }


def _append_log(record: dict) -> None:
    GUIDE_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


def read_log(limit: int = 100) -> list[dict]:
    if not LOG_PATH.is_file():
        return []
    lines = LOG_PATH.read_text(encoding="utf-8").strip().splitlines()
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def _target_players(season: int, week: int, entry_id: str | None) -> list[str]:
    """Card players first; always union a bounded starter/rotation scan for the week."""
    import guide_lib as gl

    ids: list[str] = []
    card = gl.load_entry(entry_id) if entry_id else None
    if card is None and not entry_id:
        card = gl.load_entry(None)
    if card and int(card.get("season") or 0) == season and int(card.get("week") or 0) == week:
        ids.extend(str(p["gsis_id"]) for p in card.get("players") or [] if p.get("gsis_id"))

    pred = gl.load_pred_frame(season, week)
    if not pred.empty:
        sub = (
            pred[pred["role_bucket"].isin(["starter", "rotation"])]
            if "role_bucket" in pred.columns
            else pred
        )
        ids.extend(sub.drop_duplicates("gsis_id")["gsis_id"].astype(str).head(80).tolist())

    # preserve order, unique
    seen = set()
    out = []
    for g in ids:
        if g not in seen:
            seen.add(g)
            out.append(g)
    return out


def _injury_signals(gsis_ids: list[str], season: int, week: int) -> dict[str, dict]:
    inj = _safe_parquet(
        INJ_PATH,
        columns=[
            "season",
            "week",
            "gsis_id",
            "full_name",
            "team",
            "report_status",
            "report_primary_injury",
            "practice_status",
            "date_modified",
        ],
    )
    if inj.empty or "gsis_id" not in inj.columns:
        return {}
    inj = inj[inj["season"] == season].copy()
    # compare week-1 vs week (or latest available <= week)
    out: dict[str, dict] = {}
    for gid in gsis_ids:
        sub = inj[inj["gsis_id"].astype(str) == str(gid)].sort_values("week")
        if sub.empty:
            continue
        cur = sub[sub["week"] == week]
        prev = sub[sub["week"] == week - 1]
        if cur.empty:
            # latest <= week
            cur = sub[sub["week"] <= week].tail(1)
        if cur.empty:
            continue
        c = cur.iloc[-1]
        status = str(c.get("report_status") or "")
        prev_status = str(prev.iloc[-1].get("report_status") or "") if not prev.empty else ""
        changed = bool(prev_status and status and prev_status != status)
        notable = status.lower() in {"out", "doubtful", "questionable"} or changed
        if not notable:
            continue
        out[str(gid)] = {
            "signal": "injury_status",
            "cite": "data/injuries.parquet columns: report_status, report_primary_injury, week, gsis_id",
            "report_status": status or None,
            "prev_report_status": prev_status or None,
            "report_primary_injury": c.get("report_primary_injury"),
            "practice_status": c.get("practice_status"),
            "week_observed": int(c["week"]) if pd.notna(c.get("week")) else None,
            "changed": changed,
        }
    return out


def _role_signals(gsis_ids: list[str], pred: pd.DataFrame) -> dict[str, dict]:
    roles = _safe_parquet(
        ROLES_PATH,
        columns=["gsis_id", "role_bucket", "depth_order", "position", "team", "player_name", "week", "season"],
    )
    if roles.empty:
        return {}
    roles = roles.drop_duplicates("gsis_id", keep="last")
    out: dict[str, dict] = {}
    pred_role = {}
    if not pred.empty:
        for _, r in pred.drop_duplicates("gsis_id").iterrows():
            pred_role[str(r["gsis_id"])] = {
                "role_bucket": r.get("role_bucket"),
                "depth_order": r.get("depth_order"),
            }
    for gid in gsis_ids:
        hit = roles[roles["gsis_id"].astype(str) == str(gid)]
        if hit.empty:
            continue
        r = hit.iloc[0]
        locked = pred_role.get(str(gid), {})
        cur_role = str(r.get("role_bucket") or "")
        old_role = str(locked.get("role_bucket") or "")
        cur_depth = r.get("depth_order")
        old_depth = locked.get("depth_order")
        changed = False
        if old_role and cur_role and old_role != cur_role:
            changed = True
        try:
            if old_depth is not None and cur_depth is not None and int(old_depth) != int(cur_depth):
                changed = True
        except (TypeError, ValueError):
            pass
        if not changed:
            continue
        out[str(gid)] = {
            "signal": "depth_role_change",
            "cite": "data/player_roles_current.parquet role_bucket/depth_order vs predictions lock",
            "locked_role_bucket": old_role or None,
            "current_role_bucket": cur_role or None,
            "locked_depth_order": old_depth,
            "current_depth_order": None if pd.isna(cur_depth) else cur_depth,
        }
    return out


def _usage_drift_signals(gsis_ids: list[str], season: int, week: int) -> dict[str, dict]:
    """Compare last 2 weeks avg vs prior 3 weeks for offense_pct / touches."""
    cols = [
        "player_id",
        "season",
        "week",
        "offense_pct",
        "offense_snaps",
        "touches",
        "targets",
        "carries",
        "receptions",
    ]
    uw = _safe_parquet(USAGE_WEEKLY_PATH, columns=cols)
    if uw.empty:
        return {}
    # ensure touches
    if "touches" not in uw.columns:
        carries = pd.to_numeric(uw.get("carries"), errors="coerce").fillna(0)
        rec = pd.to_numeric(uw.get("receptions"), errors="coerce").fillna(0)
        uw = uw.copy()
        uw["touches"] = carries + rec
    uw = uw[uw["season"] == season].copy()
    out: dict[str, dict] = {}
    for gid in gsis_ids:
        sub = uw[uw["player_id"].astype(str) == str(gid)].sort_values("week")
        # only weeks strictly before target week (trailing)
        sub = sub[sub["week"] < week]
        if len(sub) < 3:
            continue
        recent = sub.tail(2)
        prior = sub.iloc[:-2].tail(3)
        if prior.empty or recent.empty:
            continue
        for metric in ("offense_pct", "touches"):
            if metric not in sub.columns:
                continue
            r_mean = float(pd.to_numeric(recent[metric], errors="coerce").mean())
            p_mean = float(pd.to_numeric(prior[metric], errors="coerce").mean())
            if p_mean == 0 or np.isnan(p_mean) or np.isnan(r_mean):
                continue
            rel = (r_mean - p_mean) / abs(p_mean)
            if abs(rel) < USAGE_DRIFT_PCT:
                continue
            out[str(gid)] = {
                "signal": "usage_drift",
                "cite": f"data/player_usage_weekly.parquet metric={metric} (recent2 vs prior3 before week {week})",
                "metric": metric,
                "recent_mean": round(r_mean, 3),
                "prior_mean": round(p_mean, 3),
                "relative_change": round(float(rel), 3),
                "weeks_recent": [int(x) for x in recent["week"].tolist()],
                "weeks_prior": [int(x) for x in prior["week"].tolist()],
            }
            break
    return out


def propose_improvements(
    season: int,
    week: int,
    entry_id: str | None = None,
    *,
    write_log: bool = True,
    limit: int = MAX_SUGGESTIONS,
) -> dict[str, Any]:
    import guide_lib as gl

    pred = gl.load_pred_frame(season, week)
    gsis_ids = _target_players(season, week, entry_id)
    if not gsis_ids and not pred.empty:
        gsis_ids = list(pred.drop_duplicates("gsis_id")["gsis_id"].astype(str).head(40))

    inj = _injury_signals(gsis_ids, season, week)
    roles = _role_signals(gsis_ids, pred)
    usage = _usage_drift_signals(gsis_ids, season, week)

    # residuals from challenge (prefer entry card when it matches season/week)
    card = gl.load_entry(entry_id)
    if card and int(card.get("season") or 0) == season and int(card.get("week") or 0) == week:
        challenge = gl.build_challenge(season, week, card.get("entry_id"))
    elif entry_id:
        challenge = gl.build_challenge(season, week, entry_id)
    else:
        # latest entry if same week, else paginated locked pool page 0
        latest = gl.load_entry(None)
        if latest and int(latest.get("season") or 0) == season and int(latest.get("week") or 0) == week:
            challenge = gl.build_challenge(season, week, latest.get("entry_id"))
        else:
            challenge = gl.build_challenge(season, week, locked_only=True, page=0, page_size=40)

    residual_hits: dict[str, list[dict]] = {}
    for pl in challenge.get("players") or []:
        gid = str(pl.get("gsis_id"))
        for pr in pl.get("props") or []:
            z = pr.get("challenge_z")
            if z is None:
                continue
            if abs(float(z)) >= RESIDUAL_Z_TRIGGER:
                residual_hits.setdefault(gid, []).append(
                    {
                        "signal": "huge_residual",
                        "cite": "challenge z = (live_actual - ours_mean) / ours_sd from weekly_player_stats + predictions",
                        "prop": pr.get("prop"),
                        "challenge_z": z,
                        "live_actual": pr.get("live_actual"),
                        "ours_mean": pr.get("ours_mean"),
                        "ours_sd": pr.get("ours_sd"),
                    }
                )

    suggestions: list[dict] = []
    seen = set()

    # Build name map
    name_map = {}
    if not pred.empty:
        for _, r in pred.drop_duplicates("gsis_id").iterrows():
            name_map[str(r["gsis_id"])] = {
                "player_name": r.get("player_name"),
                "team": r.get("team"),
                "position": r.get("position"),
                "role_bucket": r.get("role_bucket"),
            }

    def _pred_props(gid: str) -> pd.DataFrame:
        if pred.empty:
            return pd.DataFrame()
        return pred[pred["gsis_id"].astype(str) == str(gid)]

    for gid in gsis_ids:
        signals: list[dict] = []
        if gid in inj:
            signals.append(inj[gid])
        if gid in roles:
            signals.append(roles[gid])
        if gid in usage:
            signals.append(usage[gid])
        if gid in residual_hits:
            signals.extend(residual_hits[gid])
        if not signals:
            continue

        props_df = _pred_props(gid)
        meta = name_map.get(gid, {})
        # propose per primary prop
        prop_rows = list(props_df.iterrows()) if not props_df.empty else []
        if not prop_rows:
            # still emit a qualitative suggestion without number change
            sug_id = str(uuid.uuid4())
            why = "; ".join(f"{s['signal']} ({s['cite']})" for s in signals[:3])
            rec = {
                "suggestion_id": sug_id,
                "created_at_pt": _now_pt(),
                "created_at_utc": _now_utc(),
                "season": season,
                "week": week,
                "gsis_id": gid,
                "player_name": meta.get("player_name"),
                "team": meta.get("team"),
                "position": meta.get("position"),
                "prop": None,
                "what_to_change": "Re-check player before locking — signals present but no prop row in predictions",
                "why": why,
                "signals": signals,
                "revision": None,
                "expected_lift": None,
                "label": "MODEL ESTIMATE — qualitative only",
                "outcome": None,
            }
            suggestions.append(rec)
            continue

        for _, prow in prop_rows:
            prop = prow["prop"]
            key = (gid, prop)
            if key in seen:
                continue
            # Only revise when we have a quantitative signal for this prop or injury/role/usage
            mean = float(prow["ours_mean"]) if pd.notna(prow.get("ours_mean")) else None
            sd = float(prow["ours_sd"]) if pd.notna(prow.get("ours_sd")) else None
            if mean is None:
                continue

            evidence_mean = mean
            n_eff = 1.0
            change_bits = []
            applicable = False

            for s in signals:
                sig = s["signal"]
                if sig == "injury_status":
                    st = str(s.get("report_status") or "").lower()
                    if st in {"out", "doubtful"}:
                        evidence_mean = 0.0
                        n_eff = 4.0
                        change_bits.append(f"injury {st} → shrink mean toward 0")
                        applicable = True
                    elif st == "questionable":
                        evidence_mean = mean * 0.85
                        n_eff = 2.0
                        change_bits.append("questionable → mild downweight (~15%)")
                        applicable = True
                elif sig == "depth_role_change":
                    new_r = str(s.get("current_role_bucket") or "")
                    old_r = str(s.get("locked_role_bucket") or "")
                    order = {"starter": 0, "rotation": 1, "bench_warmer": 2}
                    if order.get(new_r, 9) < order.get(old_r, 9):
                        evidence_mean = mean * 1.12
                        n_eff = 2.5
                        change_bits.append(f"role upgrade {old_r}→{new_r}")
                        applicable = True
                    elif order.get(new_r, 9) > order.get(old_r, 9):
                        evidence_mean = mean * 0.88
                        n_eff = 2.5
                        change_bits.append(f"role downgrade {old_r}→{new_r}")
                        applicable = True
                elif sig == "usage_drift":
                    rel = float(s.get("relative_change") or 0)
                    # map usage drift into evidence on volume props
                    if prop in {"touches", "receptions", "rushing_yards", "receiving_yards", "passing_yards", "targets"}:
                        evidence_mean = mean * (1.0 + max(-0.25, min(0.25, rel * 0.5)))
                        n_eff = 2.0
                        change_bits.append(
                            f"usage drift {s.get('metric')} rel={s.get('relative_change')}"
                        )
                        applicable = True
                elif sig == "huge_residual" and s.get("prop") == prop:
                    act = s.get("live_actual")
                    if act is not None:
                        evidence_mean = float(act)
                        n_eff = 3.0
                        change_bits.append(f"huge residual z={s.get('challenge_z')}")
                        applicable = True

            if not applicable:
                continue
            seen.add(key)
            revision = _eb_update(mean, sd or 1.0, evidence_mean, n_eff)
            why = "; ".join(
                f"{s['signal']}: cite {s['cite']}" for s in signals[:4]
            )
            sug_id = str(uuid.uuid4())
            rec = {
                "suggestion_id": sug_id,
                "created_at_pt": _now_pt(),
                "created_at_utc": _now_utc(),
                "season": season,
                "week": week,
                "gsis_id": gid,
                "player_name": meta.get("player_name") or prow.get("player_name"),
                "team": meta.get("team") or prow.get("team"),
                "position": meta.get("position") or prow.get("position"),
                "prop": prop,
                "what_to_change": (
                    f"Revise {prop} ours_mean {mean:.2f} → {revision['revised_mean']:.2f} "
                    f"(±{revision['revised_sd']}); " + ", ".join(change_bits)
                ),
                "why": why,
                "signals": signals,
                "revision": revision,
                "expected_lift": revision["expected_lift"],
                "label": "MODEL ESTIMATE — empirical Bayes / shrinkage; not a guarantee",
                "locked_ours_mean": mean,
                "locked_ours_sd": sd,
                "outcome": None,
            }
            suggestions.append(rec)
            if len(suggestions) >= limit:
                break
        if len(suggestions) >= limit:
            break

    # sort by abs expected lift
    suggestions.sort(key=lambda r: abs(r.get("expected_lift") or 0), reverse=True)
    suggestions = suggestions[:limit]

    if write_log:
        for rec in suggestions:
            log_row = {
                "event": "suggestion",
                "suggestion_id": rec["suggestion_id"],
                "season": season,
                "week": week,
                "gsis_id": rec["gsis_id"],
                "prop": rec.get("prop"),
                "expected_lift": rec.get("expected_lift"),
                "revision": rec.get("revision"),
                "locked_ours_mean": rec.get("locked_ours_mean"),
                "locked_ours_sd": rec.get("locked_ours_sd"),
                "what_to_change": rec.get("what_to_change"),
                "why": rec.get("why"),
                "created_at_pt": rec["created_at_pt"],
                "outcome": None,
            }
            _append_log(log_row)

    return {
        "season": season,
        "week": week,
        "as_of_pt": _now_pt(),
        "n_suggestions": len(suggestions),
        "suggestions": suggestions,
        "log_path": str(LOG_PATH.relative_to(ROOT)) if write_log else None,
        "notes": [
            "All revisions are MODEL ESTIMATES via empirical-Bayes shrinkage.",
            "Suggestions emitted only when real injury/role/usage/residual signals fire.",
            "ESPN/Vegas never invented; external CSVs unused here unless already on predictions.",
        ],
    }


def record_grade_outcomes(season: int, week: int) -> dict[str, Any]:
    """After grade_week, attach outcomes to prior suggestions in the log."""
    grade_path = GRADES_DIR / f"season{season}_week{week}.parquet"
    if not grade_path.is_file():
        return {"updated": 0, "note": f"missing {grade_path.name}"}
    graded = pd.read_parquet(grade_path)
    if graded.empty or not LOG_PATH.is_file():
        return {"updated": 0, "note": "empty grades or no log"}

    # index grades
    gmap: dict[tuple[str, str], dict] = {}
    for _, r in graded.iterrows():
        gmap[(str(r["gsis_id"]), str(r["prop"]))] = {
            "actual": float(r["actual"]) if pd.notna(r.get("actual")) else None,
            "ours_mean": float(r["ours_mean"]) if pd.notna(r.get("ours_mean")) else None,
            "abs_error": float(r["abs_error"]) if pd.notna(r.get("abs_error")) else None,
            "within_1sd": bool(r["within_1sd"]) if pd.notna(r.get("within_1sd")) else None,
        }

    lines = LOG_PATH.read_text(encoding="utf-8").splitlines()
    updated = 0
    new_lines = []
    for line in lines:
        try:
            rec = json.loads(line)
        except Exception:
            new_lines.append(line)
            continue
        if (
            rec.get("event") == "suggestion"
            and rec.get("season") == season
            and rec.get("week") == week
            and rec.get("outcome") is None
            and rec.get("prop")
        ):
            key = (str(rec.get("gsis_id")), str(rec.get("prop")))
            g = gmap.get(key)
            if g and g.get("actual") is not None:
                rev = (rec.get("revision") or {}).get("revised_mean")
                locked_mean = rec.get("locked_ours_mean")
                if locked_mean is None and rev is not None and rec.get("expected_lift") is not None:
                    locked_mean = float(rev) - float(rec["expected_lift"])
                err_locked = (
                    abs(float(locked_mean) - g["actual"])
                    if locked_mean is not None
                    else g.get("abs_error")
                )
                err_rev = abs(float(rev) - g["actual"]) if rev is not None else None
                improved = (
                    err_rev is not None and err_locked is not None and err_rev < err_locked - 1e-9
                )
                rec["outcome"] = {
                    "graded_at_pt": _now_pt(),
                    "actual": g["actual"],
                    "abs_error_locked": err_locked,
                    "abs_error_revised": err_rev,
                    "improved": improved,
                    "within_1sd_locked": g.get("within_1sd"),
                }
                updated += 1
                _append_log(
                    {
                        "event": "outcome",
                        "suggestion_id": rec.get("suggestion_id"),
                        "season": season,
                        "week": week,
                        "gsis_id": rec.get("gsis_id"),
                        "prop": rec.get("prop"),
                        "outcome": rec["outcome"],
                        "created_at_pt": _now_pt(),
                    }
                )
        new_lines.append(json.dumps(rec, default=str))

    LOG_PATH.write_text("\n".join(new_lines) + ("\n" if new_lines else ""), encoding="utf-8")
    return {"updated": updated, "season": season, "week": week, "as_of_pt": _now_pt()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Guide model-revision suggestions")
    parser.add_argument("--season", type=int, default=None)
    parser.add_argument("--week", type=int, default=None)
    parser.add_argument("--entry-id", type=str, default=None)
    parser.add_argument("--no-log", action="store_true")
    parser.add_argument("--record-grades", action="store_true", help="Attach outcomes from grades/")
    parser.add_argument("--limit", type=int, default=MAX_SUGGESTIONS)
    args = parser.parse_args()

    import guide_lib as gl

    season, week = args.season, args.week
    if season is None or week is None:
        card = gl.load_entry(args.entry_id)
        if card:
            season = season or int(card.get("season") or 2026)
            week = week or int(card.get("week") or 3)
        else:
            weeks = []
            for p in PRED_DIR.glob("season*_week*.parquet"):
                try:
                    _, rest = p.stem.split("season", 1)
                    s, w = rest.split("_week", 1)
                    weeks.append((int(s), int(w)))
                except Exception:
                    continue
            season, week = (sorted(weeks)[-1] if weeks else (2026, 3))

    if args.record_grades:
        result = record_grade_outcomes(season, week)
        print(json.dumps(result, indent=2))
        return 0

    out = propose_improvements(
        season, week, args.entry_id, write_log=not args.no_log, limit=args.limit
    )
    print(json.dumps({"n": out["n_suggestions"], "as_of_pt": out["as_of_pt"], "notes": out["notes"]}, indent=2))
    for s in out["suggestions"][:10]:
        print(
            f"- {s.get('player_name')} {s.get('prop')}: lift={s.get('expected_lift')} | {s.get('what_to_change')}"
        )
    if out.get("log_path"):
        print(f"Logged to {out['log_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
