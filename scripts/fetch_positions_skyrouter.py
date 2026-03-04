"""
fetch_positions_skyrouter.py
Replaces the airplanes.live/adsb.lol approach entirely.

Flow:
  1. Playwright logs into SkyRouter, extracts session cookies (X-A, X-T)
  2. GET /BsnWebApi/assets          → Asset ID → tail number map
  3. GET /BsnWebApi/assetPositions?count=100 → latest position for every asset
  4. Convert LatitudeMilliarcSeconds / 3,600,000 → decimal degrees
  5. Haversine distance check against each IHC base (10 mile radius)
  6. Write data/base_assignments.json  (same schema the dashboard reads)
"""

from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SKYROUTER_URL      = "https://skyrouter.com/skyrouter3/track"
SKYROUTER_API_BASE = "https://skyrouter.com/BsnWebApi"
SKYROUTER_USER     = os.environ["SKYROUTER_USER"]      # GitHub secret
SKYROUTER_PASS     = os.environ["SKYROUTER_PASS"]      # GitHub secret

OUTPUT_PATH = Path("data/base_assignments.json")

# Only track these tails (IHC AW109SP fleet)
IHC_TAILS = {
    "N251HC", "N261HC", "N271HC", "N281HC", "N291HC",
    "N431HC", "N531HC", "N631HC", "N731HC",
}

# Base definitions  (lat, lon, display name)
BASES: dict[str, dict] = {
    "SLC": {"lat": 40.7887,  "lon": -111.9787, "name": "Salt Lake City"},
    "PVO": {"lat": 40.2191,  "lon": -111.6585, "name": "Provo"},
    "LOG": {"lat": 41.7873,  "lon": -111.8527, "name": "Logan"},
    "OGD": {"lat": 41.1960,  "lon": -112.0120, "name": "Ogden"},
    "STG": {"lat": 37.0965,  "lon": -113.5684, "name": "St. George"},
    "CDC": {"lat": 37.7010,  "lon": -113.0980, "name": "Cedar City"},
    "VEL": {"lat": 40.4408,  "lon": -109.5260, "name": "Vernal"},
    "PGU": {"lat": 37.9362,  "lon": -110.7196, "name": "Page"},
    "EKR": {"lat": 39.0114,  "lon": -110.7296, "name": "Green River"},
}

BASE_RADIUS_MILES = 10          # within this → "at base"
AIRBORNE_SPEED_CMS = 500        # > 5 m/s (~10 kts) → airborne
STALE_HOURS = 6                 # ignore positions older than this

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mas_to_deg(milliarcseconds: int) -> float:
    """Milliarcseconds → decimal degrees."""
    return milliarcseconds / 3_600_000.0


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3_958.8  # Earth radius in miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def _closest_base(lat: float, lon: float) -> tuple[str, float]:
    """Return (base_id, distance_miles) for the nearest base."""
    best_id, best_dist = min(
        BASES.items(),
        key=lambda kv: _haversine_miles(lat, lon, kv[1]["lat"], kv[1]["lon"]),
    )
    return best_id, _haversine_miles(lat, lon, BASES[best_id]["lat"], BASES[best_id]["lon"])


# ---------------------------------------------------------------------------
# Step 1 – login with Playwright, return a requests.Session with cookies
# ---------------------------------------------------------------------------

def skyrouter_login() -> requests.Session:
    print("Launching Playwright to log in to SkyRouter...")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.goto("https://skyrouter.com/skyrouter3/login", timeout=30_000)
        page.wait_for_load_state("networkidle", timeout=30_000)

        # Fill credentials – adjust selectors if SkyRouter ever changes the form
        page.fill("input[type='text'], input[name*='user'], input[id*='user']",
                  SKYROUTER_USER)
        page.fill("input[type='password']", SKYROUTER_PASS)
        page.click("button[type='submit'], input[type='submit']")

        # Wait until we land on the track page (URL changes or network settles)
        try:
            page.wait_for_url("**/track**", timeout=20_000)
        except Exception:
            page.wait_for_load_state("networkidle", timeout=20_000)

        cookies = context.cookies()
        browser.close()

    # Transfer cookies into a requests.Session
    session = requests.Session()
    for c in cookies:
        session.cookies.set(c["name"], c["value"], domain=c.get("domain", "skyrouter.com"))

    # Mirror the custom headers SkyRouter expects
    xa = next((c["value"] for c in cookies if c["name"] == "X-A"), None)
    xt = next((c["value"] for c in cookies if c["name"] == "X-T"), None)
    if xa:
        session.headers["x-a"] = xa
    if xt:
        session.headers["x-t"] = xt
    session.headers["x-requested-with"] = "XMLHttpRequest"
    session.headers["accept"] = "application/json, text/javascript, */*; q=0.01"
    session.headers["referer"] = SKYROUTER_URL

    print(f"Login OK – X-A present: {xa is not None}, X-T present: {xt is not None}")
    return session


# ---------------------------------------------------------------------------
# Step 2 – fetch asset list → {asset_id: tail}
# ---------------------------------------------------------------------------

def fetch_asset_map(session: requests.Session) -> dict[int, str]:
    resp = session.get(f"{SKYROUTER_API_BASE}/assets", timeout=20)
    resp.raise_for_status()
    assets = resp.json()
    mapping: dict[int, str] = {}
    for a in assets:
        tail = a.get("Registration") or a.get("Name", "")
        if tail:
            mapping[int(a["Id"])] = tail
    print(f"Asset map loaded: {len(mapping)} assets")
    return mapping


# ---------------------------------------------------------------------------
# Step 3 – fetch latest positions
# ---------------------------------------------------------------------------

def fetch_positions(session: requests.Session) -> list[dict]:
    resp = session.get(
        f"{SKYROUTER_API_BASE}/assetPositions",
        params={"count": 200},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    # API returns either a plain list OR {"AssetPositions": [...], "Meta": {...}}
    if isinstance(data, list):
        return data
    return data.get("AssetPositions", [])


# ---------------------------------------------------------------------------
# Step 4 – classify each IHC aircraft
# ---------------------------------------------------------------------------

def classify_aircraft(
    positions: list[dict],
    asset_map: dict[int, str],
) -> dict[str, dict]:
    """Returns {tail: {status, lat, lon, alt_ft, speed_kts, base, dist_miles, utc}}"""
    now_utc = datetime.now(timezone.utc)
    results: dict[str, dict] = {}

    for pos in positions:
        asset_id = int(pos.get("Asset", 0))
        tail = asset_map.get(asset_id)
        if not tail or tail not in IHC_TAILS:
            continue

        # Parse timestamp
        utc_str = pos.get("Utc", "")
        try:
            pos_time = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
            age_hours = (now_utc - pos_time).total_seconds() / 3600
        except Exception:
            age_hours = 999

        if age_hours > STALE_HOURS:
            print(f"  {tail}: stale ({age_hours:.1f}h old), skipping")
            continue

        lat = _mas_to_deg(pos["LatitudeMilliarcSeconds"])
        lon = _mas_to_deg(pos["LongitudeMilliarcSeconds"])
        alt_ft = pos.get("AltitudeCentimeters", 0) / 30.48
        speed_cms = pos.get("SpeedCms", 0)
        speed_kts = speed_cms * 0.0194384

        is_airborne = speed_cms > AIRBORNE_SPEED_CMS or alt_ft > 1000

        closest_base, dist = _closest_base(lat, lon)
        at_base = (not is_airborne) and (dist <= BASE_RADIUS_MILES)

        if is_airborne:
            status = "AIRBORNE"
        elif at_base:
            status = "AT_BASE"
        else:
            status = "AWAY"

        results[tail] = {
            "tail":         tail,
            "status":       status,
            "lat":          round(lat, 6),
            "lon":          round(lon, 6),
            "alt_ft":       round(alt_ft),
            "speed_kts":    round(speed_kts, 1),
            "closest_base": closest_base,
            "dist_miles":   round(dist, 1),
            "utc":          utc_str,
            "age_hours":    round(age_hours, 2),
            "source":       "skyrouter",
        }
        print(f"  {tail}: {status} | base={closest_base} dist={dist:.1f}mi "
              f"alt={alt_ft:.0f}ft spd={speed_kts:.0f}kts")

    return results


# ---------------------------------------------------------------------------
# Step 5 – build base_assignments.json
# ---------------------------------------------------------------------------

def build_output(aircraft: dict[str, dict]) -> dict:
    assignments: dict[str, dict] = {
        base_id: {"aircraft": [], "status": "available"}
        for base_id in BASES
    }

    summary = {"total_aircraft": len(IHC_TAILS), "at_bases": 0,
               "away_from_base": 0, "airborne": 0, "no_data": 0}

    # Aircraft with data
    for tail, info in aircraft.items():
        if info["status"] == "AT_BASE":
            base_id = info["closest_base"]
            assignments[base_id]["aircraft"].append(tail)
            assignments[base_id]["status"] = "occupied"
            summary["at_bases"] += 1
        elif info["status"] == "AIRBORNE":
            summary["airborne"] += 1
        else:
            summary["away_from_base"] += 1

    # Aircraft with no data
    missing = IHC_TAILS - set(aircraft.keys())
    summary["no_data"] = len(missing)
    for tail in missing:
        print(f"  {tail}: no position data")

    return {
        "assignments":    assignments,
        "bases":          {k: {"name": v["name"], "lat": v["lat"], "lon": v["lon"]}
                           for k, v in BASES.items()},
        "aircraft_detail": aircraft,
        "missing_aircraft": sorted(missing),
        "summary":        summary,
        "source":         "skyrouter",
        "live_data":      len(aircraft) > 0,
        "last_checked":   datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=== fetch_positions_skyrouter.py ===")

    try:
        session    = skyrouter_login()
        asset_map  = fetch_asset_map(session)
        positions  = fetch_positions(session)
    except Exception as exc:
        print(f"ERROR fetching from SkyRouter: {exc}")
        # Write a fallback so git add doesn't fail
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        fallback = build_output({})
        fallback["error"] = str(exc)
        OUTPUT_PATH.write_text(json.dumps(fallback, indent=2), encoding="utf-8")
        sys.exit(1)

    print(f"Positions returned: {len(positions)}")
    aircraft = classify_aircraft(positions, asset_map)
    output   = build_output(aircraft)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, indent=2), encoding="utf-8")

    s = output["summary"]
    print(f"\nDone: {s['at_bases']} at base | {s['airborne']} airborne | "
          f"{s['away_from_base']} away | {s['no_data']} no data")


if __name__ == "__main__":
    main()
