#!/usr/bin/env python3
"""Refresh who is out, on IR, or inactive without touching locked predictions.

The Tuesday/Thursday lock publishes medians in docs/data/latest_predictions.json.
Game status often is not filled in until Friday or Saturday. This job re-reads
nflverse injuries and the weekly roster, then writes docs/data/player_availability.json.
The site hides those players. It does not rewrite prediction numbers and it does
not train.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from active_players import build_availability_report  # noqa: E402

PREDICTIONS = ROOT / "docs" / "data" / "latest_predictions.json"
META = ROOT / "docs" / "data" / "latest_predictions_meta.json"
AVAILABILITY = ROOT / "docs" / "data" / "player_availability.json"


def _now_labels() -> tuple[str, str]:
    utc = datetime.now(timezone.utc)
    pt = utc.astimezone(ZoneInfo("America/Los_Angeles"))
    return utc.isoformat(), pt.strftime("%Y-%m-%d %H:%M:%S %Z") + " (PT)"


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _board_season_week(predictions: pd.DataFrame, meta: dict | None) -> tuple[int, int]:
    if "season" in predictions.columns and predictions["season"].notna().any():
        season = int(predictions["season"].dropna().iloc[0])
    elif meta and meta.get("season") is not None:
        season = int(meta["season"])
    else:
        raise ValueError("Published board has no season")
    if "week" in predictions.columns and predictions["week"].notna().any():
        week = int(predictions["week"].dropna().iloc[0])
    elif meta and meta.get("week") is not None:
        week = int(meta["week"])
    else:
        raise ValueError("Published board has no week")
    return season, week


def load_injuries(path: Path | None, season: int) -> pd.DataFrame:
    if path is not None:
        return pd.read_parquet(path)
    import nflreadpy as nfl

    return nfl.load_injuries([int(season)]).to_pandas()


def load_rosters(path: Path | None, season: int) -> pd.DataFrame | None:
    if path is not None:
        return pd.read_parquet(path)
    try:
        import nflreadpy as nfl

        return nfl.load_rosters_weekly([int(season)]).to_pandas()
    except Exception as exc:
        print(f"Weekly rosters unavailable ({exc}); flagging from the injury report only")
        return None


def refresh_availability(
    predictions_path: Path,
    out_path: Path,
    injuries: pd.DataFrame,
    rosters: pd.DataFrame | None,
    season: int | None = None,
    week: int | None = None,
    meta: dict | None = None,
) -> dict:
    """Write the availability file. The predictions file is only read."""
    before = predictions_path.read_bytes()
    records = _read_json(predictions_path)
    predictions = pd.DataFrame(records)
    board_season, board_week = _board_season_week(predictions, meta)
    season = board_season if season is None else int(season)
    week = board_week if week is None else int(week)
    if season != board_season or week != board_week:
        raise ValueError(
            f"Refusing to flag season {season} week {week} against the "
            f"published board (season {board_season} week {board_week})"
        )

    utc, pt = _now_labels()
    report = build_availability_report(
        predictions,
        season,
        week,
        injuries,
        rosters=rosters,
        id_col="player_id" if "player_id" in predictions.columns else "gsis_id",
        generated_at_utc=utc,
        generated_at_pt=pt,
        # Saturday and Sunday reports already carry a game status. Do not reuse
        # last week's Out when this week's report_status is still blank.
        carry_forward=False,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    after = predictions_path.read_bytes()
    if after != before:
        raise RuntimeError(f"Refresh modified locked predictions at {predictions_path}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, default=PREDICTIONS)
    parser.add_argument("--meta", type=Path, default=META)
    parser.add_argument("--out", type=Path, default=AVAILABILITY)
    parser.add_argument("--season", type=int, default=None)
    parser.add_argument("--week", type=int, default=None)
    parser.add_argument("--injuries", type=Path, default=None, help="Local injuries parquet. Default: nflverse.")
    parser.add_argument("--rosters", type=Path, default=None, help="Local weekly rosters parquet. Default: nflverse.")
    parser.add_argument("--skip-rosters", action="store_true")
    args = parser.parse_args()

    meta = _read_json(args.meta) if args.meta.is_file() else None
    # Season for the download. The published board wins once the file is read.
    probe = pd.DataFrame(_read_json(args.predictions))
    season, week = _board_season_week(probe, meta)
    if args.season is not None:
        season = args.season
    if args.week is not None:
        week = args.week

    print(f"Refreshing availability for {season} week {week}")
    injuries = load_injuries(args.injuries, season)
    rosters = None if args.skip_rosters else load_rosters(args.rosters, season)
    report = refresh_availability(
        args.predictions,
        args.out,
        injuries,
        rosters,
        season=season,
        week=week,
        meta=meta,
    )
    print(
        f"Flagged {report['unavailable_count']} players "
        f"(out / IR / inactive). Wrote {args.out}"
    )
    print("Locked prediction file was not modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
