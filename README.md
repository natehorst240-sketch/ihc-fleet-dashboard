# IHC Fleet Maintenance Dashboard

An automated web dashboard that tracks helicopter fleet maintenance for IHC Health Services. Upload a new CSV from CAMP and the dashboard rebuilds itself — no server required.

Live site: deployed on Azure Static Web Apps ("white-mud").

---

## How It Works

```
CAMP (Veryon) CSV export
        │
        ▼
  data/ folder in this repo
        │
        ▼
GitHub Actions (build_dashboard.yml)
  • Runs every 6 hours, and immediately when a CSV is pushed
  • Fetches real-time aircraft locations from Trootrax
  • Runs scripts/fleet_dashboard_generator.py
  • Commits generated data/index.html back to main
        │
        ▼
GitHub Actions (azure-static-web-apps.yml)
  • Triggered by every push to main
  • Publishes the repo to Azure Static Web Apps
        │
        ▼
Live dashboard at your Azure SWA URL

(Aircraft location data also refreshes every 15 minutes via
 update_aircraft_locations.yml, which commits and triggers a redeploy.)
```

---

## Dashboard Tabs

| Tab | What it shows |
|-----|--------------|
| **Maintenance Due List** | All phase inspections (50 hr – 3,200 hr). Color-coded green / amber / red / overdue. Filterable table + 200-hr bar chart. |
| **Components** | Per-aircraft component tracking with remaining hours and retirement flags. |
| **Flight Hours** | Daily, 7-day, and 30-day utilization averages. Per-aircraft trend charts. |
| **Calendar** | FullCalendar view of estimated inspection dates with editable events and hover detail cards. |
| **Base Location** | AT BASE / AIRBORNE / AWAY status based on GPS distance from each aircraft's assigned base. |
| **Component Changes** | Monthly breakdown of installed/removed parts from the Component Change Report. |

---

## Updating the Dashboard

Upload a new CSV to `data/` on GitHub (drag-and-drop in the web UI or via git push) and the pipeline rebuilds and redeploys automatically within a few minutes.

```bash
cp path/to/latest-export.csv data/Due-List_BIG_WEEKLY_aw109sp.csv
git add data/Due-List_BIG_WEEKLY_aw109sp.csv
git commit -m "Update maintenance data"
git push
```

---

## Running Locally

```bash
pip install Pillow requests
python scripts/fleet_dashboard_generator.py
open data/index.html
```

---

## Project Structure

```
ihc-fleet-dashboard/
├── .github/workflows/
│   ├── build_dashboard.yml             # Rebuilds dashboard every 6h + on CSV push
│   ├── update_aircraft_locations.yml   # Refreshes Trootrax locations every 15 min
│   └── azure-static-web-apps.yml       # Deploys to Azure SWA on every push to main
├── scripts/
│   ├── fleet_dashboard_generator.py    # Main generator (~2,000 lines) — produces data/index.html
│   ├── trootrax.py                     # Fetches real-time aircraft GPS from Trootrax API
│   ├── fleet_builder.py                # Interactive wizard for setting up a new fleet config
│   └── generate_pwa_icons.py           # Regenerates PWA icons (192px, 512px)
├── api/
│   └── src/functions/
│       ├── calendar.js                 # Azure Function: calendar event CRUD (stored in GitHub Gist)
│       └── watchlist.js                # Azure Function: per-aircraft notes (stored in GitHub Gist)
├── configs/
│   └── aw109sp.json                    # AW109SP aircraft config (intervals, CSV columns, ATA patterns)
├── data/
│   ├── Due-List_BIG_WEEKLY_aw109sp.csv # INPUT: CAMP due-list export
│   ├── ComponentChangeReport_109SP.csv # INPUT: component change history
│   ├── base_locations.json             # 8 IHC base GPS coordinates
│   ├── base_assignments.json           # Aircraft-to-base assignments
│   ├── aircraft_locations.json         # Real-time Trootrax positions (auto-updated)
│   ├── flight_hours_history.json       # 90-day rolling flight hours log (auto-generated)
│   ├── dashboard_version.json          # Version token for client-side auto-refresh (auto-generated)
│   ├── aog_status.json                 # Aircraft on Ground status
│   ├── manifest.json                   # PWA manifest
│   ├── sw.js                           # Service Worker (offline support)
│   └── index.html                      # GENERATED dashboard output — do not edit by hand
├── staticwebapp.config.json            # Azure SWA routing and security headers
└── requirements.txt                    # Python dependency: Pillow
```

---

## Required GitHub Secrets

| Secret | Purpose |
|--------|---------|
| `AZURE_STATIC_WEB_APPS_API_TOKEN_WHITE_MUD_028C6491E` | Azure SWA deployment token |
| `TROOTRAX_USER` | Trootrax API username |
| `TROOTRAX_PASS` | Trootrax API password |
| `TROOTRAX_CUSTOMER_ID` | Trootrax customer ID (default: 312) |
| `GOOGLE_MAPS_API_KEY` | Google Maps API key for live location rendering |
| `CALENDAR_GITHUB_TOKEN` | GitHub PAT with `gist` scope — stores calendar notes |
| `CALENDAR_GIST_ID` | ID of the private Gist used for calendar/watchlist storage |

---

## Security

Keep this repository **private** — it contains aircraft tail numbers, maintenance schedules, and GPS data. All credentials are stored as GitHub Secrets and never committed to the repo.

---

**License:** Private — IHC Health Services Internal Use Only  
**Maintained by:** IHC Aviation Maintenance Team
