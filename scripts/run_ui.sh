#!/usr/bin/env bash
# One-command launcher for the NFL props Flask UI on your local machine.
# For a browser-only version, visit https://traplandlord.github.io/nfl-props-stats/
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "Missing venv at .venv — run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi
export NFL_PROPS_HOST="${NFL_PROPS_HOST:-127.0.0.1}"
export NFL_PROPS_PORT="${NFL_PROPS_PORT:-5056}"
export NFL_PROPS_DATA="${NFL_PROPS_DATA:-$ROOT/data}"

echo "=============================================="
echo " NFL Props Flask UI — Local Server"
echo " Open your browser and go to:"
echo "   http://${NFL_PROPS_HOST}:${NFL_PROPS_PORT}/"
echo " For browser-only version, visit:"
echo "   https://traplandlord.github.io/nfl-props-stats/"
echo " Health: $PY scripts/ui_healthcheck.py"
echo "=============================================="
exec "$PY" scripts/player_lookup_app.py
