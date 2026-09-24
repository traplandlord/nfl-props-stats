"""Lineup / 'Build my card' helpers — crash-safe, bounded loads.

Uses current-week prediction parquet + player_roles_current + season rollups.
Never invents players; never loads full weekly_player_stats (59k+) into memory.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

try:
    from config import ROOT, DATA_DIR as DATA, PRED_DIR, ENTRIES_DIR
except ImportError:  # pragma: no cover
    ROOT = Path(__file__).resolve().parents[1]
    DATA = ROOT / "data"
    PRED_DIR = DATA / "predictions"
    ENTRIES_DIR = DATA / "entries"
ROLES_PATH = DATA / "player_roles_current.parquet"
USAGE_SEASON_PATH = DATA / "player_usage_season.parquet"
PHOTOS_PATH = DATA / "players_with_photos.parquet"
PLAYERS_PATH = DATA / "players.parquet"
LOGOS_PATH = DATA / "team_logos.parquet"

ROLE_WEIGHT = {"starter": 4.0, "rotation": 2.0, "bench_warmer": 0.35}
SKILL_POS = {"QB", "RB", "WR", "TE", "FB", "HB"}
MAX_SEARCH = 25
MAX_TEAMS_PAGE = 8
MAX_PLAYERS_PER_TEAM_PAGE = 40


def _now_pt() -> str:
    pt = datetime.now(timezone.utc).astimezone(ZoneInfo("America/Los_Angeles"))
    return pt.strftime("%Y-%m-%d %H:%M:%S %Z") + " (PT)"


def _safe_parquet(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    try:
        if columns:
            # pyarrow supports columns=; fall back if schema mismatch
            try:
                return pd.read_parquet(path, columns=columns)
            except Exception:
                df = pd.read_parquet(path)
                keep = [c for c in columns if c in df.columns]
                return df[keep].copy() if keep else df
        return pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()


@lru_cache(maxsize=4)
def load_pred_frame(season: int, week: int) -> pd.DataFrame:
    path = PRED_DIR / f"season{season}_week{week}.parquet"
    df = _safe_parquet(path)
    if df.empty:
        return df
    # keep only columns needed for card / randomize
    return df


@lru_cache(maxsize=1)
def load_roles_skill() -> pd.DataFrame:
    cols = [
        "gsis_id",
        "player_name",
        "team",
        "position",
        "depth_order",
        "role_bucket",
        "jersey_number",
        "espn_id",
    ]
    df = _safe_parquet(ROLES_PATH)
    if df.empty:
        return df
    keep = [c for c in cols if c in df.columns]
    out = df[keep].copy()
    out["position"] = out["position"].astype(str).str.upper()
    out = out[out["position"].isin(SKILL_POS)]
    return out.reset_index(drop=True)


@lru_cache(maxsize=1)
def load_season_usage_rollup() -> pd.DataFrame:
    """Season rollup only — not 59k weekly rows."""
    df = _safe_parquet(USAGE_SEASON_PATH)
    if df.empty:
        return df
    # latest season per player
    if "season" in df.columns:
        max_season = int(pd.to_numeric(df["season"], errors="coerce").max())
        df = df[pd.to_numeric(df["season"], errors="coerce") == max_season]
    id_col = "player_id" if "player_id" in df.columns else ("gsis_id" if "gsis_id" in df.columns else None)
    if id_col is None:
        return pd.DataFrame()
    keep = [id_col]
    for c in ("avg_touches", "avg_offense_snaps", "games_played", "sum_touches", "team"):
        if c in df.columns:
            keep.append(c)
    out = df[keep].copy()
    out = out.rename(columns={id_col: "gsis_id"})
    # one row per player
    out = out.drop_duplicates("gsis_id", keep="first")
    return out


@lru_cache(maxsize=1)
def load_photo_map() -> dict[str, str]:
    path = PHOTOS_PATH if PHOTOS_PATH.is_file() else PLAYERS_PATH
    df = _safe_parquet(path)
    if df.empty or "gsis_id" not in df.columns:
        return {}
    url_col = None
    for c in ("photo_url", "headshot", "espn_headshot_url"):
        if c in df.columns:
            url_col = c
            break
    if url_col is None:
        return {}
    out: dict[str, str] = {}
    for _, r in df[["gsis_id", url_col]].dropna(subset=["gsis_id"]).iterrows():
        if pd.notna(r[url_col]) and str(r[url_col]).strip():
            out[str(r["gsis_id"])] = str(r[url_col])
    return out


@lru_cache(maxsize=1)
def load_logo_map() -> dict[str, str]:
    df = _safe_parquet(LOGOS_PATH)
    if df.empty:
        return {}
    abbr = "team_abbr" if "team_abbr" in df.columns else None
    logo = None
    for c in ("team_logo_espn", "logo_espn", "team_logo"):
        if c in df.columns:
            logo = c
            break
    if not abbr or not logo:
        return {}
    out = {}
    for _, r in df.iterrows():
        out[str(r[abbr]).upper()] = str(r[logo]) if pd.notna(r[logo]) else ""
    return out


def list_pred_weeks() -> list[tuple[int, int]]:
    if not PRED_DIR.is_dir():
        return []
    out = []
    for p in PRED_DIR.glob("season*_week*.parquet"):
        try:
            _, rest = p.stem.split("season", 1)
            s, w = rest.split("_week", 1)
            out.append((int(s), int(w)))
        except Exception:
            continue
    return sorted(set(out))


def default_season_week() -> tuple[int, int]:
    try:
        import nflreadpy as nfl

        return int(nfl.get_current_season()), int(nfl.get_current_week())
    except Exception:
        weeks = list_pred_weeks()
        return weeks[-1] if weeks else (2026, 3)


def _confidence_weight(row: pd.Series) -> float:
    role = str(row.get("role_bucket") or "bench_warmer")
    w = ROLE_WEIGHT.get(role, 0.2)
    # trailing usage confidence from pred n_games or season rollup
    n = row.get("ours_n_games")
    if pd.isna(n):
        n = row.get("actuals_n")
    try:
        n = float(n) if n is not None and not pd.isna(n) else 0.0
    except (TypeError, ValueError):
        n = 0.0
    conf = row.get("ours_confidence")
    if conf == "high":
        w *= 1.4
    elif conf == "medium":
        w *= 1.1
    elif conf == "low":
        w *= 0.6
    w *= 1.0 + min(n, 6) / 6.0
    avg_touches = row.get("avg_touches")
    try:
        if avg_touches is not None and not pd.isna(avg_touches):
            w *= 1.0 + min(float(avg_touches), 20) / 40.0
    except (TypeError, ValueError):
        pass
    return max(w, 0.01)


def candidate_pool(season: int, week: int) -> pd.DataFrame:
    """League-wide unique skill players for the week (all teams).

    Used by search + randomize — never restricted to one team.
    """
    pred = load_pred_frame(season, week)
    usage = load_season_usage_rollup()
    photos = load_photo_map()

    if not pred.empty:
        # one row per player; keep first prop's meta + aggregate confidence
        cols = [
            c
            for c in (
                "gsis_id",
                "player_name",
                "team",
                "position",
                "jersey_number",
                "photo_url",
                "depth_order",
                "role_bucket",
                "opponent",
                "ours_n_games",
                "actuals_n",
                "ours_confidence",
            )
            if c in pred.columns
        ]
        # take max n_games / best confidence per player
        g = pred.sort_values(
            ["gsis_id", "ours_n_games"] if "ours_n_games" in pred.columns else ["gsis_id"],
            ascending=[True, False] if "ours_n_games" in pred.columns else [True],
        )
        base = g.drop_duplicates("gsis_id", keep="first")[cols].copy()
    else:
        base = load_roles_skill().copy()
        if base.empty:
            return base
        base["photo_url"] = base["gsis_id"].map(lambda x: photos.get(str(x)))
        base["opponent"] = None
        base["ours_n_games"] = 0
        base["actuals_n"] = 0
        base["ours_confidence"] = "low"

    if not usage.empty:
        base = base.merge(usage, on="gsis_id", how="left", suffixes=("", "_usage"))

    if "photo_url" not in base.columns or base["photo_url"].isna().all():
        base["photo_url"] = base["gsis_id"].astype(str).map(lambda x: photos.get(x))

    base["weight"] = base.apply(_confidence_weight, axis=1)
    return base.reset_index(drop=True)


def player_props(season: int, week: int, gsis_id: str) -> list[dict]:
    pred = load_pred_frame(season, week)
    if pred.empty:
        return []
    sub = pred[pred["gsis_id"].astype(str) == str(gsis_id)]
    out = []
    for _, r in sub.iterrows():
        out.append(
            {
                "prop": r["prop"],
                "ours_mean": float(r["ours_mean"]) if pd.notna(r.get("ours_mean")) else None,
                "ours_sd": float(r["ours_sd"]) if pd.notna(r.get("ours_sd")) else None,
                "actuals_mean": float(r["actuals_mean"]) if pd.notna(r.get("actuals_mean")) else None,
                "espn_status": r.get("espn_status"),
                "vegas_status": r.get("vegas_status"),
                "flags": r.get("flags") or "",
            }
        )
    return out


def enrich_player(row: dict | pd.Series, season: int, week: int) -> dict:
    logos = load_logo_map()
    if isinstance(row, pd.Series):
        row = row.to_dict()
    gsis = str(row["gsis_id"])
    team = str(row.get("team") or "").upper()
    return {
        "gsis_id": gsis,
        "player_name": row.get("player_name") or row.get("display_name") or "",
        "team": team,
        "team_logo": logos.get(team, ""),
        "position": str(row.get("position") or "").upper(),
        "jersey_number": None
        if row.get("jersey_number") is None or (isinstance(row.get("jersey_number"), float) and pd.isna(row.get("jersey_number")))
        else row.get("jersey_number"),
        "photo_url": row.get("photo_url") or load_photo_map().get(gsis),
        "role_bucket": row.get("role_bucket") or "bench_warmer",
        "depth_order": row.get("depth_order"),
        "opponent": row.get("opponent"),
        "ours_confidence": row.get("ours_confidence"),
        "props": player_props(season, week, gsis),
    }


def search_candidates(season: int, week: int, q: str, limit: int = MAX_SEARCH) -> list[dict]:
    q = (q or "").strip().lower()
    if len(q) < 2:
        return []
    pool = candidate_pool(season, week)
    if pool.empty:
        return []
    names = pool["player_name"].astype(str).str.lower()
    mask = names.str.contains(re.escape(q), na=False)
    # also team abbr
    if "team" in pool.columns:
        mask = mask | pool["team"].astype(str).str.lower().str.contains(re.escape(q), na=False)
    hits = pool[mask].head(limit)
    return [enrich_player(r, season, week) for _, r in hits.iterrows()]


def randomize_entry(season: int, week: int, n: int, exclude: set[str] | None = None) -> list[dict]:
    """Sample N real players league-wide (any team mix — PrizePicks-style).

    Same-team is allowed but never required. Prefer starters/rotation via weights.
    Never invent players; never filter the pool to a single team.
    """
    n = max(2, min(6, int(n)))
    pool = candidate_pool(season, week)
    if pool.empty:
        return []
    exclude = exclude or set()
    pool = pool[~pool["gsis_id"].astype(str).isin(exclude)]
    # prefer starters/rotation already in weights; drop zero-weight
    if pool.empty:
        return []
    # unique players only
    pool = pool.drop_duplicates("gsis_id")
    take = min(n, len(pool))
    weights = pool["weight"].to_numpy(dtype=float)
    weights = np.nan_to_num(weights, nan=0.01)
    if weights.sum() <= 0:
        weights = np.ones(len(pool))
    probs = weights / weights.sum()
    rng = np.random.default_rng()
    idxs = rng.choice(len(pool), size=take, replace=False, p=probs)
    picked = pool.iloc[list(idxs)]
    return [enrich_player(r, season, week) for _, r in picked.iterrows()]


def build_card(players: list[dict], season: int, week: int, n: int, entry_id: str | None = None) -> dict:
    return {
        "entry_id": entry_id or str(uuid.uuid4()),
        "season": season,
        "week": week,
        "entry_size": n,
        "players": players[:n],
        "updated_at_pt": _now_pt(),
        "label": "MODEL ESTIMATES on card — not invented past results; ESPN/Vegas only if loaded",
    }


def save_entry(card: dict) -> Path:
    ENTRIES_DIR.mkdir(parents=True, exist_ok=True)
    path = ENTRIES_DIR / f"{card['entry_id']}.json"
    path.write_text(json.dumps(card, indent=2), encoding="utf-8")
    # also write latest pointer
    (ENTRIES_DIR / "latest.json").write_text(
        json.dumps({"entry_id": card["entry_id"], "path": path.name}, indent=2),
        encoding="utf-8",
    )
    return path


def load_entry(entry_id: str | None = None) -> dict | None:
    ENTRIES_DIR.mkdir(parents=True, exist_ok=True)
    if entry_id:
        path = ENTRIES_DIR / f"{entry_id}.json"
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
        return None
    latest = ENTRIES_DIR / "latest.json"
    if latest.is_file():
        meta = json.loads(latest.read_text(encoding="utf-8"))
        return load_entry(meta.get("entry_id"))
    return None


def paginate_teams(season: int, week: int, page: int = 0, page_size: int = MAX_TEAMS_PAGE) -> dict:
    """Bounded team list from predictions — never dump all rows."""
    pred = load_pred_frame(season, week)
    logos = load_logo_map()
    if pred.empty:
        return {"page": page, "page_size": page_size, "total_teams": 0, "teams": []}
    teams = sorted(pred["team"].astype(str).str.upper().unique())
    total = len(teams)
    page = max(0, int(page))
    start = page * page_size
    chunk = teams[start : start + page_size]
    out = []
    for abbr in chunk:
        sub = pred[pred["team"].astype(str).str.upper() == abbr]
        # unique players, cap
        players = []
        for gsis, g in sub.groupby("gsis_id"):
            r = g.iloc[0]
            players.append(
                {
                    "gsis_id": str(gsis),
                    "player_name": r.get("player_name"),
                    "position": r.get("position"),
                    "role_bucket": r.get("role_bucket"),
                    "jersey_number": r.get("jersey_number") if pd.notna(r.get("jersey_number")) else None,
                }
            )
            if len(players) >= MAX_PLAYERS_PER_TEAM_PAGE:
                break
        # sort role
        order = {"starter": 0, "rotation": 1, "bench_warmer": 2}
        players.sort(key=lambda p: (order.get(str(p.get("role_bucket")), 9), str(p.get("player_name"))))
        out.append(
            {
                "abbr": abbr,
                "logo": logos.get(abbr, ""),
                "opponent": str(sub["opponent"].iloc[0]) if "opponent" in sub.columns else "",
                "players": players,
            }
        )
    return {
        "page": page,
        "page_size": page_size,
        "total_teams": total,
        "has_next": start + page_size < total,
        "has_prev": page > 0,
        "teams": out,
    }


def clear_caches() -> None:
    load_pred_frame.cache_clear()
    load_roles_skill.cache_clear()
    load_season_usage_rollup.cache_clear()
    load_photo_map.cache_clear()
    load_logo_map.cache_clear()
