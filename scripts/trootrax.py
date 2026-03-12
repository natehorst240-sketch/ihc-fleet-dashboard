import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

LOGIN_URL = "https://apps4.trootrax.com/emstracker/login/main.php"
ASSETS_URL = "https://apps4.trootrax.com/rest/v2.0/assets/locations"
DEFAULT_CUSTOMER_ID = "312"
REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPO_ROOT / "data" / "aircraft_locations.json"
BASE_ASSIGNMENTS_OUTPUT_PATH = REPO_ROOT / "data" / "base_assignments.json"

BASES = {
    "LOGAN": {"name": "Logan", "lat": 41.7912, "lon": -111.8522, "radius_miles": 5},
    "MCKAY": {"name": "McKay", "lat": 41.2545, "lon": -112.0126, "radius_miles": 5},
    "IMED": {"name": "IMed", "lat": 40.2338, "lon": -111.6585, "radius_miles": 5},
    "PROVO": {"name": "Provo", "lat": 40.2192, "lon": -111.7233, "radius_miles": 5},
    "ROOSEVELT": {"name": "Roosevelt", "lat": 40.2765, "lon": -110.0518, "radius_miles": 5},
    "CEDAR_CITY": {"name": "Cedar City", "lat": 37.7010, "lon": -113.0989, "radius_miles": 5},
    "ST_GEORGE": {"name": "St George", "lat": 37.0365, "lon": -113.5101, "radius_miles": 5},
    "KSLC": {"name": "KSLC", "lat": 40.7884, "lon": -111.9778, "radius_miles": 10},
}


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _haversine_miles(lat1, lon1, lat2, lon2):
    from math import atan2, cos, radians, sin, sqrt

    r = 3958.8
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return r * (2 * atan2(sqrt(a), sqrt(1 - a)))


def _closest_base(lat, lon):
    if lat is None or lon is None:
        return None, None
    best_id, best_dist = None, None
    for base_id, meta in BASES.items():
        dist = _haversine_miles(lat, lon, meta["lat"], meta["lon"])
        if best_dist is None or dist < best_dist:
            best_id, best_dist = base_id, dist
    return best_id, best_dist


def _status_for(asset, dist_miles):
    state = str(asset.get("_state", "")).upper()
    speed = _to_float(asset.get("speed"))
    if "AIRBORNE" in state or "FLIGHT" in state or (speed is not None and speed >= 35):
        return "AIRBORNE"
    if dist_miles is not None and dist_miles <= 5:
        return "AT_BASE"
    return "AWAY"


def login_and_fetch(session, username, password, customer_id):
    login_data = {
        "login": username,
        "passwd": password,
        "passwd_type": "text",
        "submitit": "Login",
    }
    session.post(LOGIN_URL, data=login_data, timeout=30)
    session_id = session.cookies.get("Sessionid")
    if not session_id:
        raise RuntimeError("Login failed — could not retrieve session ID")

    params = {
        "customer_id": customer_id,
        "app": "weathermap",
        "tail": "true",
        "trip_plan": "true",
    }
    resp = session.get(ASSETS_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    assets = data.get("assets")
    if not isinstance(assets, list):
        raise RuntimeError(f"Unexpected API response: {data}")
    return assets


def build_feed(assets):
    now_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    aircraft = []

    for asset in assets:
        tail_history = asset.get("_tail") or []
        latest = tail_history[0] if tail_history else {}

        lat = _to_float(latest.get("latitude"))
        lon = _to_float(latest.get("longitude"))
        alt = _to_float(asset.get("altitude") or latest.get("altitude"))
        speed = _to_float(asset.get("speed") or latest.get("speed"))
        tail = str(asset.get("registration") or asset.get("vin") or "").strip().upper()
        if not tail:
            continue

        base_id, dist_miles = _closest_base(lat, lon)
        status = _status_for(asset, dist_miles)

        aircraft.append(
            {
                "tail": tail,
                "status": status,
                "state_raw": asset.get("_state", ""),
                "lat": lat,
                "lon": lon,
                "speed_kts": speed,
                "alt_ft": alt,
                "closest_base": base_id,
                "dist_miles": round(dist_miles, 2) if dist_miles is not None else None,
                "timestamp_utc": latest.get("timestamp", ""),
                "timestamp_local": latest.get("timestamp_local", ""),
            }
        )

    return {
        "source": "trootrax",
        "last_updated": now_utc,
        "bases": BASES,
        "aircraft": sorted(aircraft, key=lambda a: a["tail"]),
    }


def build_base_assignments(feed):
    assignments = {base_id: {"aircraft": []} for base_id in BASES}
    assignments["unassigned"] = []
    aircraft_detail = {}

    for ac in feed.get("aircraft", []):
        tail = ac.get("tail")
        if not tail:
            continue

        status = str(ac.get("status", "")).upper() or "UNKNOWN"
        base_id = ac.get("closest_base") if ac.get("closest_base") in BASES else None

        aircraft_detail[tail] = {
            "status": status,
            "base_id": base_id,
            "dist_miles": ac.get("dist_miles"),
            "lat": ac.get("lat"),
            "lon": ac.get("lon"),
            "utc": ac.get("timestamp_utc") or ac.get("timestamp_local") or feed.get("last_updated", ""),
        }

        node = {
            "tail": tail,
            "status": status,
            "distance_miles": ac.get("dist_miles") or 0,
            "altitude": ac.get("alt_ft"),
            "ground_speed": ac.get("speed_kts"),
        }

        if status == "AT_BASE" and base_id:
            assignments[base_id]["aircraft"].append(node)
        else:
            assignments["unassigned"].append(node)

    return {
        "source": feed.get("source", "trootrax"),
        "last_updated": feed.get("last_updated", ""),
        "bases": BASES,
        "assignments": assignments,
        "aircraft_detail": aircraft_detail,
    }


def main():
    username = os.environ["TROOTRAX_USER"]
    password = os.environ["TROOTRAX_PASS"]
    customer_id = os.environ.get("TROOTRAX_CUSTOMER_ID", DEFAULT_CUSTOMER_ID)

    session = requests.Session()
    assets = login_and_fetch(session, username, password, customer_id)
    feed = build_feed(assets)
    base_assignments_payload = build_base_assignments(feed)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(feed, indent=2), encoding="utf-8")
    BASE_ASSIGNMENTS_OUTPUT_PATH.write_text(json.dumps(base_assignments_payload, indent=2), encoding="utf-8")

    print(f"Wrote {len(feed['aircraft'])} aircraft to {OUTPUT_PATH}")
    print(f"Wrote base assignment payload to {BASE_ASSIGNMENTS_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
