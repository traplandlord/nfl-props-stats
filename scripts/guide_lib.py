"""Guide tab: challenge card / locked week vs predictions + weekly actuals.

Real data only. Live progress = latest weekly_player_stats parquet for that
season/week when present — never fabricated play-by-play.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

try:
    from config import ROOT, DATA_DIR as DATA, PRED_DIR, ENTRIES_DIR, EXT_DIR, GUIDE_DIR, GRADES_DIR
except ImportError:  # pragma: no cover
    ROOT = Path(__file__).resolve().parents[1]
    DATA = ROOT / "data"
    PRED_DIR = DATA / "predictions"
    ENTRIES_DIR = DATA / "entries"
    EXT_DIR = DATA / "external"
    GUIDE_DIR = DATA / "guide"
    GRADES_DIR = DATA / "grades"
WEEKLY_PATH = DATA / "weekly_player_stats.parquet"
LOG_PATH = GUIDE_DIR / "improvement_log.jsonl"

PROP_COLS = {
    "passing_yards": "passing_yards",
    "passing_tds": "passing_tds",
    "rushing_yards": "rushing_yards",
    "rushing_tds": "rushing_tds",
    "receiving_yards": "receiving_yards",
    "receptions": "receptions",
    "touches": "touches",
}

_WEEKLY_CACHE: dict[str, Any] = {"ts": 0.0, "df": None, "key": None}
_WEEKLY_TTL = 180.0


def _now_pt() -> str:
    pt = datetime.now(timezone.utc).astimezone(ZoneInfo("America/Los_Angeles"))
    return pt.strftime("%Y-%m-%d %H:%M:%S %Z") + " (PT)"


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


def list_entries(limit: int = 20) -> list[dict]:
    ENTRIES_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for p in sorted(ENTRIES_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.name == "latest.json":
            continue
        try:
            card = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows.append(
            {
                "entry_id": card.get("entry_id") or p.stem,
                "season": card.get("season"),
                "week": card.get("week"),
                "entry_size": card.get("entry_size") or len(card.get("players") or []),
                "updated_at_pt": card.get("updated_at_pt"),
                "player_names": [pl.get("player_name") for pl in (card.get("players") or [])[:6]],
            }
        )
        if len(rows) >= limit:
            break
    return rows


def load_entry(entry_id: str | None = None) -> dict | None:
    ENTRIES_DIR.mkdir(parents=True, exist_ok=True)
    if not entry_id:
        latest = ENTRIES_DIR / "latest.json"
        if latest.is_file():
            meta = json.loads(latest.read_text(encoding="utf-8"))
            entry_id = meta.get("entry_id")
    if not entry_id:
        return None
    path = ENTRIES_DIR / f"{entry_id}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_pred_meta(season: int, week: int) -> dict:
    js = PRED_DIR / f"season{season}_week{week}.json"
    if js.is_file():
        try:
            return json.loads(js.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


@lru_cache(maxsize=4)
def load_pred_frame(season: int, week: int) -> pd.DataFrame:
    return _safe_parquet(PRED_DIR / f"season{season}_week{week}.parquet")


def _ensure_touches(df: pd.DataFrame) -> pd.DataFrame:
    w = df.copy()
    if "touches" not in w.columns:
        carries = pd.to_numeric(w["carries"], errors="coerce").fillna(0) if "carries" in w.columns else 0
        rec = pd.to_numeric(w["receptions"], errors="coerce").fillna(0) if "receptions" in w.columns else 0
        w["touches"] = carries + rec
    return w


def load_weekly_slice(season: int, week: int) -> pd.DataFrame:
    """Bounded weekly actuals for one season/week — not full 59k scan per prop."""
    key = f"{season}_{week}"
    now = time.time()
    if (
        _WEEKLY_CACHE["df"] is not None
        and _WEEKLY_CACHE["key"] == key
        and (now - _WEEKLY_CACHE["ts"]) < _WEEKLY_TTL
    ):
        return _WEEKLY_CACHE["df"]

    if not WEEKLY_PATH.is_file():
        _WEEKLY_CACHE.update({"df": pd.DataFrame(), "key": key, "ts": now})
        return _WEEKLY_CACHE["df"]

    # Read only needed columns; filter season/week in pandas (still one file read, cached)
    cols = [
        "player_id",
        "player_display_name",
        "season",
        "week",
        "team",
        "passing_yards",
        "passing_tds",
        "rushing_yards",
        "rushing_tds",
        "receiving_yards",
        "receptions",
        "carries",
        "targets",
    ]
    df = _safe_parquet(WEEKLY_PATH, columns=cols)
    if df.empty:
        _WEEKLY_CACHE.update({"df": df, "key": key, "ts": now})
        return df
    df = df[(df["season"] == season) & (df["week"] == week)].copy()
    df = _ensure_touches(df)
    # aggregate multi-row players
    num_cols = [c for c in PROP_COLS.values() if c in df.columns]
    if num_cols and not df.empty:
        agg = df.groupby("player_id", as_index=False)[num_cols].sum()
    else:
        agg = df
    _WEEKLY_CACHE.update({"df": agg, "key": key, "ts": now})
    return agg


def _z_score(actual: float | None, mean: float | None, sd: float | None) -> float | None:
    if actual is None or mean is None:
        return None
    if sd is None or sd <= 1e-9:
        return None
    return float((actual - mean) / sd)


def _challenge_label(z: float | None) -> str:
    if z is None:
        return "no_actual_yet"
    az = abs(z)
    if az < 0.5:
        return "on_track"
    if az < 1.0:
        return "mild_miss"
    if az < 2.0:
        return "off_track"
    return "large_residual"


def _espn_vegas_from_pred_row(row: pd.Series | dict) -> tuple[Any, str, Any, str]:
    if isinstance(row, pd.Series):
        row = row.to_dict()
    espn = row.get("espn_projection")
    espn_status = row.get("espn_status") or (
        "loaded" if espn is not None and not (isinstance(espn, float) and np.isnan(espn)) else "not_loaded"
    )
    if espn is not None and isinstance(espn, float) and np.isnan(espn):
        espn = None
        espn_status = "not_loaded"
    vegas = row.get("vegas_line")
    vegas_status = row.get("vegas_status") or (
        "loaded" if vegas is not None and not (isinstance(vegas, float) and np.isnan(vegas)) else "not_loaded"
    )
    if vegas is not None and isinstance(vegas, float) and np.isnan(vegas):
        vegas = None
        vegas_status = "not_loaded"
    # Never show fabricated numbers
    if espn_status != "loaded":
        espn = None
    if vegas_status != "loaded":
        vegas = None
    return espn, str(espn_status), vegas, str(vegas_status)


def challenge_player_props(
    season: int,
    week: int,
    gsis_id: str,
    player_meta: dict | None = None,
) -> list[dict]:
    pred = load_pred_frame(season, week)
    actuals = load_weekly_slice(season, week)
    actual_map: dict[str, float] = {}
    if not actuals.empty and "player_id" in actuals.columns:
        hit = actuals[actuals["player_id"].astype(str) == str(gsis_id)]
        if not hit.empty:
            for prop, col in PROP_COLS.items():
                if col in hit.columns and pd.notna(hit.iloc[0][col]):
                    actual_map[prop] = float(hit.iloc[0][col])

    rows_out: list[dict] = []
    if pred.empty:
        # fall back to props stored on the card
        for pr in (player_meta or {}).get("props") or []:
            prop = pr.get("prop")
            mean = pr.get("ours_mean")
            sd = pr.get("ours_sd")
            actual = actual_map.get(prop)
            z = _z_score(actual, mean, sd)
            rows_out.append(
                {
                    "prop": prop,
                    "ours_mean": mean,
                    "ours_sd": sd,
                    "espn_projection": None,
                    "espn_status": pr.get("espn_status") or "not_loaded",
                    "vegas_line": None,
                    "vegas_status": pr.get("vegas_status") or "not_loaded",
                    "live_actual": actual,
                    "live_source": (
                        f"weekly_player_stats season={season} week={week}"
                        if actual is not None
                        else "no weekly row yet (not inventing live PBP)"
                    ),
                    "challenge_z": z,
                    "challenge_residual": (actual - mean) if (actual is not None and mean is not None) else None,
                    "challenge_label": _challenge_label(z),
                    "flags": pr.get("flags") or "",
                }
            )
        return rows_out

    sub = pred[pred["gsis_id"].astype(str) == str(gsis_id)]
    for _, r in sub.iterrows():
        prop = r["prop"]
        mean = float(r["ours_mean"]) if pd.notna(r.get("ours_mean")) else None
        sd = float(r["ours_sd"]) if pd.notna(r.get("ours_sd")) else None
        espn, espn_st, vegas, vegas_st = _espn_vegas_from_pred_row(r)
        actual = actual_map.get(prop)
        z = _z_score(actual, mean, sd)
        rows_out.append(
            {
                "prop": prop,
                "ours_mean": mean,
                "ours_sd": sd,
                "espn_projection": float(espn) if espn is not None else None,
                "espn_status": espn_st if espn is not None else "not_loaded",
                "vegas_line": float(vegas) if vegas is not None else None,
                "vegas_status": vegas_st if vegas is not None else "not_loaded",
                "live_actual": actual,
                "live_source": (
                    f"data/weekly_player_stats.parquet season={season} week={week}"
                    if actual is not None
                    else "no weekly row yet (awaiting nflverse weekly; not inventing live PBP)"
                ),
                "challenge_z": round(z, 3) if z is not None else None,
                "challenge_residual": (
                    round(actual - mean, 3) if (actual is not None and mean is not None) else None
                ),
                "challenge_label": _challenge_label(z),
                "flags": r.get("flags") or "",
            }
        )
    return rows_out


def build_challenge(
    season: int | None = None,
    week: int | None = None,
    entry_id: str | None = None,
    *,
    page: int = 0,
    page_size: int = 12,
    locked_only: bool = False,
) -> dict[str, Any]:
    """Challenge an entry card, or paginated locked-week props if no card / locked_only."""
    card = None if locked_only else load_entry(entry_id)
    if card and season is None:
        season = int(card.get("season") or 2026)
    if card and week is None:
        week = int(card.get("week") or 3)
    if season is None or week is None:
        # default from latest prediction
        weeks = []
        for p in PRED_DIR.glob("season*_week*.parquet"):
            try:
                _, rest = p.stem.split("season", 1)
                s, w = rest.split("_week", 1)
                weeks.append((int(s), int(w)))
            except Exception:
                continue
        if weeks:
            season, week = sorted(weeks)[-1]
        else:
            season, week = 2026, 3

    meta = load_pred_meta(season, week)
    weekly = load_weekly_slice(season, week)
    has_weekly = not weekly.empty

    players_out: list[dict] = []
    source = "entry"

    if card and not locked_only:
        for pl in card.get("players") or []:
            gsis = str(pl.get("gsis_id") or "")
            props = challenge_player_props(season, week, gsis, pl)
            players_out.append(
                {
                    "gsis_id": gsis,
                    "player_name": pl.get("player_name"),
                    "team": pl.get("team"),
                    "team_logo": pl.get("team_logo") or "",
                    "position": pl.get("position"),
                    "photo_url": pl.get("photo_url"),
                    "role_bucket": pl.get("role_bucket"),
                    "opponent": pl.get("opponent"),
                    "jersey_number": pl.get("jersey_number"),
                    "props": props,
                }
            )
        entry_meta = {
            "entry_id": card.get("entry_id"),
            "entry_size": card.get("entry_size"),
            "updated_at_pt": card.get("updated_at_pt"),
        }
    else:
        source = "locked_predictions"
        pred = load_pred_frame(season, week)
        entry_meta = None
        if pred.empty:
            return {
                "season": season,
                "week": week,
                "source": source,
                "entry": None,
                "meta": meta,
                "has_weekly_actuals": has_weekly,
                "as_of_pt": _now_pt(),
                "players": [],
                "page": page,
                "page_size": page_size,
                "total_players": 0,
                "note": "No predictions parquet — run predict_week.py",
            }
        # unique players, paginate
        ids = list(pred.drop_duplicates("gsis_id")["gsis_id"].astype(str))
        total = len(ids)
        page = max(0, int(page))
        page_size = max(1, min(40, int(page_size)))
        chunk = ids[page * page_size : (page + 1) * page_size]
        for gsis in chunk:
            sub = pred[pred["gsis_id"].astype(str) == gsis].iloc[0]
            props = challenge_player_props(season, week, gsis)
            photo = sub.get("photo_url")
            if isinstance(photo, float) and np.isnan(photo):
                photo = None
            players_out.append(
                {
                    "gsis_id": gsis,
                    "player_name": sub.get("player_name"),
                    "team": str(sub.get("team") or "").upper(),
                    "team_logo": "",
                    "position": sub.get("position"),
                    "photo_url": photo,
                    "role_bucket": sub.get("role_bucket"),
                    "opponent": sub.get("opponent"),
                    "jersey_number": (
                        None
                        if pd.isna(sub.get("jersey_number"))
                        else sub.get("jersey_number")
                    ),
                    "props": props,
                }
            )
        # attach logos
        try:
            from entry_builder_lib import load_logo_map

            logos = load_logo_map()
            for pl in players_out:
                pl["team_logo"] = logos.get(str(pl.get("team") or "").upper(), "")
        except Exception:
            pass
        return {
            "season": season,
            "week": week,
            "source": source,
            "entry": entry_meta,
            "meta": meta,
            "has_weekly_actuals": has_weekly,
            "weekly_note": (
                f"Weekly actuals present for {season} w{week} ({len(weekly)} players)"
                if has_weekly
                else f"No weekly_player_stats rows for {season} w{week} yet — challenge z unavailable until nflverse updates"
            ),
            "as_of_pt": _now_pt(),
            "players": players_out,
            "page": page,
            "page_size": page_size,
            "total_players": total,
            "has_next": (page + 1) * page_size < total,
            "has_prev": page > 0,
            "label": "MODEL ESTIMATES challenged vs real weekly actuals when available",
        }

    return {
        "season": season,
        "week": week,
        "source": source,
        "entry": entry_meta,
        "meta": meta,
        "has_weekly_actuals": has_weekly,
        "weekly_note": (
            f"Weekly actuals present for {season} w{week} ({len(weekly)} players)"
            if has_weekly
            else f"No weekly_player_stats rows for {season} w{week} yet — live progress awaits nflverse weekly parquet"
        ),
        "as_of_pt": _now_pt(),
        "players": players_out,
        "page": 0,
        "page_size": len(players_out),
        "total_players": len(players_out),
        "has_next": False,
        "has_prev": False,
        "label": "MODEL ESTIMATES on card — ESPN/Vegas only if loaded; never invented",
    }


def clear_caches() -> None:
    load_pred_frame.cache_clear()
    _WEEKLY_CACHE.update({"ts": 0.0, "df": None, "key": None})
