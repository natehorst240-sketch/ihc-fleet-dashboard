# Data Folder

This folder contains your dashboard data files.

## Files to Put Here:

### CSV Files (from CAMP):
- `Due-List_Latest.csv` - Daily export from CAMP
- `Due-List_BIG_WEEKLY.csv` - Weekly export from CAMP

### Auto-Generated JSON Files:
- `skyrouter_status.json` - Aircraft positions
- `base_assignments.json` - Base assignments
- `flight_hours_history.json` - Historical flight hours

### Output:
- `fleet_dashboard.html` - Generated dashboard (also copied to `public/`)

## Note:

CSV files are **gitignored** by default for security.
You can upload them via GitHub web interface or push them manually if needed.

## Testing:

Run this to create test data:
```bash
python scripts/create_test_data.py
```
