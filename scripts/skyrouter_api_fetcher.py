"""
SkyRouter API Data Fetcher
==========================
Fetches aircraft position data using the SkyRouter Data Exchange API and saves
a status JSON file used by the dashboard.

Environment variables required:
  - SKYROUTER_USER
  - SKYROUTER_PASS
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import requests


# ── CONFIG ──────────────────────────────────────────────────────────────────

# Credentials (from GitHub Actions env)
SKYROUTER_USER = os.getenv("SKYROUTER_USER")
SKYROUTER_PASS = os.getenv("SKYROUTER_PASS")

if not SKYROUTER_USER or not SKYROUTER_PASS:
    raise RuntimeError("Missing SKYROUTER_USER or SKYROUTER_PASS env vars")

# Base API URL (confirm your endpoint; some installations may require a more specific path)
SKYROUTER_API_BASE = "https://new.skyrouter.com/Bsn.Skyrouter.DataExchange/"

# Output
OUTPUT_FOLDER = Path("data")
OUTPUT_FILENAME = "skyrouter_status.json"

# Base location (update for your real base)
BASE_LAT = 40.7884
BASE_LON = -111.7233
BASE_RADIUS_MILES = 5.0  # "at base" if within this radius

# How far back to consider positions (only used if you switch to SinceUTC option)
LOOKBACK_HOURS = 6

# Request config
HTTP_TIMEOUT_SECS = 30


# ── HELPERS ────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    """Print and append to scripts/skyrouter_api_log.txt."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)

    try:
        log_path = Path(__file__).with_name("skyrouter_api_log.txt")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        # Logging should never crash the run
        pass


def haversine_distance_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in miles between two lat/lon points."""
    r = 3959.0  # Earth radius in miles
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = (math.sin(dlat / 2) ** 2) + math.cos(lat1_rad) * math.cos(lat2_rad) * (math.sin(dlon / 2) ** 2)
    c = 2 * math.asin(math.sqrt(a))
    return r * c


def parse_skyrouter_csv_record(record: str) -> Optional[Dict[str, Any]]:
    """
    Parse one CSV record line from SkyRouter FlightTracking.

    Expected fields (0-based indexing shown):
      2  -> report type
      6  -> registration (tail)
      7  -> date (YYYYMMDD)
      8  -> time (HHMMSS)
      9  -> latitude (decimal)
      10 -> longitude (decimal)
      11 -> altitude
      12 -> velocity
      13 -> heading
    """
    fields = [f.strip() for f in record.split(",")]
    if len(fields) < 14:
        return None

    try:
        report_type = fields[2]
        registration = fields[6]

        lat_str = fields[9]
        lon_str = fields[10]
        if not registration or not lat_str or not lon_str:
            return None

        latitude = float(lat_str)
        longitude = float(lon_str)

        date_str = fields[7]  # YYYYMMDD
        time_str = fields[8]  # HHMMSS

        return {
            "registration": registration,
            "report_type": report_type,
            "latitude": latitude,
            "longitude": longitude,
            "altitude": fields[11] if len(fields) > 11 else "",
            "velocity": fields[12] if len(fields) > 12 else "",
            "heading": fields[13] if len(fields) > 13 else "",
            "date": date_str,
            "time": time_str,
        }
    except Exception as e:
        log(f"Parse error: {e} (record={record[:120]!r})")
        return None


def build_api_url_everything_since_last_request() -> str:
    # Example per your current approach
    return (
        f"{SKYROUTER_API_BASE}"
        f"?username={SKYROUTER_USER}&password={SKYROUTER_PASS}"
        f"&datatype=FlightTracking&option=EverythingSinceLastRequest"
    )


def build_api_url_since_utc() -> str:
    # Optional alternative if you prefer a time window:
    now = datetime.utcnow()
    from_time = now - timedelta(hours=LOOKBACK_HOURS)
    from_time_str = from_time.strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"{SKYROUTER_API_BASE}"
        f"?username={SKYROUTER_USER}&password={SKYROUTER_PASS}"
        f"&datatype=FlightTracking&option=SinceUTC&sinceutc={from_time_str}"
    )


def fetch_raw_flight_tracking() -> str:
    """
    Fetch raw response text. Raises on hard failures.
    """
    url = build_api_url_everything_since_last_request()
    # url = build_api_url_since_utc()  # <- switch if desired

    log(f"Requesting SkyRouter FlightTracking…")
    # Don't log full URL because it contains credentials.
    resp = requests.get(url, timeout=HTTP_TIMEOUT_SECS)
    resp.raise_for_status()

    text = resp.text or ""
    if not text.strip():
        raise RuntimeError("SkyRouter API returned empty response")

    # Common failure mode: HTML login page or error page
    head = text.lstrip()[:200].lower()
    if head.startswith("<!doctype html") or head.startswith("<html") or "login" in head[:200]:
        raise RuntimeError("SkyRouter API returned HTML (likely wrong endpoint or auth issue)")

    return text


def process_raw_to_status(raw_text: str) -> Dict[str, Any]:
    """
    Convert raw response into per-aircraft status dict.
    """
    aircraft: Dict[str, Dict[str, Any]] = {}

    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue

        pos = parse_skyrouter_csv_record(line)
        if not pos:
            continue

        tail = pos["registration"]

        # distance from base
        dist = haversine_distance_miles(BASE_LAT, BASE_LON, pos["latitude"], pos["longitude"])
        at_base = dist <= BASE_RADIUS_MILES

        report_type = str(pos["report_type"]).upper()
        status_map = {
            "POS": "ACTIVE",
            "QPS": "ACTIVE",
            "HBT": "ACTIVE",
            "BEA": "ACTIVE",
            "TOF": "TAKE-OFF",
            "LAN": "LANDING",
            "OGA": "DEPARTED",
            "IGA": "ARRIVED",
        }
        status = status_map.get(report_type, report_type)

        if at_base and report_type not in ("TOF", "OGA"):
            status = "AT BASE"

        # timestamp
        timestamp_str = f"{pos['date']} {pos['time']}"
        try:
            dt = datetime.strptime(timestamp_str, "%Y%m%d %H%M%S")
            iso_ts = dt.isoformat()
        except Exception:
            iso_ts = datetime.utcnow().isoformat()

        new_record = {
            "status": status,
            "at_base": at_base,
            "last_update": timestamp_str,
            "timestamp": iso_ts,
            "latitude": pos["latitude"],
            "longitude": pos["longitude"],
            "altitude": pos["altitude"],
            "velocity": pos["velocity"],
            "heading": pos["heading"],
            "distance_from_base": round(dist, 2),
        }

        # Keep newest per tail
        if tail not in aircraft:
            aircraft[tail] = new_record
        else:
            try:
                old_dt = datetime.fromisoformat(aircraft[tail]["timestamp"])
                new_dt = datetime.fromisoformat(iso_ts)
                if new_dt > old_dt:
                    aircraft[tail] = new_record
            except Exception:
                # If timestamps don't parse, just replace
                aircraft[tail] = new_record

    return aircraft


def fetch_and_save() -> None:
    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

    log("SkyRouter API fetch started")

    raw = fetch_raw_flight_tracking()
    log(f"Received {len(raw)} bytes")

    aircraft = process_raw_to_status(raw)
    log(f"Parsed {len(aircraft)} aircraft")

    out = {
        "last_updated": datetime.utcnow().isoformat(),
        "aircraft": aircraft,
    }

    output_path = OUTPUT_FOLDER / OUTPUT_FILENAME
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    at_base_count = sum(1 for a in aircraft.values() if a.get("at_base"))
    log(f"Saved {output_path} (at base: {at_base_count}, away: {len(aircraft) - at_base_count})")
    log("SkyRouter API fetch completed successfully")


def main() -> int:
    try:
        fetch_and_save()
        return 0
    except Exception as e:
        log(f"ERROR: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())