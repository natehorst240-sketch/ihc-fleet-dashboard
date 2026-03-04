"""
fetch_positions_skyrouter.py
Fetches latest IHC AW109SP positions from SkyRouter GPS API.
Uses per-asset IMEI queries (?imei=X&count=1) — no bulk history dump.
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

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_PATH = REPO_ROOT / "data/base_assignments.json"
RUNNER_OUTPUT_PATH = REPO_ROOT / "runner/data/base_assignments.json"

if "SKYROUTER_OUTPUT_PATH" in os.environ:
    OUTPUT_PATH = Path(os.environ["SKYROUTER_OUTPUT_PATH"]).expanduser()
elif RUNNER_OUTPUT_PATH.parent.exists():
    OUTPUT_PATH = RUNNER_OUTPUT_PATH
else:
    OUTPUT_PATH = DEFAULT_OUTPUT_PATH

SCREENSHOT_PATH = REPO_ROOT / "data/login_debug.png"

# Hardcoded IMEI map — Id field from /assets endpoint IS the IMEI
IHC_FLEET: dict[str, int] = {
    "N251HC": 300224010509530,
    "N261HC": 300224010508530,
    "N271HC": 300224010843560,
    "N281HC": 300025010233130,
    "N291HC": 300025010735240,
    "N431HC": 300425060219260,
    "N531HC": 300125010916710,
    "N631HC": 300125010804580,
    # N731HC tracker not yet activated in SkyRouter — uncomment when live:
    # "N731HC": 89011004300085847284,
}

BASES: dict[str, dict] = {
    "LOGAN":      {"lat": 41.7912,  "lon": -111.8522, "name": "Logan"},
    "MCKAY":      {"lat": 41.2545,  "lon": -112.0126, "name": "McKay-Dee"},
    "IMED":       {"lat": 40.2338,  "lon": -111.6585, "name": "IMed"},
    "PROVO":      {"lat": 40.2192,  "lon": -111.7233, "name": "Provo"},
    "ROOSEVELT":  {"lat": 40.2765,  "lon": -110.0518, "name": "Roosevelt"},
    "CEDAR_CITY": {"lat": 37.7010,  "lon": -113.0989, "name": "Cedar City"},
    "ST_GEORGE":  {"lat": 37.0365,  "lon": -113.5101, "name": "St George"},
    "KSLC":       {"lat": 40.7884,  "lon": -111.9778, "name": "KSLC"},
}

ALL_TAILS       = set(IHC_FLEET.keys()) | {"N731HC"}
BASE_RADIUS_MI  = 10
AIRBORNE_SPD    = 500   # cm/s (~10 kts) — speed-only, altitude is MSL not AGL
STALE_HOURS     = 6

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mas_to_deg(mas: int) -> float:
    return mas / 3_600_000.0

def _haversine_mi(lat1, lon1, lat2, lon2) -> float:
    R = 3_958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a  = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return R * 2 * math.asin(math.sqrt(a))

def _closest_base(lat, lon):
    best = min(BASES.items(), key=lambda kv: _haversine_mi(lat, lon, kv[1]["lat"], kv[1]["lon"]))
    return best[0], _haversine_mi(lat, lon, best[1]["lat"], best[1]["lon"])

def _parse_utc(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None

# ---------------------------------------------------------------------------
# Step 1 – Login
# ---------------------------------------------------------------------------

def skyrouter_login() -> requests.Session:
    print("Launching Playwright → SkyRouter login...")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx     = browser.new_context(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ))
        page = ctx.new_page()
        page.goto(SKYROUTER_LOGIN_URL, wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_load_state("networkidle", timeout=30_000)
        time.sleep(2)

        # Find fields
        u = p = None
        for sel in ["input[type='text']", "input[type='email']",
                    "input[name='username']", "input[placeholder*='ser']"]:
            el = page.query_selector(sel)
            if el and el.is_visible(): u = el; break
        for sel in ["input[type='password']", "input[name='password']"]:
            el = page.query_selector(sel)
            if el and el.is_visible(): p = el; break

        if not u or not p:
            page.screenshot(path=str(SCREENSHOT_PATH), full_page=True)
            browser.close()
            raise RuntimeError("Login form not found — screenshot saved to data/login_debug.png")

        u.click(); u.fill(SKYROUTER_USER); time.sleep(0.3)
        p.click(); p.fill(SKYROUTER_PASS); time.sleep(0.3)

        submitted = False
        for sel in ["button[type='submit']", "button:has-text('Login')",
                    "button:has-text('Sign In')", "form button"]:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click(); submitted = True; break
        if not submitted:
            p.press("Enter")

        try:
            page.wait_for_url("**/track**", timeout=20_000)
        except PlaywrightTimeout:
            page.wait_for_load_state("networkidle", timeout=15_000)

        print(f"Logged in → {page.url}")
        cookies = ctx.cookies()
        browser.close()

    session = requests.Session()
    for c in cookies:
        session.cookies.set(c["name"], c["value"], domain=c.get("domain", "skyrouter.com"))
    xa = next((c["value"] for c in cookies if c["name"] == "X-A"), None)
    xt = next((c["value"] for c in cookies if c["name"] == "X-T"), None)
    if xa: session.headers["x-a"] = xa
    if xt: session.headers["x-t"] = xt
    session.headers["x-requested-with"] = "XMLHttpRequest"
    session.headers["accept"]           = "application/json"
    session.headers["referer"]          = "https://skyrouter.com/skyrouter3/track"
    print(f"X-A={xa is not None}  X-T={xt is not None}")
    return session

# ---------------------------------------------------------------------------
# Step 2 – Fetch latest position per aircraft (targeted IMEI queries)
# ---------------------------------------------------------------------------

def fetch_aircraft_positions(session: requests.Session) -> dict[str, dict]:
    """
    Try multiple API strategies to get the latest position per IHC aircraft.
    Strategy 1: /assetPositions?assetId=X  (most likely correct param name)
    Strategy 2: /assets/{id}/positions
    Strategy 3: /assetPositions?asset=X
    Filters returned records by Asset field matching known IMEI/ID.
    """
    now_utc = datetime.now(timezone.utc)
    results = {}

    # Probe which query param the API actually accepts — test with first aircraft
    probe_tail  = "N281HC"
    probe_imei  = IHC_FLEET[probe_tail]
    working_strategy = None

    strategies = [
        ("assetId", f"{SKYROUTER_API_BASE}/assetPositions", {"assetId": probe_imei, "count": 500}),
        ("asset",   f"{SKYROUTER_API_BASE}/assetPositions", {"asset":   probe_imei, "count": 500}),
        ("imei",    f"{SKYROUTER_API_BASE}/assetPositions", {"imei":    probe_imei, "count": 500}),
        ("path",    f"{SKYROUTER_API_BASE}/assets/{probe_imei}/positions", {"count": 500}),
    ]

    print(f"  Probing API with {probe_tail} (id={probe_imei})...")
    for name, url, params in strategies:
        try:
            resp = session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            raw  = resp.json()
            recs = raw if isinstance(raw, list) else raw.get("AssetPositions", [])
            matched = [r for r in recs if int(r.get("Asset", 0)) == probe_imei]
            print(f"    strategy={name}: {len(recs)} records, {len(matched)} matched Asset={probe_imei}")
            if matched and working_strategy is None:
                working_strategy = (name, url.replace(str(probe_imei), "{imei}"), params)
        except Exception as e:
            print(f"    strategy={name}: ERROR {e}")

    if working_strategy is None:
        print("  No strategy matched — dumping Asset IDs from bulk fetch for diagnosis")
        try:
            resp = session.get(f"{SKYROUTER_API_BASE}/assetPositions", timeout=20)
            raw  = resp.json()
            recs = raw if isinstance(raw, list) else raw.get("AssetPositions", [])
            seen_assets = sorted(set(int(r.get("Asset", 0)) for r in recs))
            print(f"  Bulk Asset IDs in response: {seen_assets[:20]}")
            ihc_ids = set(IHC_FLEET.values())
            overlap = [a for a in seen_assets if a in ihc_ids]
            print(f"  IHC matches in bulk: {overlap}")
        except Exception as e:
            print(f"  Bulk diagnostic failed: {e}")
        return {}

    strat_name, url_template, _ = working_strategy
    print(f"  Using strategy: {strat_name}")

    for tail, imei in IHC_FLEET.items():
        try:
            url    = url_template.replace("{imei}", str(imei))
            params = {strat_name: imei, "count": 500} if strat_name != "path" else {"count": 500}
            resp   = session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            raw    = resp.json()
            recs   = raw if isinstance(raw, list) else raw.get("AssetPositions", [])
            matched = [r for r in recs if int(r.get("Asset", 0)) == imei]

            if not matched:
                print(f"  {tail}: no matching records")
                continue

            best_pos = max(matched, key=lambda r: _parse_utc(r.get("Utc","")) or datetime.min.replace(tzinfo=timezone.utc))
            best_dt  = _parse_utc(best_pos.get("Utc", ""))
            age_h    = (now_utc - best_dt).total_seconds() / 3600 if best_dt else 999

            if age_h > STALE_HOURS:
                print(f"  {tail}: stale ({age_h:.1f}h) — skipping")
                continue

            results[tail] = best_pos
            print(f"  {tail}: ok  utc={best_pos.get('Utc','')}  ({len(matched)} records)")

        except Exception as e:
            print(f"  {tail}: ERROR — {e}")

    return results

# ---------------------------------------------------------------------------
# Step 3 – Classify
# ---------------------------------------------------------------------------

def classify_aircraft(raw_positions: dict[str, dict]) -> dict[str, dict]:
    now_utc = datetime.now(timezone.utc)
    out     = {}

    for tail, pos in raw_positions.items():
        utc_str = pos.get("Utc", "")
        pos_dt  = _parse_utc(utc_str)
        age_h   = (now_utc - pos_dt).total_seconds() / 3600 if pos_dt else 999

        lat    = _mas_to_deg(pos["LatitudeMilliarcSeconds"])
        lon    = _mas_to_deg(pos["LongitudeMilliarcSeconds"])
        alt_ft = pos.get("AltitudeCentimeters", 0) / 30.48
        spd_cs = pos.get("SpeedCms", 0)
        spd_kt = spd_cs * 0.0194384

        # Use speed only — SkyRouter altitude is MSL, not AGL.
        # Utah terrain is 4000-5500ft MSL so altitude cannot be used to detect flight.
        is_airborne = spd_cs > AIRBORNE_SPD
        base_id, dist = _closest_base(lat, lon)
        at_base = (not is_airborne) and (dist <= BASE_RADIUS_MI)

        status = "AIRBORNE" if is_airborne else ("AT_BASE" if at_base else "AWAY")

        out[tail] = {
            "tail": tail, "status": status,
            "lat": round(lat, 6), "lon": round(lon, 6),
            "alt_ft": round(alt_ft), "speed_kts": round(spd_kt, 1),
            "heading": pos.get("HeadingDegrees", 0),
            "closest_base": base_id, "dist_miles": round(dist, 1),
            "utc": utc_str, "age_hours": round(age_h, 2),
            "source": "skyrouter",
        }
        print(f"  {tail}: {status} | {base_id} {dist:.1f}mi  {alt_ft:.0f}ft  {spd_kt:.0f}kts")

    return out

# ---------------------------------------------------------------------------
# Step 4 – Build output JSON
# ---------------------------------------------------------------------------

def build_output(aircraft: dict[str, dict]) -> dict:
    assignments = {bid: {"aircraft": [], "status": "available"} for bid in BASES}
    summary     = {"total_aircraft": len(ALL_TAILS),
                   "at_bases": 0, "away_from_base": 0, "airborne": 0, "no_data": 0}

    for tail, info in aircraft.items():
        st = info["status"]
        if st == "AT_BASE":
            bid = info["closest_base"]
            if bid in assignments:
                assignments[bid]["aircraft"].append(tail)
                assignments[bid]["status"] = "occupied"
            summary["at_bases"] += 1
        elif st == "AIRBORNE":
            summary["airborne"] += 1
        else:
            summary["away_from_base"] += 1

    missing = ALL_TAILS - set(aircraft.keys())
    summary["no_data"] = len(missing)
    for t in sorted(missing):
        print(f"  {t}: no data")

    return {
        "assignments":      assignments,
        "bases":            {k: {"name": v["name"], "lat": v["lat"], "lon": v["lon"]}
                             for k, v in BASES.items()},
        "aircraft_detail":  aircraft,
        "missing_aircraft": sorted(missing),
        "summary":          summary,
        "source":           "skyrouter",
        "live_data":        len(aircraft) > 0,
        "last_checked":     datetime.now(timezone.utc).isoformat(),
    }

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=== fetch_positions_skyrouter.py ===")
    print(f"Output path: {OUTPUT_PATH}")
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    try:
        session       = skyrouter_login()
        raw_positions = fetch_aircraft_positions(session)
    except Exception as exc:
        print(f"ERROR: {exc}")
        import traceback; traceback.print_exc()
        fallback = build_output({})
        fallback["error"] = str(exc)
        OUTPUT_PATH.write_text(json.dumps(fallback, indent=2))
        sys.exit(1)

    aircraft = classify_aircraft(raw_positions)
    output   = build_output(aircraft)
    OUTPUT_PATH.write_text(json.dumps(output, indent=2))

    s = output["summary"]
    print(f"\nResult: {s['at_bases']} at base | {s['airborne']} airborne | "
          f"{s['away_from_base']} away | {s['no_data']} no data")

if __name__ == "__main__":
    main()
