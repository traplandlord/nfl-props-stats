"""Active-player filter: ACT roster, injury report, and bye weeks."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from active_players import (  # noqa: E402
    eligible_active_ids,
    filter_to_active_players,
    is_unavailable_report_status,
    teams_with_game,
)


def _rosters() -> pd.DataFrame:
    rows = [
        # Plays.
        {"season": 2026, "week": 6, "gsis_id": "act", "status": "ACT", "team": "KC", "status_description_abbr": "A01"},
        # Game-day inactive, still tagged ACT until the roster status flips.
        {"season": 2026, "week": 6, "gsis_id": "inactive", "status": "ACT", "team": "KC", "status_description_abbr": "I01"},
        {"season": 2026, "week": 6, "gsis_id": "inactive2", "status": "INA", "team": "KC", "status_description_abbr": "A01"},
        # IR / reserve, including an IR code left on status ACT.
        {"season": 2026, "week": 6, "gsis_id": "ir", "status": "RES", "team": "KC", "status_description_abbr": "R01"},
        {"season": 2026, "week": 6, "gsis_id": "ir_act", "status": "ACT", "team": "BUF", "status_description_abbr": "R48"},
        # Bye week: ACT, but DET has no game.
        {"season": 2026, "week": 6, "gsis_id": "bye", "status": "ACT", "team": "DET", "status_description_abbr": "A01"},
        # Ruled out on the injury report, otherwise active.
        {"season": 2026, "week": 6, "gsis_id": "ruled_out", "status": "ACT", "team": "BUF", "status_description_abbr": "A01"},
        # Questionable players still play.
        {"season": 2026, "week": 6, "gsis_id": "questionable", "status": "ACT", "team": "BUF", "status_description_abbr": "A01"},
        # Practice squad / PUP are not active.
        {"season": 2026, "week": 6, "gsis_id": "pup", "status": "PUP", "team": "KC", "status_description_abbr": "R04"},
        {"season": 2026, "week": 6, "gsis_id": "dev", "status": "DEV", "team": "KC", "status_description_abbr": "P01"},
        # Different week must not leak in.
        {"season": 2026, "week": 5, "gsis_id": "other_week", "status": "ACT", "team": "KC", "status_description_abbr": "A01"},
        # Older files have no description code; status ACT is enough.
        {"season": 2026, "week": 6, "gsis_id": "no_abbr", "status": "ACT", "team": "PHI", "status_description_abbr": None},
    ]
    return pd.DataFrame(rows)


def _schedules() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"season": 2026, "week": 6, "game_type": "REG", "home_team": "KC", "away_team": "BUF"},
            {"season": 2026, "week": 6, "game_type": "REG", "home_team": "PHI", "away_team": "NYG"},
            # Preseason must not pull a bye team back onto the slate.
            {"season": 2026, "week": 6, "game_type": "PRE", "home_team": "DET", "away_team": "GB"},
        ]
    )


def _injuries() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"season": 2026, "week": 6, "gsis_id": "ruled_out", "report_status": "Out"},
            {"season": 2026, "week": 6, "gsis_id": "questionable", "report_status": "Questionable"},
            {"season": 2026, "week": 6, "gsis_id": "act", "report_status": None},
            {"season": 2026, "week": 6, "gsis_id": "doubtful_not_in_roster", "report_status": "Doubtful"},
            {"season": 2026, "week": 6, "gsis_id": "no_abbr", "report_status": "Injured Reserve"},
        ]
    )


def test_eligible_ids_drop_inactive_ir_ruled_out_and_bye():
    ids = eligible_active_ids(_rosters(), _schedules(), _injuries(), 2026, 6)
    assert ids == {"act", "questionable"}


def test_teams_with_game_ignores_preseason_and_bye():
    teams = teams_with_game(_schedules(), 2026, 6)
    assert teams == {"KC", "BUF", "PHI", "NYG"}
    assert "DET" not in teams


def test_injury_status_meanings():
    assert is_unavailable_report_status("Out")
    assert is_unavailable_report_status("OUT")
    assert is_unavailable_report_status("Inactive")
    assert is_unavailable_report_status("IR")
    assert is_unavailable_report_status("Injured Reserve")
    assert is_unavailable_report_status("ruled out")
    assert not is_unavailable_report_status("Questionable")
    assert not is_unavailable_report_status("Doubtful")
    assert not is_unavailable_report_status("Probable")
    assert not is_unavailable_report_status(None)
    assert not is_unavailable_report_status("Full Participation in Practice")


def test_filter_props_without_network():
    props = pd.DataFrame(
        {
            "player_id": ["act", "inactive", "ir", "bye", "ruled_out", "questionable"],
            "prop": ["passing_yards"] * 6,
        }
    )
    kept = filter_to_active_players(
        props,
        2026,
        6,
        id_col="player_id",
        eligible_ids={"act", "questionable"},
    )
    assert set(kept["player_id"]) == {"act", "questionable"}
    assert len(kept) == 2


def test_missing_schedule_or_roster_raises():
    with pytest.raises(ValueError, match="No schedule"):
        eligible_active_ids(_rosters(), pd.DataFrame(columns=["season", "week", "home_team", "away_team"]), None, 2026, 6)
    with pytest.raises(ValueError, match="No weekly roster"):
        eligible_active_ids(
            pd.DataFrame(columns=["season", "week", "gsis_id", "status", "team"]),
            _schedules(),
            None,
            2026,
            6,
        )


def test_status_act_without_abbr_column_still_filters_bye_and_out():
    rosters = pd.DataFrame(
        [
            {"season": 2026, "week": 6, "gsis_id": "act", "status": "ACT", "team": "KC"},
            {"season": 2026, "week": 6, "gsis_id": "ina", "status": "INA", "team": "KC"},
            {"season": 2026, "week": 6, "gsis_id": "bye", "status": "ACT", "team": "DET"},
            {"season": 2026, "week": 6, "gsis_id": "out", "status": "ACT", "team": "BUF"},
        ]
    )
    injuries = pd.DataFrame(
        [{"season": 2026, "week": 6, "gsis_id": "out", "report_status": "Out"}]
    )
    ids = eligible_active_ids(rosters, _schedules(), injuries, 2026, 6)
    assert ids == {"act"}
