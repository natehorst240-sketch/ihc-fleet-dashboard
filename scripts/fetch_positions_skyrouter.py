"""
fetch_positions_skyrouter.py
Fetches IHC AW109SP positions from SkyRouter GPS API.

Flow:
  1. Playwright logs in, waits for JS to render the form, extracts session cookies
  2. GET /BsnWebApi/assets          → Asset ID → tail number map
  3. GET /BsnWebApi/assetPositions  → latest positions for all assets
  4. Haversine distance check against IHC bases
  5. Write data/base_assignments.json
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SKYROUTER_LOGIN_URL = "https://skyrouter.com/skyrouter3/"
SKYROUTER_API_BASE  = "https://skyrouter.com/BsnWebApi"
SKYROUTER_USER      = os.environ["SKYROUTER_USER"]
SKYROUTER_PASS      = os.environ["SKYROUTER_PASS"]

OUTPUT_PATH = Path("data/base_assignments.json")
SCREENSHOT_PATH = Path("data/login_debug.png")  # saved on failure for debugging

IHC_TAILS = {
    "N251HC", "N261HC", "N271HC", "N281HC", "N291HC",
    "N431HC", "N531HC", "N631HC", "N731HC",
}

BASES: dict[str, dict] = {
    "LOGAN":      {"lat": 41.7912,  "lon": -111.8522, "name": "Logan"},
    "MCKAY":      {"lat": 41.2545,  "lon": -112.0126, "name": "McKay-Dee"},
    "IMED":       {"lat": 40.2338,  "lon": -111.6585, "name": "IMed Provo"},
    "PROVO":      {"lat": 40.2192,  "lon": -111.7233, "name": "Provo"},
    "ROOSEVELT":  {"lat": 40.2765,  "lon": -110.0518, "name": "Roosevelt"},
    "CEDAR_CITY": {"lat": 37.7010,  "lon": -113.0989, "name": "Cedar City"},
    "ST_GEORGE":  {"lat": 37.0365,  "lon": -113.5101, "name": "St George"},
    "KSLC":       {"lat": 40.7884,  "lon": -111.9778, "name": "KSLC"},
}

BASE_RADIUS_MILES   = 10
AIRBORNE_SPEED_CMS  = 500    # > 5 m/s (~10 kts) → airborne
STALE_HOURS         = 6

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mas_to_deg(milliarcseconds: int) -> float:
    return milliarcseconds / 3_600_000.0


def _haversine_miles(lat1, lon1, lat2, lon2) -> float:
    R = 3_958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def _closest_base(lat, lon):
    best_id, best_dist = min(
        BASES.items(),
        key=lambda kv: _haversine_miles(lat, lon, kv[1]["lat"], kv[1]["lon"]),
    )
    return best_id, _haversine_miles(lat, lon, BASES[best_id]["lat"], BASES[best_id]["lon"])


# ---------------------------------------------------------------------------
# Step 1 – Playwright login
# ---------------------------------------------------------------------------

def skyrouter_login() -> requests.Session:
    print("Launching Playwright to log in to SkyRouter...")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        # ── Navigate to login page ─────────────────────────────────────────
        print(f"Navigating to {SKYROUTER_LOGIN_URL} ...")
        page.goto(SKYROUTER_LOGIN_URL, wait_until="domcontentloaded", timeout=45_000)

        # Wait for the page to fully settle (JS frameworks need time)
        page.wait_for_load_state("networkidle", timeout=30_000)
        time.sleep(2)  # extra buffer for Angular/React hydration

        # ── Debug: print all visible inputs ───────────────────────────────
        print("Scanning for input elements on page...")
        inputs = page.query_selector_all("input")
        for i, inp in enumerate(inputs):
            t   = inp.get_attribute("type") or ""
            n   = inp.get_attribute("name") or ""
            id_ = inp.get_attribute("id") or ""
            ph  = inp.get_attribute("placeholder") or ""
            print(f"  input[{i}]: type='{t}' name='{n}' id='{id_}' placeholder='{ph}'")

        current_url = page.url
        print(f"Current URL: {current_url}")

        # ── Try to find username field with multiple strategies ────────────
        username_selectors = [
            "input[type='email']",
            "input[type='text']",
            "input[name='username']",
            "input[name='email']",
            "input[name='user']",
            "input[id*='user']",
            "input[id*='email']",
            "input[placeholder*='ser']",     # User, Username
            "input[placeholder*='mail']",    # Email
            "input:not([type='password'])",  # any non-password input
        ]

        username_field = None
        for sel in username_selectors:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    username_field = el
                    print(f"Found username field with selector: {sel}")
                    break
            except Exception:
                continue

        password_selectors = [
            "input[type='password']",
            "input[name='password']",
            "input[name='pass']",
        ]

        password_field = None
        for sel in password_selectors:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    password_field = el
                    print(f"Found password field with selector: {sel}")
                    break
            except Exception:
                continue

        if not username_field or not password_field:
            # Save screenshot for debugging, then bail
            try:
                page.screenshot(path=str(SCREENSHOT_PATH), full_page=True)
                print(f"Screenshot saved to {SCREENSHOT_PATH}")
            except Exception as e:
                print(f"Could not save screenshot: {e}")
            # Also dump page source excerpt
            content = page.content()[:3000]
            print("=== PAGE HTML (first 3000 chars) ===")
            print(content)
            print("=====================================")
            browser.close()
            raise RuntimeError(
                f"Could not find login form. "
                f"username_found={username_field is not None}, "
                f"password_found={password_field is not None}. "
                f"Check screenshot at {SCREENSHOT_PATH}"
            )

        # ── Fill and submit ────────────────────────────────────────────────
        username_field.click()
        username_field.fill(SKYROUTER_USER)
        time.sleep(0.5)

        password_field.click()
        password_field.fill(SKYROUTER_PASS)
        time.sleep(0.5)

        # Find submit button
        submit_selectors = [
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('Login')",
            "button:has-text('Sign In')",
            "button:has-text('Log In')",
            ".login-btn",
            "form button",
        ]
        submitted = False
        for sel in submit_selectors:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    print(f"Clicking submit button: {sel}")
                    btn.click()
                    submitted = True
                    break
            except Exception:
                continue

        if not submitted:
            print("No submit button found, trying Enter key...")
            password_field.press("Enter")

        # ── Wait for post-login navigation ─────────────────────────────────
        try:
            page.wait_for_url("**/track**", timeout=20_000)
            print(f"Login succeeded — now at: {page.url}")
        except PlaywrightTimeout:
            # Might still be logged in even if URL didn't change to /track
            print(f"URL after submit: {page.url}")
            page.wait_for_load_state("networkidle", timeout=15_000)

        cookies = context.cookies()
        browser.close()

    # ── Transfer cookies into requests.Session ─────────────────────────────
    session = requests.Session()
    for c in cookies:
        session.cookies.set(c["name"], c["value"], domain=c.get("domain", "skyrouter.com"))

    xa = next((c["value"] for c in cookies if c["name"] == "X-A"), None)
    xt = next((c["value"] for c in cookies if c["name"] == "X-T"), None)
    if xa:
        session.headers["x-a"] = xa
    if xt:
        session.headers["x-t"] = xt
    session.headers["x-requested-with"] = "XMLHttpRequest"
    session.headers["accept"] = "application/json, text/javascript, */*; q=0.01"
    session.headers["referer"] = "https://skyrouter.com/skyrouter3/track"

    cookie_names = [c["name"] for c in cookies]
    print(f"Session cookies: {cookie_names}")
    print(f"X-A present: {xa is not None}, X-T present: {xt is not None}")
    return session


# ---------------------------------------------------------------------------
# Step 2 – Asset map
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
    print(f"Asset map: {len(mapping)} assets")
    return mapping


# ---------------------------------------------------------------------------
# Step 3 – Positions
# ---------------------------------------------------------------------------

def fetch_positions(session: requests.Session) -> list[dict]:
    resp = session.get(
        f"{SKYROUTER_API_BASE}/assetPositions",
        params={"count": 200},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else data.get("AssetPositions", [])


# ---------------------------------------------------------------------------
# Step 4 – Classify
# ---------------------------------------------------------------------------

def classify_aircraft(positions, asset_map) -> dict[str, dict]:
    now_utc = datetime.now(timezone.utc)
    results: dict[str, dict] = {}

    for pos in positions:
        asset_id = int(pos.get("Asset", 0))
        tail = asset_map.get(asset_id)
        if not tail or tail not in IHC_TAILS:
            continue

        utc_str = pos.get("Utc", "")
        try:
            pos_time  = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
            age_hours = (now_utc - pos_time).total_seconds() / 3600
        except Exception:
            age_hours = 999

        if age_hours > STALE_HOURS:
            print(f"  {tail}: stale ({age_hours:.1f}h old), skipping")
            continue

        lat     = _mas_to_deg(pos["LatitudeMilliarcSeconds"])
        lon     = _mas_to_deg(pos["LongitudeMilliarcSeconds"])
        alt_ft  = pos.get("AltitudeCentimeters", 0) / 30.48
        spd_cms = pos.get("SpeedCms", 0)
        spd_kts = spd_cms * 0.0194384

        is_airborne = spd_cms > AIRBORNE_SPEED_CMS or alt_ft > 1000
        closest_base, dist = _closest_base(lat, lon)
        at_base = (not is_airborne) and (dist <= BASE_RADIUS_MILES)

        status = "AIRBORNE" if is_airborne else ("AT_BASE" if at_base else "AWAY")

        results[tail] = {
            "tail": tail, "status": status,
            "lat": round(lat, 6), "lon": round(lon, 6),
            "alt_ft": round(alt_ft), "speed_kts": round(spd_kts, 1),
            "closest_base": closest_base, "dist_miles": round(dist, 1),
            "utc": utc_str, "age_hours": round(age_hours, 2),
            "source": "skyrouter",
        }
        print(f"  {tail}: {status} | base={closest_base} dist={dist:.1f}mi alt={alt_ft:.0f}ft")

    return results


# ---------------------------------------------------------------------------
# Step 5 – Build output
# ---------------------------------------------------------------------------

def build_output(aircraft: dict[str, dict]) -> dict:
    assignments: dict[str, dict] = {
        base_id: {"aircraft": [], "status": "available"}
        for base_id in BASES
    }
    summary = {"total_aircraft": len(IHC_TAILS),
               "at_bases": 0, "away_from_base": 0, "airborne": 0, "no_data": 0}

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

    missing = IHC_TAILS - set(aircraft.keys())
    summary["no_data"] = len(missing)
    for tail in missing:
        print(f"  {tail}: no position data")

    return {
        "assignments":     assignments,
        "bases":           {k: {"name": v["name"], "lat": v["lat"], "lon": v["lon"]}
                            for k, v in BASES.items()},
        "aircraft_detail": aircraft,
        "missing_aircraft": sorted(missing),
        "summary":         summary,
        "source":          "skyrouter",
        "live_data":       len(aircraft) > 0,
        "last_checked":    datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=== fetch_positions_skyrouter.py ===")
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    try:
        session   = skyrouter_login()
        asset_map = fetch_asset_map(session)
        positions = fetch_positions(session)
    except Exception as exc:
        print(f"ERROR fetching from SkyRouter: {exc}")
        fallback = build_output({})
        fallback["error"] = str(exc)
        OUTPUT_PATH.write_text(json.dumps(fallback, indent=2), encoding="utf-8")
        sys.exit(1)

    print(f"Positions returned: {len(positions)}")
    aircraft = classify_aircraft(positions, asset_map)
    output   = build_output(aircraft)
    OUTPUT_PATH.write_text(json.dumps(output, indent=2), encoding="utf-8")

    s = output["summary"]
    print(f"\nDone: {s['at_bases']} at base | {s['airborne']} airborne | "
          f"{s['away_from_base']} away | {s['no_data']} no data")


if __name__ == "__main__":
    main()
