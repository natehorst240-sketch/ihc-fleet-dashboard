import json
import os

import requests

USERNAME = os.environ.get("TROOTRAX_USER", "")
PASSWORD = os.environ.get("TROOTRAX_PASS", "")
CUSTOMER_ID = os.environ.get("TROOTRAX_CUSTOMER_ID", "312")

if not USERNAME or not PASSWORD:
    raise RuntimeError("TROOTRAX_USER and TROOTRAX_PASS environment variables must be set.")

session = requests.Session()

# Step 1: Login
login_url = "https://apps4.trootrax.com/emstracker/login.php"
login_data = {
    "login": USERNAME,
    "passwd": PASSWORD,
    "passwd_type": "text",
    "submitit": "Login",
}
session.post(login_url, data=login_data)

# Step 2: Grab the cookies we need
# _tsvce and _tcum are scoped to .trootrax.com / so they reach the REST API
# sessionid is scoped to /emstracker/login only — we re-add it at root path
sessionid = next(
    (v for k, v in session.cookies.items() if k.lower() == "sessionid"),
    None,
)
tcum = session.cookies.("_tcum")
tsvce = session.cookies.("_tsvce")

if not sessionid:
    cookie_keys = list(session.cookies.keys())
    raise RuntimeError(
        f"Login failed - could not retrieve session ID. "
        f"Cookies returned: {cookie_keys}"
    )

print(f"Logged in. sessionid: {sessionid[:8]}... | _tsvce: {str(tsvce)[:12]}...")

# Step 3: Fix sessionid path so it reaches /rest/...
session.cookies.set("sessionid", sessionid, domain="apps4.trootrax.com", path="/")

# Step 4: Fetch all aircraft locations
url = "https://apps4.trootrax.com/rest/v2.0/assets/locations"
params = {
    "customer_id": "312",
    "session_id": sessionid,
    "app": "weathermap",
    "tail": "true",
    "trip_plan": "true",
}
response = session.get(url, params=params)  # <-- session.get, not requests.get
response = session.get(url, params=params)
print(f"API status: {response.status_code}")
print(f"Response text: {response.text[:500]}")  # see what came back
data = response.json()

# Step 5: Build output JSON
locations = []
for aircraft in data["assets"]:
    tail = aircraft.get("_tail") or []
    latest = tail[0] if tail else {}
    locations.append(
        {
            "vin": aircraft.get("vin"),
            "asset_id": aircraft.get("id"),
            "state": aircraft.get("_state"),
            "speed": aircraft.get("speed"),
            "latitude": latest.get("latitude"),
            "longitude": latest.get("longitude"),
            "heading": latest.get("heading"),
            "altitude": latest.get("altitude"),
            "odometer": latest.get("odometer"),
            "last_ping": latest.get("timestamp"),
        }
    )

# Step 6: Write to data/aircraft_locations.json
os.makedirs("data", exist_ok=True)
output_path = "data/aircraft_locations.json"
with open(output_path, "w") as f:
    json.dump(locations, f, indent=2)

print(f"Wrote {len(locations)} aircraft to {output_path}")

# Step 7: Print table
print(f"\n{'Tail':<12} {'State':<8} {'Speed':<8} {'Latitude':<14} {'Longitude':<14} {'Last Ping'}")
print("-" * 80)
for a in locations:
    print(
        f"{a['vin']:<12} {str(a['state']):<8} {str(a['speed']):<8} "
        f"{str(a['latitude']):<14} {str(a['longitude']):<14} {a['last_ping']}"
    )
