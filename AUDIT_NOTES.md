# AUDIT NOTES — nfl-props-stats

**Auditor:** fresh-pair-of-eyes pass  
**When (PT):** 2026-09-23 ~21:50 PDT (PT)  
**Rule:** Real nflverse only; ESPN/Vegas never invented. Scores honest.

## Scores (1–10) — BEFORE restructure

| Area | Score | Notes |
| --- | ---: | --- |
| Data integrity (nflverse provenance, zero fabricated) | **9** | Pulls via nflreadpy; empty ESPN/Vegas CSVs correctly `not_loaded`; Mahomes CLI + week3 preds show no fabricated ESPN/Vegas. Minor: `DATA_MANIFEST.md` omits depth/roles/predictions/external/grades. |
| Schema/docs clarity | **7** | README + curated schemas strong; manifest stale vs layout (depth, roles, preds, grades, entries, guide missing). README lists `sports_news.json` as present but file absent until `refresh_sports_news.py`. |
| Prediction stack (Actuals\|ESPN\|Vegas\|Ours\|Flags) | **8** | Four layers implemented correctly; ESPN/Vegas status honest. Flags/calibration thin until more graded weeks + real external CSVs. |
| Depth roles / bench separation | **8** | `starter`/`rotation`/`bench_warmer` buckets present (774/620/584); weekly board sorts by role; predict can `--include-bench`. |
| UI (Search, Weekly, Build card, Guide) | **4** | **HARD UX MISS:** shipped `http://127.0.0.1:5056` as if user-reachable. UI binds on the **assistant box only**; pasting localhost in the user's Chrome fails. Product surface (Search/Weekly/Entry/Guide) is otherwise sound; crash handlers + pagination exist; weekly HTML is huge (~1.3MB) — crash risk under weak clients. Port auto-falls to 5057 silently → link mismatch. |
| Scheduling/lock/grade loop | **7** | Lock JSON works; grade_week writes MAE + critique; `record_grade_outcomes` exists but week2 log outcomes were `None` until re-run (suggestions after grade, or skipped attach). |
| Multi-sport stubs honesty | **9** | NBA/MLB `connected=False`, empty lists, clear "feed not connected" notes. NFL from `team_schedule.parquet` only. |
| Code quality (structure, tests, error handling) | **5** | No `tests/`; duplicated `ROOT`/`DATA` in ~10 files; no single PORT/DATA_DIR; templates inlined in 982-line app; no pytest in requirements. Imports + dry-run predict OK. |

### Overall (before): **6.5 / 10**

Premise of the product (four-layer board + Build card + Guide) is sound. **First broken conjunction was delivery/access**, not the analytics design.

---

## CRITICAL — Access path (user feedback #1)

**Symptom:** `http://127.0.0.1:5056` is broken for the user — it only works on the agent/assistant computer.

**Root cause:** Flask binds `127.0.0.1` on the **shared assistant box**. That loopback is not the user's laptop. Localhost URLs in chat/README are a **false affordance**.

**Correct access path:**
1. Open the **Grok Bot computer / desktop view** (assistant desktop), not your own Chrome alone.
2. In *that* browser, go to `http://127.0.0.1:5056/` (or the port printed by the launcher).
3. Do **not** paste `127.0.0.1` into a browser on your personal machine and expect it to work.

**Policy this audit adopts:** Prefer keeping bind `127.0.0.1` (safer). Fix **messaging + launcher + health check**, not by casually exposing `0.0.0.0` to the network. If `0.0.0.0` is ever used, it must be explicit, documented, and intentional.

This alone drops the UI score to **4** despite otherwise decent pages.

---

## Top 10 concrete flaws

1. **Localhost access messaging** — README/UI print imply user-reachable URLs; they are box-only. (Critical UX)
2. **No one-command launcher / health check** — user/agent must know venv + script + which port actually bound.
3. **Port drift** — `_pick_port` may bind 5057/5058 while docs say 5056; printed URL and README diverge.
4. **No unified config** — `PORT` / `DATA_DIR` / `HOST` duplicated; no `scripts/config.py` or env override.
5. **No automated smoke tests** — regressions in photos, roles, predict honesty, entry N=2..6, guide NFL list unchecked.
6. **`DATA_MANIFEST.md` incomplete** — depth_charts, player_roles_current, predictions, grades, external, entries, guide omitted after last refresh.
7. **README claims `data/sports_news.json`** — file missing until news refresh; misleading "current layout".
8. **Weekly page payload ~1.3MB HTML** — all teams/props server-rendered; risk of slow/crash on thin clients; needs pagination or lazy team open (partially have details, still ships full DOM).
9. **improvement_log ↔ grade_week timing** — outcomes stay `null` if suggestions are logged *after* grade (must re-run `--record-grades`); easy to miss.
10. **Error HTML unescaped** — `@app.errorhandler` interpolates `{e}` into HTML (low severity local-only, still sloppy).

Honorable mentions: secret_key hardcoded (ok for local-only if access path is clear); no `pytest` dependency; polars in requirements but unused in scripts audited.

---

## Smoke tests run (this audit)

| Check | Result |
| --- | --- |
| Import scripts (refresh, predict, grade, lookup, entry, guide, active_games) | OK |
| `lookup_player.py "Patrick Mahomes"` | OK — real KC stats, headshot, no invented ESPN |
| `build_predictions(2026,3)` dry-run (no save; week3 locked) | OK — espn/vegas `not_loaded`, ours present |
| `entry_builder.randomize_entry` N=2..6 cross-team | OK |
| `active_games` NFL list + NBA stub | OK — NFL connected; NBA/MLB not connected |
| Flask pages on box `:5057` (`/`, `/weekly`, `/entry`, `/guide`, APIs) | OK **on the box** — does not prove user-laptop access |
| Locks/grades backup | `data/_audit_backup_20260923/` |

---

## Restructure targets (Phase 2)

1. Unify `scripts/config.py` (`HOST`, `PORT`, `DATA_DIR`); wire app + health.
2. Add `scripts/run_ui.sh` + `scripts/ui_healthcheck.py`; README **How YOU open this**.
3. Harden error page (escape); consistent nav banner about assistant-desktop access.
4. `tests/test_smoke.py` + pytest in requirements.
5. Append depth/roles/external/preds notes to manifest or a short `DATA_MANIFEST` addendum; fix sports_news claim.
6. Ensure grade↔improvement_log documented + callable; light CSS empty-state/badge clarity.
7. `QUALITY_SCORECARD.md` with before/after — **do not fake 10/10** while ESPN/Vegas CSVs empty.

**Ceiling without real ESPN/Vegas feeds:** ~8.5–9 overall. True 10/10 blocked on licensed external CSVs + user-reachable hosting story beyond assistant desktop.

---

## Phase 2 status (completed this pass)

Shipped: access-path docs/banner/launcher/healthcheck; `scripts/config.py`; smoke tests 6/6; manifest addendum; error escape; role legend; QUALITY_SCORECARD.

See `QUALITY_SCORECARD.md` for before **6.5** → after **8.0** and remaining blockers (real ESPN/Vegas CSVs; hosting beyond assistant desktop; weekly DOM size).
