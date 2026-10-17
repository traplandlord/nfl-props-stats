#!/usr/bin/env python3
"""Active-player gate for weekly prop predictions.

Before a week is predicted or exported, drop anyone who will not play:

- weekly roster status is not ACT (inactive, IR / reserve, PUP, practice squad, cut)
- weekly roster status_description_abbr is an inactive or reserve code (I01/I02,
  R01/R48, and the other non-A* codes) even when status is still ACT
- injury report says ruled out, inactive, or IR for this week
- this week's report row has a blank game status and the last real designation
  this season was ruled out, inactive, or IR (a practice-only row does not clear
  that designation unless practice is full participation)
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


def _status_text(value) -> str:
    """Normalized injury-report text. Blank, null, and 'nan' become ''."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = " ".join(str(value).strip().lower().replace("-", " ").replace("/", " ").split())
    if text in {"nan", "none", "<na>", "nat"}:
        return ""
    return text


def is_unavailable_report_status(value) -> bool:
    """True when an injury-report game status means ruled out, inactive, or IR."""
    text = _status_text(value)
    if not text or text in {"questionable", "doubtful", "probable"}:
        return False
    if any(phrase in text for phrase in _UNAVAILABLE_STATUS_PHRASES):
        return True
    tokens = set(text.split())
    return bool(tokens & _UNAVAILABLE_STATUS_TOKENS)


def availability_label(value) -> str | None:
    """'out', 'ir', or 'inactive' for a game status that rules the player out."""
    if not is_unavailable_report_status(value):
        return None
    text = _status_text(value)
    tokens = set(text.split())
    if any(
        phrase in text
        for phrase in (
            "injured reserve",
            "reserve injured",
            "physically unable to perform",
        )
    ):
        return "ir"
    if "pup" in tokens or "ir" in tokens:
        return "ir"
    if "inactive" in tokens or "suspended" in tokens:
        return "inactive"
    return "out"


def _injury_id_column(injuries: pd.DataFrame) -> str | None:
    """Prefer gsis_id. Some extracts only have player_id, and it is the same id."""
    if "gsis_id" in injuries.columns:
        return "gsis_id"
    if "player_id" in injuries.columns:
        return "player_id"
    return None


def _is_full_participation(value) -> bool:
    return "full participation" in _status_text(value)


def _clean_status_value(value) -> str | None:
    text = _status_text(value)
    if not text:
        return None
    return str(value).strip()


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


def _practiced_in_full(rows: pd.DataFrame) -> bool:
    if "practice_status" not in rows.columns:
        return False
    return any(_is_full_participation(value) for value in rows["practice_status"].tolist())


def _limited_practice(rows: pd.DataFrame) -> bool:
    if "practice_status" not in rows.columns:
        return False
    return any("limited participation" in _status_text(value) for value in rows["practice_status"].tolist())


def _explicit_available_status(rows: pd.DataFrame) -> bool:
    return any(
        _status_text(value) and not is_unavailable_report_status(value)
        for value in rows["report_status"].tolist()
    )


def unavailable_injury_details(
    injuries: pd.DataFrame | None,
    season: int,
    week: int,
    carry_forward: bool = True,
) -> dict[str, dict]:
    """gsis id -> why that player is ruled out for this week.

    nflverse writes one row per player-week. Early in the week that row is often
    practice-only: ``report_status`` is null and ``practice_status`` is filled in.
    A null game status is not a clearance. If the player is still on this week's
    report, still not practicing, and the last real designation this season was
    Out, inactive, or IR, that designation still applies.

    Full participation or an explicit status such as Questionable clears it,
    including a full practice in a week between the Out and the slate week.
    Limited participation is a return to practice, so the old Out is not reused.
    A player with no row in the slate week is not carried forward.

    ``carry_forward=False`` keeps only an unavailable ``report_status`` on the
    slate week. The kickoff refresh uses that so a blank Saturday status does
    not hide someone who was Out last week but is not ruled out for this game.
    """
    if injuries is None or injuries.empty:
        return {}
    id_col = _injury_id_column(injuries)
    if id_col is None or "report_status" not in injuries.columns:
        return {}
    if "season" not in injuries.columns or "week" not in injuries.columns:
        return {}

    season_num = pd.to_numeric(injuries["season"], errors="coerce")
    week_num = pd.to_numeric(injuries["week"], errors="coerce")
    frame = injuries.loc[season_num == int(season)].copy()
    if frame.empty:
        return {}
    frame["_week_num"] = week_num.loc[frame.index]
    frame = frame.loc[frame["_week_num"].notna() & (frame["_week_num"] <= int(week))]
    if frame.empty:
        return {}

    details: dict[str, dict] = {}
    for gsis, grp in frame.groupby(id_col, dropna=True, sort=False):
        gsis_s = _id_str(gsis)
        if not gsis_s:
            continue
        current = grp.loc[grp["_week_num"] == int(week)]
        # Not listed on this week's report. Do not reuse an older Out.
        if current.empty:
            continue

        chosen = None
        carried = False
        for _, row in current.iterrows():
            if is_unavailable_report_status(row.get("report_status")):
                chosen = row
                break
        if chosen is None:
            if not carry_forward:
                continue
            if _explicit_available_status(current) or _practiced_in_full(current) or _limited_practice(current):
                continue
            open_row = None
            prior = grp.loc[grp["_week_num"] < int(week)]
            if not prior.empty:
                for _, week_rows in prior.groupby("_week_num", sort=True):
                    ruled_out = [
                        row
                        for _, row in week_rows.iterrows()
                        if is_unavailable_report_status(row.get("report_status"))
                    ]
                    if ruled_out:
                        open_row = ruled_out[-1]
                        continue
                    if _explicit_available_status(week_rows) or _practiced_in_full(week_rows):
                        open_row = None
            if open_row is None:
                continue
            chosen = open_row
            carried = True

        label = availability_label(chosen.get("report_status"))
        if label is None:
            continue
        practice = chosen["practice_status"] if "practice_status" in chosen.index else None
        details[gsis_s] = {
            "availability": label,
            "report_status": _clean_status_value(chosen.get("report_status")),
            "report_week": int(chosen["_week_num"]),
            "practice_status": _clean_status_value(practice),
            "carried_forward": carried,
        }
    return details


def unavailable_injury_ids(
    injuries: pd.DataFrame | None,
    season: int,
    week: int,
    carry_forward: bool = True,
) -> set[str]:
    """gsis ids ruled out, inactive, or on IR for that week's slate."""
    return set(unavailable_injury_details(injuries, season, week, carry_forward=carry_forward))


def roster_unavailability(
    rosters: pd.DataFrame | None,
    season: int,
    week: int,
) -> dict[str, dict]:
    """gsis ids who are not ACT on the weekly roster (IR, inactive, PUP, practice squad)."""
    if rosters is None or rosters.empty:
        return {}
    week_rosters = _week_slice(rosters, season, week)
    if week_rosters.empty or "gsis_id" not in week_rosters.columns or "status" not in week_rosters.columns:
        return {}
    active = _active_roster_mask(week_rosters)
    details: dict[str, dict] = {}
    for _, row in week_rosters.loc[~active].iterrows():
        gsis = _id_str(row.get("gsis_id"))
        if not gsis:
            continue
        status = str(row.get("status") or "").strip().upper()
        if status in {"NAN", "NONE", "<NA>"}:
            status = ""
        code = ""
        if "status_description_abbr" in week_rosters.columns:
            code = str(row.get("status_description_abbr") or "").strip().upper()
            if code in {"NAN", "NONE", "<NA>"}:
                code = ""
        if status in {"RES", "PUP", "NFI"} or code.startswith("R"):
            kind = "ir"
        else:
            kind = "inactive"
        details[gsis] = {
            "availability": kind,
            "roster_status": status or None,
            "roster_status_description_abbr": code or None,
        }
    return details


def build_availability_report(
    predictions: pd.DataFrame,
    season: int,
    week: int,
    injuries: pd.DataFrame | None,
    rosters: pd.DataFrame | None = None,
    id_col: str = "player_id",
    generated_at_utc: str | None = None,
    generated_at_pt: str | None = None,
    carry_forward: bool = True,
) -> dict:
    """Flag board players who are out, on IR, or inactive.

    Reads prediction rows and does not modify them. Locked medians stay put;
    the site hides anyone listed under ``unavailable``.
    """
    if predictions is None:
        predictions = pd.DataFrame()
    if id_col not in predictions.columns:
        if "gsis_id" in predictions.columns:
            id_col = "gsis_id"
        else:
            raise KeyError(f"Prediction frame has no {id_col} column")

    injury = unavailable_injury_details(injuries, season, week, carry_forward=carry_forward)
    roster = roster_unavailability(rosters, season, week)
    name_col = "player_name" if "player_name" in predictions.columns else None
    if name_col is None and "player_display_name" in predictions.columns:
        name_col = "player_display_name"

    flags = []
    seen: set[str] = set()
    for _, row in predictions.iterrows():
        gsis = _id_str(row.get(id_col))
        if not gsis or gsis in seen:
            continue
        seen.add(gsis)
        inj = injury.get(gsis)
        ros = roster.get(gsis)
        if not inj and not ros:
            continue
        availability = (inj or ros)["availability"]
        player_name = ""
        if name_col is not None:
            player_name = _clean_status_value(row.get(name_col)) or ""
        team = _clean_status_value(row.get("team")) if "team" in predictions.columns else None
        flags.append(
            {
                "gsis_id": gsis,
                "player_name": player_name,
                "team": team,
                "availability": availability,
                "report_status": None if not inj else inj.get("report_status"),
                "report_week": None if not inj else inj.get("report_week"),
                "practice_status": None if not inj else inj.get("practice_status"),
                "carried_forward": bool(inj and inj.get("carried_forward")),
                "roster_status": None if not ros else ros.get("roster_status"),
                "roster_status_description_abbr": None if not ros else ros.get("roster_status_description_abbr"),
            }
        )

    flags.sort(key=lambda item: (item.get("team") or "", item.get("player_name") or "", item["gsis_id"]))
    return {
        "season": int(season),
        "week": int(week),
        "generated_at_utc": generated_at_utc,
        "generated_at_pt": generated_at_pt,
        "source": "nflverse injuries and weekly rosters",
        "predictions_file": "docs/data/latest_predictions.json",
        "predictions_unchanged": True,
        "unavailable_count": len(flags),
        "unavailable": flags,
    }


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
