import requests
import os

USERNAME = os.environ["TROOTRAX_USER"]
PASSWORD = os.environ["TROOTRAX_PASS"]

session = requests.Session()

# Step 1: Login
login_url = "https://apps4.trootrax.com/emstracker/login/main.php"
login_data = {
    "login": USERNAME,
    "passwd": PASSWORD,
    "passwd_type": "text",
    "submitit": "Login"
}
session.post(login_url, data=login_data)

# Step 2: Verify session
sessionid = session.cookies.get("Sessionid")
if not sessionid:
    print("Login failed — could not retrieve session ID.")
    exit(1)

print(f"Logged in. Session ID: {sessionid[:8]}...")

# Step 3: Fetch all aircraft
url = "https://apps4.trootrax.com/rest/v2.0/assets/locations"
params = {
    "customer_id": "312",
    "app": "weathermap",
    "tail": "true",
    "trip_plan": "true",
}

response = session.get(url, params=params)
data = response.json()

if "assets" not in data:
    print("Unexpected API response:", data)
    exit(1)

print(f"\n{'Tail':<12} {'State':<12} {'Speed':<8} {'Latitude':<14} {'Longitude':<14} {'Last Ping'}")
print("-" * 80)
for aircraft in data["assets"]:
    tail = aircraft.get("_tail") or []
    latest = tail[0] if tail else {}
    print(f"{aircraft['vin']:<12} {aircraft['_state']:<12} {aircraft['speed']:<8} "
          f"{str(latest.get('latitude', 'N/A')):<14} {str(latest.get('longitude', 'N/A')):<14} "
          f"{latest.get('timestamp', 'N/A')}")
