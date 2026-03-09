"""
Fleet Maintenance Dashboard Generator (CSV)
==========================================
Reads Due-List_BIG_WEEKLY_aw109sp.csv from the data/ folder
and writes data/index.html + data/flight_hours_history.json.

Run via GitHub Actions after CSV is pushed to repo.
"""

import sys
import csv
import re
import json
import base64
import io
from datetime import datetime, timedelta, date
from pathlib import Path

try:
    from PIL import Image as _PILImage
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

# â”€â”€ CONFIGURATION â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

OUTPUT_FOLDER = "data"

INPUT_FILENAME  = "Due-List_BIG_WEEKLY_aw109sp.csv"
INPUT_FALLBACKS = ["Due-List_BIG_WEEKLY.csv"]
OUTPUT_FILENAME = "index.html"
HISTORY_FILENAME   = "flight_hours_history.json"
POSITIONS_FILENAME = "base_assignments.json"
PHOTO_FILENAME     = "IMG_9250.jpeg"

TARGET_INTERVALS = [50, 100, 200, 400, 800, 2400, 3200]

PHASE_MATCH = {
    50:   [r"05 1000"],
    100:  [r"64 01\[273\]"],
    200:  [r"05 1005"],
    400:  [r"05 1010"],
    800:  [r"05 1015"],
    2400: [r"62 11\[373\]"],
    3200: [r"05 1020"],
}

COMPONENT_WINDOW_HRS = 200

RETIREMENT_KEYWORDS = [
    'RETIRE', 'OVERHAUL', 'DISCARD', 'LIFE LIMIT', 'TBO',
    'REPLACEMENT', 'REPLACE', 'CHANGE OIL', 'NOZZLE'
]

# â”€â”€ COLUMN INDICES (0-based) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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


# â”€â”€ HELPERS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def safe_float(val):
    if val is None:
        return None
    s = str(val).strip()
    if s == "":
        return None
    try:
        return float(s.replace(",", ""))
    except (ValueError, TypeError):
        return None


def classify(hrs):
    if hrs is None:
        return 'na'
    if hrs < 0:
        return 'overdue'
    if hrs <= 25:
        return 'red'
    if hrs <= 100:
        return 'amber'
    return 'green'


def classify_from_status(status_str):
    if not status_str:
        return 'na'
    s = str(status_str).strip().upper()
    if 'PAST DUE' in s:
        return 'overdue'
    if 'COMING DUE' in s:
        return 'amber'
    if 'WITHIN TOLERANCE' in s or '10+' in s:
        return 'green'
    return 'na'


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
        "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y",
        "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y %H:%M:%S",
    ]
    for f in fmts:
        try:
            return datetime.strptime(s, f)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def load_photo_b64(data_dir):
    """Load and resize the fleet photo, return base64 string or empty string."""
    # Search in data/ dir, repo root, and next to this script
    candidates = [
        data_dir / PHOTO_FILENAME,
        Path(__file__).parent.parent / PHOTO_FILENAME,
        Path(__file__).parent / PHOTO_FILENAME,
        Path(PHOTO_FILENAME),
    ]
    photo_path = next((p for p in candidates if p.exists()), None)
    if photo_path is None:
        return ''
    try:
        if _HAS_PIL:
            img = _PILImage.open(str(photo_path))
            # Resize to 120px tall (displayed at 60px, 2x for retina)
            ratio = 120 / img.height
            new_w = int(img.width * ratio)
            img = img.resize((new_w, 120), _PILImage.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, 'JPEG', quality=85, optimize=True)
            return base64.b64encode(buf.getvalue()).decode('ascii')
        else:
            with open(photo_path, 'rb') as f:
                return base64.b64encode(f.read()).decode('ascii')
    except Exception as e:
        print(f"Warning: could not load photo: {e}")
        return ''


# â”€â”€ FLIGHT HOURS TRACKING â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def load_flight_hours_history(history_path):
    if not history_path.exists():
        return {}
    try:
        with open(history_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_flight_hours_history(history_path, history_data):
    try:
        with open(history_path, 'w', encoding='utf-8') as f:
            json.dump(history_data, f, indent=2)
    except Exception as e:
        print(f"Warning: Could not save flight hours history: {e}")


def update_flight_hours_history(history_data, aircraft_list, report_date_dt):
    if not report_date_dt:
        report_date_dt = datetime.today()
    date_key = report_date_dt.strftime("%Y-%m-%d")
    for ac in aircraft_list:
        tail = ac['tail']
        hours = ac['airframe_hrs']
        if hours is None:
            continue
        if tail not in history_data:
            history_data[tail] = {}
        if date_key not in history_data[tail] or history_data[tail][date_key]['hours'] != hours:
            history_data[tail][date_key] = {'hours': hours, 'date': date_key}
    cutoff_date = (datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d")
    for tail in history_data:
        history_data[tail] = {
            d: v for d, v in history_data[tail].items() if d >= cutoff_date
        }
    return history_data


def calculate_flight_hours_stats(history_data, aircraft_list):
    today = datetime.today()
    seven_days_ago  = today - timedelta(days=7)
    thirty_days_ago = today - timedelta(days=30)
    stats = {}
    for ac in aircraft_list:
        tail = ac['tail']
        current_hours = ac['airframe_hrs']
        if tail not in history_data or current_hours is None:
            stats[tail] = {
                'current_hours': current_hours, 'daily': [],
                'weekly': None, 'monthly': None,
                'avg_daily': None, 'projection_weekly': None, 'projection_monthly': None
            }
            continue
        tail_history = history_data[tail]
        sorted_dates = sorted(tail_history.keys(), reverse=True)
        daily_data = []
        for ds in sorted_dates[:7]:
            daily_data.insert(0, {'date': ds, 'hours': tail_history[ds]['hours']})
        weekly_hours = monthly_hours = None
        seven_str  = seven_days_ago.strftime("%Y-%m-%d")
        thirty_str = thirty_days_ago.strftime("%Y-%m-%d")
        if len(sorted_dates) >= 2:
            latest = tail_history[sorted_dates[0]]['hours']
            for ds in sorted_dates:
                if ds <= seven_str:
                    weekly_hours = latest - tail_history[ds]['hours']
                    break
            for ds in sorted_dates:
                if ds <= thirty_str:
                    monthly_hours = latest - tail_history[ds]['hours']
                    break
        avg_daily = proj_weekly = proj_monthly = None
        if monthly_hours is not None:
            span = (today - datetime.strptime(thirty_str, "%Y-%m-%d")).days
            if span > 0:
                avg_daily = monthly_hours / span
        elif weekly_hours is not None:
            span = (today - datetime.strptime(seven_str, "%Y-%m-%d")).days
            if span > 0:
                avg_daily = weekly_hours / span
        elif len(sorted_dates) >= 2:
            oldest = sorted_dates[-1]
            newest = sorted_dates[0]
            span = (datetime.strptime(newest, "%Y-%m-%d") - datetime.strptime(oldest, "%Y-%m-%d")).days
            if span > 0:
                span_hrs = tail_history[newest]['hours'] - tail_history[oldest]['hours']
                avg_daily = span_hrs / span
        if avg_daily is not None:
            proj_weekly  = avg_daily * 7
            proj_monthly = avg_daily * 30
        stats[tail] = {
            'current_hours': current_hours, 'daily': daily_data,
            'weekly': weekly_hours, 'monthly': monthly_hours,
            'avg_daily': avg_daily,
            'projection_weekly': proj_weekly,
            'projection_monthly': proj_monthly,
        }
    return stats


# â”€â”€ POSITIONS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def load_positions(positions_path):
    if not positions_path.exists():
        return {}
    try:
        with open(positions_path, 'r', encoding='utf-8') as f:
            raw = f.read().strip()
        if not raw:
            return {}
        data = json.loads(raw)
    except Exception:
        return {}

    assignments  = data.get('assignments', {})
    bases_meta   = data.get('bases', {})
    last_updated = data.get('last_updated', '')
    result = {}

    for base_id, base_data in assignments.items():
        if base_id == 'unassigned':
            ac_list = base_data if isinstance(base_data, list) else []
            for ac in ac_list:
                tail = ac.get('tail') or ac.get('registration', '')
                if not tail:
                    continue
                result[tail] = {
                    'status': 'AWAY',
                    'current_base': None,
                    'nearest_base': None,
                    'last_alt_ft': ac.get('altitude', ''),
                    'last_gs_kts': ac.get('ground_speed', ''),
                    'last_updated': last_updated,
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
                result[tail] = {
                    'status': status,
                    'current_base': curr_base,
                    'nearest_base': None,
                    'last_alt_ft': ac.get('altitude', ''),
                    'last_gs_kts': ac.get('ground_speed', ''),
                    'last_updated': last_updated,
                }

    return result


def get_location_badge(tail, positions):
    ac = positions.get(tail, {})
    if not ac:
        return ''
    status = ac.get('status', '').upper()
    curr   = ac.get('current_base')
    if status == 'AIRBORNE':
        alt = ac.get('last_alt_ft', '')
        alt_str = f" {alt}ft" if alt else ''
        return f'<span class="location-badge location-active">AIRBORNE{alt_str}</span>'
    if status == 'AT_BASE':
        name = curr.get('name', '') if curr else ''
        label = 'AT BASE' + (f' Â· {name}' if name else '')
        return f'<span class="location-badge location-at-base">{label}</span>'
    if status == 'AWAY':
        near = ac.get('nearest_base')
        near_str = ''
        if near:
            near_str = f" Â· {near.get('dist_nm', '?')}nm from {near.get('name', '?')}"
        return f'<span class="location-badge location-away">AWAY{near_str}</span>'
    return ''


# â”€â”€ CSV PARSING â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def parse_due_list_parts(filepath):
    with open(filepath, "r", encoding="utf-8-sig", newline="") as f:
        raw = f.read()
    # Rejoin lines where Veryon splits a row across lines (continuation starts with ,)
    raw = raw.replace('\r\n', '\n').replace('\r', '\n')
    raw = re.sub(r'\n(?=,)', '', raw)
    reader = csv.reader(raw.splitlines())
    rows = list(reader)

    if not rows or len(rows) < 2:
        raise ValueError(f"CSV appears empty or missing data rows: {filepath}")

    data_rows = rows[1:]
    aircraft_raw  = {}
    aircraft_meta = {}
    components_raw = {}
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
                key = f"{interval:.2f}"
                existing = aircraft_raw[reg].get(key)
                if existing is None or (
                    rem_hrs is not None and (existing["rem_hrs"] is None or rem_hrs < existing["rem_hrs"])
                ):
                    aircraft_raw[reg][key] = {
                        "rem_hrs": rem_hrs, "rem_days": rem_days,
                        "status": status, "desc": desc,
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
        seen = set()
        deduped = []
        for c in sorted(components_raw[reg], key=lambda x: x["sort_key"]):
            key = c["name"][:40]
            if key not in seen:
                seen.add(key)
                deduped.append(c)
        components_raw[reg] = deduped

    return aircraft_meta, aircraft_raw, components_raw, report_date_dt


def parse_due_list(input_path):
    meta_map, raw, components, rpt_dt = parse_due_list_parts(input_path)
    all_regs = sorted(meta_map.keys())
    aircraft_list = []

    for reg in all_regs:
        meta = meta_map.get(reg) or {"airframe_hrs": None, "report_date": None}
        insp = raw.get(reg, {})
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
        })

    report_date_dt = rpt_dt
    if isinstance(report_date_dt, datetime):
        report_date_str = report_date_dt.strftime("%d %b %Y").upper()
    else:
        report_date_str = datetime.today().strftime("%d %b %Y").upper()

    return report_date_str, aircraft_list, components


# â”€â”€ CALENDAR TAB â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

import json
from datetime import datetime, timedelta, date


def _build_calendar_tab(aircraft_list, flight_hours_stats):
    today_dt  = datetime.today()
    today     = today_dt.date()
    today_str = today_dt.strftime('%Y-%m-%d')

    # Each inspection interval has a fixed color — permanent, not urgency-based
    INTERVAL_COLOR = {
        50:   '#00897b',   # teal
        100:  '#1e88e5',   # blue
        200:  '#8e24aa',   # purple
        400:  '#e53935',   # red
        800:  '#fb8c00',   # orange
        2400: '#43a047',   # green
        3200: '#6d4c41',   # brown
    }

    URGENCY_LABEL = {
        'overdue': 'OVERDUE',
        'urgent':  'DUE ≤30 DAYS',
        'soon':    'DUE ≤90 DAYS',
        'ok':      'SCHEDULED >90 DAYS',
    }

    # ── Build spanning events ─────────────────────────────────────────────────
    maint_events = []
    for ac in aircraft_list:
        tail = ac['tail']
        if ac['airframe_hrs'] is None:
            continue
        avg_daily = flight_hours_stats.get(tail, {}).get('avg_daily')
        if not avg_daily or avg_daily <= 0:
            continue

        for interval in [50, 100, 200, 400, 800, 2400, 3200]:
            v = ac['intervals'].get(interval)
            if v is None:
                continue
            rem_hrs = v.get('rem_hrs')
            if rem_hrs is None:
                continue

            color = INTERVAL_COLOR.get(interval, '#4a5568')

            if rem_hrs < 0:
                bar_start = today - timedelta(days=7)
                bar_end   = today + timedelta(days=1)
                urgency   = 'overdue'
                rem_label = f'{abs(rem_hrs):.1f} hrs PAST LIMIT'
                due_str   = today.isoformat()
            else:
                days_away = rem_hrs / avg_daily
                due       = today + timedelta(days=int(days_away))
                due_str   = due.isoformat()
                urgency   = ('urgent' if days_away <= 30 else
                             'soon'   if days_away <= 90 else 'ok')
                rem_label = f'{rem_hrs:.1f} hrs remaining (~{int(days_away)} days)'

                if urgency == 'urgent':
                    warn_days = max(3, int(days_away * 0.4))
                elif urgency == 'soon':
                    warn_days = max(7, int(days_away * 0.25))
                else:
                    warn_days = max(14, int(days_away * 0.15))

                bar_start = max(today, due - timedelta(days=warn_days))
                bar_end   = due + timedelta(days=1)

            maint_events.append({
                'id':              f'maint_{tail}_{interval}',
                'title':           f'{tail}  {interval}h',
                'start':           bar_start.isoformat(),
                'end':             bar_end.isoformat(),
                'allDay':          True,
                'backgroundColor': color,
                'borderColor':     color,
                'textColor':       '#fff',
                'extendedProps': {
                    'type':         'maintenance',
                    'tail':         tail,
                    'interval':     interval,
                    'urgency':      urgency,
                    'urgencyLabel': URGENCY_LABEL[urgency],
                    'remHrs':       rem_hrs,
                    'remLabel':     rem_label,
                    'dueDate':      due_str,
                    'color':        color,
                },
            })

    events_json    = json.dumps(maint_events)
    interval_colors = json.dumps(INTERVAL_COLOR)

    return f"""
<style>
#cal-shell {{
  display: flex;
  gap: 0;
  border: 1px solid var(--border);
  border-radius: 4px;
  overflow: hidden;
  background: var(--surface);
  height: 720px;
}}
#fc-wrap {{
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  --fc-border-color:               #1e2530;
  --fc-button-bg-color:            transparent;
  --fc-button-border-color:        #1e2530;
  --fc-button-text-color:          #a0aec0;
  --fc-button-hover-bg-color:      rgba(41,182,246,0.15);
  --fc-button-hover-border-color:  #29b6f6;
  --fc-button-hover-text-color:    #29b6f6;
  --fc-button-active-bg-color:     rgba(41,182,246,0.2);
  --fc-button-active-border-color: #29b6f6;
  --fc-button-active-text-color:   #29b6f6;
  --fc-today-bg-color:             rgba(41,182,246,0.06);
  --fc-page-bg-color:              var(--surface);
  --fc-neutral-bg-color:           var(--surface2);
  --fc-more-link-text-color:       #29b6f6;
  --fc-popover-bg-color:           #0d1117;
  --fc-popover-border-color:       #29b6f6;
}}
#fc-wrap .fc {{
  height: 100%;
  font-family: 'Barlow', sans-serif;
}}
#fc-wrap .fc-toolbar.fc-header-toolbar {{
  padding: 14px 16px 12px;
  margin-bottom: 0 !important;
  border-bottom: 1px solid var(--border);
}}
#fc-wrap .fc-toolbar-title {{
  font-family: 'Barlow Condensed', sans-serif;
  font-weight: 900; font-size: 20px;
  letter-spacing: 3px; color: #e8edf2;
  text-transform: uppercase;
}}
#fc-wrap .fc-button {{
  font-family: 'Barlow Condensed', sans-serif;
  font-weight: 700; font-size: 11px;
  letter-spacing: 1.5px; text-transform: uppercase;
  border-radius: 2px; padding: 5px 12px;
  box-shadow: none !important;
}}
#fc-wrap .fc-button:focus {{ box-shadow: none !important; outline: none; }}
#fc-wrap .fc-col-header-cell {{
  background: var(--surface2);
  border-color: var(--border) !important;
  padding: 6px 0;
}}
#fc-wrap .fc-col-header-cell-cushion {{
  font-family: 'Barlow Condensed', sans-serif;
  font-weight: 700; font-size: 11px;
  letter-spacing: 2px; color: #4a5568;
  text-decoration: none; text-transform: uppercase;
}}
#fc-wrap .fc-daygrid-day {{
  background: var(--surface);
  border-color: #1e2530 !important;
  cursor: pointer;
}}
#fc-wrap .fc-daygrid-day:hover {{ background: #0f1419; }}
#fc-wrap .fc-day-today {{ background: rgba(41,182,246,0.05) !important; }}
#fc-wrap .fc-daygrid-day.fc-day-selected {{
  background: rgba(41,182,246,0.09) !important;
  box-shadow: inset 0 0 0 1px #29b6f6;
}}
#fc-wrap .fc-daygrid-day-number {{
  font-family: 'Share Tech Mono', monospace;
  font-size: 11px; color: #4a5568;
  text-decoration: none; padding: 4px 6px;
}}
#fc-wrap .fc-day-today .fc-daygrid-day-number {{
  color: #29b6f6; font-weight: 700;
}}
#fc-wrap .fc-event {{
  font-family: 'Share Tech Mono', monospace;
  font-size: 10px; font-weight: 700;
  border-radius: 0;
  cursor: pointer;
  padding: 2px 6px;
  margin-top: 1px;
  border: none !important;
  border-left: 3px solid rgba(0,0,0,0.2) !important;
}}
#fc-wrap .fc-event.fc-event-start {{ border-radius: 3px 0 0 3px; }}
#fc-wrap .fc-event.fc-event-end   {{ border-radius: 0 3px 3px 0; }}
#fc-wrap .fc-event.fc-event-start.fc-event-end {{ border-radius: 3px; }}
#fc-wrap .fc-event:hover {{ filter: brightness(1.15); }}
#fc-wrap .fc-more-link {{
  font-family: 'Share Tech Mono', monospace;
  font-size: 10px; color: #29b6f6; padding: 1px 4px;
}}
#fc-wrap .fc-popover {{
  background: #0d1117 !important;
  border: 1px solid #29b6f6 !important;
  border-radius: 4px !important;
  box-shadow: 0 8px 32px rgba(0,0,0,0.6) !important;
}}
#fc-wrap .fc-popover-header {{
  background: #111418 !important;
  border-bottom: 1px solid #1e2530 !important;
  padding: 8px 12px !important;
}}
#fc-wrap .fc-popover-title {{
  font-family: 'Barlow Condensed', sans-serif !important;
  font-size: 12px !important; letter-spacing: 2px !important;
  color: #29b6f6 !important; text-transform: uppercase !important;
}}
#fc-wrap .fc-popover-close {{ color: #4a5568 !important; }}
#fc-wrap .fc-popover-body {{ padding: 6px !important; }}
#fc-wrap .fc-event.note-ev {{
  background-color: rgba(255,171,0,0.2) !important;
  border-left-color: #ffab00 !important;
  color: #ffab00 !important;
}}
#fc-wrap .fc-scrollgrid {{ border-color: #1e2530; }}

/* ── Right panel ─────────────────────────────────────────────────────────── */
#cal-panel {{
  width: 260px; flex-shrink: 0;
  border-left: 1px solid var(--border);
  display: flex; flex-direction: column;
  overflow: hidden; background: var(--surface2);
}}
#cal-panel-date {{
  padding: 14px 16px 10px;
  border-bottom: 1px solid var(--border); flex-shrink: 0;
}}
#cal-panel-date-main {{
  font-family: 'Barlow Condensed', sans-serif;
  font-weight: 900; font-size: 22px;
  letter-spacing: 1px; color: #e8edf2;
}}
#cal-panel-date-sub {{
  font-family: 'Share Tech Mono', monospace;
  font-size: 10px; color: #4a5568; letter-spacing: 1px; margin-top: 2px;
}}
#cal-panel-events {{
  flex: 1; overflow-y: auto; padding: 8px 0;
}}
.pan-ev-item {{
  padding: 10px 16px;
  border-bottom: 1px solid rgba(30,37,48,0.6);
  cursor: default;
}}
.pan-ev-item:last-child {{ border-bottom: none; }}
.pan-ev-row {{ display: flex; gap: 10px; align-items: flex-start; }}
.pan-ev-bar {{
  width: 4px; height: 38px; border-radius: 2px; flex-shrink: 0; margin-top: 2px;
}}
.pan-ev-title {{
  font-family: 'Barlow Condensed', sans-serif;
  font-weight: 700; font-size: 15px;
  letter-spacing: 0.5px; color: #e8edf2; line-height: 1.2;
}}
.pan-ev-sub {{
  font-family: 'Share Tech Mono', monospace;
  font-size: 9px; color: #4a5568; margin-top: 4px; line-height: 1.6;
}}
.pan-ev-urgency {{
  display: inline-block; font-family: 'Share Tech Mono', monospace;
  font-size: 8px; font-weight: 700; letter-spacing: 1px;
  padding: 1px 5px; border-radius: 2px; margin-top: 4px;
}}
.pan-placeholder {{
  font-family: 'Share Tech Mono', monospace;
  font-size: 10px; color: #2a3240;
  letter-spacing: 1px; line-height: 2.4;
  text-align: center; padding: 40px 20px;
}}
#cal-panel-footer {{
  flex-shrink: 0; border-top: 1px solid var(--border); padding: 10px 12px;
}}
#btn-add-note {{
  display: block; width: 100%;
  background: transparent; border: 1px solid #1e2530;
  color: #4a5568; border-radius: 2px; padding: 7px; cursor: pointer;
  font-family: 'Barlow Condensed', sans-serif;
  font-weight: 700; font-size: 11px;
  letter-spacing: 2px; text-transform: uppercase; transition: all 0.15s;
}}
#btn-add-note:hover {{ border-color: #ffab00; color: #ffab00; }}

/* ── Legend ──────────────────────────────────────────────────────────────── */
.cal-legend {{
  display: flex; gap: 14px; flex-wrap: wrap;
  margin-bottom: 12px; align-items: center;
  font-family: 'Share Tech Mono', monospace;
  font-size: 10px; color: #4a5568;
}}
.cal-leg-item {{ display: flex; align-items: center; gap: 6px; }}
.cal-leg-bar {{
  width: 28px; height: 8px; border-radius: 2px; flex-shrink: 0;
}}

/* ── Note modal ──────────────────────────────────────────────────────────── */
#note-modal {{
  display: none; position: fixed; inset: 0;
  background: rgba(0,0,0,0.75); z-index: 9999;
  align-items: center; justify-content: center;
}}
#note-modal-box {{
  background: #0d1117; border: 1px solid #29b6f6;
  border-radius: 6px; padding: 28px;
  min-width: 320px; max-width: 460px; width: 90%;
}}
.nm-label {{
  display: block; font-family: 'Share Tech Mono', monospace;
  font-size: 10px; color: #4a5568; letter-spacing: 1px; margin-bottom: 4px;
}}
.nm-input, .nm-textarea {{
  width: 100%; box-sizing: border-box;
  background: #161c25; border: 1px solid #1e2530;
  border-radius: 3px; color: #e8edf2; padding: 8px;
  font-family: 'Share Tech Mono', monospace; font-size: 13px;
  margin-bottom: 12px;
}}
.nm-textarea {{ font-size: 12px; resize: vertical; }}
.nm-row {{ display: flex; gap: 8px; justify-content: flex-end; margin-top: 4px; }}
.nm-btn {{
  padding: 7px 16px; border-radius: 3px; cursor: pointer;
  font-family: 'Barlow Condensed', sans-serif; font-weight: 700;
  font-size: 12px; letter-spacing: 1px; text-transform: uppercase;
}}
.nm-save   {{ background: #29b6f6; border: none; color: #000; }}
.nm-cancel {{ background: transparent; border: 1px solid #1e2530; color: #4a5568; }}
.nm-clear  {{ background: transparent; border: 1px solid rgba(192,57,43,0.4); color: #c0392b; }}
</style>

<div class="section-label">PROJECTED MAINTENANCE CALENDAR</div>
<div class="cal-legend">
  <span class="cal-leg-item"><span class="cal-leg-bar" style="background:#00897b"></span>50 HR</span>
  <span class="cal-leg-item"><span class="cal-leg-bar" style="background:#1e88e5"></span>100 HR</span>
  <span class="cal-leg-item"><span class="cal-leg-bar" style="background:#8e24aa"></span>200 HR</span>
  <span class="cal-leg-item"><span class="cal-leg-bar" style="background:#e53935"></span>400 HR</span>
  <span class="cal-leg-item"><span class="cal-leg-bar" style="background:#fb8c00"></span>800 HR</span>
  <span class="cal-leg-item"><span class="cal-leg-bar" style="background:#43a047"></span>2400 HR</span>
  <span class="cal-leg-item"><span class="cal-leg-bar" style="background:#6d4c41"></span>3200 HR</span>
  <span class="cal-leg-item"><span class="cal-leg-bar" style="background:rgba(255,171,0,0.4);border:1px solid #ffab00"></span>NOTE</span>
</div>

<div id="cal-shell">
  <div id="fc-wrap">
    <div id="fc-calendar"></div>
  </div>
  <div id="cal-panel">
    <div id="cal-panel-date">
      <div id="cal-panel-date-main">SELECT A DAY</div>
      <div id="cal-panel-date-sub">CLICK ANY DATE TO VIEW</div>
    </div>
    <div id="cal-panel-events">
      <div class="pan-placeholder" id="pan-placeholder">CLICK ANY DATE<br>TO SEE EVENTS</div>
      <div id="pan-ev-list"></div>
    </div>
    <div id="cal-panel-footer">
      <button id="btn-add-note">+ ADD NOTE</button>
    </div>
  </div>
</div>

<div id="note-modal">
  <div id="note-modal-box" onclick="event.stopPropagation()">
    <div style="font-size:10px;color:#29b6f6;letter-spacing:2px;margin-bottom:4px;font-family:'Share Tech Mono',monospace;">NOTE</div>
    <div id="nm-date-lbl" style="font-family:'Barlow Condensed',sans-serif;font-weight:900;font-size:18px;color:#e8edf2;letter-spacing:1px;margin-bottom:18px;"></div>
    <label class="nm-label">LABEL <span style="color:#2a3240">(shows on calendar)</span></label>
    <input id="nm-label-inp" type="text" maxlength="40" class="nm-input" placeholder="e.g. 50 HR INSP BOOKED">
    <label class="nm-label">NOTES</label>
    <textarea id="nm-text-inp" rows="3" maxlength="400" class="nm-textarea" placeholder="Additional details..."></textarea>
    <div class="nm-row">
      <button class="nm-btn nm-clear"  id="nm-btn-clear">CLEAR</button>
      <button class="nm-btn nm-cancel" id="nm-btn-cancel">CANCEL</button>
      <button class="nm-btn nm-save"   id="nm-btn-save">SAVE</button>
    </div>
  </div>
</div>

<script>
(function () {{
  var NOTES_KEY = 'ihc_cal_notes_v5';
  var activeDate = null;
  var cal;

  var INTERVAL_COLORS = {interval_colors};

  var URGENCY_COLORS = {{
    overdue: '#c0392b', urgent: '#e67e22', soon: '#f39c12', ok: '#2980b9'
  }};

  function loadNotes() {{
    try {{ return JSON.parse(localStorage.getItem(NOTES_KEY) || '{{}}'); }}
    catch (e) {{ return {{}}; }}
  }}
  function saveNotes(n) {{ localStorage.setItem(NOTES_KEY, JSON.stringify(n)); }}

  var MAINT = {events_json};

  function allNoteEvents() {{
    return Object.entries(loadNotes()).map(function([dk, n]) {{
      return {{
        id: 'note_' + dk, title: 'NOTE: ' + (n.label || 'Note'),
        start: dk, allDay: true, classNames: ['note-ev'],
        extendedProps: {{ type: 'note', dateKey: dk, label: n.label||'', text: n.text||'' }},
      }};
    }});
  }}

  var MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  var DAYS   = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
  function fmtDate(ds) {{
    var d = new Date(ds + 'T00:00:00');
    return DAYS[d.getDay()] + ', ' + MONTHS[d.getMonth()] + ' ' + d.getDate();
  }}

  var panDateMain = document.getElementById('cal-panel-date-main');
  var panDateSub  = document.getElementById('cal-panel-date-sub');
  var panEvList   = document.getElementById('pan-ev-list');
  var panPholder  = document.getElementById('pan-placeholder');

  function renderPanel(dateStr) {{
    activeDate = dateStr;
    panDateMain.textContent = fmtDate(dateStr);
    panDateSub.textContent  = dateStr;
    panPholder.style.display = 'none';

    var dDate = new Date(dateStr + 'T00:00:00');
    var evs = [];

    MAINT.forEach(function(ev) {{
      var s = new Date(ev.start + 'T00:00:00');
      var e = new Date(ev.end   + 'T00:00:00');
      if (dDate >= s && dDate < e) evs.push(ev);
    }});

    var notes = loadNotes();
    if (notes[dateStr]) {{
      var n = notes[dateStr];
      evs.push({{
        title: 'NOTE: ' + (n.label || 'Note'),
        backgroundColor: 'rgba(255,171,0,0.3)',
        extendedProps: {{ type:'note', text: n.text||'', label: n.label||'' }},
      }});
    }}

    if (!evs.length) {{
      panEvList.innerHTML =
        '<div style="font-family:\'Share Tech Mono\',monospace;font-size:10px;' +
        'color:#2a3240;padding:20px 16px;letter-spacing:1px;">NO EVENTS</div>';
      document.getElementById('btn-add-note').textContent = '+ ADD NOTE';
      return;
    }}

    panEvList.innerHTML = evs.map(function(ev) {{
      var ep    = ev.extendedProps || {{}};
      var color = ev.backgroundColor || '#4a5568';
      var title = ev.title || '';
      var sub   = '';
      var urgencyHtml = '';

      if (ep.type === 'maintenance') {{
        var uc = URGENCY_COLORS[ep.urgency] || '#4a5568';
        sub = ep.remLabel || '';
        urgencyHtml =
          '<div class="pan-ev-urgency" style="background:' + uc + '22;' +
          'color:' + uc + ';border:1px solid ' + uc + '44;">' +
          ep.urgencyLabel + '</div>';
      }} else {{
        sub = ep.text || '';
      }}

      return '<div class="pan-ev-item">' +
        '<div class="pan-ev-row">' +
          '<div class="pan-ev-bar" style="background:' + color + '"></div>' +
          '<div>' +
            '<div class="pan-ev-title">' + title + '</div>' +
            (sub ? '<div class="pan-ev-sub">' + sub + '</div>' : '') +
            urgencyHtml +
          '</div>' +
        '</div>' +
      '</div>';
    }}).join('');

    document.getElementById('btn-add-note').textContent =
      notes[dateStr] ? 'EDIT NOTE' : '+ ADD NOTE';
  }}

  /* ── Modal ────────────────────────────────────────────────────────────── */
  var noteModal  = document.getElementById('note-modal');
  var nmDateLbl  = document.getElementById('nm-date-lbl');
  var nmLabelInp = document.getElementById('nm-label-inp');
  var nmTextInp  = document.getElementById('nm-text-inp');

  function openModal(dk) {{
    var n = loadNotes()[dk] || {{}};
    nmDateLbl.textContent = fmtDate(dk) + ' — ' + dk;
    nmLabelInp.value = n.label || '';
    nmTextInp.value  = n.text  || '';
    noteModal.style.display = 'flex';
    setTimeout(function() {{ nmLabelInp.focus(); }}, 50);
  }}
  function closeModal() {{ noteModal.style.display = 'none'; }}

  function saveModal() {{
    var dk = activeDate;
    var label = nmLabelInp.value.trim();
    var text  = nmTextInp.value.trim();
    var notes = loadNotes();
    if (label || text) {{ notes[dk] = {{ label: label, text: text }}; }}
    else {{ delete notes[dk]; }}
    saveNotes(notes);
    refreshNoteEvents();
    if (activeDate) renderPanel(activeDate);
    closeModal();
  }}

  function clearNote() {{
    if (!activeDate) return;
    var notes = loadNotes();
    delete notes[activeDate];
    saveNotes(notes);
    refreshNoteEvents();
    renderPanel(activeDate);
    closeModal();
  }}

  document.getElementById('nm-btn-save').addEventListener('click', saveModal);
  document.getElementById('nm-btn-cancel').addEventListener('click', closeModal);
  document.getElementById('nm-btn-clear').addEventListener('click', clearNote);
  document.getElementById('btn-add-note').addEventListener('click', function() {{
    if (activeDate) openModal(activeDate);
  }});
  noteModal.addEventListener('click', function(e) {{ if (e.target===noteModal) closeModal(); }});
  noteModal.addEventListener('keydown', function(e) {{
    if (e.key==='Escape') {{ e.preventDefault(); closeModal(); }}
    if ((e.ctrlKey||e.metaKey) && e.key==='Enter') {{ e.preventDefault(); saveModal(); }}
  }});
  nmLabelInp.addEventListener('keydown', function(e) {{
    if (e.key==='Enter') {{ e.preventDefault(); nmTextInp.focus(); }}
  }});

  function refreshNoteEvents() {{
    if (!cal) return;
    cal.getEvents().forEach(function(e) {{
      if (e.id && e.id.startsWith('note_')) e.remove();
    }});
    allNoteEvents().forEach(function(ev) {{ cal.addEvent(ev); }});
  }}

  /* ── FullCalendar ─────────────────────────────────────────────────────── */
  function initCalendar() {{
    if (typeof FullCalendar === 'undefined') {{ setTimeout(initCalendar, 150); return; }}

    cal = new FullCalendar.Calendar(document.getElementById('fc-calendar'), {{
      initialView:    'dayGridMonth',
      initialDate:    new Date(),
      height:         '100%',
      firstDay:       0,
      fixedWeekCount: false,
      dayMaxEvents:   5,
      moreLinkClick:  'popover',
      headerToolbar: {{
        left:   'prev,next today',
        center: 'title',
        right:  '',
      }},
      buttonText: {{ today: 'TODAY' }},
      events: MAINT.concat(allNoteEvents()),

      dateClick: function(info) {{
        document.querySelectorAll('.fc-day-selected').forEach(function(el) {{
          el.classList.remove('fc-day-selected');
        }});
        var cell = document.querySelector(
          '.fc-daygrid-day[data-date="' + info.dateStr + '"]'
        );
        if (cell) cell.classList.add('fc-day-selected');
        renderPanel(info.dateStr);
      }},

      eventClick: function(info) {{
        info.jsEvent.stopPropagation();
        var ds     = info.event.startStr;
        var today  = new Date('{today_str}' + 'T00:00:00');
        var startD = new Date(ds + 'T00:00:00');
        renderPanel(startD < today ? '{today_str}' : ds);
      }},
    }});

    cal.render();
  }}

  document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded', initCalendar)
    : initCalendar();
}})();
</script>
"""






# â”€â”€ AIRCRAFT LOCATION TAB â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _build_location_tab(aircraft_list, positions):
    """Aircraft location tab with ac-cards. JS refreshes from base_assignments.json."""

    ALL_TAILS = [ac['tail'] for ac in aircraft_list]
    ac_hrs = {ac['tail']: ac['airframe_hrs'] for ac in aircraft_list}

    # Static fallback cards (shown until JS loads)
    static_cards = ''
    for ac in aircraft_list:
        tail = ac['tail']
        pos  = positions.get(tail, {})
        status = pos.get('status', 'NO DATA').upper()
        hrs = ac['airframe_hrs']
        ah  = f"{hrs:,.1f}" if hrs else 'N/A'

        if status == 'AT_BASE':
            curr = pos.get('current_base') or {}
            name = curr.get('name', '')
            card_cls = 'ac-card-base'
            loc_html = f'<span class="ac-loc-base">AT {name.upper()}</span>'
        elif status == 'AIRBORNE':
            card_cls = 'ac-card-air'
            alt = pos.get('last_alt_ft', '')
            spd = pos.get('last_gs_kts', '')
            detail = (f' Â· {int(alt):,} ft' if alt else '') + (f' Â· {int(float(spd))} kts' if spd else '')
            loc_html = f'<span class="ac-loc-air">AIRBORNE</span><span class="ac-loc-detail">{detail}</span>'
        elif status == 'AWAY':
            card_cls = 'ac-card-away'
            loc_html = '<span class="ac-loc-away">AWAY</span>'
        else:
            card_cls = 'ac-card-nodata'
            loc_html = '<span class="ac-loc-unknown">NO DATA</span>'

        static_cards += f'''<div class="ac-card {card_cls}">
  <div class="ac-card-header">
    <div class="ac-tail">{tail}</div>
    <div class="ac-hours">{ah} TT</div>
  </div>
  <div class="ac-card-body">
    <div class="ac-loc">{loc_html}</div>
  </div>
</div>'''

    has_positions = 'true' if positions else 'false'

    # ac_hrs_json for JS
    ac_hrs_js = json.dumps({t: (f"{h:,.1f}" if h else 'N/A') for t, h in ac_hrs.items()})

    css = '''<style>
.ac-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px;margin-top:16px;}
.ac-card{background:var(--surface);border:1px solid var(--border);border-radius:4px;overflow:hidden;transition:border-color .2s;}
.ac-card-base{border-color:rgba(0,230,118,0.35);}
.ac-card-air{border-color:rgba(41,182,246,0.4);}
.ac-card-away{border-color:rgba(255,171,0,0.35);}
.ac-card-nodata{opacity:.6;}
.ac-card-header{display:flex;justify-content:space-between;align-items:baseline;
  padding:10px 14px 8px;background:var(--surface2);border-bottom:1px solid var(--border);}
.ac-tail{font-family:var(--sans);font-weight:900;font-size:18px;letter-spacing:1px;color:var(--heading);}
.ac-hours{font-family:var(--mono);font-size:10px;color:var(--muted);}
.ac-card-body{padding:12px 14px;}
.ac-loc{font-family:var(--mono);font-size:11px;line-height:1.6;}
.ac-loc-base{color:var(--green);font-weight:700;letter-spacing:.5px;}
.ac-loc-air{color:var(--blue);font-weight:700;letter-spacing:.5px;}
.ac-loc-away{color:var(--amber);font-weight:700;letter-spacing:.5px;}
.ac-loc-unknown{color:var(--muted);}
.ac-loc-detail{color:var(--muted);font-size:10px;}
.ac-age{font-family:var(--mono);font-size:9px;color:var(--muted);margin-top:4px;opacity:.6;}
</style>'''

    refresh_js = f'''
(function() {{
  var HAS_POSITIONS = {has_positions};
  var AC_HRS = {ac_hrs_js};

  var BASES = {{
    LOGAN:      {{name:'Logan',      lat:41.7912,  lon:-111.8522}},
    MCKAY:      {{name:'McKay-Dee',  lat:41.2545,  lon:-112.0126}},
    IMED:       {{name:'IMed',       lat:40.2338,  lon:-111.6585}},
    PROVO:      {{name:'Provo',      lat:40.2192,  lon:-111.7233}},
    ROOSEVELT:  {{name:'Roosevelt',  lat:40.2765,  lon:-110.0518}},
    CEDAR_CITY: {{name:'Cedar City', lat:37.7010,  lon:-113.0989}},
    ST_GEORGE:  {{name:'St George',  lat:37.0365,  lon:-113.5101}},
    KSLC:       {{name:'KSLC',       lat:40.7884,  lon:-111.9778}},
  }};

  function bearing(lat1,lon1,lat2,lon2) {{
    var dLon=(lon2-lon1)*Math.PI/180;
    lat1=lat1*Math.PI/180; lat2=lat2*Math.PI/180;
    var y=Math.sin(dLon)*Math.cos(lat2);
    var x=Math.cos(lat1)*Math.sin(lat2)-Math.sin(lat1)*Math.cos(lat2)*Math.cos(dLon);
    return ((Math.atan2(y,x)*180/Math.PI)+360)%360;
  }}
  function cardinal(d) {{ return ['N','NE','E','SE','S','SW','W','NW'][Math.round(d/45)%8]; }}
  function esc(t) {{ return String(t||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }}
  function ageFmt(utcStr) {{
    if (!utcStr) return '';
    var dt=new Date(utcStr),now=new Date();
    var m=Math.round((now-dt)/60000);
    if (isNaN(m)||m<0) return '';
    return m<60 ? m+'m ago' : (m/60).toFixed(1)+'h ago';
  }}

  function locLine(d, bases) {{
    if (!d) return '<span class="ac-loc-unknown">NO DATA</span>';
    var status=(d.status||'').toUpperCase();
    var baseId=d.closest_base||'';
    var baseMeta=bases[baseId]||BASES[baseId]||{{}};
    var baseName=baseMeta.name||baseId;
    var distMi=d.dist_miles||0;
    var dir='';
    if (d.lat && d.lon && baseMeta.lat) dir=cardinal(bearing(baseMeta.lat,baseMeta.lon,d.lat,d.lon));
    if (status==='AT_BASE') return '<span class="ac-loc-base">AT '+esc(baseName.toUpperCase())+'</span>';
    if (status==='AIRBORNE') {{
      var alt=d.alt_ft ? parseInt(d.alt_ft).toLocaleString()+' ft' : '';
      var spd=d.speed_kts ? Math.round(d.speed_kts)+' kts' : '';
      var pos=distMi&&baseName ? (Math.round(distMi)+' mi '+(dir?dir+' of ':' from ')+baseName) : '';
      var parts=[pos,alt,spd].filter(Boolean).join(' Â· ');
      return '<span class="ac-loc-air">AIRBORNE</span>'+(parts?'<span class="ac-loc-detail"> '+esc(parts)+'</span>':'');
    }}
    if (status==='AWAY') {{
      var pos=distMi&&baseName ? (Math.round(distMi)+' mi '+(dir?dir+' of ':' from ')+baseName) : (baseName||'unknown');
      return '<span class="ac-loc-away">AWAY</span><span class="ac-loc-detail"> Â· '+esc(pos)+'</span>';
    }}
    return '<span class="ac-loc-unknown">'+esc(status||'UNKNOWN')+'</span>';
  }}

  function render(payload) {{
    var grid=document.getElementById('ac-location-grid');
    if (!grid||!payload) return;
    var detail=payload.aircraft_detail||{{}};
    var bases=payload.bases||{{}};
    var cards=Object.keys(AC_HRS).map(function(tail) {{
      var d=detail[tail];
      var status=d?(d.status||'UNKNOWN').toUpperCase():'NO DATA';
      var hrs=AC_HRS[tail]||'N/A';
      var cardCls={{AT_BASE:'ac-card-base',AIRBORNE:'ac-card-air',AWAY:'ac-card-away'}}[status]||'ac-card-nodata';
      var age=d?ageFmt(d.utc):'';
      return '<div class="ac-card '+cardCls+'">'
        +'<div class="ac-card-header">'
          +'<div class="ac-tail">'+esc(tail)+'</div>'
          +'<div class="ac-hours">'+esc(hrs)+' TT</div>'
        +'</div>'
        +'<div class="ac-card-body">'
          +'<div class="ac-loc">'+locLine(d,bases)+'</div>'
          +(age?'<div class="ac-age">'+esc(age)+'</div>':'')
        +'</div></div>';
    }});
    grid.innerHTML=cards.join('');
  }}

  function refresh() {{
    // base_assignments.json is at root because Pages serves from data/
    fetch('base_assignments.json?ts='+Date.now(),{{cache:'no-store'}})
      .then(function(r){{ if(!r.ok) throw new Error('failed'); return r.json(); }})
      .then(render)
      .catch(function(){{}});
  }}

  refresh();
  setInterval(refresh, 60000);
}})();'''

    return f'''{css}
<div class="section-label">Aircraft Location</div>
<div style="font-family:var(--mono);font-size:10px;color:var(--muted);margin-bottom:4px;">
  Live positions via SkyRouter GPS &middot; refreshes every 60 seconds
</div>
<div class="ac-grid" id="ac-location-grid">
{static_cards}
</div>
<script>{refresh_js}</script>'''


# â”€â”€ BUILD HTML â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def build_html(report_date, aircraft_list, components, flight_hours_stats, positions,
               source_filename, photo_b64=''):

    def fmt_hrs(val_dict):
        if val_dict is None:
            return '<span class="hr-na">-</span>'
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
            rem   = c['rem_hrs']
            rem_d = c.get('rem_days')
            if (rem is not None and rem < 0) or (rem is None and rem_d is not None and rem_d < 0):
                comp_overdue += 1

    airborne_count = sum(1 for t in aircraft_list if positions.get(t['tail'], {}).get('status') == 'AIRBORNE')
    at_base_count  = sum(1 for t in aircraft_list if positions.get(t['tail'], {}).get('status') == 'AT_BASE')

    # Photo tag
    if photo_b64:
        photo_tag = (
            f'<img src="data:image/jpeg;base64,{photo_b64}" '
            f'style="height:60px;margin-left:16px;border-radius:4px;opacity:0.88;'
            f'box-shadow:0 0 8px rgba(41,182,246,0.3);" alt="IHC Fleet">'
        )
    else:
        photo_tag = ''

    # Table rows
    table_rows_html = ''
    for ac in aircraft_list:
        tail = ac['tail']
        ah   = f"{ac['airframe_hrs']:,.1f}" if ac['airframe_hrs'] else 'N/A'
        loc_badge = get_location_badge(tail, positions)
        cells = f'<td><div class="tail-number">{tail}{loc_badge}</div><div class="airframe-hrs">{ah} TT</div></td>'
        for i in TARGET_INTERVALS:
            cells += f'<td class="hr-cell">{fmt_hrs(ac["intervals"].get(i))}</td>'
        table_rows_html += f'<tr data-tail="{tail}">{cells}</tr>\n'

    # Component panels
    comp_panels_html = ''
    for ac in aircraft_list:
        reg   = ac['tail']
        comps = components.get(reg, [])
        if not comps:
            continue
        ah = f"{ac['airframe_hrs']:.1f}" if ac['airframe_hrs'] else 'N/A'
        rows_html = ''
        for c in comps:
            rem      = c['rem_hrs']
            rem_days = c.get('rem_days')
            status   = c.get('status', '')
            if rem is not None:
                cls = classify(rem)
            elif rem_days is not None:
                cls = 'overdue' if rem_days < 0 else ('red' if rem_days <= 7 else ('amber' if rem_days <= 30 else 'green'))
            else:
                cls = classify_from_status(status)
            ind_cls   = {'overdue':'comp-overdue','red':'comp-red','amber':'comp-amber','green':'comp-green'}.get(cls,'comp-green')
            txt_color = {'overdue':'var(--overdue)','red':'var(--red)','amber':'var(--amber)','green':'var(--green)'}.get(cls,'var(--green)')
            rii_badge = ' <span class="rii-badge">RII</span>' if c.get('rii') else ''
            if rem is not None:
                rem_label = f'OVERDUE - {abs(rem):.1f} hrs past limit' if rem < 0 else f'{rem:.1f} hrs remaining'
            elif rem_days is not None:
                rem_label = f'OVERDUE - {abs(rem_days):.0f} days past limit' if rem_days < 0 else f'{rem_days:.0f} days remaining'
            else:
                rem_label = status
            rows_html += f'''<div class="component-row">
  <div class="comp-indicator {ind_cls}"></div>
  <div class="comp-info">
    <div class="comp-name" title="{c['name']}">{c['name']}{rii_badge}</div>
    <div class="comp-hrs" style="color:{txt_color}">{rem_label}</div>
  </div>
</div>'''
        comp_panels_html += f'''<div class="aircraft-panel">
  <div class="panel-header">
    <div class="panel-tail">{reg}</div>
    <div class="panel-hours">{ah} TT</div>
  </div>
  {rows_html}
</div>'''
    if not comp_panels_html:
        comp_panels_html = '<div style="font-family:var(--mono);font-size:12px;color:var(--muted);padding:20px;">No components within 200 hours across fleet.</div>'

    # Flight hours tab — sorted most to least by avg daily utilization
    util_pairs = sorted(
        [(ac['tail'], flight_hours_stats.get(ac['tail'], {}).get('avg_daily') or 0) for ac in aircraft_list],
        key=lambda x: x[1], reverse=True
    )
    util_tails  = [t for t, _ in util_pairs]
    util_daily  = [round(v, 2) for _, v in util_pairs]
    util_weekly = [round(v * 7, 2) for _, v in util_pairs]

    tails_js  = '[' + ','.join(f'"{t}"' for t in util_tails) + ']'
    daily_js  = '[' + ','.join(str(v) for v in util_daily) + ']'
    weekly_js = '[' + ','.join(str(v) for v in util_weekly) + ']'

    hours_cards_html = ''
    for ac in aircraft_list:
        tail  = ac['tail']
        stats = flight_hours_stats.get(tail, {})
        avg   = stats.get('avg_daily')
        ah    = f"{stats.get('current_hours'):,.1f}" if stats.get('current_hours') else 'N/A'
        d_str = f"{avg:.2f}" if avg else "-"
        w_str = f"{avg*7:.1f}" if avg else "-"
        m_str = f"{avg*30:.1f}" if avg else "-"
        hours_cards_html += f'''<div class="hours-card">
  <div class="hours-card-header">
    <div class="hours-card-tail">{tail}</div>
    <div class="hours-card-current">{ah} TT</div>
  </div>
  <div class="hours-card-body">
    <div class="hours-stat-row"><div class="hours-stat-label">Avg Daily</div><div class="hours-stat-value">{d_str} hrs</div></div>
    <div class="hours-stat-row"><div class="hours-stat-label">Avg Weekly</div><div class="hours-stat-value">{w_str} hrs</div></div>
    <div class="hours-stat-row"><div class="hours-stat-label">Avg Monthly</div><div class="hours-stat-value">{m_str} hrs</div></div>
  </div>
</div>'''

    # 200hr bar chart data
    chart_rows = sorted(
        [(ac['tail'], float(v['rem_hrs'])) for ac in aircraft_list
         if (v := ac['intervals'].get(200)) and v.get('rem_hrs') is not None],
        key=lambda x: x[1]
    )
    labels_js = "[" + ",".join([f"'{t}'" for t, _ in chart_rows]) + "]"
    values_js = "[" + ",".join([f"{v:.2f}" for _, v in chart_rows]) + "]"

    calendar_tab_html  = _build_calendar_tab(aircraft_list, flight_hours_stats)
    location_tab_html  = _build_location_tab(aircraft_list, positions)
    gen_time = datetime.today().strftime('%d %b %Y %H:%M').upper()
    version  = datetime.today().strftime('%Y%m%d%H%M%S')

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>IHC Health Services - Fleet Due List</title>
<link rel="icon" href="data:,">
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
  .header-left{{display:flex;align-items:center;gap:0;}}
  .logo{{font-family:var(--sans);font-weight:900;font-size:22px;letter-spacing:3px;color:var(--heading);text-transform:uppercase;}}
  .logo span{{color:var(--blue);}}
  .subtitle{{font-family:var(--mono);font-size:11px;color:var(--muted);letter-spacing:2px;text-transform:uppercase;margin-top:3px;}}
  .header-photo{{height:60px;margin-left:16px;border-radius:4px;opacity:0.88;box-shadow:0 0 8px rgba(41,182,246,0.3);}}
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
  .location-badge{{display:inline-block;padding:2px 8px;border-radius:2px;font-size:9px;font-family:var(--mono);margin-left:8px;letter-spacing:0.5px;vertical-align:middle;}}
  .location-at-base{{background:rgba(0,230,118,0.15);color:var(--green);border:1px solid rgba(0,230,118,0.3);}}
  .location-away{{background:rgba(255,23,68,0.12);color:var(--red);border:1px solid rgba(255,23,68,0.3);}}
  .location-active{{background:rgba(41,182,246,0.12);color:var(--blue);border:1px solid rgba(41,182,246,0.3);}}
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
  footer{{margin-top:48px;padding:16px 32px;border-top:1px solid var(--border);font-family:var(--mono);font-size:10px;color:var(--muted);display:flex;justify-content:space-between;letter-spacing:1px;}}
</style>
<script src="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.10/index.global.min.js"></script>
</head>
<body>
<header>
  <div class="header-left">
    <div>
      <div class="logo">IHC <span>HEALTH</span> SERVICES</div>
      <div class="subtitle">AW109SP Fleet &nbsp;-&nbsp; Maintenance Due List</div>
    </div>
    {photo_tag}
  </div>
  <div class="header-meta">
    <div class="date">REPORT DATE: {report_date}</div>
    <div>FLEET: {total_ac} AIRCRAFT &nbsp;|&nbsp; {airborne_count} AIRBORNE &nbsp;|&nbsp; {at_base_count} AT BASE &nbsp;|&nbsp; GENERATED: {gen_time}</div>
  </div>
</header>
<div class="legend">
  <div class="legend-item"><div class="dot dot-green"></div> OK (&gt;100 hrs)</div>
  <div class="legend-item"><div class="dot dot-amber"></div> Coming Due (26â€“100 hrs)</div>
  <div class="legend-item"><div class="dot dot-red"></div> Critical (0â€“25 hrs)</div>
  <div class="legend-item"><div class="dot dot-overdue"></div> Past Due / Overdue</div>
  <div style="margin-left:auto;font-family:var(--mono);font-size:11px;color:var(--muted);letter-spacing:1px;">- = Not due this cycle</div>
</div>
<main>
  <div class="tabs">
    <button class="tab-btn active" onclick="switchTab('maintenance',this)">Maintenance Due List</button>
    <button class="tab-btn" onclick="switchTab('flight-hours',this)">Flight Hours Tracking</button>
    <button class="tab-btn" onclick="switchTab('calendar',this)">Calendar</button>
    <button class="tab-btn" onclick="switchTab('location',this)">Aircraft Location</button>
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
    <div class="section-label">Scheduled Phase Inspections - Hours Remaining</div>
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
          </tr>
        </thead>
        <tbody id="insp-tbody">
{table_rows_html}
        </tbody>
      </table>
    </div>
    <div class="section-label" style="margin-top:36px;">Component Retirement / Overhaul - Within {COMPONENT_WINDOW_HRS} Hours</div>
    <div class="components-grid">{comp_panels_html}</div>
  </div>

  <!-- FLIGHT HOURS TAB -->
  <div id="tab-flight-hours" class="tab-content">
    <div class="section-label">Fleet Utilization Rates</div>
    <div style="font-family:var(--mono);font-size:10px;color:var(--muted);margin-bottom:20px;">Average based on available history. Updates as more data accumulates.</div>
    <div style="background:var(--surface);border:1px solid var(--border);border-radius:4px;padding:24px;margin-bottom:32px;">
      <canvas id="utilChart" style="width:100%;height:320px;"></canvas>
    </div>
    <div class="hours-grid">{hours_cards_html}</div>
  </div>

  <!-- CALENDAR TAB -->
  <div id="tab-calendar" class="tab-content">
{calendar_tab_html}
  </div>

  <!-- AIRCRAFT LOCATION TAB -->
  <div id="tab-location" class="tab-content">
{location_tab_html}
  </div>
</main>
<footer>
  <span>SOURCE: VERYON MAINTENANCE TRACKING &nbsp;|&nbsp; {source_filename}</span>
  <span>IHC HEALTH SERVICES - AVIATION MAINTENANCE</span>
</footer>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2"></script>
<script>
  const DASHBOARD_VERSION = "{version}";

  // Auto-reload when a newer build is deployed
  (function() {{
    var versionUrl = 'dashboard_version.json?ts=' + Date.now();
    fetch(versionUrl, {{cache:'no-store'}})
      .then(function(r){{ return r.ok ? r.json() : null; }})
      .then(function(data) {{
        if (!data || !data.version || data.version === DASHBOARD_VERSION) return;
        var next = new URL(window.location.href);
        if (next.searchParams.get('v') === data.version) return;
        next.searchParams.set('v', data.version);
        window.location.replace(next.toString());
      }})
      .catch(function(){{}});
  }})();

  function switchTab(tabName, btn) {{
    document.querySelectorAll('.tab-btn').forEach(function(b){{ b.classList.remove('active'); }});
    btn.classList.add('active');
    document.querySelectorAll('.tab-content').forEach(function(t){{ t.classList.remove('active'); }});
    document.getElementById('tab-' + tabName).classList.add('active');
  }}

  function filterTable(filter, btn) {{
    document.querySelectorAll('.filter-btn').forEach(function(b){{ b.classList.remove('active'); }});
    btn.classList.add('active');
    document.querySelectorAll('#insp-tbody tr').forEach(function(tr) {{
      var badges = tr.querySelectorAll('.hr-badge, .hr-na');
      var show = filter === 'all';
      if (!show) {{
        badges.forEach(function(b) {{
          var cls = b.className;
          if (filter === 'overdue' && cls.includes('hr-overdue')) show = true;
          if (filter === 'critical' && cls.includes('hr-red'))    show = true;
          if (filter === 'coming'   && cls.includes('hr-amber'))  show = true;
          if (filter === 'ok'       && cls.includes('hr-green'))  show = true;
        }});
      }}
      tr.style.display = show ? '' : 'none';
    }});
  }}

  // 200hr bar chart
  var labels200 = {labels_js};
  var values200 = {values_js};
  if (labels200.length === 0) {{
    document.getElementById('bar200').parentElement.innerHTML =
      "<div style='font-family:var(--mono);font-size:12px;color:var(--muted);padding:10px;'>No numeric 200-hr data found.</div>";
  }} else {{
    new Chart(document.getElementById('bar200'), {{
      type: 'bar',
      data: {{ labels: labels200, datasets: [{{ label: 'Hours remaining to 200 Hr', data: values200, backgroundColor: '#29b6f6' }}] }},
      options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{
          legend: {{ display: true }},
          datalabels: {{
            anchor: 'end', align: 'top', color: '#cdd6e0',
            font: {{ family: 'Share Tech Mono', size: 11 }},
            formatter: function(v) {{ return v.toFixed(1); }}
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

  // Utilization chart
  (function() {{
    var ctx = document.getElementById('utilChart');
    if (!ctx) return;
    new Chart(ctx, {{
      type: 'bar',
      data: {{
        labels: {tails_js},
        datasets: [
          {{ label: 'Avg Daily (hrs)', data: {daily_js}, backgroundColor: 'rgba(41,182,246,0.8)', borderColor: '#29b6f6', borderWidth: 1, yAxisID: 'yDaily' }},
          {{ label: 'Avg Weekly (hrs)', data: {weekly_js}, backgroundColor: 'rgba(246,173,85,0.8)', borderColor: '#f6ad55', borderWidth: 1, yAxisID: 'yWeekly' }}
        ]
      }},
      options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{
          legend: {{ labels: {{ color: '#a0aec0', font: {{ family: 'monospace', size: 11 }} }} }},
          datalabels: {{
            anchor: 'end', align: 'top', color: '#a0aec0',
            font: {{ size: 9, family: 'monospace' }},
            formatter: function(v) {{ return v > 0 ? v.toFixed(2) : ''; }}
          }}
        }},
        scales: {{
          yDaily:  {{ type: 'linear', position: 'left', beginAtZero: true, title: {{ display: true, text: 'Daily Avg (hrs)', color: '#29b6f6', font: {{ size: 10 }} }}, ticks: {{ color: '#4a5568', font: {{ size: 10 }} }}, grid: {{ color: 'rgba(30,37,48,0.8)' }} }},
          yWeekly: {{ type: 'linear', position: 'right', beginAtZero: true, title: {{ display: true, text: 'Weekly Avg (hrs)', color: '#f6ad55', font: {{ size: 10 }} }}, ticks: {{ color: '#4a5568', font: {{ size: 10 }} }}, grid: {{ drawOnChartArea: false }} }},
          x: {{ ticks: {{ color: '#a0aec0', font: {{ size: 10, family: 'monospace' }} }}, grid: {{ display: false }} }}
        }}
      }},
      plugins: [ChartDataLabels]
    }});
  }})();
</script>
</body>
</html>"""


# â”€â”€ MAIN â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def main():
    data_dir       = Path(OUTPUT_FOLDER)
    input_path     = data_dir / INPUT_FILENAME
    output_path    = data_dir / OUTPUT_FILENAME
    history_path   = data_dir / HISTORY_FILENAME
    positions_path = data_dir / POSITIONS_FILENAME
    version_path   = data_dir / "dashboard_version.json"
    log_path       = Path(__file__).with_name("dashboard_log.txt")

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
                log(f"Using fallback: {input_path}")
                break

    if not input_path.exists():
        log(f"WARNING: Input file not found: {input_path}")
        sys.exit(0)

    file_age_hrs = (datetime.now().timestamp() - input_path.stat().st_mtime) / 3600
    if file_age_hrs > 36:
        log(f"WARNING: Input file is {file_age_hrs:.1f} hours old.")

    try:
        log(f"Parsing {input_path} ...")
        report_date, aircraft_list, components = parse_due_list(input_path)
        log(f"Parsed {len(aircraft_list)} aircraft.")

        log("Loading flight hours history...")
        history_data   = load_flight_hours_history(history_path)
        report_date_dt = next((ac['report_date'] for ac in aircraft_list if ac.get('report_date')), None)
        history_data   = update_flight_hours_history(history_data, aircraft_list, report_date_dt)
        save_flight_hours_history(history_path, history_data)
        flight_hours_stats = calculate_flight_hours_stats(history_data, aircraft_list)
        log("Flight hours stats calculated.")

        log("Loading positions...")
        positions = load_positions(positions_path)
        if positions:
            log(f"Loaded positions for {len(positions)} aircraft.")
        else:
            log("No positions data yet.")

        log("Loading fleet photo...")
        photo_b64 = load_photo_b64(data_dir)
        log(f"Photo: {'loaded' if photo_b64 else 'not found'}")

        html = build_html(
            report_date, aircraft_list, components,
            flight_hours_stats, positions,
            input_path.name, photo_b64,
        )

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)
        log(f"Dashboard written to {output_path}")

        # Write version file for auto-reload detection
        version = datetime.today().strftime('%Y%m%d%H%M%S')
        with open(version_path, 'w', encoding='utf-8') as f:
            json.dump({"version": version}, f)
        log(f"Version: {version}")
        log("Done.")

    except Exception as e:
        log(f"ERROR: {e}")
        import traceback
        log(traceback.format_exc())
        sys.exit(1)


if __name__ == '__main__':
    main()




