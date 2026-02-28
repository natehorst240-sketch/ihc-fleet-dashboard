"""
Base Assignment System with ADSB.lol Integration
===============================================
Automatically assigns aircraft to bases based on ADSB.lol position data.
Generates JSON for the dashboard's "Bases" tab.
"""

import json
import math
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple

import requests

# ── CONFIGURATION ─────────────────────────────────────────────────────────────

ONEDRIVE_FOLDER = r"C:\Users\nateh\Documents\ihc-fleet-dashboard\data"

OUTPUT_FOLDER = "data"
BASE_ASSIGNMENTS_FILE = "base_assignments.json"

ADSBLOL_BASE_URL = "https://api.adsb.lol"
REQUEST_TIMEOUT_SEC = 15
USER_AGENT = "407-Fleet-Tracker/1.0 (base-assignments)"

AIRCRAFT_MAPPING_FILE = "aircraft_icao_map.json"

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

# How many seconds old an ADSB position can be before we consider it stale
MAX_SEEN_AGE_SECONDS = 300  # 5 minutes

# ── HELPERS ───────────────────────────────────────────────────────────────────

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3959.0
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    )
    c = 2 * math.asin(math.sqrt(a))
    return R * c


def load_previous_output(assignments_path: Path) -> Optional[Dict[str, Any]]:
    """Load the entire previous output file so we can preserve it when needed."""
    if not assignments_path.exists():
        return None
    try:
        with open(assignments_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ── ADSB.lol INTEGRATION ──────────────────────────────────────────────────────

def _requests_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return s


def fetch_adsblol_by_icao(session: requests.Session, icao_hex: str) -> Optional[Dict[str, Any]]:
    icao_hex = icao_hex.strip().lower()
    candidate_urls = [
        f"{ADSBLOL_BASE_URL}/v2/icao/{icao_hex}",
        f"{ADSBLOL_BASE_URL}/api/v2/icao/{icao_hex}",
        f"{ADSBLOL_BASE_URL}/api/icao/{icao_hex}",
    ]
    for url in candidate_urls:
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT_SEC)
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception:
            continue
    return None


def normalize_adsblol_aircraft(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return None

    # Direct lat/lon
    if "lat" in payload and "lon" in payload:
        return {
            "latitude": payload.get("lat"),
            "longitude": payload.get("lon"),
            "seen": payload.get("seen"),
            "altitude": payload.get("alt_baro") or payload.get("altitude"),
            "ground_speed": payload.get("gs") or payload.get("ground_speed"),
            "track": payload.get("track"),
        }

    # Nested single aircraft dict
    if "aircraft" in payload and isinstance(payload["aircraft"], dict):
        ac = payload["aircraft"]
        if "lat" in ac and "lon" in ac:
            return {
                "latitude": ac.get("lat"),
                "longitude": ac.get("lon"),
                "seen": ac.get("seen"),
                "altitude": ac.get("alt_baro") or ac.get("altitude"),
                "ground_speed": ac.get("gs") or ac.get("ground_speed"),
                "track": ac.get("track"),
            }

    # List under "aircraft" or "ac" key
    for key in ("aircraft", "ac"):
        if key in payload and isinstance(payload[key], list) and payload[key]:
            ac0 = payload[key][0]
            if isinstance(ac0, dict) and "lat" in ac0 and "lon" in ac0:
                return {
                    "latitude": ac0.get("lat"),
                    "longitude": ac0.get("lon"),
                    "seen": ac0.get("seen"),
                    "altitude": ac0.get("alt_baro") or ac0.get("altitude"),
                    "ground_speed": ac0.get("gs") or ac0.get("ground_speed"),
                    "track": ac0.get("track"),
                }

    return None


def normalize_aircraft_mapping(raw_mapping: Any) -> Dict[str, Dict[str, str]]:
    normalized: Dict[str, Dict[str, str]] = {}
    if isinstance(raw_mapping, dict):
        for tail, value in raw_mapping.items():
            tail_key = str(tail).strip().upper()
            if not tail_key:
                continue
            if isinstance(value, str):
                icao = value.strip().upper()
            elif isinstance(value, dict):
                icao = str(value.get("icao") or "").strip().upper()
            else:
                icao = ""
            if icao:
                normalized[tail_key] = {"icao": icao}
    elif isinstance(raw_mapping, list):
        for entry in raw_mapping:
            if not isinstance(entry, dict):
                continue
            tail_key = str(entry.get("tail") or "").strip().upper()
            icao = str(entry.get("icao") or "").strip().upper()
            if tail_key and icao:
                normalized[tail_key] = {"icao": icao}
    return normalized


def load_aircraft_mapping(base_folder: Path) -> Tuple[Dict[str, Dict[str, str]], str]:
    mapping_path = base_folder / AIRCRAFT_MAPPING_FILE
    if mapping_path.exists():
        try:
            with open(mapping_path, "r", encoding="utf-8") as f:
                file_mapping = json.load(f)
            normalized = normalize_aircraft_mapping(file_mapping)
            if normalized:
                return normalized, f"file:{mapping_path}"
        except Exception:
            pass
    return normalize_aircraft_mapping(DEFAULT_AIRCRAFT), "embedded DEFAULT_AIRCRAFT"


def load_adsblol_status(aircraft_mapping: Dict[str, Dict[str, str]]) -> Dict[str, Dict[str, Any]]:
    status: Dict[str, Dict[str, Any]] = {}
    session = _requests_session()
    for tail, info in aircraft_mapping.items():
        icao_hex = (info.get("icao") or "").strip()
        if not icao_hex:
            continue
        payload = fetch_adsblol_by_icao(session, icao_hex)
        if not payload:
            continue
        norm = normalize_adsblol_aircraft(payload)
        if not norm:
            continue
        # Skip stale positions
        seen = norm.get("seen")
        if seen is not None and seen > MAX_SEEN_AGE_SECONDS:
            continue
        status[tail] = norm
    return status


# ── BASE ASSIGNMENT LOGIC ─────────────────────────────────────────────────────

def find_base_for_aircraft(aircraft_data: Dict[str, Any]) -> Tuple[Optional[str], Optional[float], bool]:
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


def assign_aircraft_to_bases(aircraft_status: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    assignments: Dict[str, Any] = {
        base_id: {"aircraft": [], "status": "available"} for base_id in BASES.keys()
    }
    assignments["unassigned"] = []

    for tail, aircraft_data in aircraft_status.items():
        base_id, distance, at_base = find_base_for_aircraft(aircraft_data)

        alt = aircraft_data.get("altitude")
        gs  = aircraft_data.get("ground_speed")

        # Determine if airborne: altitude > 400ft AGL or groundspeed > 30kts
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
            "tail": tail,
            "hours": None,
            "at_base": at_base and not is_airborne,
            "airborne": is_airborne,
            "seen_seconds_ago": aircraft_data.get("seen"),
            "altitude": alt,
            "ground_speed": gs,
            "track": aircraft_data.get("track"),
            "distance_miles": round(float(distance), 2) if distance is not None else None,
            "closest_base": BASES[base_id]["name"] if base_id else None,
        }

        if is_airborne:
            # Airborne: put in unassigned with airborne flag
            assignments["unassigned"].append(entry)
        elif at_base and base_id:
            assignments[base_id]["aircraft"].append(entry)
            assignments[base_id]["status"] = "occupied"
        else:
            assignments["unassigned"].append(entry)

    return assignments


# ── MAIN ──────────────────────────────────────────────────────────────────────

def generate_base_assignments() -> bool:
    base_folder = Path(ONEDRIVE_FOLDER)
    assignments_path = base_folder / BASE_ASSIGNMENTS_FILE
    log_path = base_folder / "base_assignment_log.txt"

    def log(msg: str) -> None:
        timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
        line = f"[{timestamp}] {msg}"
        print(line)
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    try:
        log("Base assignment generation started (ADSB.lol)")

        aircraft_mapping, mapping_source = load_aircraft_mapping(base_folder)
        if not aircraft_mapping:
            log("ERROR: AIRCRAFT mapping is empty.")
            return False

        log(f"Loaded {len(aircraft_mapping)} aircraft ICAO mappings from {mapping_source}")

        log("Loading ADSB.lol positions...")
        aircraft_status = load_adsblol_status(aircraft_mapping)

        if not aircraft_status:
            # ── KEY FIX: No live data → preserve previous file completely ──
            log("WARNING: No live ADSB.lol data available. Preserving previous assignments.")
            previous = load_previous_output(assignments_path)
            if previous:
                # Just update the last_updated timestamp so dashboard knows we ran
                previous["last_checked"] = datetime.now(timezone.utc).isoformat()
                previous["live_data"] = False
                with open(assignments_path, "w", encoding="utf-8") as f:
                    json.dump(previous, f, indent=2)
                log("Previous assignments preserved.")
            else:
                log("No previous assignments to preserve (first run with no data).")
                # Write an empty-but-valid file
                empty = {
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                    "last_checked": datetime.now(timezone.utc).isoformat(),
                    "live_data": False,
                    "source": "adsb.lol",
                    "bases": BASES,
                    "assignments": {
                        **{base_id: {"aircraft": [], "status": "available"} for base_id in BASES},
                        "unassigned": []
                    },
                    "summary": {"total_aircraft": 0, "at_bases": 0, "away_from_base": 0},
                }
                with open(assignments_path, "w", encoding="utf-8") as f:
                    json.dump(empty, f, indent=2)
            log("Base assignment generation completed (no live data).")
            return True

        log(f"Loaded position data for {len(aircraft_status)} aircraft")

        log("Calculating base assignments...")
        assignments = assign_aircraft_to_bases(aircraft_status)

        at_bases_count = sum(
            len(a["aircraft"]) for k, a in assignments.items() if k != "unassigned"
        )
        unassigned_count = len(assignments["unassigned"])
        airborne_count   = sum(1 for a in assignments["unassigned"] if a.get("airborne"))

        output_data = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "last_checked": datetime.now(timezone.utc).isoformat(),
            "live_data": True,
            "source": "adsb.lol",
            "bases": BASES,
            "assignments": assignments,
            "summary": {
                "total_aircraft": len(aircraft_status),
                "at_bases": at_bases_count,
                "away_from_base": unassigned_count - airborne_count,
                "airborne": airborne_count,
            },
        }

        with open(assignments_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2)

        log(f"Base assignments saved to {assignments_path}")
        for base_id, data in assignments.items():
            if base_id == "unassigned":
                log(f"  Unassigned/Airborne: {len(data)} aircraft")
                for a in data:
                    status_str = "AIRBORNE" if a.get("airborne") else "AWAY"
                    log(f"    {a['tail']} — {status_str} | alt:{a.get('altitude')} gs:{a.get('ground_speed')} | closest: {a.get('closest_base')} {a.get('distance_miles')} mi")
            else:
                count = len(data["aircraft"])
                log(f"  {BASES[base_id]['name']}: {count} aircraft")
                for a in data["aircraft"]:
                    log(f"    {a['tail']} — {a.get('distance_miles')} mi from base")

        log("Base assignment generation completed successfully")
        return True

    except Exception as e:
        log(f"ERROR: {e}")
        import traceback
        log(traceback.format_exc())
        return False


if __name__ == "__main__":
    generate_base_assignments()
