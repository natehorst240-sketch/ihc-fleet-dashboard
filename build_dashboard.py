# “””
Fleet Maintenance Dashboard Generator (CSV)

Reads Due-List_Latest_aw109sp.csv and Due-List_BIG_WEEKLY_aw109sp.csv
from the data/ folder and writes data/fleet_dashboard.html.

Run via GitHub Actions after CSV files are pushed to repo.
“””

import sys
import csv
import re
import json
from datetime import datetime, timedelta
from pathlib import Path

# ── CONFIGURATION ─────────────────────────────────────────────────────────────

OUTPUT_FOLDER = “data”

INPUT_FILENAME     = “Due-List_Latest_aw109sp.csv”
WEEKLY_FILENAME    = “Due-List_BIG_WEEKLY_aw109sp.csv”
INPUT_FALLBACKS    = [“Due-List_Latest.csv”]
WEEKLY_FALLBACKS   = [“Due-List_BIG_WEEKLY.csv”]
OUTPUT_FILENAME    = “fleet_dashboard.html”
HISTORY_FILENAME   = “flight_hours_history.json”
POSITIONS_FILENAME = “base_assignments.json”

# Phase inspection intervals to track (hours)

TARGET_INTERVALS = [50, 100, 200, 400, 800, 2400, 3200]

# Map each interval to regex pattern(s) found in Column F (ATA and Code)

PHASE_MATCH = {
50:   [r”05 1000”],
100:  [r”64 01[273]”],
200:  [r”05 1005”],
400:  [r”05 1010”],
800:  [r”05 1015”],
2400: [r”62 11[373]”],
3200: [r”05 1020”],
}

# Calendar-based certifications to track (keyed by inspection code)

CERT_INSPECTIONS = {
“XPDR_24M”: {
“label”:      “24M CERT”,
“ata_pattern”: r”34 0009”,
“col_header”: “Transponder Cert”,
},
}

# Component panel: show items within this many hours of retire/overhaul

COMPONENT_WINDOW_HRS = 200

# Keywords that identify retirement/overhaul component items

RETIREMENT_KEYWORDS = [
‘RETIRE’, ‘OVERHAUL’, ‘DISCARD’, ‘LIFE LIMIT’, ‘TBO’,
‘REPLACEMENT’, ‘REPLACE’, ‘CHANGE OIL’, ‘NOZZLE’
]

# ── COLUMN INDICES (0-based) ──────────────────────────────────────────────────

COL_REG          = 0
COL_AIRFRAME_RPT = 2
COL_AIRFRAME_HRS = 3
COL_ATA          = 5
COL_EQUIP_HRS    = 7
COL_ITEM_TYPE    = 11
COL_DISPOSITION  = 13
COL_DESC         = 15
COL_INTERVAL_HRS = 30
COL_REM_DAYS     = 50
COL_REM_MONTHS   = 52
COL_REM_HRS      = 54
COL_STATUS       = 63

# ── HELPERS ───────────────────────────────────────────────────────────────────

def safe_float(val):
if val is None:
return None
s = str(val).strip()
if s == “”:
return None
try:
return float(s.replace(”,”, “”))
except (ValueError, TypeError):
return None

def classify(hrs):
if hrs is None:
return ‘na’
if hrs < 0:
return ‘overdue’
if hrs <= 25:
return ‘red’
if hrs <= 100:
return ‘amber’
return ‘green’

def classify_from_status(status_str):
if not status_str:
return ‘na’
s = str(status_str).strip().upper()
if ‘PAST DUE’ in s:
return ‘overdue’
if ‘COMING DUE’ in s:
return ‘amber’
if ‘WITHIN TOLERANCE’ in s or ‘10+’ in s:
return ‘green’
return ‘na’

def has_retirement_keyword(desc):
desc_upper = str(desc).upper()
return any(kw in desc_upper for kw in RETIREMENT_KEYWORDS)

def parse_report_date(val):
if not val:
return None
s = str(val).strip()
if not s:
return None
fmts = [
“%Y-%m-%d”, “%m/%d/%Y”, “%m/%d/%y”,
“%Y-%m-%d %H:%M:%S”, “%m/%d/%Y %H:%M”, “%m/%d/%Y %H:%M:%S”,
]
for f in fmts:
try:
return datetime.strptime(s, f)
except ValueError:
pass
try:
return datetime.fromisoformat(s.replace(“Z”, “+00:00”))
except Exception:
return None

# ── FLIGHT HOURS TRACKING ─────────────────────────────────────────────────────

def load_flight_hours_history(history_path):
if not history_path.exists():
return {}
try:
with open(history_path, ‘r’, encoding=‘utf-8’) as f:
return json.load(f)
except Exception:
return {}

def save_flight_hours_history(history_path, history_data):
try:
with open(history_path, ‘w’, encoding=‘utf-8’) as f:
json.dump(history_data, f, indent=2)
except Exception as e:
print(f”Warning: Could not save flight hours history: {e}”)

def update_flight_hours_history(history_data, aircraft_list, report_date_dt):
if not report_date_dt:
report_date_dt = datetime.today()
date_key = report_date_dt.strftime(”%Y-%m-%d”)
for ac in aircraft_list:
tail = ac[‘tail’]
hours = ac[‘airframe_hrs’]
if hours is None:
continue
if tail not in history_data:
history_data[tail] = {}
if date_key not in history_data[tail] or history_data[tail][date_key][‘hours’] != hours:
history_data[tail][date_key] = {‘hours’: hours, ‘date’: date_key}
cutoff_date = (datetime.today() - timedelta(days=90)).strftime(”%Y-%m-%d”)
for tail in history_data:
history_data[tail] = {
date: data for date, data in history_data[tail].items()
if date >= cutoff_date
}
return history_data

def calculate_flight_hours_stats(history_data, aircraft_list):
today = datetime.today()
seven_days_ago  = today - timedelta(days=7)
thirty_days_ago = today - timedelta(days=30)
stats = {}
for ac in aircraft_list:
tail = ac[‘tail’]
current_hours = ac[‘airframe_hrs’]
if tail not in history_data or current_hours is None:
stats[tail] = {
‘current_hours’: current_hours, ‘daily’: [],
‘weekly’: None, ‘monthly’: None,
‘avg_daily’: None, ‘projection_weekly’: None, ‘projection_monthly’: None
}
continue
tail_history = history_data[tail]
sorted_dates = sorted(tail_history.keys(), reverse=True)
daily_data = []
for date_str in sorted_dates[:7]:
daily_data.insert(0, {‘date’: date_str, ‘hours’: tail_history[date_str][‘hours’]})
weekly_hours = None
monthly_hours = None
seven_days_ago_str  = seven_days_ago.strftime(”%Y-%m-%d”)
thirty_days_ago_str = thirty_days_ago.strftime(”%Y-%m-%d”)
if len(sorted_dates) >= 2:
latest_hours = tail_history[sorted_dates[0]][‘hours’]
for date_str in sorted_dates:
if date_str <= seven_days_ago_str:
weekly_hours = latest_hours - tail_history[date_str][‘hours’]
break
for date_str in sorted_dates:
if date_str <= thirty_days_ago_str:
monthly_hours = latest_hours - tail_history[date_str][‘hours’]
break
avg_daily = projection_weekly = projection_monthly = None
if monthly_hours is not None:
days_of_data = (today - datetime.strptime(thirty_days_ago_str, “%Y-%m-%d”)).days
if days_of_data > 0:
avg_daily = monthly_hours / days_of_data
elif weekly_hours is not None:
days_of_data = (today - datetime.strptime(seven_days_ago_str, “%Y-%m-%d”)).days
if days_of_data > 0:
avg_daily = weekly_hours / days_of_data
elif len(sorted_dates) >= 2:
oldest = sorted_dates[-1]
newest = sorted_dates[0]
span_days = (datetime.strptime(newest, “%Y-%m-%d”) - datetime.strptime(oldest, “%Y-%m-%d”)).days
if span_days > 0:
span_hours = tail_history[newest][‘hours’] - tail_history[oldest][‘hours’]
avg_daily = span_hours / span_days
if avg_daily is not None:
projection_weekly  = avg_daily * 7
projection_monthly = avg_daily * 30
stats[tail] = {
‘current_hours’: current_hours, ‘daily’: daily_data,
‘weekly’: weekly_hours, ‘monthly’: monthly_hours,
‘avg_daily’: avg_daily,
‘projection_weekly’: projection_weekly,
‘projection_monthly’: projection_monthly,
}
return stats

# ── POSITIONS (ADSB) ──────────────────────────────────────────────────────────

def load_positions(positions_path):
“””
Load positions from base_assignments.json and normalize into a
per-tail dict that the rest of the dashboard expects.

```
Output format per tail:
  {
    'status': 'AT_BASE' | 'AWAY' | 'AIRBORNE' | 'UNKNOWN',
    'current_base': {'id': str, 'name': str, 'dist_nm': float} | None,
    'nearest_base':  {'id': str, 'name': str, 'dist_nm': float} | None,
    'last_alt_ft': int | '',
    'last_gs_kts': int | '',
    'last_updated': str,
    'flights_today': [],
    'total_flight_hrs_today': 0.0,
  }
"""
if not positions_path.exists():
    return {}
try:
    with open(positions_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
except Exception:
    return {}

assignments  = data.get('assignments', {})
bases_meta   = data.get('bases', {})
last_updated = data.get('last_updated', '')
aircraft_positions = {}

# Walk every base and collect assigned aircraft
for base_id, base_data in assignments.items():
    if base_id == 'unassigned':
        ac_list = base_data if isinstance(base_data, list) else []
        for ac in ac_list:
            tail = ac.get('tail') or ac.get('registration', '')
            if not tail:
                continue
            aircraft_positions[tail] = {
                'status': 'AWAY',
                'current_base': None,
                'nearest_base': None,
                'last_alt_ft': ac.get('altitude', ''),
                'last_gs_kts': ac.get('ground_speed', ''),
                'last_updated': last_updated,
                'flights_today': [],
                'total_flight_hrs_today': 0.0,
            }
    else:
        ac_list = base_data.get('aircraft', []) if isinstance(base_data, dict) else []
        base_name = bases_meta.get(base_id, {}).get('name', base_id)
        for ac in ac_list:
            tail = ac.get('tail') or ac.get('registration', '')
            if not tail:
                continue
            status_raw = str(ac.get('status', '')).upper()
            if 'AIRBORNE' in status_raw or 'IN_FLIGHT' in status_raw:
                status = 'AIRBORNE'
                curr_base = None
            else:
                status = 'AT_BASE'
                curr_base = {
                    'id': base_id,
                    'name': base_name,
                    'dist_nm': round(ac.get('distance_miles', 0) * 0.868976, 1),
                }
            aircraft_positions[tail] = {
                'status': status,
                'current_base': curr_base,
                'nearest_base': None,
                'last_alt_ft': ac.get('altitude', ''),
                'last_gs_kts': ac.get('ground_speed', ''),
                'last_updated': last_updated,
                'flights_today': [],
                'total_flight_hrs_today': 0.0,
            }

return aircraft_positions
```

def get_location_badge(tail, positions):
ac = positions.get(tail, {})
if not ac:
return ‘’
status    = ac.get(‘status’, ‘’).upper()
curr_base = ac.get(‘current_base’)
near_base = ac.get(‘nearest_base’)
if status == ‘AIRBORNE’:
last_alt = ac.get(‘last_alt_ft’, ‘’)
alt_str  = f” {last_alt}ft” if last_alt else ‘’
return f’<span class="location-badge location-active">AIRBORNE{alt_str}</span>’
if status == ‘AT_BASE’:
base_name = curr_base.get(‘name’, ‘’) if curr_base else ‘’
label = f’AT BASE’ + (f’ · {base_name}’ if base_name else ‘’)
return f’<span class="location-badge location-at-base">{label}</span>’
if status == ‘AWAY’:
near_str = ‘’
if near_base:
near_str = f” · {near_base.get(‘dist_nm’, ‘?’)}nm from {near_base.get(‘name’, ‘?’)}”
return f’<span class="location-badge location-away">AWAY{near_str}</span>’
if status == ‘NO_SIGNAL’:
return ‘<span class="location-badge location-unknown">NO SIGNAL</span>’
return ‘’

def get_flights_today(tail, positions):
ac = positions.get(tail, {})
return ac.get(‘flights_today’, [])

def get_hours_today(tail, positions):
ac = positions.get(tail, {})
return ac.get(‘total_flight_hrs_today’, 0.0)

# ── CSV PARSING ───────────────────────────────────────────────────────────────

def merge_inspections(weekly_raw, daily_raw):
merged = {}
tails = set(weekly_raw.keys()) | set(daily_raw.keys())
for tail in tails:
merged[tail] = {}
if tail in weekly_raw:
merged[tail].update(weekly_raw[tail])
if tail in daily_raw:
merged[tail].update(daily_raw[tail])
return merged

def parse_due_list_parts(filepath):
with open(filepath, “r”, encoding=“utf-8-sig”, newline=””) as f:
reader = csv.reader(f)
rows = list(reader)

```
if not rows or len(rows) < 2:
    raise ValueError(f"CSV appears empty or missing data rows: {filepath}")

data_rows = rows[1:]
aircraft_raw  = {}
aircraft_meta = {}
components_raw = {}
certs_raw = {}
report_date_dt = None

compiled_phase = {
    interval: [re.compile(p, re.IGNORECASE) for p in pats]
    for interval, pats in PHASE_MATCH.items()
}

for row in data_rows:
    if len(row) <= COL_STATUS:
        continue
    reg = row[COL_REG].strip() if row[COL_REG] else ""
    if not reg:
        continue

    airframe_hrs = safe_float(row[COL_AIRFRAME_HRS])
    rpt_date_dt  = parse_report_date(row[COL_AIRFRAME_RPT])

    if reg not in aircraft_meta:
        aircraft_meta[reg] = {'airframe_hrs': airframe_hrs, 'report_date': rpt_date_dt}
        if report_date_dt is None and rpt_date_dt:
            report_date_dt = rpt_date_dt

    ata_text  = row[COL_ATA].strip()       if row[COL_ATA]       else ""
    item_type = row[COL_ITEM_TYPE].strip()  if row[COL_ITEM_TYPE] else ""
    desc      = row[COL_DESC].strip()       if row[COL_DESC]      else ""
    rem_hrs   = safe_float(row[COL_REM_HRS])
    rem_days  = safe_float(row[COL_REM_DAYS])
    status    = row[COL_STATUS].strip()     if row[COL_STATUS]    else ""

    if item_type.upper() == "INSPECTION":
        for interval in TARGET_INTERVALS:
            patterns = compiled_phase.get(interval, [])
            if not patterns:
                continue
            if not any(rx.search(ata_text) for rx in patterns):
                continue
            if reg not in aircraft_raw:
                aircraft_raw[reg] = {}
            interval_key = f"{interval:.2f}"
            existing = aircraft_raw[reg].get(interval_key)
            if existing is None or (
                rem_hrs is not None and (existing["rem_hrs"] is None or rem_hrs < existing["rem_hrs"])
            ):
                aircraft_raw[reg][interval_key] = {
                    "rem_hrs": rem_hrs, "rem_days": rem_days,
                    "status": status, "desc": desc,
                }

    if item_type.upper() == "INSPECTION":
        for cert_key, cert_cfg in CERT_INSPECTIONS.items():
            rx = re.compile(cert_cfg["ata_pattern"], re.IGNORECASE)
            if not rx.search(ata_text):
                continue
            if reg not in certs_raw:
                certs_raw[reg] = {}
            existing = certs_raw[reg].get(cert_key)
            if existing is None or (
                rem_days is not None and
                (existing["rem_days"] is None or rem_days < existing["rem_days"])
            ):
                certs_raw[reg][cert_key] = {
                    "rem_days": rem_days,
                    "rem_hrs":  rem_hrs,
                    "status":   status,
                }

    is_part = (item_type.upper() == "PART")
    is_retirement_insp = (item_type.upper() == "INSPECTION" and has_retirement_keyword(desc))
    if is_part or is_retirement_insp:
        hrs_in_window  = rem_hrs is not None and rem_hrs <= COMPONENT_WINDOW_HRS
        days_in_window = rem_hrs is None and rem_days is not None and rem_days <= 60
        past_due       = status.strip().upper() == "PAST DUE"
        if hrs_in_window or days_in_window or past_due:
            if reg not in components_raw:
                components_raw[reg] = []
            clean_desc = re.sub(r"^\(RII\)\s*", "", desc, flags=re.IGNORECASE)
            clean_desc = re.sub(r"^RII\s+", "", clean_desc, flags=re.IGNORECASE)
            clean_desc = re.sub(r"\n.*", "", clean_desc).strip().title()
            disposition = row[COL_DISPOSITION] if row[COL_DISPOSITION] else ""
            rii_flag = ("RII" in str(disposition).upper()) or ("RII" in desc.upper())
            if rem_hrs is not None:
                sort_key = rem_hrs
            elif rem_days is not None:
                sort_key = rem_days * 0.5
            else:
                sort_key = 9999
            components_raw[reg].append({
                "name": clean_desc, "rem_hrs": rem_hrs, "rem_days": rem_days,
                "status": status, "rii": rii_flag, "sort_key": sort_key,
            })

for reg in components_raw:
    seen_names = set()
    deduped = []
    for c in sorted(components_raw[reg], key=lambda x: x["sort_key"]):
        key = c["name"][:40]
        if key not in seen_names:
            seen_names.add(key)
            deduped.append(c)
    components_raw[reg] = deduped

return aircraft_meta, aircraft_raw, components_raw, certs_raw, report_date_dt
```

def parse_due_list(daily_path, weekly_path=None):
daily_meta, daily_raw, daily_components, daily_certs, daily_rpt_dt = parse_due_list_parts(daily_path)
weekly_meta  = {}
weekly_raw   = {}
weekly_certs = {}
weekly_rpt_dt = None
if weekly_path and Path(weekly_path).exists():
weekly_meta, weekly_raw, _, weekly_certs, weekly_rpt_dt = parse_due_list_parts(weekly_path)

```
merged_raw   = merge_inspections(weekly_raw, daily_raw)
# Merge certs: daily overrides weekly per tail+key
merged_certs = {}
for reg in set(weekly_certs.keys()) | set(daily_certs.keys()):
    merged_certs[reg] = {}
    if reg in weekly_certs:
        merged_certs[reg].update(weekly_certs[reg])
    if reg in daily_certs:
        merged_certs[reg].update(daily_certs[reg])

all_regs   = sorted(set(weekly_meta.keys()) | set(daily_meta.keys()))
aircraft_list = []

for reg in all_regs:
    meta = daily_meta.get(reg) or weekly_meta.get(reg) or {"airframe_hrs": None, "report_date": None}
    insp = merged_raw.get(reg, {})
    intervals = {}
    for i in TARGET_INTERVALS:
        key = f"{i:.2f}"
        if key in insp:
            entry = insp[key]
            intervals[i] = {
                "rem_hrs":  entry.get("rem_hrs"),
                "rem_days": entry.get("rem_days"),
                "status":   entry.get("status", ""),
            }
        else:
            intervals[i] = None
    aircraft_list.append({
        "tail":         reg,
        "airframe_hrs": meta.get("airframe_hrs"),
        "report_date":  meta.get("report_date"),
        "intervals":    intervals,
        "certs":        merged_certs.get(reg, {}),
    })

report_date_dt = daily_rpt_dt or weekly_rpt_dt
if isinstance(report_date_dt, datetime):
    report_date_str = report_date_dt.strftime("%d %b %Y").upper()
else:
    report_date_str = datetime.today().strftime("%d %b %Y").upper()

return report_date_str, aircraft_list, daily_components
```

# ── BUILD HTML ────────────────────────────────────────────────────────────────

def build_html(report_date, aircraft_list, components, flight_hours_stats, positions, source_filename):

```
def fmt_hrs(val_dict):
    if val_dict is None:
        return '<span class="hr-na">—</span>'
    hrs    = val_dict['rem_hrs']
    status = val_dict['status']
    if hrs is not None:
        cls   = classify(hrs)
        label = f'OVRD {abs(hrs):.0f}' if hrs < 0 else f'{hrs:.1f}'
    else:
        cls  = classify_from_status(status)
        days = val_dict.get('rem_days')
        if days is not None:
            label = f'OVRD {abs(days):.0f}d' if days < 0 else f'{days:.0f}d'
        else:
            label = status[:8] if status else '?'
    badge_cls = {
        'overdue': 'hr-overdue', 'red': 'hr-red',
        'amber': 'hr-amber', 'green': 'hr-green', 'na': 'hr-na',
    }.get(cls, 'hr-na')
    if cls == 'na':
        return f'<span class="hr-na">{label}</span>'
    return f'<span class="hr-badge {badge_cls}">{label}</span>'

def fmt_cert(cert_entry):
    """Render a calendar cert as '24M CERT DUE MM-DD-YYYY' badge."""
    if cert_entry is None:
        return '<span class="hr-na">—</span>'
    rem_days = cert_entry.get("rem_days")
    status   = cert_entry.get("status", "")
    if rem_days is not None:
        due_dt  = datetime.today() + timedelta(days=rem_days)
        due_str = due_dt.strftime("%m-%d-%Y")
        if rem_days < 0:
            cls   = 'hr-overdue'
            label = f'CERT OD {due_str}'
        elif rem_days <= 30:
            cls   = 'hr-red'
            label = f'24M CERT DUE {due_str}'
        elif rem_days <= 90:
            cls   = 'hr-amber'
            label = f'24M CERT DUE {due_str}'
        else:
            cls   = 'hr-green'
            label = f'24M CERT DUE {due_str}'
    else:
        cls   = classify_from_status(status)
        label = f'24M CERT — {status[:10]}' if status else '24M CERT — ?'
    badge_cls = {
        'overdue': 'hr-overdue', 'red': 'hr-red',
        'amber': 'hr-amber',     'green': 'hr-green', 'na': 'hr-na',
    }.get(cls, 'hr-na')
    if cls == 'na':
        return f'<span class="hr-na">{label}</span>'
    return f'<span class="hr-badge {badge_cls}" style="min-width:126px;font-size:10px;letter-spacing:0;">{label}</span>'

total_ac = len(aircraft_list)
crit_count = coming_count = comp_overdue = 0
for ac in aircraft_list:
    for i in TARGET_INTERVALS:
        v = ac['intervals'].get(i)
        if v:
            c = classify(v['rem_hrs']) if v['rem_hrs'] is not None else classify_from_status(v['status'])
            if c in ('overdue', 'red'):
                crit_count += 1
            elif c == 'amber':
                coming_count += 1
for reg, comps in components.items():
    for c in comps:
        rem = c['rem_hrs']
        rem_d = c.get('rem_days')
        if (rem is not None and rem < 0) or (rem is None and rem_d is not None and rem_d < 0):
            comp_overdue += 1

airborne_count = sum(1 for t in aircraft_list if positions.get(t['tail'], {}).get('status') == 'AIRBORNE')
at_base_count  = sum(1 for t in aircraft_list if positions.get(t['tail'], {}).get('status') == 'AT_BASE')

table_rows_html = ''
for ac in aircraft_list:
    tail = ac['tail']
    ah   = f"{ac['airframe_hrs']:,.1f}" if ac['airframe_hrs'] else 'N/A'
    location_badge = get_location_badge(tail, positions)
    hrs_today = get_hours_today(tail, positions)
    hrs_today_str = f'<div class="airframe-today">{hrs_today:.1f} hrs today</div>' if hrs_today else ''
    cells = f'''<td>
      <div class="tail-number">{tail}{location_badge}</div>
      <div class="airframe-hrs">{ah} TT</div>
      {hrs_today_str}
    </td>'''
    for i in TARGET_INTERVALS:
        cells += f'<td class="hr-cell">{fmt_hrs(ac["intervals"].get(i))}</td>'
    xpdr = ac.get("certs", {}).get("XPDR_24M")
    cells += f'<td class="hr-cell">{fmt_cert(xpdr)}</td>'
    table_rows_html += f'<tr data-tail="{tail}">{cells}</tr>\n'

comp_panels_html = ''
for ac in aircraft_list:
    reg   = ac['tail']
    comps = components.get(reg, [])
    if not comps:
        continue
    ah = f"{ac['airframe_hrs']:.1f}" if ac['airframe_hrs'] else 'N/A'
    rows_html = ''
    for c in comps:
        rem     = c['rem_hrs']
        rem_days = c.get('rem_days')
        status  = c.get('status', '')
        if rem is not None:
            cls = classify(rem)
        elif rem_days is not None:
            cls = 'overdue' if rem_days < 0 else ('red' if rem_days <= 7 else ('amber' if rem_days <= 30 else 'green'))
        else:
            cls = classify_from_status(status)
        ind_cls   = {'overdue': 'comp-overdue', 'red': 'comp-red', 'amber': 'comp-amber', 'green': 'comp-green'}.get(cls, 'comp-green')
        txt_color = {'overdue': 'var(--overdue)', 'red': 'var(--red)', 'amber': 'var(--amber)', 'green': 'var(--green)'}.get(cls, 'var(--green)')
        rii_badge = ' <span class="rii-badge">RII</span>' if c.get('rii') else ''
        if rem is not None:
            rem_label = f'OVERDUE — {abs(rem):.1f} hrs past limit' if rem < 0 else f'{rem:.1f} hrs remaining'
        elif rem_days is not None:
            rem_label = f'OVERDUE — {abs(rem_days):.0f} days past limit' if rem_days < 0 else f'{rem_days:.0f} days remaining'
        else:
            rem_label = status
        rows_html += f'''
        <div class="component-row">
          <div class="comp-indicator {ind_cls}"></div>
          <div class="comp-info">
            <div class="comp-name" title="{c['name']}">{c['name']}{rii_badge}</div>
            <div class="comp-hrs" style="color:{txt_color}">{rem_label}</div>
          </div>
        </div>'''
    comp_panels_html += f'''
    <div class="aircraft-panel">
      <div class="panel-header">
        <div class="panel-tail">{reg}</div>
        <div class="panel-hours">{ah} TT</div>
      </div>
      {rows_html}
    </div>'''
if not comp_panels_html:
    comp_panels_html = '<div style="font-family:var(--mono);font-size:12px;color:var(--muted);padding:20px;">No components within 200 hours across fleet.</div>'

# Build utilization rates data for bar chart
util_tails = []
util_avg_daily = []
util_avg_weekly = []
util_tt = []

for ac in aircraft_list:
    tail = ac['tail']
    stats = flight_hours_stats.get(tail, {})
    avg_daily = stats.get('avg_daily')
    util_tails.append(tail)
    util_avg_daily.append(round(avg_daily, 2) if avg_daily is not None else 0)
    util_avg_weekly.append(round(avg_daily * 7, 2) if avg_daily is not None else 0)
    util_tt.append(stats.get('current_hours') or 0)

tails_js    = '[' + ','.join(f'"{t}"' for t in util_tails) + ']'
daily_js    = '[' + ','.join(str(v) for v in util_avg_daily) + ']'
weekly_js   = '[' + ','.join(str(v) for v in util_avg_weekly) + ']'
tt_js       = '[' + ','.join(str(v) for v in util_tt) + ']'

flight_hours_tab_html = f'''
<div class="section-label">Fleet Utilization Rates</div>
<div style="font-family:var(--mono);font-size:10px;color:var(--muted);margin-bottom:20px;">
  Average based on available history. Updates as more data accumulates.
</div>
<div style="background:var(--surface);border:1px solid var(--border);border-radius:4px;padding:24px;margin-bottom:32px;">
  <canvas id="utilChart" style="width:100%;height:320px;"></canvas>
</div>
<div class="hours-grid">
'''

for ac in aircraft_list:
    tail = ac['tail']
    stats = flight_hours_stats.get(tail, {})
    avg_daily = stats.get('avg_daily')
    current_hrs = stats.get('current_hours')
    ah = f"{current_hrs:,.1f}" if current_hrs else 'N/A'
    d_str = f"{avg_daily:.2f}" if avg_daily else "—"
    w_str = f"{avg_daily*7:.1f}" if avg_daily else "—"
    m_str = f"{avg_daily*30:.1f}" if avg_daily else "—"
    flight_hours_tab_html += f'''
  <div class="hours-card">
    <div class="hours-card-header">
      <div class="hours-card-tail">{tail}</div>
      <div class="hours-card-current">{ah} TT</div>
    </div>
    <div class="hours-card-body">
      <div class="hours-stat-row"><div class="hours-stat-label">Avg Daily</div>
        <div class="hours-stat-value">{d_str} hrs</div></div>
      <div class="hours-stat-row"><div class="hours-stat-label">Avg Weekly</div>
        <div class="hours-stat-value">{w_str} hrs</div></div>
      <div class="hours-stat-row"><div class="hours-stat-label">Avg Monthly</div>
        <div class="hours-stat-value">{m_str} hrs</div></div>
    </div>
  </div>'''

flight_hours_tab_html += '</div>'

mini_charts_js = f'''
(function() {{
  var ctx = document.getElementById('utilChart');
  if (!ctx) return;
  new Chart(ctx, {{
    type: 'bar',
    data: {{
      labels: {tails_js},
      datasets: [
        {{
          label: 'Avg Daily (hrs)',
          data: {daily_js},
          backgroundColor: 'rgba(41,182,246,0.8)',
          borderColor: '#29b6f6',
          borderWidth: 1,
          yAxisID: 'yDaily'
        }},
        {{
          label: 'Avg Weekly (hrs)',
          data: {weekly_js},
          backgroundColor: 'rgba(246,173,85,0.8)',
          borderColor: '#f6ad55',
          borderWidth: 1,
          yAxisID: 'yWeekly'
        }}
      ]
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{
        legend: {{ labels: {{ color: '#a0aec0', font: {{ family: 'monospace', size: 11 }} }} }},
        datalabels: {{
          anchor: 'end', align: 'top',
          color: '#a0aec0',
          font: {{ size: 9, family: 'monospace' }},
          formatter: function(v) {{ return v > 0 ? v.toFixed(2) : ''; }}
        }}
      }},
      scales: {{
        yDaily: {{
          type: 'linear', position: 'left',
          beginAtZero: true,
          title: {{ display: true, text: 'Daily Avg (hrs)', color: '#29b6f6', font: {{ size: 10 }} }},
          ticks: {{ color: '#4a5568', font: {{ size: 10 }} }},
          grid: {{ color: 'rgba(30,37,48,0.8)' }}
        }},
        yWeekly: {{
          type: 'linear', position: 'right',
          beginAtZero: true,
          title: {{ display: true, text: 'Weekly Avg (hrs)', color: '#f6ad55', font: {{ size: 10 }} }},
          ticks: {{ color: '#4a5568', font: {{ size: 10 }} }},
          grid: {{ drawOnChartArea: false }}
        }},
        x: {{
          ticks: {{ color: '#a0aec0', font: {{ size: 10, family: 'monospace' }} }},
          grid: {{ display: false }}
        }}
      }}
    }},
    plugins: [ChartDataLabels]
  }});
}})();'''

bases_tab_html = _build_bases_tab(aircraft_list, positions)

# Calendar tab
calendar_tab_html = _build_calendar_tab(aircraft_list, flight_hours_stats)

chart_rows = sorted(
    [(ac['tail'], float(v['rem_hrs'])) for ac in aircraft_list
     if (v := ac['intervals'].get(200)) and v.get('rem_hrs') is not None],
    key=lambda x: x[1]
)
labels_js = "[" + ",".join([f"'{t}'" for t, _ in chart_rows]) + "]"
values_js = "[" + ",".join([f"{v:.2f}" for _, v in chart_rows]) + "]"

return f"""<!DOCTYPE html>
```

<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>IHC Health Services — Fleet Due List</title>
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Barlow+Condensed:wght@300;400;600;700;900&family=Barlow:wght@300;400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg:#0a0c0f; --surface:#111418; --surface2:#181c22; --border:#1e2530;
    --green:#00e676; --amber:#ffab00; --red:#ff1744; --overdue:#ff6d00;
    --blue:#29b6f6; --text:#cdd6e0; --muted:#4a5568; --heading:#e8edf2;
    --mono:'Share Tech Mono',monospace;
    --sans:'Barlow Condensed',sans-serif;
    --body:'Barlow',sans-serif;
  }}
  *{{margin:0;padding:0;box-sizing:border-box;}}
  body{{background:var(--bg);color:var(--text);font-family:var(--body);min-height:100vh;overflow-x:hidden;}}
  body::before{{content:'';position:fixed;inset:0;background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,0,0,0.03) 2px,rgba(0,0,0,0.03) 4px);pointer-events:none;z-index:1000;}}
  header{{background:var(--surface);border-bottom:1px solid var(--border);padding:18px 32px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100;}}
  .logo{{font-family:var(--sans);font-weight:900;font-size:22px;letter-spacing:3px;color:var(--heading);text-transform:uppercase;}}
  .logo span{{color:var(--blue);}}
  .subtitle{{font-family:var(--mono);font-size:11px;color:var(--muted);letter-spacing:2px;text-transform:uppercase;margin-top:3px;}}
  .header-meta{{font-family:var(--mono);font-size:11px;color:var(--muted);text-align:right;line-height:1.8;}}
  .header-meta .date{{color:var(--blue);}}
  .legend{{display:flex;gap:20px;padding:10px 32px;background:var(--surface2);border-bottom:1px solid var(--border);font-family:var(--mono);font-size:11px;flex-wrap:wrap;align-items:center;}}
  .legend-item{{display:flex;align-items:center;gap:6px;color:var(--muted);text-transform:uppercase;letter-spacing:1px;}}
  .dot{{width:8px;height:8px;border-radius:50%;flex-shrink:0;}}
  .dot-green{{background:var(--green);box-shadow:0 0 6px var(--green);}}
  .dot-amber{{background:var(--amber);box-shadow:0 0 6px var(--amber);}}
  .dot-red{{background:var(--red);box-shadow:0 0 6px var(--red);}}
  .dot-overdue{{background:var(--overdue);box-shadow:0 0 6px var(--overdue);}}
  main{{padding:24px 32px;max-width:1600px;margin:0 auto;}}
  .tabs{{display:flex;gap:0;margin-bottom:24px;border-bottom:2px solid var(--border);}}
  .tab-btn{{font-family:var(--sans);font-size:13px;font-weight:700;letter-spacing:2px;text-transform:uppercase;padding:12px 24px;background:transparent;border:none;color:var(--muted);cursor:pointer;transition:all 0.2s;border-bottom:3px solid transparent;}}
  .tab-btn:hover{{color:var(--text);background:rgba(255,255,255,0.02);}}
  .tab-btn.active{{color:var(--blue);border-bottom-color:var(--blue);}}
  .tab-content{{display:none;}}
  .tab-content.active{{display:block;}}
  .summary-bar{{display:flex;gap:16px;margin-bottom:24px;flex-wrap:wrap;}}
  .summary-stat{{background:var(--surface);border:1px solid var(--border);border-radius:4px;padding:12px 20px;min-width:130px;}}
  .stat-value{{font-family:var(--sans);font-size:32px;font-weight:900;line-height:1;margin-bottom:4px;}}
  .stat-label{{font-family:var(--mono);font-size:10px;color:var(--muted);letter-spacing:1.5px;text-transform:uppercase;}}
  .divider-line{{width:40px;height:2px;margin:8px 0;border-radius:1px;}}
  .section-label{{font-family:var(--sans);font-size:11px;font-weight:600;letter-spacing:4px;text-transform:uppercase;color:var(--muted);margin-bottom:12px;margin-top:28px;padding-bottom:6px;border-bottom:1px solid var(--border);}}
  .filter-row{{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap;}}
  .filter-btn{{font-family:var(--sans);font-size:12px;font-weight:600;letter-spacing:2px;text-transform:uppercase;padding:5px 14px;border:1px solid var(--border);background:transparent;color:var(--muted);border-radius:2px;cursor:pointer;transition:all 0.15s;}}
  .filter-btn:hover,.filter-btn.active{{background:var(--blue);border-color:var(--blue);color:#000;}}
  .chart-card{{background:var(--surface);border:1px solid var(--border);border-radius:4px;padding:14px;margin-bottom:16px;}}
  .chart-title{{font-family:var(--sans);font-weight:800;letter-spacing:2px;text-transform:uppercase;font-size:12px;color:var(--muted);margin-bottom:10px;}}
  .chart-card canvas{{display:block;width:100% !important;height:320px !important;}}
  .insp-table-wrap{{overflow-x:auto;border:1px solid var(--border);border-radius:4px;}}
  table{{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:12px;min-width:900px;}}
  thead th{{background:var(--surface2);padding:10px 14px;text-align:left;font-family:var(--sans);font-weight:700;font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--border);white-space:nowrap;}}
  thead th:first-child{{color:var(--heading);min-width:110px;}}
  tbody tr{{border-bottom:1px solid var(--border);transition:background 0.15s;}}
  tbody tr:hover{{background:rgba(255,255,255,0.02);}}
  tbody td{{padding:11px 14px;vertical-align:middle;}}
  .tail-number{{font-family:var(--sans);font-weight:700;font-size:16px;letter-spacing:1px;color:var(--heading);}}
  .airframe-hrs{{font-size:10px;color:var(--muted);margin-top:1px;}}
  .airframe-today{{font-size:10px;color:var(--blue);margin-top:1px;}}
  .location-badge{{display:inline-block;padding:2px 8px;border-radius:2px;font-size:9px;font-family:var(--mono);margin-left:8px;letter-spacing:0.5px;vertical-align:middle;}}
  .location-at-base{{background:rgba(0,230,118,0.15);color:var(--green);border:1px solid rgba(0,230,118,0.3);}}
  .location-away{{background:rgba(255,23,68,0.12);color:var(--red);border:1px solid rgba(255,23,68,0.3);}}
  .location-active{{background:rgba(41,182,246,0.12);color:var(--blue);border:1px solid rgba(41,182,246,0.3);}}
  .location-unknown{{background:rgba(74,85,104,0.2);color:var(--muted);border:1px solid rgba(74,85,104,0.3);}}
  .hr-cell{{text-align:center;min-width:80px;}}
  .hr-badge{{display:inline-block;padding:4px 10px;border-radius:3px;font-size:12px;text-align:center;min-width:56px;letter-spacing:0.5px;}}
  .hr-green{{background:rgba(0,230,118,0.08);color:var(--green);border:1px solid rgba(0,230,118,0.2);}}
  .hr-amber{{background:rgba(255,171,0,0.10);color:var(--amber);border:1px solid rgba(255,171,0,0.25);}}
  .hr-red{{background:rgba(255,23,68,0.10);color:var(--red);border:1px solid rgba(255,23,68,0.25);}}
  .hr-overdue{{background:rgba(255,109,0,0.12);color:var(--overdue);border:1px solid rgba(255,109,0,0.3);animation:pulse 2s ease-in-out infinite;}}
  .hr-na{{color:var(--muted);font-size:11px;letter-spacing:1px;}}
  @keyframes pulse{{0%,100%{{opacity:1;}}50%{{opacity:0.55;}}}}
  .components-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px;}}
  .aircraft-panel{{background:var(--surface);border:1px solid var(--border);border-radius:4px;overflow:hidden;}}
  .panel-header{{display:flex;align-items:center;justify-content:space-between;padding:10px 16px;background:var(--surface2);border-bottom:1px solid var(--border);}}
  .panel-tail{{font-family:var(--sans);font-weight:900;font-size:18px;letter-spacing:1px;color:var(--heading);}}
  .panel-hours{{font-family:var(--mono);font-size:10px;color:var(--muted);}}
  .component-row{{display:flex;align-items:center;padding:9px 16px;border-bottom:1px solid rgba(30,37,48,0.8);gap:12px;}}
  .component-row:last-child{{border-bottom:none;}}
  .comp-indicator{{width:3px;height:32px;border-radius:2px;flex-shrink:0;}}
  .comp-green{{background:var(--green);}} .comp-amber{{background:var(--amber);}}
  .comp-red{{background:var(--red);}} .comp-overdue{{background:var(--overdue);animation:pulse 2s ease-in-out infinite;}}
  .comp-info{{flex:1;min-width:0;}}
  .comp-name{{font-family:var(--body);font-size:12px;font-weight:500;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.3;}}
  .comp-hrs{{font-family:var(--mono);font-size:11px;margin-top:2px;}}
  .rii-badge{{display:inline-block;padding:1px 5px;font-size:9px;font-family:var(--mono);background:rgba(255,171,0,0.15);color:var(--amber);border:1px solid rgba(255,171,0,0.3);border-radius:2px;vertical-align:middle;margin-left:4px;letter-spacing:1px;}}
  .hours-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(380px,1fr));gap:16px;}}
  .hours-card{{background:var(--surface);border:1px solid var(--border);border-radius:4px;overflow:hidden;}}
  .hours-card-header{{padding:14px 18px;background:var(--surface2);border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;}}
  .hours-card-tail{{font-family:var(--sans);font-weight:900;font-size:18px;letter-spacing:1px;color:var(--heading);}}
  .hours-card-current{{font-family:var(--mono);font-size:11px;color:var(--muted);}}
  .hours-card-body{{padding:18px;}}
  .hours-stat-row{{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:16px;padding-bottom:12px;border-bottom:1px solid rgba(30,37,48,0.6);}}
  .hours-stat-row:last-child{{border-bottom:none;margin-bottom:0;}}
  .hours-stat-label{{font-family:var(--mono);font-size:10px;color:var(--muted);letter-spacing:1px;text-transform:uppercase;}}
  .hours-stat-value{{font-family:var(--sans);font-size:24px;font-weight:900;color:var(--heading);}}
  .hours-stat-value.positive{{color:var(--green);}} .hours-stat-value.low{{color:var(--amber);}}
  .hours-stat-sub{{font-family:var(--mono);font-size:10px;color:var(--muted);margin-top:2px;}}
  .mini-chart{{height:80px;margin-top:12px;}}
  .bases-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px;margin-bottom:24px;}}
  .base-card{{background:var(--surface);border:1px solid var(--border);border-radius:4px;overflow:hidden;}}
  .base-card.occupied{{border-color:var(--green);box-shadow:0 0 0 1px var(--green);}}
  .base-header{{padding:12px 16px;background:var(--surface2);border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;}}
  .base-name{{font-family:var(--sans);font-weight:900;font-size:18px;letter-spacing:1px;color:var(--heading);}}
  .base-capacity{{font-family:var(--mono);font-size:10px;color:var(--muted);}}
  .base-body{{padding:16px;min-height:80px;}}
  .base-aircraft{{display:flex;align-items:center;gap:10px;padding:10px;background:rgba(0,230,118,0.08);border:1px solid rgba(0,230,118,0.2);border-radius:3px;margin-bottom:8px;}}
  .base-aircraft.away{{background:rgba(255,171,0,0.10);border-color:rgba(255,171,0,0.25);}}
  .base-aircraft.airborne{{background:rgba(41,182,246,0.10);border-color:rgba(41,182,246,0.25);}}
  .base-aircraft-tail{{font-family:var(--sans);font-weight:700;font-size:14px;color:var(--heading);}}
  .base-aircraft-hours{{font-family:var(--mono);font-size:11px;color:var(--muted);margin-left:auto;}}
  .base-status-badge{{display:inline-block;padding:4px 10px;border-radius:3px;font-family:var(--mono);font-size:10px;font-weight:600;letter-spacing:1px;}}
  .base-status-at{{background:rgba(0,230,118,0.15);color:var(--green);border:1px solid rgba(0,230,118,0.3);}}
  .base-status-away{{background:rgba(255,171,0,0.15);color:var(--amber);border:1px solid rgba(255,171,0,0.3);}}
  .base-status-airborne{{background:rgba(41,182,246,0.15);color:var(--blue);border:1px solid rgba(41,182,246,0.3);}}
  .base-empty{{font-family:var(--mono);font-size:11px;color:var(--muted);text-align:center;padding:20px;}}
  .away-section{{margin-top:24px;}}
  .away-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;}}
  .away-card{{background:var(--surface);border:1px solid var(--border);border-radius:3px;padding:12px;}}
  .away-tail{{font-family:var(--sans);font-weight:700;font-size:14px;color:var(--heading);margin-bottom:4px;}}
  .away-info{{font-family:var(--mono);font-size:10px;color:var(--muted);}}
  .cal-months-wrap{{display:flex;flex-direction:column;gap:32px;}}
  footer{{margin-top:48px;padding:16px 32px;border-top:1px solid var(--border);font-family:var(--mono);font-size:10px;color:var(--muted);display:flex;justify-content:space-between;letter-spacing:1px;}}
</style>
</head>
<body>
<header>
  <div style="display:flex;align-items:center;gap:20px;">
    <div>
      <div class="logo">IHC <span>HEALTH</span> SERVICES</div>
      <img src="data:image/jpeg;base64,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"
           alt="IHC AW109SP"
           style="display:block;height:110px;width:auto;border-radius:4px;
                  margin-top:8px;margin-bottom:6px;object-fit:cover;
                  box-shadow:0 2px 12px rgba(0,0,0,0.5);">
      <div class="subtitle">AW109SP Fleet &nbsp;—&nbsp; Maintenance Due List</div>
    </div>
  </div>
  <div class="header-meta">
    <div class="date">REPORT DATE: {report_date}</div>
    <div>FLEET: {total_ac} AIRCRAFT &nbsp;|&nbsp; {airborne_count} AIRBORNE &nbsp;|&nbsp; {at_base_count} AT BASE &nbsp;|&nbsp; GENERATED: {datetime.today().strftime('%d %b %Y %H:%M').upper()}</div>
  </div>
</header>
<div class="legend">
  <div class="legend-item"><div class="dot dot-green"></div> OK (&gt;100 hrs)</div>
  <div class="legend-item"><div class="dot dot-amber"></div> Coming Due (26–100 hrs)</div>
  <div class="legend-item"><div class="dot dot-red"></div> Critical (0–25 hrs)</div>
  <div class="legend-item"><div class="dot dot-overdue"></div> Past Due / Overdue</div>
  <div style="margin-left:auto;font-family:var(--mono);font-size:11px;color:var(--muted);letter-spacing:1px;">— = Not due this cycle</div>
</div>
<main>
  <div class="tabs">
    <button class="tab-btn active" onclick="switchTab('maintenance',this)">Maintenance Due List</button>
    <button class="tab-btn" onclick="switchTab('flight-hours',this)">Flight Hours Tracking</button>
    <button class="tab-btn" onclick="switchTab('calendar',this)">Calendar</button>
    <button class="tab-btn" onclick="switchTab('bases',this)">Bases</button>
  </div>

  <!-- MAINTENANCE TAB -->

  <div id="tab-maintenance" class="tab-content active">
    <div class="summary-bar">
      <div class="summary-stat"><div class="stat-value" style="color:var(--blue)">{total_ac}</div><div class="divider-line" style="background:var(--blue)"></div><div class="stat-label">Aircraft</div></div>
      <div class="summary-stat"><div class="stat-value" style="color:var(--blue)">{airborne_count}</div><div class="divider-line" style="background:var(--blue)"></div><div class="stat-label">Airborne</div></div>
      <div class="summary-stat"><div class="stat-value" style="color:var(--red)">{crit_count}</div><div class="divider-line" style="background:var(--red)"></div><div class="stat-label">Insp. Critical / OD</div></div>
      <div class="summary-stat"><div class="stat-value" style="color:var(--amber)">{coming_count}</div><div class="divider-line" style="background:var(--amber)"></div><div class="stat-label">Insp. Coming Due</div></div>
      <div class="summary-stat"><div class="stat-value" style="color:var(--overdue)">{comp_overdue}</div><div class="divider-line" style="background:var(--overdue)"></div><div class="stat-label">Components Overdue</div></div>
    </div>
    <div class="chart-card">
      <div class="chart-title">200 Hr Remaining (Bar)</div>
      <canvas id="bar200"></canvas>
    </div>
    <div class="section-label">Scheduled Phase Inspections — Hours Remaining</div>
    <div class="filter-row">
      <button class="filter-btn active" onclick="filterTable('all',this)">All</button>
      <button class="filter-btn" onclick="filterTable('overdue',this)">Past Due</button>
      <button class="filter-btn" onclick="filterTable('critical',this)">Critical</button>
      <button class="filter-btn" onclick="filterTable('coming',this)">Coming Due</button>
      <button class="filter-btn" onclick="filterTable('ok',this)">OK</button>
    </div>
    <div class="insp-table-wrap">
      <table>
        <thead>
          <tr>
            <th>Aircraft</th>
            <th class="hr-cell">50 Hr</th><th class="hr-cell">100 Hr</th>
            <th class="hr-cell">200 Hr</th><th class="hr-cell">400 Hr</th>
            <th class="hr-cell">800 Hr</th><th class="hr-cell">2400 Hr</th>
            <th class="hr-cell">3200 Hr</th>
            <th class="hr-cell">Transponder Cert</th>
          </tr>
        </thead>
        <tbody id="insp-tbody">
{table_rows_html}
        </tbody>
      </table>
    </div>
    <div class="section-label" style="margin-top:36px;">Component Retirement / Overhaul — Within {COMPONENT_WINDOW_HRS} Hours</div>
    <div class="components-grid">{comp_panels_html}</div>
  </div>

  <!-- FLIGHT HOURS TAB -->

  <div id="tab-flight-hours" class="tab-content">
{flight_hours_tab_html}
  </div>

  <!-- CALENDAR TAB -->

  <div id="tab-calendar" class="tab-content">
{calendar_tab_html}
  </div>

  <!-- BASES TAB -->

  <div id="tab-bases" class="tab-content">
{bases_tab_html}
  </div>
</main>
<footer>
  <span>SOURCE: VERYON MAINTENANCE TRACKING &nbsp;|&nbsp; {source_filename}</span>
  <span>IHC HEALTH SERVICES — AVIATION MAINTENANCE</span>
</footer>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2"></script>
<script>
  function switchTab(tabName, btn) {{
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.getElementById('tab-' + tabName).classList.add('active');
  }}
  function filterTable(filter, btn) {{
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.querySelectorAll('#insp-tbody tr').forEach(tr => {{
      const badges = tr.querySelectorAll('.hr-badge, .hr-na');
      let show = filter === 'all';
      if (!show) {{
        badges.forEach(b => {{
          const cls = b.className;
          if (filter === 'overdue' && cls.includes('hr-overdue')) show = true;
          if (filter === 'critical' && cls.includes('hr-red'))    show = true;
          if (filter === 'coming'   && cls.includes('hr-amber'))  show = true;
          if (filter === 'ok'       && cls.includes('hr-green'))  show = true;
        }});
      }}
      tr.style.display = show ? '' : 'none';
    }});
  }}
  const labels200 = {labels_js};
  const values200 = {values_js};
  if (!labels200 || labels200.length === 0) {{
    document.getElementById('bar200').parentElement.innerHTML =
      "<div style='font-family:var(--mono);font-size:12px;color:var(--muted);padding:10px;'>No numeric 200-hr remaining hours found.</div>";
  }} else {{
    new Chart(document.getElementById('bar200'), {{
      type: 'bar',
      data: {{ labels: labels200, datasets: [{{ label: 'Hours remaining to 200 Hr', data: values200, backgroundColor: '#29b6f6' }}] }},
      options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{
          legend: {{ display: true }},
          datalabels: {{
            anchor: 'end', align: 'top',
            color: '#cdd6e0',
            font: {{ family: 'Share Tech Mono', size: 11 }},
            formatter: function(value) {{ return value.toFixed(1); }}
          }}
        }},
        scales: {{
          y: {{ beginAtZero: true, title: {{ display: true, text: 'Hours Remaining' }} }},
          x: {{ title: {{ display: true, text: 'Aircraft (closest first)' }} }}
        }}
      }},
      plugins: [ChartDataLabels]
    }});
  }}
  {mini_charts_js}

// ── EDITABLE CALENDAR ─────────────────────────────────────────────────────
(function() {{
var STORAGE_KEY = ‘ihc_cal_notes’;

```
function loadNotes() {{
  try {{ return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{{}}'); }} catch(e) {{ return {{}}; }}
}}
function saveNotes(notes) {{
  localStorage.setItem(STORAGE_KEY, JSON.stringify(notes));
}}

function renderUserEvents() {{
  var notes = loadNotes();
  Object.keys(notes).forEach(function(dateKey) {{
    var note = notes[dateKey];
    if (!note || (!note.text && !note.label)) return;
    var cell = document.querySelector('.cal-day[data-date="' + dateKey + '"]');
    if (!cell) return;
    var existing = cell.querySelector('.cal-user-ev');
    if (existing) existing.remove();
    var el = document.createElement('div');
    el.className = 'cal-user-ev';
    el.textContent = (note.label || 'NOTE') + (note.text ? ': ' + note.text : '');
    el.title = note.text || '';
    cell.appendChild(el);
  }});
}}

function openModal(dateKey) {{
  var notes = loadNotes();
  var existing = notes[dateKey] || {{}};
  var modal = document.getElementById('cal-modal');
  document.getElementById('cal-modal-date').textContent = dateKey;
  document.getElementById('cal-modal-label').value = existing.label || '';
  document.getElementById('cal-modal-text').value = existing.text || '';
  document.getElementById('cal-modal-color').value = existing.color || '#f6ad55';
  modal.style.display = 'flex';
  document.getElementById('cal-modal-text').focus();
}}

function closeModal() {{
  document.getElementById('cal-modal').style.display = 'none';
}}

function saveModal() {{
  var dateKey = document.getElementById('cal-modal-date').textContent;
  var label = document.getElementById('cal-modal-label').value.trim();
  var text  = document.getElementById('cal-modal-text').value.trim();
  var color = document.getElementById('cal-modal-color').value;
  var notes = loadNotes();
  if (label || text) {{
    notes[dateKey] = {{ label: label, text: text, color: color }};
  }} else {{
    delete notes[dateKey];
  }}
  saveNotes(notes);
  closeModal();
  renderUserEvents();
}}

function clearModal() {{
  var dateKey = document.getElementById('cal-modal-date').textContent;
  var notes = loadNotes();
  delete notes[dateKey];
  saveNotes(notes);
  closeModal();
  renderUserEvents();
}}

// Attach click handlers to all cal-day cells
document.querySelectorAll('.cal-day').forEach(function(cell) {{
  cell.style.cursor = 'pointer';
  cell.addEventListener('click', function() {{
    var dateKey = cell.getAttribute('data-date');
    if (dateKey) openModal(dateKey);
  }});
}});

document.getElementById('cal-modal-save').addEventListener('click', saveModal);
document.getElementById('cal-modal-clear').addEventListener('click', clearModal);
document.getElementById('cal-modal-cancel').addEventListener('click', closeModal);
document.getElementById('cal-modal').addEventListener('click', function(e) {{
  if (e.target === this) closeModal();
}});

renderUserEvents();
```

}})();
</script>

<!-- Calendar Note Modal -->

<div id="cal-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.7);
  z-index:9999;align-items:center;justify-content:center;">
  <div style="background:#0d1117;border:1px solid #29b6f6;border-radius:6px;padding:28px;
    min-width:340px;max-width:480px;width:90%;font-family:monospace;">
    <div style="font-size:11px;color:#4a9eff;letter-spacing:2px;margin-bottom:4px;">SCHEDULE / NOTE</div>
    <div id="cal-modal-date" style="font-size:16px;color:#e2e8f0;font-weight:700;margin-bottom:20px;"></div>
    <label style="display:block;font-size:10px;color:#718096;letter-spacing:1px;margin-bottom:4px;">LABEL (e.g. 50 HR INSP)</label>
    <input id="cal-modal-label" type="text" maxlength="30"
      style="width:100%;box-sizing:border-box;background:#161c25;border:1px solid #2d3748;
      border-radius:3px;color:#e2e8f0;padding:8px;font-family:monospace;font-size:13px;margin-bottom:14px;">
    <label style="display:block;font-size:10px;color:#718096;letter-spacing:1px;margin-bottom:4px;">NOTES</label>
    <textarea id="cal-modal-text" rows="3" maxlength="200"
      style="width:100%;box-sizing:border-box;background:#161c25;border:1px solid #2d3748;
      border-radius:3px;color:#e2e8f0;padding:8px;font-family:monospace;font-size:12px;
      resize:vertical;margin-bottom:14px;"></textarea>
    <label style="display:block;font-size:10px;color:#718096;letter-spacing:1px;margin-bottom:4px;">COLOR</label>
    <input id="cal-modal-color" type="color" value="#f6ad55"
      style="width:48px;height:32px;border:none;background:none;cursor:pointer;margin-bottom:20px;">
    <div style="display:flex;gap:10px;justify-content:flex-end;">
      <button id="cal-modal-clear"
        style="background:transparent;border:1px solid #c0392b;color:#c0392b;
        padding:7px 16px;border-radius:3px;cursor:pointer;font-family:monospace;font-size:11px;">
        CLEAR</button>
      <button id="cal-modal-cancel"
        style="background:transparent;border:1px solid #4a5568;color:#718096;
        padding:7px 16px;border-radius:3px;cursor:pointer;font-family:monospace;font-size:11px;">
        CANCEL</button>
      <button id="cal-modal-save"
        style="background:#29b6f6;border:none;color:#000;
        padding:7px 16px;border-radius:3px;cursor:pointer;font-family:monospace;font-size:11px;font-weight:700;">
        SAVE</button>
    </div>
  </div>
</div>
</body>
</html>"""

def _build_calendar_tab(aircraft_list, flight_hours_stats):
“”“Build a month-view calendar with projected maintenance due dates.”””
import calendar as cal_mod

```
today = datetime.today()

# Collect all projected events: {date_str: [(tail, interval, urgency), ...]}
events = {}
fallback_cards = []

for ac in aircraft_list:
    tail = ac['tail']
    current_hrs = ac['airframe_hrs']
    if current_hrs is None:
        continue

    stats = flight_hours_stats.get(tail, {})
    avg_daily = stats.get('avg_daily')

    if not avg_daily or avg_daily <= 0:
        rows = []
        for interval in TARGET_INTERVALS:
            v = ac['intervals'].get(interval)
            if v is None:
                continue
            rem_hrs = v.get('rem_hrs')
            if rem_hrs is None:
                continue
            if rem_hrs < 0:
                cls = 'cal-ev-overdue'
                label = 'OVERDUE'
            elif rem_hrs <= 25:
                cls = 'cal-ev-urgent'
                label = f'{rem_hrs:.0f} hrs'
            elif rem_hrs <= 100:
                cls = 'cal-ev-soon'
                label = f'{rem_hrs:.0f} hrs'
            else:
                cls = ''
                label = f'{rem_hrs:.0f} hrs'
            rows.append(
                f'<div class="cal-fb-row"><span class="cal-fb-insp">{interval} Hr</span>'
                f'<span class="cal-fb-val {cls}">{label}</span></div>'
            )
        if rows:
            ah = f'{current_hrs:,.1f}' if current_hrs else 'N/A'
            fallback_cards.append(
                f'<div class="cal-fb-card"><div class="cal-fb-head">'
                f'<span class="cal-fb-tail">{tail}</span>'
                f'<span class="cal-fb-hrs">{ah} TT &mdash; no utilization data</span>'
                f'</div>{"".join(rows)}</div>'
            )
        continue

    for interval in TARGET_INTERVALS:
        v = ac['intervals'].get(interval)
        if v is None:
            continue
        rem_hrs = v.get('rem_hrs')
        if rem_hrs is None:
            continue

        if rem_hrs < 0:
            due_date = today
            urgency = 'overdue'
        else:
            days_until = rem_hrs / avg_daily
            due_date = today + timedelta(days=days_until)
            if days_until <= 30:
                urgency = 'urgent'
            elif days_until <= 90:
                urgency = 'soon'
            else:
                urgency = 'ok'

        key = due_date.strftime('%Y-%m-%d')
        events.setdefault(key, []).append((tail, interval, urgency))

# Build 3-month calendar view
months_html = ''
for month_offset in range(3):
    m = today.month + month_offset
    y = today.year + (m - 1) // 12
    m = ((m - 1) % 12) + 1

    month_name = datetime(y, m, 1).strftime('%B %Y').upper()
    first_dow = datetime(y, m, 1).weekday()  # 0=Monday
    days_in_month = cal_mod.monthrange(y, m)[1]

    day_headers = ''.join(
        f'<div class="cal-dow">{d}</div>'
        for d in ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN']
    )

    cells = '<div class="cal-empty"></div>' * first_dow

    for day in range(1, days_in_month + 1):
        date_key = f'{y}-{m:02d}-{day:02d}'
        day_events = events.get(date_key, [])
        is_today = (y == today.year and m == today.month and day == today.day)
        today_cls = ' cal-today' if is_today else ''

        if day_events:
            if any(e[2] == 'overdue' for e in day_events):
                cell_cls = 'cal-day-overdue'
            elif any(e[2] == 'urgent' for e in day_events):
                cell_cls = 'cal-day-urgent'
            elif any(e[2] == 'soon' for e in day_events):
                cell_cls = 'cal-day-soon'
            else:
                cell_cls = 'cal-day-ok'

            ev_html = ''
            for t, interval, urgency in day_events:
                ev_cls = f'cal-ev-{urgency}'
                ev_html += f'<div class="cal-ev {ev_cls}">{t} {interval}h</div>'

            cells += (
                f'<div class="cal-day {cell_cls}{today_cls}" data-date="{date_key}">'
                f'<div class="cal-day-num">{day}</div>{ev_html}</div>'
            )
        else:
            is_past = (y == today.year and m == today.month and day < today.day)
            past_cls = ' cal-past' if is_past else ''
            cells += (
                f'<div class="cal-day{today_cls}{past_cls}" data-date="{date_key}">'
                f'<div class="cal-day-num">{day}</div></div>'
            )

    months_html += (
        f'<div class="cal-month">'
        f'<div class="cal-month-title">{month_name}</div>'
        f'<div class="cal-grid-days">{day_headers}{cells}</div>'
        f'</div>'
    )

fallback_html = ''
if fallback_cards:
    fallback_html = (
        f'<div class="section-label" style="margin-top:32px;">AIRCRAFT WITHOUT UTILIZATION DATA</div>'
        f'<div style="font-family:var(--mono);font-size:10px;color:var(--muted);margin-bottom:12px;">'
        f'Showing hours remaining. Projected dates appear once utilization history accumulates.</div>'
        f'<div class="cal-fb-grid">{"".join(fallback_cards)}</div>'
    )

legend_html = (
    '<div class="cal-legend">'
    '<span class="cal-leg-item"><span class="cal-leg-dot cal-ev-overdue"></span>OVERDUE</span>'
    '<span class="cal-leg-item"><span class="cal-leg-dot cal-ev-urgent"></span>DUE &le;30 DAYS</span>'
    '<span class="cal-leg-item"><span class="cal-leg-dot cal-ev-soon"></span>DUE &le;90 DAYS</span>'
    '<span class="cal-leg-item"><span class="cal-leg-dot cal-ev-ok"></span>SCHEDULED</span>'
    '</div>'
)

css = (
    '<style>'
    '.cal-months-wrap{display:flex;flex-direction:column;gap:32px;}'
    '.cal-month{width:100%;}'
    '.cal-month-title{font-family:var(--mono);font-size:11px;font-weight:700;'
    'color:var(--cyan);letter-spacing:2px;margin-bottom:8px;}'
    '.cal-grid-days{display:grid;grid-template-columns:repeat(7,1fr);gap:2px;}'
    '.cal-dow{font-family:var(--mono);font-size:9px;color:var(--muted);'
    'text-align:center;padding:4px 0;letter-spacing:1px;}'
    '.cal-empty{background:transparent;min-height:60px;}'
    '.cal-day{background:#0d1117;border:1px solid #1e2533;border-radius:3px;'
    'min-height:60px;padding:4px;position:relative;overflow:hidden;}'
    '.cal-day-num{font-family:var(--mono);font-size:9px;color:var(--muted);margin-bottom:2px;}'
    '.cal-today{border-color:var(--cyan)!important;}'
    '.cal-today .cal-day-num{color:var(--cyan);font-weight:700;}'
    '.cal-past{opacity:0.4;}'
    '.cal-day-overdue{background:#2a0a0a;border-color:#c0392b;}'
    '.cal-day-urgent{background:#1a1200;border-color:#e67e22;}'
    '.cal-day-soon{background:#0d1a0d;border-color:#f39c12;}'
    '.cal-day-ok{background:#0a1520;border-color:#2980b9;}'
    '.cal-ev{font-family:var(--mono);font-size:8px;padding:1px 3px;'
    'border-radius:2px;margin-bottom:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}'
    '.cal-ev-overdue{background:#c0392b;color:#fff;}'
    '.cal-ev-urgent{background:#e67e22;color:#000;}'
    '.cal-ev-soon{background:#f39c12;color:#000;}'
    '.cal-ev-ok{background:#2980b9;color:#fff;}'
    '.cal-legend{display:flex;gap:20px;margin-bottom:20px;font-family:var(--mono);'
    'font-size:10px;color:var(--muted);flex-wrap:wrap;}'
    '.cal-leg-item{display:flex;align-items:center;gap:6px;}'
    '.cal-leg-dot{width:10px;height:10px;border-radius:2px;display:inline-block;}'
    '.cal-fb-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px;}'
    '.cal-fb-card{background:#0d1117;border:1px solid #1e2533;border-radius:4px;padding:12px;}'
    '.cal-fb-head{display:flex;justify-content:space-between;align-items:baseline;'
    'margin-bottom:8px;border-bottom:1px solid #1e2533;padding-bottom:6px;}'
    '.cal-fb-tail{font-family:var(--mono);font-size:13px;font-weight:700;color:var(--cyan);}'
    '.cal-fb-hrs{font-family:var(--mono);font-size:9px;color:var(--muted);}'
    '.cal-fb-row{display:flex;justify-content:space-between;font-family:var(--mono);'
    'font-size:11px;padding:3px 0;border-bottom:1px solid #161c25;}'
    '.cal-fb-insp{color:var(--muted);}'
    '.cal-fb-val{font-weight:700;}'
    '.cal-user-ev{font-family:var(--mono);font-size:8px;padding:2px 4px;border-radius:2px;'
    'margin-bottom:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'
    'background:#2d3748;color:#e2e8f0;border-left:3px solid #f6ad55;}'
    '</style>'
)

return (
    f'{css}'
    f'<div class="section-label">PROJECTED MAINTENANCE CALENDAR</div>'
    f'<div style="font-family:var(--mono);font-size:10px;color:var(--muted);margin-bottom:16px;">'
    f'Dates projected from average daily utilization. Actual dates will vary.</div>'
    f'{legend_html}'
    f'<div class="cal-months-wrap">{months_html}</div>'
    f'{fallback_html}'
)
```

def _build_bases_tab(aircraft_list, positions):
if not positions:
return ‘<div style="font-family:var(--mono);font-size:12px;color:var(--muted);padding:20px;">No position data available. Runs after fetch_positions.py completes.</div>’

```
base_buckets = {}
away_list    = []
airborne_list = []
ac_hrs = {ac['tail']: ac['airframe_hrs'] for ac in aircraft_list}

for ac in aircraft_list:
    tail    = ac['tail']
    pos     = positions.get(tail, {})
    status  = pos.get('status', 'UNKNOWN')
    curr    = pos.get('current_base')
    near    = pos.get('nearest_base')
    hrs     = ac_hrs.get(tail)

    if status == 'AIRBORNE':
        airborne_list.append({'tail': tail, 'hrs': hrs, 'pos': pos})
    elif status == 'AT_BASE' and curr:
        bid = curr.get('id', 'UNKNOWN')
        base_buckets.setdefault(bid, {'name': curr.get('name', bid), 'aircraft': []})
        base_buckets[bid]['aircraft'].append({'tail': tail, 'hrs': hrs, 'dist_nm': curr.get('dist_nm'), 'pos': pos})
    else:
        away_list.append({'tail': tail, 'hrs': hrs, 'pos': pos, 'nearest': near})

base_cards_html = ''
for bid, bdata in sorted(base_buckets.items()):
    count = len(bdata['aircraft'])
    occupied_cls = 'occupied' if count else ''
    aircraft_html = ''
    for a in bdata['aircraft']:
        hrs_str  = f"{a['hrs']:,.1f} TT" if a['hrs'] else 'N/A'
        dist_str = f"{a['dist_nm']} nm" if a['dist_nm'] else ''
        aircraft_html += f'''
        <div class="base-aircraft">
          <div class="base-aircraft-tail">{a['tail']}</div>
          <span class="base-status-badge base-status-at">AT BASE</span>
          <div class="base-aircraft-hours">{hrs_str} {dist_str}</div>
        </div>'''
    if not aircraft_html:
        aircraft_html = '<div class="base-empty">No aircraft</div>'
    base_cards_html += f'''
    <div class="base-card {occupied_cls}">
      <div class="base-header">
        <div class="base-name">{bdata["name"]}</div>
        <div class="base-capacity">{count} aircraft</div>
      </div>
      <div class="base-body">{aircraft_html}</div>
    </div>'''

airborne_html = ''
if airborne_list:
    cards = ''
    for a in airborne_list:
        hrs_str = f"{a['hrs']:,.1f} TT" if a['hrs'] else 'N/A'
        alt     = a['pos'].get('last_alt_ft', '')
        gs      = a['pos'].get('last_gs_kts', '')
        cards += f'''
        <div class="away-card">
          <div class="away-tail">{a['tail']}</div>
          <div class="away-info" style="color:var(--blue);">AIRBORNE</div>
          <div class="away-info">{hrs_str}</div>
          <div class="away-info">{alt}ft · {gs}kts</div>
        </div>'''
    airborne_html = f'''
    <div class="away-section">
      <div class="section-label">Currently Airborne</div>
      <div class="away-grid">{cards}</div>
    </div>'''

away_html = ''
if away_list:
    cards = ''
    for a in away_list:
        hrs_str  = f"{a['hrs']:,.1f} TT" if a['hrs'] else 'N/A'
        near     = a.get('nearest')
        near_str = f"{near.get('dist_nm','?')} nm from {near.get('name','?')}" if near else 'Position unknown'
        cards += f'''
        <div class="away-card">
          <div class="away-tail">{a['tail']}</div>
          <div class="away-info" style="color:var(--amber);">AWAY FROM BASE</div>
          <div class="away-info">{hrs_str}</div>
          <div class="away-info">{near_str}</div>
        </div>'''
    away_html = f'''
    <div class="away-section">
      <div class="section-label">Away From Base</div>
      <div class="away-grid">{cards}</div>
    </div>'''

fetched_at = positions.get(list(positions.keys())[0], {}).get('last_updated', '') if positions else ''

return f'''
<div class="section-label">Aircraft Base Assignments — Live ADSB</div>
<div style="font-family:var(--mono);font-size:10px;color:var(--muted);margin-bottom:16px;">Last updated: {fetched_at}</div>
<div class="bases-grid">{base_cards_html}</div>
{airborne_html}
{away_html}'''
```

# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
data_dir       = Path(OUTPUT_FOLDER)
input_path     = data_dir / INPUT_FILENAME
weekly_path    = data_dir / WEEKLY_FILENAME
output_path    = Path(OUTPUT_FOLDER) / OUTPUT_FILENAME
history_path   = Path(OUTPUT_FOLDER) / HISTORY_FILENAME
positions_path = Path(OUTPUT_FOLDER) / POSITIONS_FILENAME
log_path       = Path(**file**).with_name(“dashboard_log.txt”)

```
def log(msg):
    ts   = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass

log("Dashboard generator started.")

if not input_path.exists():
    for fallback in INPUT_FALLBACKS:
        candidate = data_dir / fallback
        if candidate.exists():
            input_path = candidate
            log(f"Primary input missing. Using fallback file: {input_path}")
            break

if not input_path.exists():
    log(f"WARNING: Input file not found: {input_path}")
    log("Previous dashboard left in place. Will retry next run.")
    sys.exit(0)

file_age_hrs = (datetime.now().timestamp() - input_path.stat().st_mtime) / 3600
if file_age_hrs > 36:
    log(f"WARNING: Input file is {file_age_hrs:.1f} hours old. May not be today's data.")

if not weekly_path.exists():
    for fallback in WEEKLY_FALLBACKS:
        candidate = data_dir / fallback
        if candidate.exists():
            weekly_path = candidate
            log(f"Primary weekly file missing. Using fallback file: {weekly_path}")
            break

if not weekly_path.exists():
    log(f"WARNING: Weekly file not found: {weekly_path} (long-range inspections will stay blank)")

try:
    log(f"Parsing {input_path} ...")
    report_date, aircraft_list, components = parse_due_list(input_path, weekly_path)
    log(f"Parsed {len(aircraft_list)} aircraft.")

    log("Loading flight hours history...")
    history_data    = load_flight_hours_history(history_path)
    report_date_dt  = next((ac['report_date'] for ac in aircraft_list if ac.get('report_date')), None)
    history_data    = update_flight_hours_history(history_data, aircraft_list, report_date_dt)
    save_flight_hours_history(history_path, history_data)
    flight_hours_stats = calculate_flight_hours_stats(history_data, aircraft_list)
    log("Flight hours stats calculated.")

    log("Loading ADSB positions...")
    positions = load_positions(positions_path)
    if positions:
        log(f"Loaded positions for {len(positions)} aircraft.")
    else:
        log("No positions data (fetch_positions.py may not have run yet).")

    html = build_html(
        report_date,
        aircraft_list,
        components,
        flight_hours_stats,
        positions,
        input_path.name,
    )

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    log(f"Dashboard written to {output_path}")
    log("Done.")

except Exception as e:
    log(f"ERROR: {e}")
    import traceback
    log(traceback.format_exc())
    log("Previous dashboard left in place.")
    sys.exit(1)
```

if **name** == ‘**main**’:
main()