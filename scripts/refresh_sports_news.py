#!/usr/bin/env python3
"""Lightweight live refresh for the props board.

Prefer re-calling nflverse refresh pieces (injuries, depth, schedules, weekly)
plus optional Google News RSS headlines via feedparser.

Does NOT scrape Google Sports HTML. Live updates = nflverse refresh + news
headlines — never invented crawl content.

Usage:
  ./.venv/bin/python scripts/refresh_sports_news.py
  ./.venv/bin/python scripts/refresh_sports_news.py --skip-nflverse
  ./.venv/bin/python scripts/refresh_sports_news.py --news-only
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
NEWS_PATH = DATA / "sports_news.json"

# Google News RSS (public Atom/RSS) — headlines only, not Google Sports HTML scrape
NEWS_QUERIES = [
    "NFL injury",
    "NFL",
]


def _now() -> tuple[str, str]:
    utc = datetime.now(timezone.utc)
    pt = utc.astimezone(ZoneInfo("America/Los_Angeles"))
    return utc.isoformat(), pt.strftime("%Y-%m-%d %H:%M:%S %Z") + " (PT)"


def fetch_news_rss(queries: list[str], limit_per: int = 8) -> list[dict]:
    try:
        import feedparser
    except ImportError:
        print("feedparser not installed; skipping RSS (pip install feedparser)", file=sys.stderr)
        return []

    items: list[dict] = []
    seen = set()
    for q in queries:
        url = f"https://news.google.com/rss/search?q={quote_plus(q)}&hl=en-US&gl=US&ceid=US:en"
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"RSS error for {q!r}: {e}", file=sys.stderr)
            continue
        for e in feed.entries[:limit_per]:
            link = getattr(e, "link", "") or ""
            title = getattr(e, "title", "") or ""
            key = (title, link)
            if key in seen:
                continue
            seen.add(key)
            items.append(
                {
                    "query": q,
                    "title": title,
                    "link": link,
                    "published": getattr(e, "published", None),
                    "source": getattr(getattr(e, "source", None), "title", None),
                }
            )
    return items


def refresh_nflverse_pieces(seasons: list[int]) -> dict:
    """Re-call refresh_nfl_stats pieces: weekly, schedule, injuries, depth."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from refresh_nfl_stats import (  # noqa: WPS433
        pull_depth_charts,
        pull_injuries,
        pull_schedule,
        pull_weekly,
    )

    errors: list[dict] = []
    results = {}
    for name, fn, kwargs in [
        ("weekly", pull_weekly, {"seasons": seasons, "errors": errors}),
        ("schedule", pull_schedule, {"seasons": seasons, "errors": errors}),
        ("injuries", pull_injuries, {"seasons": seasons, "errors": errors}),
        ("depth", pull_depth_charts, {"seasons": seasons, "errors": errors}),
    ]:
        print(f"--- refresh {name} ---")
        res = fn(**kwargs)
        if res:
            # drop heavy frames
            for k in list(res.keys()):
                if k.startswith("_df"):
                    res.pop(k, None)
            results[name] = {
                "files": [
                    {"stem": f.get("stem"), "rows": f.get("rows")} for f in res.get("files", [])
                ]
            }
        else:
            results[name] = None
    results["errors"] = errors
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Lightweight nflverse + News RSS refresh")
    parser.add_argument("--seasons", nargs="+", type=int, default=[2025, 2026])
    parser.add_argument("--skip-nflverse", action="store_true")
    parser.add_argument("--news-only", action="store_true")
    parser.add_argument(
        "--teams",
        nargs="*",
        default=[],
        help="Optional team names/abbr to add as News RSS queries",
    )
    args = parser.parse_args()

    utc, pt = _now()
    out: dict = {
        "pulled_at_utc": utc,
        "pulled_at_pt": pt,
        "method": "nflverse refresh pieces + Google News RSS (feedparser); NOT Google Sports HTML scrape",
        "nflverse": None,
        "news": [],
    }

    if not args.news_only and not args.skip_nflverse:
        out["nflverse"] = refresh_nflverse_pieces(list(args.seasons))

    queries = list(NEWS_QUERIES)
    for t in args.teams:
        queries.append(f"NFL {t}")
    print("--- Google News RSS ---")
    out["news"] = fetch_news_rss(queries)
    print(f"  {len(out['news'])} headlines")

    DATA.mkdir(parents=True, exist_ok=True)
    NEWS_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote {NEWS_PATH}")
    print("Live updates = nflverse refresh + news headlines, not invented crawl.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
