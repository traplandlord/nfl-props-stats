"""Multi-sport active-games registry.

NFL is live (team_schedule / nflverse). NBA/MLB are stubs until feeds connect.
Consumers should call ``list_active_games(sport=...)`` and respect ``connected``.
"""

from __future__ import annotations

from typing import Any

from .base import ActiveGame, SportFeed
from . import nfl as nfl_feed
from . import nba as nba_feed
from . import mlb as mlb_feed

_REGISTRY: dict[str, SportFeed] = {
    "nfl": nfl_feed.NFLFeed(),
    "nba": nba_feed.NBAFeed(),
    "mlb": mlb_feed.MLBFeed(),
}


def available_sports() -> list[dict[str, Any]]:
    out = []
    for key, feed in _REGISTRY.items():
        out.append(
            {
                "sport": key,
                "label": feed.label,
                "connected": feed.connected,
                "note": feed.note,
            }
        )
    return out


def get_feed(sport: str = "nfl") -> SportFeed:
    key = (sport or "nfl").lower().strip()
    if key not in _REGISTRY:
        raise KeyError(f"Unknown sport {sport!r}; known: {sorted(_REGISTRY)}")
    return _REGISTRY[key]


def list_active_games(
    sport: str = "nfl",
    *,
    include_upcoming_hours: int = 72,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Return active/today + optional upcoming window for one sport.

    Never invents scores. Unconnected sports return empty lists + clear note.
    """
    feed = get_feed(sport)
    return feed.list_games(
        include_upcoming_hours=include_upcoming_hours,
        as_of_date=as_of_date,
    )


def list_all_sports_snapshot(
    *,
    include_upcoming_hours: int = 72,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    sports = []
    for key in _REGISTRY:
        try:
            sports.append(
                list_active_games(
                    key,
                    include_upcoming_hours=include_upcoming_hours,
                    as_of_date=as_of_date,
                )
            )
        except Exception as e:
            sports.append(
                {
                    "sport": key,
                    "connected": False,
                    "note": f"error: {e}",
                    "active": [],
                    "upcoming": [],
                    "as_of_pt": None,
                }
            )
    return {"sports": sports}


__all__ = [
    "ActiveGame",
    "SportFeed",
    "available_sports",
    "get_feed",
    "list_active_games",
    "list_all_sports_snapshot",
]
