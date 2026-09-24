# NFL Props Stats - Web App

This is a client-side web application that runs entirely in your browser. No server required.

## Features

- **Search** — Find any NFL player and see their stats, team, position, and role (starter/rotation/bench)
- **Weekly Predictions** — Model predictions based on recent performance using empirical Bayes methods
- **Build My Card** — Create PrizePicks-style player cards with 2-6 players from any teams
- **Guide** — View upcoming games and get plain-English tips based on real data

## Data

All data in the `data/` directory is exported from the main parquet files in the repository root. The export script (`scripts/export_web_data.py`) converts parquet data to JSON for browser consumption.

Data files:
- `players.json` — Active players (last_season >= 2023) with photos and key fields
- `teams.json` — Team metadata and logo URLs
- `player_roles.json` — Current depth chart roles (starter/rotation/bench)
- `player_stats_2026.json` — 2026 season averages per player
- `latest_predictions.json` — Most recent week's model predictions (sample)
- `latest_predictions_meta.json` — Prediction metadata
- `latest_grades.json` — Most recent week's prediction grades
- `schedule.json` — Upcoming games (next 7 days)

## Zero Fabricated Numbers

All data comes from official nflverse sources. ESPN and Vegas data require manual CSV upload and are not included in the default export. If data is missing, it's marked as "not loaded" rather than invented.

## Updating Data

To refresh the web app data after updating the parquet files:

```bash
python3 scripts/export_web_data.py
```

This will regenerate all JSON files in `docs/data/`.

## Local Development

To test the web app locally, you can use any simple HTTP server:

```bash
cd docs
python3 -m http.server 8000
# Then open http://localhost:8000/
```

Or use the Flask UI from the repository root:

```bash
./scripts/run_ui.sh
```

## Project

Created by [@traplandlord](https://github.com/traplandlord) (Valentino)

Live app: https://traplandlord.github.io/nfl-props-stats/
