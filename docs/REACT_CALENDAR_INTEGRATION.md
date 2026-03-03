# React Maintenance Calendar Integration Plan

This repository currently generates a static dashboard page (`public/index.html`) from Python (`build_dashboard.py`).

Because of that architecture, the `MaintenanceCalendar` React component cannot be dropped in directly without adding a JavaScript build/runtime layer.

## Current architecture (important)

- Python script builds the full HTML dashboard.
- Calendar UI is generated as plain HTML/CSS inside `_build_calendar_tab(...)`.
- Generated output is written to `public/index.html`.

## Can you replace the calendar and keep current styling?

Yes, with one of these approaches:

### Option A (recommended): migrate dashboard frontend to React

1. Create a React app (Vite/Next/CRA).
2. Move current style tokens and theme values from `build_dashboard.py` CSS into a shared stylesheet.
3. Render tabs in React.
4. Replace current calendar tab with:
   - `MaintenanceCalendar`
   - imported `maintenance-calendar.css`
5. Feed events from the same maintenance data source currently used by Python.
6. Publish built assets to `public/` via CI.

**Pros:** best long-term UX and maintainability.
**Cons:** largest migration effort.

### Option B: keep Python dashboard, embed React calendar island

1. Build a small React bundle that only renders the calendar.
2. Include that bundle in generated HTML from `build_dashboard.py`.
3. Replace calendar-tab markup with a mount node (`<div id="calendar-root"></div>`).
4. Pass event data from Python to JS via inline JSON (`<script type="application/json">`).
5. Ensure the React calendar CSS maps to current dashboard tokens (`--bg`, `--surface`, `--blue`, etc.) so visual style remains consistent.

**Pros:** smaller migration than full rewrite.
**Cons:** mixed architecture (Python HTML + React island).

### Option C: no React, port UX only

Re-implement the same UX behaviors in plain JavaScript inside `_build_calendar_tab(...)`:

- month/week/day modes
- modal create/edit/delete
- drag & drop
- filters

**Pros:** no frontend toolchain.
**Cons:** more custom UI logic to maintain.

## Styling compatibility notes

To keep the existing look, map the React calendar CSS to current dashboard variables:

- Backgrounds: `--bg`, `--surface`, `--surface2`
- Borders: `--border`
- Typography: `--sans`, `--mono`, `--body`
- Accent/status colors: `--blue`, `--amber`, `--red`, `--green`

Also keep spacing and border-radius aligned to existing card/table styles.

## Data mapping from current dashboard to React component

The React component expects:

- `id`
- `aircraftId`
- `registration`
- `inspectionType`
- `dueDate` (`YYYY-MM-DD`)
- `hoursRemaining`
- `notes` (optional)

Current Python logic already computes due-date style projections from hours remaining and average utilization; that data can be transformed into the React event shape during render/export.

## Recommendation for this repo

Given current static-Python architecture, **Option B** is usually the best compromise if you want to adopt this component now while preserving your current theme.
