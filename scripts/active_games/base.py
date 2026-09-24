"""Sport-agnostic active-game interface."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


@dataclass
class ActiveGame:
    sport: str
    game_id: str
    season: int | None
    week: int | None
    gameday: str | None
    gametime: str | None
    away_team: str
    home_team: str
    away_logo: str = ""
    home_logo: str = ""
    away_score: float | None = None
    home_score: float | None = None
    status: str = "unknown"  # scheduled | in_progress | final | upcoming | unknown
    status_note: str = ""
    venue: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # JSON-friendly scores
        if d["away_score"] is not None:
            d["away_score"] = float(d["away_score"])
        if d["home_score"] is not None:
            d["home_score"] = float(d["home_score"])
        return d


class SportFeed(Protocol):
    sport: str
    label: str
    connected: bool
    note: str

    def list_games(
        self,
        *,
        include_upcoming_hours: int = 72,
        as_of_date: str | None = None,
    ) -> dict[str, Any]:
        ...
