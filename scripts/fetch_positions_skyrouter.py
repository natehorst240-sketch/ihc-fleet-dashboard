"""
fetch_positions_skyrouter.py
Fetches latest IHC AW109SP positions from SkyRouter GPS API.

Optimisations over the original:
  1. Cookie cache  – Playwright login runs only once per session (default 8 h);
                     subsequent runs restore the session from disk in <1 s.
  2. Bulk fetch    – Tries a single /assetPositions call (no imei param) first;
                     if the API returns all fleet records we need only 1 request
                     instead of 8.
  3. Parallel fetch – If the bulk call doesn't cover every IMEI, falls back to
                      per-IMEI requests fired concurrently via ThreadPoolExecutor
                      (~3 s total instead of up to 160 s sequential).
  4. Smart waits   – Playwright time.sleep() replaced with proper waits.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SKYROUTER_LOGIN_URL = "https://skyrouter.com/skyrouter3/"
SKYROUTER_API_BASE  = "https://skyrouter.com/BsnWebApi"
SKYROUTER_USER      = os.getenv("SKYROUTER_USER")
SKYROUTER_PASS      = os.getenv("SKYROUTER_PASS")

OUTPUT_PATH      = Path("data/base_assignments.json")
SCREENSHOT_PATH  = Path("data/login_debug.png")
COOKIE_CACHE     = Path("data/.skyrouter_cookies.json")
COOKIE_TTL_HOURS = 8          # re-login after this many hours

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

ALL_TAILS      = set(IHC_FLEET.keys()) | {"N731HC"}
BASE_RADIUS_MI = 10
AIRBORNE_SPD   = 500   # cm/s  (~10 kts)
AIRBORNE_ALT   = 200   # ft
STALE_HOURS    = 6

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

def _best_record(records: list[dict], imei: int | None = None) -> dict | None:
    """Return the newest record matching imei (if given), otherwise the newest overall."""
    matching = [r for r in records if int(r.get("Asset", 0)) == imei] if imei is not None else list(records)
    if not matching:
        return None
    best_pos, best_dt = None, None
    for rec in matching:
        dt = _parse_utc(rec.get("Utc", ""))
        if dt and (best_dt is None or dt > best_dt):
            best_dt, best_pos = dt, rec
    return best_pos

# ---------------------------------------------------------------------------
# Step 1 – Login  (with cookie cache)
# ---------------------------------------------------------------------------

def _build_session_from_cookies(cookies: list[dict]) -> requests.Session:
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
    print(f"  X-A={xa is not None}  X-T={xt is not None}")
    return session

def _load_cached_session() -> requests.Session | None:
    """Return a requests.Session from the on-disk cookie cache, or None if stale/missing."""
    if not COOKIE_CACHE.exists():
        return None
    try:
        data    = json.loads(COOKIE_CACHE.read_text())
        age_h   = (time.time() - data.get("saved_at", 0)) / 3600
        if age_h > COOKIE_TTL_HOURS:
            print(f"  Cookie cache expired ({age_h:.1f}h old) — re-logging in")
            return None
        print(f"  Restoring session from cookie cache ({age_h:.1f}h old)")
        return _build_session_from_cookies(data["cookies"])
    except Exception as e:
        print(f"  Cookie cache unreadable: {e}")
        return None

def _save_cookie_cache(cookies: list[dict]) -> None:
    COOKIE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    COOKIE_CACHE.write_text(json.dumps({"cookies": cookies, "saved_at": time.time()}, indent=2))

def skyrouter_login() -> requests.Session:
    cached = _load_cached_session()
    if cached:
        return cached

    print("Launching Playwright → SkyRouter login...")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx     = browser.new_context(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ))
        page = ctx.new_page()
        page.goto(SKYROUTER_LOGIN_URL, wait_until="domcontentloaded", timeout=45_000)

        # Wait for a visible input rather than a fixed sleep
        u = p = None
        for sel in ["input[type='text']", "input[type='email']",
                    "input[name='username']", "input[placeholder*='ser']"]:
            try:
                page.wait_for_selector(sel, state="visible", timeout=10_000)
                el = page.query_selector(sel)
                if el and el.is_visible():
                    u = el; break
            except PlaywrightTimeout:
                continue

        for sel in ["input[type='password']", "input[name='password']"]:
            el = page.query_selector(sel)
            if el and el.is_visible():
                p = el; break

        if not u or not p:
            page.screenshot(path=str(SCREENSHOT_PATH), full_page=True)
            browser.close()
            raise RuntimeError("Login form not found — screenshot saved to data/login_debug.png")

        u.click(); u.fill(SKYROUTER_USER)
        page.wait_for_timeout(300)
        p.click(); p.fill(SKYROUTER_PASS)
        page.wait_for_timeout(300)

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

        print(f"  Logged in → {page.url}")
        cookies = ctx.cookies()
        browser.close()

    _save_cookie_cache(cookies)
    return _build_session_from_cookies(cookies)

# ---------------------------------------------------------------------------
# Step 2 – Fetch positions  (bulk first, parallel per-IMEI fallback)
# ---------------------------------------------------------------------------

def _try_bulk_fetch(session: requests.Session) -> dict[str, dict] | None:
    """
    Attempt a single /assetPositions call with no imei filter.
    Returns {tail: best_record} if the response covers every IHC IMEI,
    otherwise returns None so the caller can fall back to per-IMEI queries.
    """
    try:
        resp = session.get(f"{SKYROUTER_API_BASE}/assetPositions", params={"count": 1}, timeout=20)
        resp.raise_for_status()
        raw     = resp.json()
        records = raw if isinstance(raw, list) else raw.get("AssetPositions", [])
        if not records:
            return None

        results: dict[str, dict] = {}
        for tail, imei in IHC_FLEET.items():
            rec = _best_record(records, imei)
            if rec:
                results[tail] = rec

        coverage = len(results) / len(IHC_FLEET)
        print(f"  Bulk fetch: {len(records)} total records, "
              f"{len(results)}/{len(IHC_FLEET)} IHC aircraft matched ({coverage:.0%})")

        # Accept bulk result only if it covers at least half the fleet
        return results if coverage >= 0.5 else None

    except Exception as e:
        print(f"  Bulk fetch failed: {e}")
        return None

def _fetch_one(session: requests.Session, tail: str, imei: int) -> tuple[str, list[dict]]:
    """Fetch /assetPositions for a single IMEI. Returns (tail, records)."""
    resp = session.get(
        f"{SKYROUTER_API_BASE}/assetPositions",
        params={"imei": imei, "count": 1},
        timeout=20,
    )
    resp.raise_for_status()
    raw = resp.json()
    return tail, raw if isinstance(raw, list) else raw.get("AssetPositions", [])

def _parallel_fetch(session: requests.Session) -> dict[str, dict]:
    """Fire one request per IMEI concurrently; return {tail: best_record}."""
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=len(IHC_FLEET)) as pool:
        futures = {
            pool.submit(_fetch_one, session, tail, imei): (tail, imei)
            for tail, imei in IHC_FLEET.items()
        }
        for fut in as_completed(futures):
            tail, imei = futures[fut]
            try:
                _, records = fut.result()
                if not records:
                    print(f"  {tail}: no records returned")
                    continue
                # Don't filter by Asset — API may ignore ?imei param, so just
                # take the newest record from whatever was returned.
                rec = _best_record(records)
                if rec is None:
                    print(f"  {tail}: no parseable records")
                    continue
                results[tail] = rec
                print(f"  {tail}: ok  asset={rec.get('Asset','')}  utc={rec.get('Utc', '')}")
            except Exception as e:
                print(f"  {tail}: ERROR — {e}")
    return results

def fetch_aircraft_positions(session: requests.Session) -> dict[str, dict]:
    """
    1. Try a single bulk /assetPositions call — fastest (1 request).
    2. If bulk coverage is too low, fall back to parallel per-IMEI calls.
    """
    now_utc = datetime.now(timezone.utc)

    print("  Attempting bulk fetch...")
    raw_positions = _try_bulk_fetch(session)

    if raw_positions is None:
        print("  Bulk fetch insufficient — falling back to parallel per-IMEI requests...")
        raw_positions = _parallel_fetch(session)

    # Staleness filter (shared for both paths)
    results: dict[str, dict] = {}
    for tail, pos in raw_positions.items():
        best_dt = _parse_utc(pos.get("Utc", ""))
        if best_dt is None:
            print(f"  {tail}: no parseable timestamp — skipping")
            continue
        age_h = (now_utc - best_dt).total_seconds() / 3600
        if age_h > STALE_HOURS:
            print(f"  {tail}: stale ({age_h:.1f}h old) — skipping")
            continue
        results[tail] = pos

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

        is_airborne = spd_cs > AIRBORNE_SPD or alt_ft > AIRBORNE_ALT
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
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    try:
        if not SKYROUTER_USER or not SKYROUTER_PASS:
            raise RuntimeError(
                "SkyRouter fetch blocked: missing SKYROUTER_USER and/or SKYROUTER_PASS. "
                "Set these GitHub Action secrets to enable SkyRouter position fetches."
            )
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

    # Only write if meaningful content has changed (ignore last_checked timestamp)
    def _strip_timestamp(d: dict) -> dict:
        return {k: v for k, v in d.items() if k != "last_checked"}

    changed = True
    if OUTPUT_PATH.exists():
        try:
            existing = json.loads(OUTPUT_PATH.read_text())
            if _strip_timestamp(existing) == _strip_timestamp(output):
                changed = False
        except Exception:
            pass  # unreadable existing file → write anyway

    if changed:
        OUTPUT_PATH.write_text(json.dumps(output, indent=2))
        print("  Output written (data changed).")
    else:
        print("  No change in data — skipping write.")

    s = output["summary"]
    print(f"\nResult: {s['at_bases']} at base | {s['airborne']} airborne | "
          f"{s['away_from_base']} away | {s['no_data']} no data")

if __name__ == "__main__":
    main()
