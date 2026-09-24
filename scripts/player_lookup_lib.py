"""Shared player lookup helpers for CLI and local web UI.

Uses only local parquet (and optional nflreadpy teams for logos).
Never invents stats or photos.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from config import ROOT, DATA_DIR as DATA
except ImportError:  # pragma: no cover
    ROOT = Path(__file__).resolve().parents[1]
    DATA = ROOT / "data"

# Common nicknames / initials -> preferred display_name fragment for matching boost
NICKNAMES = {
    "cmc": "christian mccaffrey",
    "mahomes": "patrick mahomes",
    "pat mahomes": "patrick mahomes",
    "jj": "justin jefferson",
    "cd lamb": "ceedee lamb",
    "ceedee": "ceedee lamb",
    "c.d. lamb": "ceedee lamb",
    "dk": "dk metcalf",
    "jt": "jonathan taylor",
    "saquon": "saquon barkley",
    "lamar": "lamar jackson",
    "josh allen": "josh allen",
    "hurts": "jalen hurts",
    "purdy": "brock purdy",
}


def _safe_read_parquet(path: Path) -> pd.DataFrame | None:
    if path.is_file():
        return pd.read_parquet(path)
    return None


@lru_cache(maxsize=1)
def load_players() -> pd.DataFrame:
    enriched = _safe_read_parquet(DATA / "players_with_photos.parquet")
    if enriched is not None:
        df = enriched.copy()
    else:
        base = _safe_read_parquet(DATA / "players.parquet")
        if base is None:
            raise FileNotFoundError(f"Missing {DATA / 'players.parquet'}")
        df = base.copy()

    # Normalize expected columns
    if "display_name" not in df.columns and "player_display_name" in df.columns:
        df["display_name"] = df["player_display_name"]
    if "gsis_id" not in df.columns and "player_id" in df.columns:
        df["gsis_id"] = df["player_id"]
    if "headshot" not in df.columns:
        for alt in ("headshot_url", "photo_url", "espn_headshot"):
            if alt in df.columns:
                df["headshot"] = df[alt]
                break
        else:
            df["headshot"] = None

    # Prefer active / recent players in ranking: higher last_season first
    if "last_season" in df.columns:
        df["_sort_season"] = pd.to_numeric(df["last_season"], errors="coerce").fillna(0)
    else:
        df["_sort_season"] = 0
    return df


@lru_cache(maxsize=1)
def load_team_logos() -> dict[str, dict[str, str]]:
    """Map team_abbr -> {name, logo_url} from file or nflreadpy."""
    logos_path = DATA / "team_logos.parquet"
    df = _safe_read_parquet(logos_path)
    if df is None:
        try:
            import nflreadpy as nfl

            teams = nfl.load_teams()
            df = teams.to_pandas() if hasattr(teams, "to_pandas") else pd.DataFrame(teams)
        except Exception:
            return {}

    out: dict[str, dict[str, str]] = {}
    abbr_col = "team_abbr" if "team_abbr" in df.columns else ("abbr" if "abbr" in df.columns else None)
    name_col = "team_name" if "team_name" in df.columns else ("name" if "name" in df.columns else None)
    logo_col = None
    for c in ("team_logo_espn", "logo_espn", "team_logo", "logo_url"):
        if c in df.columns:
            logo_col = c
            break
    if abbr_col is None:
        return {}
    for _, row in df.iterrows():
        abbr = str(row[abbr_col]).upper()
        out[abbr] = {
            "name": str(row[name_col]) if name_col and pd.notna(row.get(name_col)) else abbr,
            "logo_url": str(row[logo_col]) if logo_col and pd.notna(row.get(logo_col)) else "",
        }
    return out


@lru_cache(maxsize=1)
def load_usage_season() -> pd.DataFrame:
    df = _safe_read_parquet(DATA / "player_usage_season.parquet")
    return df if df is not None else pd.DataFrame()


@lru_cache(maxsize=1)
def load_weekly_stats() -> pd.DataFrame:
    df = _safe_read_parquet(DATA / "weekly_player_stats.parquet")
    return df if df is not None else pd.DataFrame()


@lru_cache(maxsize=1)
def load_injuries() -> pd.DataFrame:
    df = _safe_read_parquet(DATA / "injuries.parquet")
    return df if df is not None else pd.DataFrame()


def _norm(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9\s\.]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def _initials(name: str) -> str:
    parts = [p for p in _norm(name).split() if p]
    return "".join(p[0] for p in parts if p)


def _score_name(query: str, display_name: str, short_name: str | None = None) -> float:
    q = _norm(query)
    if not q:
        return 0.0

    # Nickname expansion
    expanded = NICKNAMES.get(q, q)
    dn = _norm(display_name or "")
    sn = _norm(short_name or "") if short_name else ""

    best = 0.0
    for candidate_q in {q, expanded}:
        if not candidate_q:
            continue
        if dn == candidate_q:
            best = max(best, 1.0)
        elif dn.startswith(candidate_q) or candidate_q in dn:
            # substring / prefix
            best = max(best, 0.92 + 0.05 * (len(candidate_q) / max(len(dn), 1)))
        elif sn and (candidate_q in sn or sn in candidate_q):
            best = max(best, 0.85)
        else:
            best = max(best, SequenceMatcher(None, candidate_q, dn).ratio())
            # token overlap (last name match etc.)
            q_tokens = set(candidate_q.split())
            d_tokens = set(dn.split())
            if q_tokens and d_tokens:
                overlap = len(q_tokens & d_tokens) / len(q_tokens)
                best = max(best, 0.55 + 0.4 * overlap)
        # initials e.g. CMC
        if len(candidate_q) <= 4 and candidate_q.isalpha() and _initials(dn) == candidate_q:
            best = max(best, 0.88)

    return min(best, 1.0)


def search_players(query: str, limit: int = 15, min_score: float = 0.55) -> list[dict[str, Any]]:
    players = load_players()
    q = query.strip()
    if not q:
        return []

    scored: list[tuple[float, int]] = []
    for idx, row in players.iterrows():
        score = _score_name(q, str(row.get("display_name") or ""), str(row.get("short_name") or "") or None)
        if score >= min_score:
            # Boost more recent / active players slightly
            boost = 0.0
            last = row.get("_sort_season") or 0
            try:
                boost = min(float(last) / 10000.0, 0.05)
            except (TypeError, ValueError):
                pass
            scored.append((score + boost, idx))

    scored.sort(key=lambda x: (-x[0], -float(players.loc[x[1]].get("_sort_season") or 0)))
    results = []
    for score, idx in scored[:limit]:
        row = players.loc[idx]
        results.append(_player_card(row, match_score=round(float(score), 3)))
    return results


def get_player_by_gsis(gsis_id: str) -> dict[str, Any] | None:
    players = load_players()
    hit = players[players["gsis_id"].astype(str) == str(gsis_id)]
    if hit.empty:
        return None
    # Prefer highest last_season if duplicates
    hit = hit.sort_values("_sort_season", ascending=False)
    return _player_card(hit.iloc[0])


def _player_card(row: pd.Series, match_score: float | None = None) -> dict[str, Any]:
    team = str(row.get("latest_team") or "") if pd.notna(row.get("latest_team")) else ""
    logos = load_team_logos()
    team_info = logos.get(team.upper(), {"name": team, "logo_url": ""})
    jersey = row.get("jersey_number")
    if pd.isna(jersey):
        jersey = None
    else:
        try:
            jersey = int(jersey)
        except (TypeError, ValueError):
            jersey = str(jersey)

    headshot = row.get("headshot")
    if pd.isna(headshot) or not headshot:
        headshot = None
    else:
        headshot = str(headshot)

    card: dict[str, Any] = {
        "gsis_id": str(row.get("gsis_id") or ""),
        "display_name": str(row.get("display_name") or ""),
        "position": str(row.get("position") or "") if pd.notna(row.get("position")) else "",
        "position_group": str(row.get("position_group") or "") if pd.notna(row.get("position_group")) else "",
        "jersey_number": jersey,
        "latest_team": team,
        "team_name": team_info.get("name") or team,
        "team_logo_url": team_info.get("logo_url") or "",
        "headshot": headshot,
        "status": str(row.get("status") or "") if pd.notna(row.get("status")) else "",
        "espn_id": str(int(row["espn_id"])) if pd.notna(row.get("espn_id")) else None,
        "last_season": int(row["last_season"]) if pd.notna(row.get("last_season")) else None,
    }
    if match_score is not None:
        card["match_score"] = round(min(float(match_score), 1.0), 3)
    return card


def season_stats_summary(gsis_id: str, seasons: int = 3) -> list[dict[str, Any]]:
    """Combine usage_season with weekly yard/TD totals. Real data only."""
    usage = load_usage_season()
    weekly = load_weekly_stats()
    pid = str(gsis_id)

    usage_rows = usage[usage["player_id"].astype(str) == pid] if not usage.empty else pd.DataFrame()
    weekly_rows = weekly[weekly["player_id"].astype(str) == pid] if not weekly.empty else pd.DataFrame()

    seasons_present: set[int] = set()
    if not usage_rows.empty:
        seasons_present.update(int(s) for s in usage_rows["season"].dropna().unique())
    if not weekly_rows.empty:
        seasons_present.update(int(s) for s in weekly_rows["season"].dropna().unique())

    if not seasons_present:
        return []

    top_seasons = sorted(seasons_present, reverse=True)[:seasons]
    out: list[dict[str, Any]] = []

    for season in top_seasons:
        u = usage_rows[usage_rows["season"] == season] if not usage_rows.empty else pd.DataFrame()
        w = weekly_rows[weekly_rows["season"] == season] if not weekly_rows.empty else pd.DataFrame()

        # If multiple teams in a season, keep separate or aggregate — aggregate weekly, take usage per team rows
        teams = []
        if not u.empty:
            teams = [str(t) for t in u["team"].dropna().unique()]
        elif not w.empty:
            teams = [str(t) for t in w["team"].dropna().unique()]

        def _sum(col: str) -> int | float | None:
            if w.empty or col not in w.columns:
                return None
            val = w[col].fillna(0).sum()
            if pd.isna(val):
                return None
            # ints for counting stats
            try:
                if float(val) == int(val):
                    return int(val)
            except (TypeError, ValueError):
                pass
            return float(val)

        usage_agg: dict[str, Any] = {}
        if not u.empty:
            # Prefer the team row with most games if multiple
            u2 = u.sort_values("games_played", ascending=False)
            primary = u2.iloc[0]
            usage_agg = {
                "games_played": int(primary["games_played"]) if pd.notna(primary.get("games_played")) else None,
                "avg_offense_snaps": round(float(primary["avg_offense_snaps"]), 1)
                if pd.notna(primary.get("avg_offense_snaps"))
                else None,
                "avg_offense_pct": round(float(primary["avg_offense_pct"]), 3)
                if pd.notna(primary.get("avg_offense_pct"))
                else None,
                "avg_touches": round(float(primary["avg_touches"]), 2)
                if pd.notna(primary.get("avg_touches"))
                else None,
                "sum_touches": int(primary["sum_touches"]) if pd.notna(primary.get("sum_touches")) else None,
                "sum_targets": int(primary["sum_targets"]) if pd.notna(primary.get("sum_targets")) else None,
                "sum_carries": int(primary["sum_carries"]) if pd.notna(primary.get("sum_carries")) else None,
                "injury_games_count": int(primary["injury_games_count"])
                if pd.notna(primary.get("injury_games_count"))
                else None,
                "usage_team": str(primary.get("team") or ""),
            }
            if len(u2) > 1:
                usage_agg["games_played"] = int(u2["games_played"].fillna(0).sum())
                usage_agg["sum_touches"] = int(u2["sum_touches"].fillna(0).sum())
                usage_agg["sum_targets"] = int(u2["sum_targets"].fillna(0).sum())
                usage_agg["sum_carries"] = int(u2["sum_carries"].fillna(0).sum())
                usage_agg["injury_games_count"] = int(u2["injury_games_count"].fillna(0).max())

        row = {
            "season": season,
            "teams": teams,
            "passing_yards": _sum("passing_yards"),
            "passing_tds": _sum("passing_tds"),
            "rushing_yards": _sum("rushing_yards"),
            "rushing_tds": _sum("rushing_tds"),
            "receiving_yards": _sum("receiving_yards"),
            "receiving_tds": _sum("receiving_tds"),
            "receptions": _sum("receptions"),
            "targets": _sum("targets"),
            "carries": _sum("carries"),
            "completions": _sum("completions"),
            "attempts": _sum("attempts"),
            **usage_agg,
        }
        out.append(row)
    return out


def recent_weeks(gsis_id: str, n: int = 5) -> list[dict[str, Any]]:
    weekly = load_weekly_stats()
    if weekly.empty:
        return []
    w = weekly[weekly["player_id"].astype(str) == str(gsis_id)].copy()
    if w.empty:
        return []
    w = w.sort_values(["season", "week"], ascending=[False, False]).head(n)
    cols = [
        "season",
        "week",
        "team",
        "opponent_team",
        "completions",
        "attempts",
        "passing_yards",
        "passing_tds",
        "carries",
        "rushing_yards",
        "rushing_tds",
        "receptions",
        "targets",
        "receiving_yards",
        "receiving_tds",
    ]
    rows = []
    for _, r in w.iterrows():
        item = {}
        for c in cols:
            if c not in w.columns:
                continue
            v = r[c]
            if pd.isna(v):
                item[c] = None
            elif hasattr(v, "item"):
                item[c] = v.item()
            else:
                item[c] = v
        rows.append(item)
    return rows


def injury_weeks(gsis_id: str, season: int | None = None, limit: int = 12) -> list[dict[str, Any]]:
    inj = load_injuries()
    if inj.empty:
        return []
    m = inj[inj["gsis_id"].astype(str) == str(gsis_id)].copy()
    if m.empty:
        return []
    if season is not None:
        m = m[m["season"] == season]
    # Prefer rows with a report_status
    m = m.sort_values(["season", "week", "date_modified"], ascending=[False, False, False])
    rows = []
    seen = set()
    for _, r in m.iterrows():
        key = (int(r["season"]), int(r["week"]))
        if key in seen:
            continue
        seen.add(key)
        status = r.get("report_status")
        injury = r.get("report_primary_injury")
        status_s = str(status) if pd.notna(status) else None
        injury_s = str(injury) if pd.notna(injury) else None
        if not status_s and not injury_s:
            continue
        rows.append(
            {
                "season": int(r["season"]),
                "week": int(r["week"]),
                "team": str(r["team"]) if pd.notna(r.get("team")) else "",
                "report_status": status_s,
                "report_primary_injury": injury_s,
            }
        )
        if len(rows) >= limit:
            break
    return rows


def full_profile(gsis_id: str) -> dict[str, Any] | None:
    card = get_player_by_gsis(gsis_id)
    if not card:
        return None
    seasons = season_stats_summary(gsis_id)
    latest_season = seasons[0]["season"] if seasons else None
    card["season_stats"] = seasons
    card["recent_weeks"] = recent_weeks(gsis_id, n=5)
    card["injury_weeks"] = injury_weeks(gsis_id, season=latest_season, limit=10)
    return card


def format_cli_profile(profile: dict[str, Any]) -> str:
    lines: list[str] = []
    jersey = profile.get("jersey_number")
    jersey_s = f"#{jersey}" if jersey is not None else "#?"
    lines.append("=" * 60)
    lines.append(f"{profile['display_name']}  {jersey_s}  {profile.get('position') or '?'}")
    lines.append(f"Team: {profile.get('team_name') or profile.get('latest_team') or '?'} ({profile.get('latest_team') or '?'})")
    lines.append(f"gsis_id: {profile.get('gsis_id')}")
    if profile.get("headshot"):
        lines.append(f"Headshot: {profile['headshot']}")
    else:
        lines.append("Headshot: (none in data)")
    if profile.get("team_logo_url"):
        lines.append(f"Team logo: {profile['team_logo_url']}")
    lines.append("-" * 60)
    lines.append("Season stats (from local parquet):")
    for s in profile.get("season_stats") or []:
        lines.append(
            f"  {s['season']} [{','.join(s.get('teams') or [])}] "
            f"G:{s.get('games_played')}  "
            f"Pass:{s.get('passing_yards')}yd/{s.get('passing_tds')}TD  "
            f"Rush:{s.get('rushing_yards')}yd/{s.get('rushing_tds')}TD  "
            f"Rec:{s.get('receiving_yards')}yd/{s.get('receiving_tds')}TD "
            f"({s.get('receptions')} rec / {s.get('targets')} tgt)  "
            f"Touches:{s.get('sum_touches')}  "
            f"AvgSnaps:{s.get('avg_offense_snaps')}  "
            f"InjWeeks:{s.get('injury_games_count')}"
        )
    if not profile.get("season_stats"):
        lines.append("  (no season stats found)")
    lines.append("-" * 60)
    lines.append("Recent weeks:")
    for w in profile.get("recent_weeks") or []:
        lines.append(
            f"  {w.get('season')} W{w.get('week')} {w.get('team')} vs {w.get('opponent_team')}: "
            f"pass {w.get('passing_yards')}/{w.get('passing_tds')}TD, "
            f"rush {w.get('rushing_yards')}/{w.get('rushing_tds')}TD, "
            f"rec {w.get('receiving_yards')}/{w.get('receiving_tds')}TD "
            f"({w.get('receptions')}/{w.get('targets')})"
        )
    if not profile.get("recent_weeks"):
        lines.append("  (none)")
    inj = profile.get("injury_weeks") or []
    if inj:
        lines.append("-" * 60)
        lines.append("Injury report weeks (latest season in summary):")
        for i in inj:
            lines.append(
                f"  {i['season']} W{i['week']} {i.get('team')}: "
                f"{i.get('report_status') or '—'} / {i.get('report_primary_injury') or '—'}"
            )
    lines.append("=" * 60)
    return "\n".join(lines)
