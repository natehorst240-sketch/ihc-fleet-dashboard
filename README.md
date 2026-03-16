# IHC Health Services — Fleet Maintenance Dashboard

A lightweight, automated web dashboard that turns CAMP CSV exports into a
live, interactive maintenance-tracking page hosted on GitHub Pages. Push a
new CSV and the dashboard rebuilds itself — no server required.

---
## If this breaks last good commit was 1 parent be376f5 commit 19958e8

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                             │
│                                                                 │
│  Veryon Export                   Component Change Report        │
│  (Due-List CSV)                (ComponentChangeReport CSV)      │
└────────────┬───────────────────────────────┬────────────────────┘
             │  bot CSV commit or schedule       │
             ▼                               ▼
┌─────────────────────────────────────────────────────────────────┐
│               GitHub Actions  (build_dashboard.yml)             │
│                                                                 │
│  1. Checkout repo                                               │
│  2. pip install Pillow                                          │
│  3. python scripts/fleet_dashboard_generator.py                 │
│     ├─ Parse Due-List CSV  ──────────────────────────────────┐  │
│     ├─ Parse Component Change CSV                            │  │
│     ├─ Load / update flight_hours_history.json               │  │
│     ├─ Load base_assignments.json (GPS positions)            │  │
│     └─ Embed fleet photo (IMG_9250.jpeg, base64)             │  │
│  4. Commit generated files back to repo                      │  │
│     • data/index.html                ◄──────────────────────┘  │
│     • data/flight_hours_history.json                            │
│     • data/dashboard_version.json                               │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│              GitHub Actions  (deploy-pages.yml)                 │
│                                                                 │
│  Deploys data/ folder → GitHub Pages                            │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│   https://natehorst240-sketch.github.io/ihc-fleet-dashboard/    │
│                                                                 │
│  Tab 1 │ Maintenance Due List   — phase inspections, urgency    │
│  Tab 2 │ Components             — per-aircraft component status │
│  Tab 3 │ Flight Hours           — utilization trends & charts   │
│  Tab 4 │ Calendar               — FullCalendar maintenance view │
│  Tab 5 │ Base Location          — GPS assignment & AT BASE/AWAY │
│  Tab 6 │ Component Changes      — monthly parts-replaced log    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Features

| Tab | What it shows |
|-----|--------------|
| **Maintenance Due List** | All phase inspections (50 hr – 3 200 hr). Color-coded: green / amber / red / overdue. Filterable table + 200 hr bar chart. |
| **Components** | Per-aircraft component tracking with remaining hours and retirement flags. |
| **Flight Hours** | Daily, 7-day, and 30-day utilization averages. Per-aircraft trend charts powered by Chart.js. |
| **Calendar** | Interactive FullCalendar projection of estimated inspection dates with editable event pills, hover detail cards, and a synchronized estimated inspection list. |
| **Base Location** | AT BASE / AIRBORNE / AWAY status based on GPS distance from assigned base. |
| **Component Changes** | Monthly breakdown of installed/removed parts from the Component Change Report. |

---


## Trootrax Live Tablet Map Feed

The **Aircraft Location** tab now includes a **Google Maps** panel that reads
`data/aircraft_locations.json` and plots each aircraft as helicopter markers with
registration labels.

To enable map rendering, define your API key before opening the dashboard:

```html
<script>window.GOOGLE_MAPS_API_KEY = "YOUR_API_KEY";</script>
```

(You can place this in a small local wrapper page or inject it with your hosting
platform's template system.)

Generate that feed with:

```bash
export TROOTRAX_USER='your_user'
export TROOTRAX_PASS='your_pass'
python scripts/trootrax.py
```

Optional: set `TROOTRAX_CUSTOMER_ID` if you need a customer ID other than `312`.


## AOG Tracker (Manual clear + weekly OOS report)

A standalone AOG tracker is available at `data/aog.html`.

- Add a grounded aircraft manually.
- Clear AOG events manually when the aircraft returns to service.
- View 7-day out-of-service totals by tail in the **Weekly Report** tab.
- Data persists in browser storage (`localStorage` fallback).

Open it locally with:

```bash
open data/aog.html
```

For an implementation blueprint to automate email-to-AOG flags on the main dashboard, see [AOG_AUTOMATION_PLAN.md](AOG_AUTOMATION_PLAN.md).

## Quick Start

```bash
# 1. Install the only runtime dependency
pip install Pillow

# 2. Drop your CAMP exports into data/
cp path/to/Due-List_BIG_WEEKLY_aw109sp.csv data/
cp path/to/ComponentChangeReport_109SP.csv  data/   # optional

# 3. Generate the dashboard locally
python scripts/fleet_dashboard_generator.py

# 4. Open in browser
open data/index.html
```

For full GitHub Pages setup see [SETUP_GUIDE.md](SETUP_GUIDE.md).

---

## Updating the Dashboard

Upload new CSVs to `data/` on GitHub (drag-and-drop or via the web UI) and
the Actions pipeline rebuilds and redeploys automatically.

`build_dashboard.yml` runs every 6 hours and rebuilds from the latest committed
`Due-List_BIG_WEEKLY_aw109sp.csv` in the repo. If your export bot commits that file to
`main`, the push trigger will also rebuild immediately.

Or via the command line:

```bash
cp path/to/Due-List_Latest.csv data/Due-List_BIG_WEEKLY_aw109sp.csv
git add data/
git commit -m "Update maintenance data"
git push
```

---

## Project Structure

```
ihc-fleet-dashboard/
├── .github/workflows/
│   ├── build_dashboard.yml      # Builds index.html on CSV push
│   └── deploy-pages.yml         # Deploys data/ to GitHub Pages
├── data/
│   ├── Due-List_BIG_WEEKLY_aw109sp.csv   # CAMP due-list export (input)
│   ├── ComponentChangeReport_109SP.csv   # Component change export (input)
│   ├── IMG_9250.jpeg                     # Fleet photo (embedded in dashboard)
│   ├── flight_hours_history.json         # 90-day rolling flight hours log
│   ├── base_assignments.json             # GPS aircraft positions
│   ├── dashboard_version.json            # Auto-refresh version token
│   └── index.html                        # Generated dashboard (output)
├── scripts/
│   └── fleet_dashboard_generator.py      # Main generator (2 000 lines)
├── requirements.txt                      # Pillow only
├── quick-start.sh                        # Local setup helper
└── SETUP_GUIDE.md                        # Full GitHub Pages setup guide
```

---

## Configuration

Key constants at the top of `scripts/fleet_dashboard_generator.py`:

| Constant | Default | Purpose |
|----------|---------|---------|
| `INPUT_FILENAME` | `Due-List_BIG_WEEKLY_aw109sp.csv` | Primary CSV source |
| `TARGET_INTERVALS` | `[50,100,200,400,800,2400,3200]` | Tracked inspection intervals (hours) |
| `COMPONENT_WINDOW_HRS` | `200` | Hours window for component status |
| `PHOTO_FILENAME` | `IMG_9250.jpeg` | Fleet photo shown in header |

---

## Security

- Keep the repository **private** — the dashboard embeds aircraft tail numbers and maintenance data.
- Store any API credentials (SkyRouter, etc.) in **GitHub Secrets**, never in committed files.

---

**License:** Private — IHC Health Services Internal Use Only
**Maintained by:** IHC Aviation Maintenance Team
