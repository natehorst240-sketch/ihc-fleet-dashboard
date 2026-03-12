import requests
import os
import json

USERNAME = os.environ.get(“TROOTRAX_USER”, “”)
PASSWORD = os.environ.get(“TROOTRAX_PASS”, “”)
CUSTOMER_ID = os.environ.get(“TROOTRAX_CUSTOMER_ID”, “312”)

if not USERNAME or not PASSWORD:
raise RuntimeError(“TROOTRAX_USER and TROOTRAX_PASS environment variables must be set.”)

session = requests.Session()

# Step 1: Login

login_url = “https://apps4.trootrax.com/emstracker/login.php”
login_data = {
“login”: USERNAME,
“passwd”: PASSWORD,
“passwd_type”: “text”,
“submitit”: “Login”
}
session.post(login_url, data=login_data)

# Step 2: Get sessionid cookie and re-add it with path=/ so it reaches the REST API

sessionid = session.cookies.get(“sessionid”)
if not sessionid:
raise RuntimeError(“Login failed — could not retrieve session ID.”)

# The cookie is scoped to /emstracker/login by default — force it to root path

session.cookies.set(“sessionid”, sessionid, domain=“apps4.trootrax.com”, path=”/”)
session.cookies.set(“Sessionid”, sessionid, domain=“apps4.trootrax.com”, path=”/”)

print(f”Logged in successfully. Session ID: {sessionid[:8]}…”)

# Step 3: Fetch all aircraft locations

url = “https://apps4.trootrax.com/rest/v2.0/assets/locations”
params = {
“customer_id”: CUSTOMER_ID,
“app”: “weathermap”,
“tail”: “true”,
“trip_plan”: “true”,
}

response = session.get(url, params=params)
data = response.json()

if “assets” not in data:
raise RuntimeError(f”Unexpected API response: {data}”)

# Step 4: Build output JSON

locations = []
for aircraft in data[“assets”]:
tail = aircraft.get(”_tail”) or []
latest = tail[0] if tail else {}
locations.append({
“vin”: aircraft.get(“vin”),
“asset_id”: aircraft.get(“id”),
“state”: aircraft.get(”_state”),
“speed”: aircraft.get(“speed”),
“latitude”: latest.get(“latitude”),
“longitude”: latest.get(“longitude”),
“heading”: latest.get(“heading”),
“altitude”: latest.get(“altitude”),
“odometer”: latest.get(“odometer”),
“last_ping”: latest.get(“timestamp”),
})

# Step 5: Write to data/aircraft_locations.json

os.makedirs(“data”, exist_ok=True)
output_path = “data/aircraft_locations.json”
with open(output_path, “w”) as f:
json.dump(locations, f, indent=2)

print(f”Wrote {len(locations)} aircraft to {output_path}”)

# Step 6: Print table to console

print(f”\n{‘Tail’:<12} {‘State’:<8} {‘Speed’:<8} {‘Latitude’:<14} {‘Longitude’:<14} {‘Last Ping’}”)
print(”-” * 80)
for a in locations:
print(f”{a[‘vin’]:<12} {str(a[‘state’]):<8} {str(a[‘speed’]):<8} “
f”{str(a[‘latitude’]):<14} {str(a[‘longitude’]):<14} {a[‘last_ping’]}”)