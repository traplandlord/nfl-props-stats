"""NFL active games from local team_schedule.parquet (nflverse).

Real scores only when present in the parquet. Never invents live PBP.
Schedule is cached in-memory with a short TTL to avoid re-reading on every request.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from .base import ActiveGame

_ROOT_FALLBACK = Path(__file__).resolve().parents[2]
try:
    import sys as _sys
    _scripts = str(Path(__file__).resolve().parents[1])
    if _scripts not in _sys.path:
        _sys.path.insert(0, _scripts)
    from config import ROOT, DATA_DIR as DATA
except ImportError:  # pragma: no cover
    ROOT = _ROOT_FALLBACK
    DATA = ROOT / "data"
SCHED_PATH = DATA / "team_schedule.parquet"
LOGOS_PATH = DATA / "team_logos.parquet"

# In-memory TTL cache (seconds)
_CACHE: dict[str, Any] = {"ts": 0.0, "df": None, "logos": None}
_TTL = 120.0  # 2 minutes


def _now_pt() -> datetime:
    return datetime.now(timezone.utc).astimezone(ZoneInfo("America/Los_Angeles"))


def _load_schedule_cached() -> pd.DataFrame:
    now = time.time()
    if _CACHE["df"] is not None and (now - _CACHE["ts"]) < _TTL:
        return _CACHE["df"]
    if not SCHED_PATH.is_file():
        _CACHE["df"] = pd.DataFrame()
        _CACHE["ts"] = now
        return _CACHE["df"]
    df = pd.read_parquet(SCHED_PATH)
    _CACHE["df"] = df
    _CACHE["ts"] = now
    return df


def _load_logos_cached() -> dict[str, str]:
    now = time.time()
    if _CACHE["logos"] is not None and (now - _CACHE["ts"]) < _TTL:
        return _CACHE["logos"] or {}
    logos: dict[str, str] = {}
    if LOGOS_PATH.is_file():
        try:
            ldf = pd.read_parquet(LOGOS_PATH)
            abbr = "team_abbr" if "team_abbr" in ldf.columns else None
            logo_col = None
            for c in ("team_logo_espn", "logo_espn", "team_logo"):
                if c in ldf.columns:
                    logo_col = c
                    break
            if abbr and logo_col:
                for _, r in ldf.iterrows():
                    a = str(r[abbr]).upper()
                    logos[a] = str(r[logo_col]) if pd.notna(r[logo_col]) else ""
        except Exception:
            logos = {}
    _CACHE["logos"] = logos
    return logos


def _status_for_row(row: pd.Series, as_of: datetime.date) -> tuple[str, str]:
    """Derive coarse status from schedule only — no invented live clock."""
    gd = row.get("gameday")
    try:
        gday = pd.Timestamp(gd).date() if pd.notna(gd) else None
    except Exception:
        gday = None
    away_s = row.get("away_score")
    home_s = row.get("home_score")
    has_score = pd.notna(away_s) and pd.notna(home_s)

    if has_score:
        return "final", "scores present in team_schedule.parquet"
    if gday is None:
        return "unknown", "missing gameday"
    if gday == as_of:
        return "scheduled", "gameday is today; no scores in schedule yet (not inventing live PBP)"
    if gday < as_of:
        # Scores missing after kickoff day → treat as possible in-progress / delayed report
        if (as_of - gday).days <= 1:
            return (
                "in_progress",
                "gameday recent, scores still null in schedule — may be in progress or not yet reported",
            )
        return "scheduled", "past gameday without scores in local parquet"
    return "upcoming", "future gameday; scores not expected yet"


def _row_to_game(row: pd.Series, logos: dict[str, str], as_of: datetime.date) -> ActiveGame:
    away = str(row.get("away_team") or "").upper()
    home = str(row.get("home_team") or "").upper()
    status, note = _status_for_row(row, as_of)
    away_score = float(row["away_score"]) if pd.notna(row.get("away_score")) else None
    home_score = float(row["home_score"]) if pd.notna(row.get("home_score")) else None
    return ActiveGame(
        sport="nfl",
        game_id=str(row.get("game_id") or f"{away}@{home}"),
        season=int(row["season"]) if pd.notna(row.get("season")) else None,
        week=int(row["week"]) if pd.notna(row.get("week")) else None,
        gameday=str(row["gameday"]) if pd.notna(row.get("gameday")) else None,
        gametime=str(row["gametime"]) if pd.notna(row.get("gametime")) else None,
        away_team=away,
        home_team=home,
        away_logo=logos.get(away, ""),
        home_logo=logos.get(home, ""),
        away_score=away_score,
        home_score=home_score,
        status=status,
        status_note=note,
        venue=str(row["stadium"]) if pd.notna(row.get("stadium")) else "",
        extra={
            "weekday": str(row["weekday"]) if pd.notna(row.get("weekday")) else None,
            "game_type": str(row["game_type"]) if pd.notna(row.get("game_type")) else None,
        },
    )


class NFLFeed:
    sport = "nfl"
    label = "NFL"
    connected = True
    note = "Connected: data/team_schedule.parquet (nflverse). Scores only when present locally."

    def list_games(
        self,
        *,
        include_upcoming_hours: int = 72,
        as_of_date: str | None = None,
    ) -> dict[str, Any]:
        pt = _now_pt()
        as_of = (
            datetime.strptime(as_of_date, "%Y-%m-%d").date()
            if as_of_date
            else pt.date()
        )
        df = _load_schedule_cached()
        logos = _load_logos_cached()
        if df.empty:
            return {
                "sport": self.sport,
                "label": self.label,
                "connected": True,
                "note": "team_schedule.parquet missing or empty",
                "as_of_pt": pt.strftime("%Y-%m-%d %H:%M:%S %Z") + " (PT)",
                "as_of_date": as_of.isoformat(),
                "include_upcoming_hours": include_upcoming_hours,
                "active": [],
                "upcoming": [],
                "cache_ttl_sec": _TTL,
            }

        work = df.copy()
        work["_gday"] = pd.to_datetime(work["gameday"], errors="coerce")
        # Active: today OR in_progress heuristic (recent day, no scores)
        today_mask = work["_gday"].dt.date == as_of
        active_rows = work[today_mask]
        # also re-check recent unscored as in_progress
        yesterday = as_of - timedelta(days=1)
        recent_null = work[
            (work["_gday"].dt.date == yesterday)
            & work["away_score"].isna()
            & work["home_score"].isna()
        ]
        if not recent_null.empty:
            active_rows = pd.concat([active_rows, recent_null]).drop_duplicates("game_id")

        active = [
            _row_to_game(r, logos, as_of).to_dict() for _, r in active_rows.iterrows()
        ]

        # Upcoming window (clearly separate): after as_of through +hours
        horizon = datetime.combine(as_of, datetime.min.time()) + timedelta(
            hours=max(0, int(include_upcoming_hours))
        )
        start = datetime.combine(as_of, datetime.min.time()) + timedelta(days=1)
        # include remaining of today already in active; upcoming = future days in window
        up_mask = (work["_gday"] >= pd.Timestamp(start)) & (
            work["_gday"] <= pd.Timestamp(horizon)
        )
        # also today games that are still upcoming (no score) already in active —
        # add future-day games only
        upcoming = [
            _row_to_game(r, logos, as_of).to_dict() for _, r in work[up_mask].iterrows()
        ]
        # sort
        active.sort(key=lambda g: (g.get("gametime") or "", g.get("game_id") or ""))
        upcoming.sort(key=lambda g: (g.get("gameday") or "", g.get("gametime") or ""))

        return {
            "sport": self.sport,
            "label": self.label,
            "connected": True,
            "note": self.note,
            "as_of_pt": pt.strftime("%Y-%m-%d %H:%M:%S %Z") + " (PT)",
            "as_of_date": as_of.isoformat(),
            "include_upcoming_hours": include_upcoming_hours,
            "active": active,
            "upcoming": upcoming,
            "cache_ttl_sec": _TTL,
            "source": str(SCHED_PATH.relative_to(ROOT)),
        }


def clear_cache() -> None:
    _CACHE["ts"] = 0.0
    _CACHE["df"] = None
    _CACHE["logos"] = None
