"""Fetch and persist AOG status feed into data/aog_status.json.

This script is designed for CI use. It reads AOG status JSON from an endpoint
provided by environment variable `AOG_STATUS_URL` and writes it to
`data/aog_status.json` when the payload changes.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from urllib import error, request

DEFAULT_PAYLOAD = {"active": [], "history": [], "lastUpdated": None}


def _normalize(payload: object) -> dict:
    """Normalize supported payload shapes into dashboard format."""
    if isinstance(payload, list):
        return {"active": payload, "history": [], "lastUpdated": None}

    if isinstance(payload, dict):
        active = payload.get("active") or payload.get("active_events") or payload.get("activeEvents") or []
        history = payload.get("history") or payload.get("resolved") or payload.get("resolved_events") or payload.get("resolvedEvents") or []
        last_updated = payload.get("lastUpdated") or payload.get("last_updated") or payload.get("updated_at")
        if not isinstance(active, list):
            active = []
        if not isinstance(history, list):
            history = []
        return {"active": active, "history": history, "lastUpdated": last_updated}

    return dict(DEFAULT_PAYLOAD)


def main() -> int:
    url = os.getenv("AOG_STATUS_URL", "").strip()
    out_path = Path("data/aog_status.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not url:
        if not out_path.exists():
            out_path.write_text(json.dumps(DEFAULT_PAYLOAD, indent=2) + "\n", encoding="utf-8")
            print("AOG_STATUS_URL not configured; seeded default data/aog_status.json")
        else:
            print("AOG_STATUS_URL not configured; skipping remote AOG refresh")
        return 0

    headers = {}
    token = os.getenv("AOG_STATUS_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    timeout = float(os.getenv("AOG_STATUS_TIMEOUT", "20"))

    req = request.Request(url, headers=headers)

    try:
        with request.urlopen(req, timeout=timeout) as response:
            status = getattr(response, "status", response.getcode())
            if status and int(status) >= 400:
                raise RuntimeError(f"HTTP {status}")
            body = response.read().decode("utf-8")
            payload = _normalize(json.loads(body))
    except (error.URLError, error.HTTPError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"ERROR: Failed to refresh AOG status from {url}: {exc}")
        return 1

    new_content = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    old_content = out_path.read_text(encoding="utf-8") if out_path.exists() else None

    if new_content == old_content:
        print("AOG status unchanged")
        return 0

    out_path.write_text(new_content, encoding="utf-8")
    print(f"Updated {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
