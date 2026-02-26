# github_auto_upload.py - ONLY uploads CSVs
import os
import base64
import requests
from pathlib import Path

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USERNAME = "natehorst240-sketch"
GITHUB_REPO = "ihc-fleet-dashboard"

# Configuration: Where to find CSVs for each fleet
FLEETS = {
    "aw109sp": {
        "csv_folder": r"C:\Users\nateh\OneDrive - Intermountain Health\VeryonExports\Veryon Exports",
        "csv_files": ["Due-List_Latest.csv", "Due-List_BIG_WEEKLY.csv"]
    },
    "fleet2": {
        "csv_folder": r"C:\path\to\fleet2\data",
        "csv_files": ["Due-List_Latest.csv", "Due-List_BIG_WEEKLY.csv"]
    }
}

def upload_file(local_path, github_path):
    """Upload a single file to GitHub"""
    with open(local_path, 'rb') as f:
        content = base64.b64encode(f.read()).decode('utf-8')
    
    url = f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/contents/{github_path}"
    
    # Check if file exists (to get SHA)
    response = requests.get(url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
    sha = response.json().get('sha') if response.status_code == 200 else None
    
    data = {
        "message": f"Update {os.path.basename(local_path)}",
        "content": content,
        "branch": "main"
    }
    if sha:
        data["sha"] = sha
    
    response = requests.put(url, headers={"Authorization": f"token {GITHUB_TOKEN}"}, json=data)
    return response.status_code in [200, 201]

def main():
    print("Uploading CSV files to GitHub...")
    
    for fleet_name, config in FLEETS.items():
        print(f"\nProcessing {fleet_name}...")
        
        for csv_file in config["csv_files"]:
            local_path = Path(config["csv_folder"]) / csv_file
            github_path = f"data/{fleet_name}/{csv_file}"
            
            if local_path.exists():
                if upload_file(local_path, github_path):
                    print(f"  ✓ Uploaded {csv_file}")
                else:
                    print(f"  ✗ Failed to upload {csv_file}")
            else:
                print(f"  ! File not found: {local_path}")
    
    print("\n✓ Upload complete! GitHub will now generate dashboards automatically.")

if __name__ == '__main__':
    main()
