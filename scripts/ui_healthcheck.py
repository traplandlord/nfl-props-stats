#!/usr/bin/env python3
"""Health-check the local Flask UI.

Usage:
  ./.venv/bin/python scripts/ui_healthcheck.py
  ./.venv/bin/python scripts/ui_healthcheck.py --port 5056
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import HOST, PORT, access_message  # noqa: E402


def check(host: str, port: int, path: str, timeout: float = 5.0) -> tuple[int, str]:
    url = f"http://{host}:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read(200)
            return int(resp.status), body[:80].decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return int(e.code), str(e.reason)
    except Exception as e:
        return 0, str(e)


def main() -> int:
    parser = argparse.ArgumentParser(description="NFL props UI health check (box-local)")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()

    print(access_message(args.host, args.port))
    print(f"Probing http://{args.host}:{args.port}/ ...")

    paths = ["/", "/weekly", "/entry", "/guide", "/api/guide/active"]
    failed = 0
    for path in paths:
        code, snip = check(args.host, args.port, path)
        ok = 200 <= code < 400
        line = f"  {'OK' if ok else 'FAIL'} {code:>3} {path}  {snip!r}"
        print(line[:120])
        if not ok:
            failed += 1

    if failed:
        print(
            f"\nFAIL: {failed}/{len(paths)} checks failed. "
            "Start UI with: ./scripts/run_ui.sh",
            file=sys.stderr,
        )
        return 1
    print("\nPASS: UI healthy on your local machine.")
    print(json.dumps({"host": args.host, "port": args.port, "ok": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
