"""MLB active-games stub — feed not connected."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo


class MLBFeed:
    sport = "mlb"
    label = "MLB"
    connected = False
    note = "MLB feed not connected — stub only. No invented scores or lines."

    def list_games(
        self,
        *,
        include_upcoming_hours: int = 72,
        as_of_date: str | None = None,
    ) -> dict[str, Any]:
        pt = datetime.now(timezone.utc).astimezone(ZoneInfo("America/Los_Angeles"))
        return {
            "sport": self.sport,
            "label": self.label,
            "connected": False,
            "note": self.note,
            "as_of_pt": pt.strftime("%Y-%m-%d %H:%M:%S %Z") + " (PT)",
            "as_of_date": as_of_date or pt.strftime("%Y-%m-%d"),
            "include_upcoming_hours": include_upcoming_hours,
            "active": [],
            "upcoming": [],
        }
