"""
Base Assignment System with ADSB.lol + Airplanes.live Integration
=================================================================
Primary source: airplanes.live (free, no key required)
Fallback source: adsb.lol
"""

import json
import math
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any

import requests

# ── CONFIGURATION ─────────────────────────────────────────────────────────────

if os.getenv("GITHUB_ACTIONS"):
    OUTPUT_FOLDER = Path("data")
else:
    OUTPUT_FOLDER = Path(r"C:\Users\nateh\Documents\ihc-fleet-dashboard\data")

BASE_ASSIGNMENTS_FILE = "base_assignments.json"

AIRPLANESLIVE_BASE_URL = "https://api.airplanes.live/v2"
ADSBLOL_BASE_URL = "https://api.adsb.lol"
REQUEST_TIMEOUT_SEC = 15
USER_AGENT = "IHC-Fleet-Dashboard/1.0 (base-assignments)"

DEFAULT_AIRCRAFT: Dict[str, Dict[str, str]] = {
    "N251HC": {"icao": "A25BE7"},
    "N261HC": {"icao": "A28366"},
    "N271HC": {"icao": "A2AAE5"},
    "N281HC": {"icao": "A2D264"},
    "N291HC": {"icao": "A2F9E3"},
    "N431HC": {"icao": "A52787"},
    "N531HC": {"icao": "A6B4D6"},
    "N631HC": {"icao": "A84225"},
    "N731HC": {"icao": "A9CF74"},
}

BASES = {
    "LOGAN":      {"name": "Logan",      "lat": 41.7912, "lon": -111.8522, "radius_miles": 5},
    "MCKAY":      {"name": "McKay",      "lat": 41.2545, "lon": -112.0126, "radius_miles": 5},
    "IMED":       {"name": "IMed",       "lat": 40.2338, "lon": -111.6585, "radius_miles": 5},
    "PROVO":      {"name": "Provo",      "lat": 40.2192, "lon": -111.7233, "radius_miles": 5},
    "ROOSEVELT":  {"name": "Roosevelt",  "lat": 40.2765, "lon": -110.0518, "radius_miles": 5},
    "CEDAR_CITY": {"name": "Cedar City", "lat": 37.7010, "lon": -113.0989, "radius_miles": 5},
    "ST_GEORGE":  {"name": "St George",  "lat": 37.0365, "lon": -113.5101, "radius_miles": 5},
    "KSLC":       {"name": "KSLC",       "lat": 40.7884, "lon": -111.9778, "radius_miles": 10},
}

MAX_SEEN_AGE_SECONDS = 300

# ── HELPERS ───────────────────────────────────────────────────────────────────

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 3959.0
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    a = (math.sin(delta_lat / 2) ** 2
         + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def load_previous_output(assignments_path):
    if not assignments_path.exists():
        return None
    try:
        with open(assignments_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ── ADS-B FETCH ───────────────────────────────────────────────────────────────

def _requests_session():
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return s


def fetch_aircraft_by_icao(session, icao_hex):
    icao_hex = icao_hex.strip().lower()
    urls = [
        f"{AIRPLANESLIVE_BASE_URL}/icao/{icao_hex}",
        f"{ADSBLOL_BASE_URL}/v2/icao/{icao_hex}",
        f"{ADSBLOL_BASE_URL}/api/v2/icao/{icao_hex}",
        f"{ADSBLOL_BASE_URL}/api/icao/{icao_hex}",
    ]
    for url in urls:
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT_SEC)
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception:
            continue
    return None


def normalize_aircraft_payload(payload):
    if not isinstance(payload, dict):
        return None

    # ADSBExchange/airplanes.live v2 format: {"ac": [{...}]}
    for key in ("ac", "aircraft"):
        if key in payload and isinstance(payload[key], list) and payload[key]:
            ac0 = payload[key][0]
            if isinstance(ac0, dict) and "lat" in ac0 and "lon" in ac0:
                return {
                    "latitude":     ac0.get("lat"),
                    "longitude":    ac0.get("lon"),
                    "seen":         ac0.get("seen"),
                    "altitude":     ac0.get("alt_baro") or ac0.get("altitude"),
                    "ground_speed": ac0.get("gs") or ac0.get("ground_speed"),
                    "track":        ac0.get("track"),
                }

    # Flat format
    if "lat" in payload and "lon" in payload:
        return {
            "latitude":     payload.get("lat"),
            "longitude":    payload.get("lon"),
            "seen":         payload.get("seen"),
            "altitude":     payload.get("alt_baro") or payload.get("altitude"),
            "ground_speed": payload.get("gs") or payload.get("ground_speed"),
            "track":        payload.get("track"),
        }

    # Nested aircraft dict
    if "aircraft" in payload and isinstance(payload["aircraft"], dict):
        ac = payload["aircraft"]
        if "lat" in ac and "lon" in ac:
            return {
                "latitude":     ac.get("lat"),
                "longitude":    ac.get("lon"),
                "seen":         ac.get("seen"),
                "altitude":     ac.get("alt_baro") or ac.get("altitude"),
                "ground_speed": ac.get("gs") or ac.get("ground_speed"),
                "track":        ac.get("track"),
            }

    return None


def load_aircraft_status(aircraft_mapping):
    status = {}
    session = _requests_session()
    for tail, info in aircraft_mapping.items():
        icao_hex = (info.get("icao") or "").strip()
        if not icao_hex:
            continue
        payload = fetch_aircraft_by_icao(session, icao_hex)
        if not payload:
            continue
        norm = normalize_aircraft_payload(payload)
        if not norm:
            continue
        seen = norm.get("seen")
        if seen is not None and seen > MAX_SEEN_AGE_SECONDS:
            continue
        status[tail] = norm
    return status


# ── BASE ASSIGNMENT LOGIC ─────────────────────────────────────────────────────

def find_base_for_aircraft(aircraft_data):
    if aircraft_data.get("latitude") is None or aircraft_data.get("longitude") is None:
        return None, None, False
    lat = float(aircraft_data["latitude"])
    lon = float(aircraft_data["longitude"])
    closest_base = None
    closest_distance = float("inf")
    for base_id, base_info in BASES.items():
        distance = haversine_distance(lat, lon, base_info["lat"], base_info["lon"])
        if distance < closest_distance:
            closest_distance = distance
            closest_base = base_id
    if closest_base and closest_distance <= BASES[closest_base]["radius_miles"]:
        return closest_base, closest_distance, True
    return closest_base, closest_distance, False


def assign_aircraft_to_bases(aircraft_status):
    assignments = {base_id: {"aircraft": [], "status": "available"} for base_id in BASES}
    assignments["unassigned"] = []

    for tail, aircraft_data in aircraft_status.items():
        base_id, distance, at_base = find_base_for_aircraft(aircraft_data)
        alt = aircraft_data.get("altitude")
        gs  = aircraft_data.get("ground_speed")

        is_airborne = False
        if alt is not None:
            try:
                is_airborne = float(alt) > 400
            except (ValueError, TypeError):
                pass
        if not is_airborne and gs is not None:
            try:
                is_airborne = float(gs) > 30
            except (ValueError, TypeError):
                pass

        entry = {
            "tail":             tail,
            "hours":            None,
            "at_base":          at_base and not is_airborne,
            "airborne":         is_airborne,
            "seen_seconds_ago": aircraft_data.get("seen"),
            "altitude":         alt,
            "ground_speed":     gs,
            "track":            aircraft_data.get("track"),
            "distance_miles":   round(float(distance), 2) if distance is not None else None,
            "closest_base":     BASES[base_id]["name"] if base_id else None,
        }

        if is_airborne:
            assignments["unassigned"].append(entry)
        elif at_base and base_id:
            assignments[base_id]["aircraft"].append(entry)
            assignments[base_id]["status"] = "occupied"
        else:
            assignments["unassigned"].append(entry)

    return assignments


# ── MAIN ──────────────────────────────────────────────────────────────────────

def generate_base_assignments():
    assignments_path = OUTPUT_FOLDER / BASE_ASSIGNMENTS_FILE
    log_path = OUTPUT_FOLDER / "base_assignment_log.txt"

    def log(msg):
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        line = f"[{ts}] {msg}"
        print(line)
        if not os.getenv("GITHUB_ACTIONS"):
            try:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception:
                pass

    try:
        log("Base assignment generation started (airplanes.live + adsb.lol fallback)")
        log(f"Loaded {len(DEFAULT_AIRCRAFT)} aircraft from DEFAULT_AIRCRAFT")

        log("Fetching positions...")
        aircraft_status = load_aircraft_status(DEFAULT_AIRCRAFT)

        if not aircraft_status:
            log("WARNING: No live data from any source. Writing default structure.")
            previous = load_previous_output(assignments_path)
            if not previous:
                previous = {
                    "assignments": {base_id: {"aircraft": [], "status": "available"} for base_id in BASES},
                    "bases": BASES,
                    "summary": {"total_aircraft": 0, "at_bases": 0, "away_from_base": 0, "airborne": 0},
                    "source": "none",
                    "live_data": False,
                }
            previous["last_checked"] = datetime.now(timezone.utc).isoformat()
            previous["live_data"] = False
            OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
            with open(assignments_path, "w", encoding="utf-8") as f:
                json.dump(previous, f, indent=2)
            return True

        log(f"Got positions for {len(aircraft_status)} aircraft")
        assignments = assign_aircraft_to_bases(aircraft_status)

        at_bases_count = sum(len(a["aircraft"]) for k, a in assignments.items() if k != "unassigned")
        airborne_count = sum(1 for a in assignments["unassigned"] if a.get("airborne"))
        away_count     = len(assignments["unassigned"]) - airborne_count

        output_data = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "last_checked": datetime.now(timezone.utc).isoformat(),
            "live_data":    True,
            "source":       "airplanes.live",
            "bases":        BASES,
            "assignments":  assignments,
            "summary": {
                "total_aircraft": len(aircraft_status),
                "at_bases":       at_bases_count,
                "away_from_base": away_count,
                "airborne":       airborne_count,
            },
        }

        OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
        with open(assignments_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2)

        log(f"Saved to {assignments_path}")
        for base_id, data in assignments.items():
            if base_id == "unassigned":
                for a in data:
                    status_str = "AIRBORNE" if a.get("airborne") else "AWAY"
                    log(f"  {a['tail']} — {status_str} | alt:{a.get('altitude','')} gs:{a.get('ground_speed','')} | closest: {a.get('closest_base','?')} {a.get('distance_miles','?')} mi")
            else:
                count = len(data["aircraft"])
                if count:
                    log(f"  {BASES[base_id]['name']}: {count} aircraft")
        log("Base assignment generation completed successfully")
        return True

    except Exception as e:
        log(f"ERROR: {e}")
        import traceback
        log(traceback.format_exc())
        return False


if __name__ == "__main__":
    generate_base_assignments()
