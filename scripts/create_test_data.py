"""
Quick Setup - Generate Test Data for Dashboard
==============================================
This creates all the test files you need to see the dashboard working.
"""

import json
from datetime import datetime
from pathlib import Path

# Update this path to match your system
OUTPUT_FOLDER = r"C:\Users\nateh\OneDrive - Intermountain Health\VeryonExports\Veryon Exports"

def create_test_skyrouter_data():
    """Create test SkyRouter position data."""
    data = {
        "last_updated": datetime.now().isoformat(),
        "aircraft": {
            "N291HC": {
                "status": "AT BASE",
                "at_base": True,
                "latitude": 40.2192,  # Provo
                "longitude": -111.7233,
                "altitude": "0",
                "velocity": "0",
                "heading": "0",
                "current_hours": 3068.9,
                "last_update": datetime.now().strftime("%Y%m%d %H%M%S"),
                "timestamp": datetime.now().isoformat()
            },
            "N281HC": {
                "status": "AT BASE", 
                "at_base": True,
                "latitude": 41.7912,  # Logan
                "longitude": -111.8522,
                "altitude": "0",
                "velocity": "0",
                "heading": "0",
                "current_hours": 5682.7,
                "last_update": datetime.now().strftime("%Y%m%d %H%M%S"),
                "timestamp": datetime.now().isoformat()
            },
            "N271HC": {
                "status": "ACTIVE",
                "at_base": False,
                "latitude": 40.5,  # In flight
                "longitude": -111.5,
                "altitude": "5000",
                "velocity": "120",
                "heading": "180",
                "current_hours": 1943.1,
                "last_update": datetime.now().strftime("%Y%m%d %H%M%S"),
                "timestamp": datetime.now().isoformat()
            },
            "N261HC": {
                "status": "AT BASE",
                "at_base": True,
                "latitude": 40.7884,  # KSLC
                "longitude": -111.9778,
                "altitude": "0",
                "velocity": "0",
                "heading": "0",
                "current_hours": 6480.5,
                "last_update": datetime.now().strftime("%Y%m%d %H%M%S"),
                "timestamp": datetime.now().isoformat()
            },
            "N251HC": {
                "status": "AT BASE",
                "at_base": True,
                "latitude": 40.2338,  # IMed
                "longitude": -111.6585,
                "altitude": "0",
                "velocity": "0",
                "heading": "0",
                "current_hours": 6849.7,
                "last_update": datetime.now().strftime("%Y%m%d %H%M%S"),
                "timestamp": datetime.now().isoformat()
            }
        }
    }
    
    output_path = Path(OUTPUT_FOLDER) / "skyrouter_status.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    
    print(f"✓ Created {output_path}")
    return data


def create_test_base_assignments(skyrouter_data):
    """Create test base assignments."""
    data = {
        "last_updated": datetime.now().isoformat(),
        "bases": {
            "LOGAN": {"name": "Logan", "lat": 41.7912, "lon": -111.8522, "radius_miles": 5},
            "MCKAY": {"name": "McKay", "lat": 41.2545, "lon": -112.0126, "radius_miles": 5},
            "IMED": {"name": "IMed", "lat": 40.2338, "lon": -111.6585, "radius_miles": 5},
            "PROVO": {"name": "Provo", "lat": 40.2192, "lon": -111.7233, "radius_miles": 5},
            "ROOSEVELT": {"name": "Roosevelt", "lat": 40.2765, "lon": -110.0518, "radius_miles": 5},
            "CEDAR_CITY": {"name": "Cedar City", "lat": 37.7010, "lon": -113.0989, "radius_miles": 5},
            "ST_GEORGE": {"name": "St George", "lat": 37.0365, "lon": -113.5101, "radius_miles": 5},
            "KSLC": {"name": "KSLC", "lat": 40.7884, "lon": -111.9778, "radius_miles": 10}
        },
        "assignments": {
            "LOGAN": {
                "aircraft": [{
                    "tail": "N281HC",
                    "hours": 5682.7,
                    "distance": 0.5,
                    "at_base": True
                }],
                "status": "occupied"
            },
            "MCKAY": {"aircraft": [], "status": "available"},
            "IMED": {
                "aircraft": [{
                    "tail": "N251HC",
                    "hours": 6849.7,
                    "distance": 1.2,
                    "at_base": True
                }],
                "status": "occupied"
            },
            "PROVO": {
                "aircraft": [{
                    "tail": "N291HC",
                    "hours": 3068.9,
                    "distance": 0.3,
                    "at_base": True
                }],
                "status": "occupied"
            },
            "ROOSEVELT": {"aircraft": [], "status": "available"},
            "CEDAR_CITY": {"aircraft": [], "status": "available"},
            "ST_GEORGE": {"aircraft": [], "status": "available"},
            "KSLC": {
                "aircraft": [{
                    "tail": "N261HC",
                    "hours": 6480.5,
                    "distance": 2.1,
                    "at_base": True
                }],
                "status": "occupied"
            },
            "unassigned": [{
                "tail": "N271HC",
                "hours": 1943.1,
                "closest_base": "Provo",
                "distance_from_closest": 35.5,
                "at_base": False
            }]
        },
        "summary": {
            "total_aircraft": 5,
            "at_bases": 4,
            "away_from_base": 1
        }
    }
    
    output_path = Path(OUTPUT_FOLDER) / "base_assignments.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    
    print(f"✓ Created {output_path}")
    return data


def main():
    print("Creating test data files...")
    print()
    
    # Create SkyRouter test data
    skyrouter_data = create_test_skyrouter_data()
    
    # Create base assignments
    base_data = create_test_base_assignments(skyrouter_data)
    
    print()
    print("=" * 60)
    print("✓ Test data created successfully!")
    print("=" * 60)
    print()
    print("Now run your dashboard generator:")
    print("  python fleet_dashboard_generator_fixed.py")
    print()
    print("Then open the dashboard and click the 'Bases' tab")
    print()


if __name__ == '__main__':
    main()
