#!/usr/bin/env python3
"""Active-player gate for weekly prop predictions.

Before a week is predicted or exported, drop anyone who will not play:

- weekly roster status is not ACT (inactive, IR / reserve, PUP, practice squad, cut)
- weekly roster status_description_abbr is an inactive or reserve code (I01/I02,
  R01/R48, and the other non-A* codes) even when status is still ACT
- injury report says ruled out, inactive, or IR
- their team is on bye (no game on that week's schedule)

Training is untouched. This module only filters the slate that gets predicted
and the rows written to the web export.

Data is nflverse via nflreadpy: load_rosters_weekly, load_injuries, load_schedules.
"""

from __future__ import annotations

import warnings

import pandas as pd

# Game-status strings on the official injury report that mean the player will not play.
# Questionable and Doubtful stay in: they are not ruled out.
_UNAVAILABLE_STATUS_TOKENS = {
    "out",
    "inactive",
    "ir",
    "pup",
    "suspended",
}
_UNAVAILABLE_STATUS_PHRASES = (
    "ruled out",
    "injured reserve",
    "physically unable to perform",
    "reserve injured",
)

# Regular season and postseason. Preseason rows must not mark a team as "playing".
_SEASON_GAME_TYPES = {"REG", "POST", "WC", "DIV", "CON", "SB"}


def _id_str(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "<na>"}:
        return None
    return text


def _week_slice(df: pd.DataFrame | None, season: int, week: int) -> pd.DataFrame:
    if df is None or df.empty or "season" not in df.columns or "week" not in df.columns:
        return pd.DataFrame() if df is None else df.iloc[0:0]
    season_s = pd.to_numeric(df["season"], errors="coerce")
    week_s = pd.to_numeric(df["week"], errors="coerce")
    return df.loc[(season_s == int(season)) & (week_s == int(week))].copy()


def is_unavailable_report_status(value) -> bool:
    """True when an injury-report game status means ruled out, inactive, or IR."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    text = " ".join(str(value).strip().lower().replace("-", " ").replace("/", " ").split())
    if not text or text in {"nan", "none", "questionable", "doubtful", "probable"}:
        return False
    if any(phrase in text for phrase in _UNAVAILABLE_STATUS_PHRASES):
        return True
    tokens = set(text.split())
    return bool(tokens & _UNAVAILABLE_STATUS_TOKENS)


def teams_with_game(schedules: pd.DataFrame, season: int, week: int) -> set[str]:
    """Team abbreviations that have a game in this season/week. Everyone else is on bye."""
    games = _week_slice(schedules, season, week)
    if games.empty:
        return set()
    if "game_type" in games.columns:
        game_type = games["game_type"].fillna("").astype(str).str.strip().str.upper()
        in_season = games.loc[game_type.isin(_SEASON_GAME_TYPES)]
        if not in_season.empty:
            games = in_season
    teams: set[str] = set()
    if {"home_team", "away_team"} <= set(games.columns):
        for col in ("home_team", "away_team"):
            teams.update(
                games[col].dropna().astype(str).str.strip().str.upper().tolist()
            )
    elif "team" in games.columns:
        teams.update(games["team"].dropna().astype(str).str.strip().str.upper().tolist())
    teams.discard("")
    teams.discard("NAN")
    return teams


def _active_roster_mask(rosters: pd.DataFrame) -> pd.Series:
    """Weekly roster rows that are actually available.

    status == ACT is required. nflverse also leaves game-day inactives and the
    occasional IR/practice-squad row on status ACT and records the real code in
    status_description_abbr (I01/I02 inactive, R01/R48 injured reserve, P* practice
    squad). Those codes are not active. A blank abbr keeps the ACT row, so older
    roster files that only have status still work.
    """
    status = rosters["status"].fillna("").astype(str).str.strip().str.upper()
    active = status.eq("ACT")
    if "status_description_abbr" not in rosters.columns:
        return active
    code = rosters["status_description_abbr"].fillna("").astype(str).str.strip().str.upper()
    blank = code.isin({"", "NAN", "NONE", "<NA>"})
    return active & (blank | code.str.startswith("A"))


def unavailable_injury_ids(injuries: pd.DataFrame | None, season: int, week: int) -> set[str]:
    """gsis ids ruled out, inactive, or on IR on that week's injury report."""
    if injuries is None or injuries.empty or "gsis_id" not in injuries.columns:
        return set()
    if "report_status" not in injuries.columns:
        return set()
    week_inj = _week_slice(injuries, season, week)
    if week_inj.empty:
        return set()
    mask = week_inj["report_status"].map(is_unavailable_report_status)
    ids = set()
    for value in week_inj.loc[mask, "gsis_id"].tolist():
        gsis = _id_str(value)
        if gsis:
            ids.add(gsis)
    return ids


def eligible_active_ids(
    rosters: pd.DataFrame,
    schedules: pd.DataFrame,
    injuries: pd.DataFrame | None,
    season: int,
    week: int,
) -> set[str]:
    """gsis ids who are ACT, not ruled out / inactive / IR, and whose team plays."""
    playing = teams_with_game(schedules, season, week)
    if not playing:
        raise ValueError(f"No schedule games for season {season} week {week}")

    week_rosters = _week_slice(rosters, season, week)
    if week_rosters.empty or "gsis_id" not in week_rosters.columns or "status" not in week_rosters.columns:
        raise ValueError(f"No weekly roster rows for season {season} week {week}")
    if "team" not in week_rosters.columns:
        raise ValueError("Weekly rosters are missing team")

    team = week_rosters["team"].fillna("").astype(str).str.strip().str.upper()
    playable = _active_roster_mask(week_rosters) & team.isin(playing)
    ids = set()
    for value in week_rosters.loc[playable, "gsis_id"].tolist():
        gsis = _id_str(value)
        if gsis:
            ids.add(gsis)
    return ids - unavailable_injury_ids(injuries, season, week)


def load_eligible_active_ids(season: int, week: int) -> set[str]:
    """Load nflverse weekly rosters, injuries, and the schedule for one week."""
    import nflreadpy as nfl

    season = int(season)
    week = int(week)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        rosters = nfl.load_rosters_weekly([season]).to_pandas()
        schedules = nfl.load_schedules([season]).to_pandas()
        injuries = nfl.load_injuries([season]).to_pandas()

    week_inj = _week_slice(injuries, season, week)
    if week_inj.empty:
        print(
            f"No injury-report rows for {season} week {week}; "
            "applying roster ACT + bye filter only"
        )
    ids = eligible_active_ids(rosters, schedules, injuries, season, week)
    print(
        f"Eligible active players for {season} week {week}: {len(ids)} "
        "(weekly roster status ACT, not ruled out/inactive/IR, team has a game)"
    )
    return ids


def filter_to_active_players(
    df: pd.DataFrame,
    season: int,
    week: int,
    id_col: str = "gsis_id",
    eligible_ids: set[str] | None = None,
) -> pd.DataFrame:
    """Drop rows whose player is ruled out, inactive, on IR, or on bye.

    Pass eligible_ids to skip the nflverse download (tests, or a caller that
    already loaded the week).
    """
    if df is None or df.empty:
        return df
    if id_col not in df.columns:
        raise KeyError(f"Prediction frame has no {id_col} column")
    if eligible_ids is None:
        eligible_ids = load_eligible_active_ids(season, week)
    keep = df[id_col].map(_id_str).isin(eligible_ids)
    dropped = int((~keep).sum())
    print(
        f"Active-player filter: kept {int(keep.sum())} of {len(df)} rows; "
        f"dropped {dropped} "
        "(not roster ACT, inactive/IR, injury report ruled out, or team on bye)"
    )
    return df.loc[keep].copy()
