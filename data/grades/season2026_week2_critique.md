# Grade critique — season 2026 week 2

- Graded at: **2026-09-22 22:26:14 PDT (PT)**
- Predictions locked: **True** (locked_at=2026-09-23T05:26:13.563526+00:00)
- Scored rows: **886** / 1080 (missing actuals: 194)
- Overall MAE (ours_mean vs nflverse actual): **10.183**
- Within-1-SD hit rate: **77.3%**
- Bias (ours − actual): **-0.351**

## By prop

| Prop | MAE | Within 1 SD |
| --- | --- | --- |
| passing_tds | 0.97 | 54.1% |
| passing_yards | 67.52 | 75.7% |
| receiving_yards | 19.78 | 77.5% |
| receptions | 1.51 | 74.2% |
| rushing_tds | 0.36 | 92.1% |
| rushing_yards | 12.18 | 84.9% |
| touches | 2.59 | 74.0% |

## Notes

- Actuals are **nflverse weekly stats only** — never fabricated.
- ESPN/Vegas columns graded only when those external files were loaded at predict time; empty means not loaded (not zero).
- MODEL ESTIMATES use empirical-Bayes shrink of trailing usage; high MAE on TDs is expected (high variance).
- Competency signal for the UI Flags column is written into the grade JSON (`mae_by_prop`).

## Largest misses

- Jaxson Dart (NYG QB) passing_yards: ours=179.1 actual=20.0 abs_err=159.1
- Patrick Mahomes (KC QB) passing_yards: ours=226.1 actual=382.0 abs_err=155.9
- Davante Adams (LA WR) receiving_yards: ours=46.0 actual=195.0 abs_err=149.0
- C.J. Stroud (HOU QB) passing_yards: ours=214.3 actual=353.0 abs_err=138.7
- Jacoby Brissett (ARI QB) passing_yards: ours=224.2 actual=95.0 abs_err=129.2
- Mac Jones (SF QB) passing_yards: ours=127.7 actual=0.0 abs_err=127.7
- Caleb Williams (CHI QB) passing_yards: ours=251.0 actual=138.0 abs_err=113.0
- Dalton Schultz (HOU TE) receiving_yards: ours=32.5 actual=140.0 abs_err=107.5
