"""
Mock SkyRouter Data Generator
==============================
Creates fake position data for testing the dashboard
while waiting for real API access.

Run this instead of skyrouter_api_fetcher.py for testing.
"""

import json
import random
from datetime import datetime
from pathlib import Path

# ── CONFIGURATION ─────────────────────────────────────────────────────────────

OUTPUT_FOLDER = r"C:\Users\nateh\OneDrive - Intermountain Health\VeryonExports\Veryon Exports"
OUTPUT_FILENAME = "skyrouter_status.json"

# Your bases (for generating realistic test positions)
BASES = {
    "LOGAN": {"lat": 41.7912, "lon": -111.8522},
    "MCKAY": {"lat": 41.2545, "lon": -112.0126},
    "IMED": {"lat": 40.2338, "lon": -111.6585},
    "PROVO": {"lat": 40.2192, "lon": -111.7233},
    "ROOSEVELT": {"lat": 40.2765, "lon": -110.0518},
    "CEDAR_CITY": {"lat": 37.7010, "lon": -113.0989},
    "ST_GEORGE": {"lat": 37.0365, "lon": -113.5101},
    "KSLC": {"lat": 40.7884, "lon": -111.9778}
}

# Your fleet
AIRCRAFT = [
    {"tail": "N291HC", "hours": 3068.9},
    {"tail": "N281HC", "hours": 5682.7},
    {"tail": "N271HC", "hours": 1943.1},
    {"tail": "N261HC", "hours": 6480.5},
    {"tail": "N251HC", "hours": 6849.7},
    {"tail": "N731HC", "hours": 1093.1},
    {"tail": "N271HC", "hours": 51.5},
    {"tail": "N281HC", "hours": 9405.8},
    {"tail": "N291HC", "hours": 9407.4}
]

# ── MOCK DATA GENERATOR ───────────────────────────────────────────────────────

def generate_mock_data():
    """Generate realistic mock SkyRouter position data."""
    
    mock_data = {
        "last_updated": datetime.now().isoformat(),
        "aircraft": {}
    }
    
    base_list = list(BASES.keys())
    
    for aircraft in AIRCRAFT:
        tail = aircraft['tail']
        
        # Randomly decide if at base or away
        scenario = random.choice(['at_base', 'at_base', 'at_base', 'in_flight', 'at_other_location'])
        
        if scenario == 'at_base':
            # Place at one of the bases (within radius)
            base_id = random.choice(base_list)
            base = BASES[base_id]
            
            # Add small random offset to place within ~2 miles of base
            lat_offset = random.uniform(-0.02, 0.02)  # ~1-2 miles
            lon_offset = random.uniform(-0.02, 0.02)
            
            mock_data['aircraft'][tail] = {
                "status": "AT BASE",
                "at_base": True,
                "last_update": datetime.now().strftime("%Y%m%d %H%M%S"),
                "timestamp": datetime.now().isoformat(),
                "latitude": base['lat'] + lat_offset,
                "longitude": base['lon'] + lon_offset,
                "altitude": "0",
                "velocity": "0",
                "heading": "0",
                "distance_from_base": round(random.uniform(0.5, 2.5), 2),
                "current_hours": aircraft['hours']
            }
        
        elif scenario == 'in_flight':
            # Place somewhere random in Utah
            mock_data['aircraft'][tail] = {
                "status": "ACTIVE",
                "at_base": False,
                "last_update": datetime.now().strftime("%Y%m%d %H%M%S"),
                "timestamp": datetime.now().isoformat(),
                "latitude": random.uniform(37.0, 42.0),  # Utah latitude range
                "longitude": random.uniform(-114.0, -109.0),  # Utah longitude range
                "altitude": str(random.randint(3000, 8000)),
                "velocity": str(random.randint(100, 140)),
                "heading": str(random.randint(0, 359)),
                "distance_from_base": round(random.uniform(30, 150), 2),
                "current_hours": aircraft['hours']
            }
        
        else:  # at_other_location
            # Place far from any base
            mock_data['aircraft'][tail] = {
                "status": "AWAY",
                "at_base": False,
                "last_update": datetime.now().strftime("%Y%m%d %H%M%S"),
                "timestamp": datetime.now().isoformat(),
                "latitude": random.uniform(38.0, 41.0),
                "longitude": random.uniform(-112.5, -110.5),
                "altitude": "0",
                "velocity": "0",
                "heading": "0",
                "distance_from_base": round(random.uniform(10, 50), 2),
                "current_hours": aircraft['hours']
            }
    
    return mock_data


def save_mock_data():
    """Generate and save mock data."""
    print("Generating mock SkyRouter data...")
    
    mock_data = generate_mock_data()
    output_path = Path(OUTPUT_FOLDER) / OUTPUT_FILENAME
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(mock_data, f, indent=2)
    
    print(f"✓ Mock data saved to {output_path}")
    print(f"✓ Generated data for {len(mock_data['aircraft'])} aircraft")
    
    # Print summary
    at_base = sum(1 for a in mock_data['aircraft'].values() if a['at_base'])
    away = len(mock_data['aircraft']) - at_base
    
    print(f"  - {at_base} aircraft at bases")
    print(f"  - {away} aircraft away/in-flight")
    print("\nYou can now run the dashboard generator to see the test data!")


if __name__ == '__main__':
    save_mock_data()
