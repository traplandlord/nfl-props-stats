# QUALITY SCORECARD — nfl-props-stats

**After restructure (PT):** 2026-09-23 ~22:00 PDT (PT)  
**Honesty rule:** ESPN/Vegas remain **not loaded** (empty CSVs). No fake 10/10.

## Before → After

| Area | Before | After | Delta | Notes |
| --- | ---: | ---: | ---: | --- |
| Data integrity | 9 | **9** | 0 | Unchanged — nflverse only; external still empty by design |
| Schema/docs clarity | 7 | **8.5** | +1.5 | README access path; manifest addendum; sports_news optional |
| Prediction stack | 8 | **8** | 0 | Still correct; still blocked on real ESPN/Vegas CSVs |
| Depth roles / bench | 8 | **8.5** | +0.5 | Role legend in Weekly UI; smoke asserts buckets |
| UI (access + pages) | **4** | **7** | +3 | Access banner + How YOU open this + launcher/health; still box-only (by design). Weekly DOM still large |
| Scheduling/lock/grade | 7 | **8** | +1 | Documented grade↔improvement_log; week2 outcomes re-attached in audit |
| Multi-sport stubs | 9 | **9** | 0 | Still honest stubs |
| Code quality | 5 | **7.5** | +2.5 | `config.py`, smoke tests (6/6 pass), escaped errors, unified DATA_DIR |

### Overall

| | Score |
| --- | ---: |
| **Before** | **6.5 / 10** |
| **After** | **8.0 / 10** |
| Ceiling without real ESPN/Vegas + product hosting | ~8.5–9 |

"Perfect" here means **best achievable without fake external feeds** and without claiming the user's laptop can hit box localhost.

---

## Fixes shipped (this pass)

1. **Access-path honesty** — AUDIT_NOTES + README **How YOU open this** + per-page access banner (assistant desktop, not user Chrome).
2. **`scripts/config.py`** — single `HOST` / `PORT` / `DATA_DIR` (+ env overrides); libs wired.
3. **`scripts/run_ui.sh`** + **`scripts/ui_healthcheck.py`** — one-command start + probe.
4. **Hardened error pages** — escaped exception text; access reminder.
5. **`tests/test_smoke.py`** — photos, role buckets, predict honesty, entry N=2..6, guide NFL list, config — **6 passed**.
6. **DATA_MANIFEST addendum** — depth/roles/predictions/grades/external/entries/guide; sports_news optional.
7. **Light UI** — role legend, empty-state for missing preds.
8. **Locks backup** — `data/_audit_backup_20260923/` (predictions/grades/entries/guide).

---

## Remaining blockers for true 10/10

1. **Real ESPN projections CSV** (licensed/allowed export) loaded into `data/external/espn_projections.csv`.
2. **Real Vegas lines CSV** into `data/external/vegas_lines.csv`.
3. **User-reachable UI story** beyond assistant-desktop localhost (tunnel, shared preview, or documented remote desktop only) — without silently binding `0.0.0.0`.
4. **Weekly board pagination / lazy team fetch** — cut ~1.3MB full-board HTML.
5. **More graded weeks** for Flags calibration depth.
6. **Broader test coverage** (Flask routes, lock refusal, grade_week) beyond smoke.

Until (1)(2) are real files, prediction-stack and overall must stay **below 10** — marking them 10 would be lying.
