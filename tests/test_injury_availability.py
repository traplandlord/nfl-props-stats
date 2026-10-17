"""Late injury refresh flags out / IR / inactive players and leaves locked medians alone."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from active_players import build_availability_report  # noqa: E402
from refresh_injury_availability import refresh_availability  # noqa: E402

LAMAR = "00-0034796"
INGOLD = "00-0035125"


def test_refresh_flags_out_and_ir_without_editing_predictions(tmp_path: Path):
    predictions = [
        {
            "season": 2026,
            "week": 6,
            "player_id": LAMAR,
            "player_name": "Lamar Jackson",
            "team": "BAL",
            "prop": "passing_yards",
            "median": 244.41,
        },
        {
            "season": 2026,
            "week": 6,
            "player_id": INGOLD,
            "player_name": "Alec Ingold",
            "team": "LAC",
            "prop": "receptions",
            "median": 3.2,
        },
        {
            "season": 2026,
            "week": 6,
            "player_id": "00-0032764",
            "player_name": "Derrick Henry",
            "team": "BAL",
            "prop": "rushing_yards",
            "median": 80.5,
        },
    ]
    pred_path = tmp_path / "latest_predictions.json"
    pred_path.write_text(json.dumps(predictions), encoding="utf-8")
    before = pred_path.read_bytes()

    injuries = pd.DataFrame(
        [
            {
                "season": 2026,
                "week": 6,
                "gsis_id": LAMAR,
                "report_status": "Out",
                "practice_status": "Did Not Participate In Practice",
            }
        ]
    )
    rosters = pd.DataFrame(
        [
            {
                "season": 2026,
                "week": 6,
                "gsis_id": LAMAR,
                "status": "ACT",
                "team": "BAL",
                "status_description_abbr": "A01",
            },
            {
                "season": 2026,
                "week": 6,
                "gsis_id": INGOLD,
                "status": "RES",
                "team": "LAC",
                "status_description_abbr": "R01",
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
    out_path = tmp_path / "player_availability.json"
    report = refresh_availability(pred_path, out_path, injuries, rosters, season=2026, week=6)

    assert pred_path.read_bytes() == before
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written["unavailable_count"] == report["unavailable_count"] == 2
    flagged = {row["gsis_id"]: row for row in written["unavailable"]}
    assert flagged[LAMAR]["availability"] == "out"
    assert flagged[LAMAR]["report_status"] == "Out"
    assert flagged[LAMAR]["carried_forward"] is False
    assert flagged[INGOLD]["availability"] == "ir"
    assert flagged[INGOLD]["roster_status"] == "RES"
    assert flagged[INGOLD]["roster_status_description_abbr"] == "R01"
    assert "00-0032764" not in flagged
    assert written["predictions_unchanged"] is True

    # Building the report does not rewrite medians on the frame either.
    frame = pd.DataFrame(predictions)
    original = frame.copy()
    build_availability_report(frame, 2026, 6, injuries, rosters)
    pd.testing.assert_frame_equal(frame, original)


def test_published_docs_json_parses_in_the_browser():
    """The weekly board fetches these files with JSON.parse. Bare NaN breaks the page."""
    data = Path(__file__).resolve().parents[1] / "docs" / "data"
    for path in sorted(data.glob("*.json")):
        json.loads(path.read_text(encoding="utf-8"))


def test_refresh_refuses_a_different_week_than_the_board(tmp_path: Path):
    pred_path = tmp_path / "latest_predictions.json"
    pred_path.write_text(
        json.dumps(
            [
                {
                    "season": 2026,
                    "week": 6,
                    "player_id": LAMAR,
                    "player_name": "Lamar Jackson",
                    "team": "BAL",
                    "median": 244.41,
                }
            ]
        ),
        encoding="utf-8",
    )
    injuries = pd.DataFrame(
        [{"season": 2026, "week": 7, "gsis_id": LAMAR, "report_status": "Out"}]
    )
    try:
        refresh_availability(
            pred_path,
            tmp_path / "player_availability.json",
            injuries,
            None,
            season=2026,
            week=7,
        )
    except ValueError as exc:
        assert "published board" in str(exc)
    else:
        raise AssertionError("expected week mismatch to raise")
    assert pred_path.read_bytes()
