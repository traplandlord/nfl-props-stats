"""Active-player filter: ACT roster, injury report, and bye weeks."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from active_players import (  # noqa: E402
    build_availability_report,
    eligible_active_ids,
    filter_to_active_players,
    is_unavailable_report_status,
    unavailable_injury_details,
    unavailable_injury_ids,
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


LAMAR_JACKSON = "00-0034796"


def _lamar_thursday_injuries() -> pd.DataFrame:
    """Thursday Oct 15 injuries.parquet shape for Lamar Jackson.

    Week 5 game status is Out. Week 6 is a practice row with a blank
    report_status. gsis_id matches the locked board (00-0034796).
    """
    return pd.DataFrame(
        [
            {
                "season": 2026,
                "week": 5,
                "gsis_id": LAMAR_JACKSON,
                "full_name": "Lamar Jackson",
                "team": "BAL",
                "report_status": "Out",
                "practice_status": "Did Not Participate In Practice",
                "report_primary_injury": "Ankle",
                "practice_primary_injury": "Ankle",
            },
            {
                "season": 2026,
                "week": 6,
                "gsis_id": LAMAR_JACKSON,
                "full_name": "Lamar Jackson",
                "team": "BAL",
                "report_status": None,
                "practice_status": "Did Not Participate In Practice",
                "report_primary_injury": None,
                "practice_primary_injury": "Ankle",
            },
        ]
    )


def _lamar_week6_roster() -> tuple[pd.DataFrame, pd.DataFrame]:
    rosters = pd.DataFrame(
        [
            {
                "season": 2026,
                "week": 6,
                "gsis_id": LAMAR_JACKSON,
                "status": "ACT",
                "team": "BAL",
                "status_description_abbr": "A01",
            },
            {
                "season": 2026,
                "week": 6,
                "gsis_id": "00-0032764",
                "status": "ACT",
                "team": "BAL",
                "status_description_abbr": "A01",
            },
        ]
    )
    schedules = pd.DataFrame(
        [
            {"season": 2026, "week": 6, "game_type": "REG", "home_team": "BAL", "away_team": "LA"},
        ]
    )
    return rosters, schedules


def test_lamar_jackson_blank_week_status_keeps_prior_out():
    """The Thursday filter missed him: week 6 report_status is null, week 5 is Out."""
    rosters, schedules = _lamar_week6_roster()
    ids = eligible_active_ids(rosters, schedules, _lamar_thursday_injuries(), 2026, 6)
    assert LAMAR_JACKSON not in ids
    assert ids == {"00-0032764"}
    detail = unavailable_injury_details(_lamar_thursday_injuries(), 2026, 6)[LAMAR_JACKSON]
    assert detail["availability"] == "out"
    assert detail["report_status"] == "Out"
    assert detail["report_week"] == 5
    assert detail["carried_forward"] is True


def test_thursday_injuries_parquet_excludes_lamar_jackson():
    path = Path(__file__).resolve().parents[1] / "data" / "injuries.parquet"
    injuries = pd.read_parquet(path)
    lamar = injuries[(injuries["gsis_id"] == LAMAR_JACKSON) & (injuries["season"] == 2026)]
    week5 = lamar[lamar["week"] == 5]
    week6 = lamar[lamar["week"] == 6]
    assert not week5.empty
    assert week5.iloc[0]["report_status"] == "Out"
    assert not week6.empty
    assert pd.isna(week6.iloc[0]["report_status"])

    rosters, schedules = _lamar_week6_roster()
    ids = eligible_active_ids(rosters, schedules, lamar, 2026, 6)
    assert LAMAR_JACKSON not in ids
    detail = unavailable_injury_details(lamar, 2026, 6)[LAMAR_JACKSON]
    assert detail["carried_forward"] is True
    assert detail["report_week"] == 5


def test_full_participation_or_questionable_clears_a_prior_out():
    rosters, schedules = _lamar_week6_roster()
    cleared = _lamar_thursday_injuries()
    cleared.loc[cleared["week"] == 6, "practice_status"] = "Full Participation in Practice"
    ids = eligible_active_ids(rosters, schedules, cleared, 2026, 6)
    assert LAMAR_JACKSON in ids

    questionable = _lamar_thursday_injuries()
    questionable.loc[questionable["week"] == 6, "report_status"] = "Questionable"
    ids = eligible_active_ids(rosters, schedules, questionable, 2026, 6)
    assert LAMAR_JACKSON in ids


def test_limited_practice_or_an_earlier_full_week_does_not_reuse_an_old_out():
    """Diggs is limited this week. Collins was Out in week 3 and practiced in full in week 4."""
    rosters, schedules = _lamar_week6_roster()
    limited = _lamar_thursday_injuries()
    limited.loc[limited["week"] == 6, "practice_status"] = "Limited Participation in Practice"
    ids = eligible_active_ids(rosters, schedules, limited, 2026, 6)
    assert LAMAR_JACKSON in ids

    returned = pd.concat(
        [
            _lamar_thursday_injuries(),
            pd.DataFrame(
                [
                    {
                        "season": 2026,
                        "week": 4,
                        "gsis_id": LAMAR_JACKSON,
                        "team": "BAL",
                        "report_status": "Out",
                        "practice_status": "Did Not Participate In Practice",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    # Week 5 in the Thursday fixture is Out. Insert a full week between week 4 and that Out
    # by clearing week 5, then a later DNP week must not revive week 4.
    returned.loc[returned["week"] == 5, "report_status"] = None
    returned.loc[returned["week"] == 5, "practice_status"] = "Full Participation in Practice"
    ids = eligible_active_ids(rosters, schedules, returned, 2026, 6)
    assert LAMAR_JACKSON in ids


def test_prior_out_without_a_current_week_row_stays_eligible():
    rosters, schedules = _lamar_week6_roster()
    only_last_week = _lamar_thursday_injuries()
    only_last_week = only_last_week[only_last_week["week"] == 5]
    ids = eligible_active_ids(rosters, schedules, only_last_week, 2026, 6)
    assert LAMAR_JACKSON in ids


def test_lamar_gsis_matches_prediction_player_id_and_median_is_unchanged():
    props = pd.DataFrame(
        {
            "player_id": [LAMAR_JACKSON, "00-0032764"],
            "player_name": ["Lamar Jackson", "Derrick Henry"],
            "team": ["BAL", "BAL"],
            "median": [244.41, 80.5],
        }
    )
    before = props.copy()
    report = build_availability_report(props, 2026, 6, _lamar_thursday_injuries())
    pd.testing.assert_frame_equal(props, before)
    flagged = {row["gsis_id"]: row for row in report["unavailable"]}
    assert flagged[LAMAR_JACKSON]["carried_forward"] is True
    assert "00-0032764" not in flagged

    rosters, schedules = _lamar_week6_roster()
    eligible = eligible_active_ids(rosters, schedules, _lamar_thursday_injuries(), 2026, 6)
    kept = filter_to_active_players(props, 2026, 6, id_col="player_id", eligible_ids=eligible)
    assert list(kept["player_id"]) == ["00-0032764"]
    assert kept.iloc[0]["median"] == 80.5

    # Same gsis stored under player_id on the injury extract still joins.
    renamed = _lamar_thursday_injuries().rename(columns={"gsis_id": "player_id"})
    assert unavailable_injury_ids(renamed, 2026, 6) == {LAMAR_JACKSON}


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
