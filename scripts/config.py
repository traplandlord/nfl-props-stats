"""Single source of truth for app paths and bind settings.

Override with env:
  NFL_PROPS_HOST   default 127.0.0.1
  NFL_PROPS_PORT   default 5056
  NFL_PROPS_DATA   default <repo>/data

When running the Flask UI locally, it binds to 127.0.0.1 (your machine's localhost).
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = Path(os.environ.get("NFL_PROPS_DATA") or (ROOT / "data")).expanduser().resolve()

# Prefer loopback for local development. Do not default to 0.0.0.0.
HOST = os.environ.get("NFL_PROPS_HOST", "127.0.0.1").strip() or "127.0.0.1"
PORT = int(os.environ.get("NFL_PROPS_PORT", "5056"))

PRED_DIR = DATA_DIR / "predictions"
GRADES_DIR = DATA_DIR / "grades"
EXT_DIR = DATA_DIR / "external"
ENTRIES_DIR = DATA_DIR / "entries"
GUIDE_DIR = DATA_DIR / "guide"

ACCESS_BANNER = (
    "This Flask UI runs on your local machine at http://{host}:{port}/. "
    "For a browser-only version, visit https://traplandlord.github.io/nfl-props-stats/"
)


def access_message(host: str | None = None, port: int | None = None) -> str:
    return ACCESS_BANNER.format(host=host or HOST, port=port or PORT)


def pick_port(preferred: int | None = None) -> int:
    """Bind probe: try preferred PORT then nearby. Still box-local only."""
    import socket

    preferred = preferred if preferred is not None else PORT
    candidates = []
    for p in (preferred, 5056, 5057, 5058, 5055):
        if p not in candidates:
            candidates.append(p)
    for port in candidates:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((HOST if HOST != "0.0.0.0" else "127.0.0.1", port))
                return port
            except OSError:
                continue
    return preferred
