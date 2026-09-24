#!/usr/bin/env python3
"""CLI player lookup with fuzzy name match.

Usage:
  ./.venv/bin/python scripts/lookup_player.py "Patrick Mahomes"
  ./.venv/bin/python scripts/lookup_player.py CMC
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as scripts/lookup_player.py
sys.path.insert(0, str(Path(__file__).resolve().parent))

from player_lookup_lib import (  # noqa: E402
    format_cli_profile,
    full_profile,
    search_players,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Lookup NFL player face/team/jersey/stats from local parquet.")
    parser.add_argument("name", help="Player name (fuzzy), e.g. 'Mahomes' or 'CMC'")
    parser.add_argument("--limit", type=int, default=8, help="Max matches to list when ambiguous")
    parser.add_argument("--pick", type=int, default=None, help="1-based index when multiple matches")
    args = parser.parse_args()

    matches = search_players(args.name, limit=args.limit)
    if not matches:
        print(f"No players matched {args.name!r}.", file=sys.stderr)
        return 1

    # Auto-pick if clear top match
    if args.pick is not None:
        if args.pick < 1 or args.pick > len(matches):
            print(f"--pick must be 1..{len(matches)}", file=sys.stderr)
            return 1
        chosen = matches[args.pick - 1]
    elif len(matches) == 1 or (matches[0]["match_score"] >= 0.9 and (
        len(matches) == 1 or matches[0]["match_score"] - matches[1]["match_score"] >= 0.05
    )):
        chosen = matches[0]
    else:
        print(f"Multiple matches for {args.name!r}:")
        for i, m in enumerate(matches, 1):
            j = m.get("jersey_number")
            j_s = f"#{j}" if j is not None else "#?"
            print(
                f"  {i}. {m['display_name']}  {j_s}  {m.get('position') or '?'}  "
                f"{m.get('latest_team') or '?'}  (score={m.get('match_score')}, last={m.get('last_season')})"
            )
        print("\nRe-run with --pick N to select, e.g. --pick 1")
        # Still show top match profile for convenience if score is strong
        if matches[0]["match_score"] >= 0.85:
            print(f"\nShowing top match ({matches[0]['display_name']}):\n")
            profile = full_profile(matches[0]["gsis_id"])
            if profile:
                print(format_cli_profile(profile))
            return 0
        return 2

    profile = full_profile(chosen["gsis_id"])
    if not profile:
        print("Player id found but profile load failed.", file=sys.stderr)
        return 1
    if len(matches) > 1 and args.pick is None:
        print(f"(auto-selected top match score={chosen.get('match_score')})\n")
    print(format_cli_profile(profile))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
