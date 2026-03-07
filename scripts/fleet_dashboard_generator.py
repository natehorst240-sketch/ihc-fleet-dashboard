"""
Fleet Maintenance Dashboard Generator (CSV)
==========================================
Reads Due-List_Latest_aw109sp.csv and Due-List_BIG_WEEKLY_aw109sp.csv
from the data/ folder and writes data/fleet_dashboard.html.

Run via GitHub Actions after CSV files are pushed to repo.
"""

import sys
import csv
import re
import json
from datetime import datetime, timedelta
from pathlib import Path

# ── CONFIGURATION ─────────────────────────────────────────────────────────────

OUTPUT_FOLDER = "data"

INPUT_FILENAME     = "Due-List_BIG_WEEKLY_aw109sp.csv"
WEEKLY_FILENAME    = "Due-List_BIG_WEEKLY_aw109sp.csv"
INPUT_FALLBACKS    = ["Due-List_BIG_WEEKLY_aw109sp.csv"]
WEEKLY_FALLBACKS   = ["Due-List_BIG_WEEKLY.csv"]
OUTPUT_FILENAME    = "fleet_dashboard.html"
HISTORY_FILENAME   = "flight_hours_history.json"
POSITIONS_FILENAME = "base_assignments.json"

# Phase inspection intervals to track (hours)
TARGET_INTERVALS = [50, 100, 200, 400, 800, 2400, 3200]

# Map each interval to regex pattern(s) found in Column F (ATA and Code)
PHASE_MATCH = {
    50:   [r"05 1000"],
    100:  [r"64 01\[273\]"],
    200:  [r"05 1005"],
    400:  [r"05 1010"],
    800:  [r"05 1015"],
    2400: [r"62 11\[373\]"],
    3200: [r"05 1020"],
}

# Calendar-based certifications to track (keyed by inspection code)
CERT_INSPECTIONS = {
    "XPDR_24M": {
        "label":       "24M CERT",
        "ata_pattern": r"34 0009",
        "col_header":  "Transponder Cert",
    },
}

# Component panel: show items within this many hours of retire/overhaul
COMPONENT_WINDOW_HRS = 200

# Keywords that identify retirement/overhaul component items
RETIREMENT_KEYWORDS = [
    'RETIRE', 'OVERHAUL', 'DISCARD', 'LIFE LIMIT', 'TBO',
    'REPLACEMENT', 'REPLACE', 'CHANGE OIL', 'NOZZLE'
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


# ── FLIGHT HOURS TRACKING ─────────────────────────────────────────────────────

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
        for date_str in sorted_dates[:7]:
            daily_data.insert(0, {'date': date_str, 'hours': tail_history[date_str]['hours']})
        weekly_hours = None
        monthly_hours = None
        seven_days_ago_str  = seven_days_ago.strftime("%Y-%m-%d")
        thirty_days_ago_str = thirty_days_ago.strftime("%Y-%m-%d")
        if len(sorted_dates) >= 2:
            latest_hours = tail_history[sorted_dates[0]]['hours']
            for date_str in sorted_dates:
                if date_str <= seven_days_ago_str:
                    weekly_hours = latest_hours - tail_history[date_str]['hours']
                    break
            for date_str in sorted_dates:
                if date_str <= thirty_days_ago_str:
                    monthly_hours = latest_hours - tail_history[date_str]['hours']
                    break
        avg_daily = projection_weekly = projection_monthly = None
        if monthly_hours is not None:
            days_of_data = (today - datetime.strptime(thirty_days_ago_str, "%Y-%m-%d")).days
            if days_of_data > 0:
                avg_daily = monthly_hours / days_of_data
        elif weekly_hours is not None:
            days_of_data = (today - datetime.strptime(seven_days_ago_str, "%Y-%m-%d")).days
            if days_of_data > 0:
                avg_daily = weekly_hours / days_of_data
        elif len(sorted_dates) >= 2:
            oldest = sorted_dates[-1]
            newest = sorted_dates[0]
            span_days = (datetime.strptime(newest, "%Y-%m-%d") - datetime.strptime(oldest, "%Y-%m-%d")).days
            if span_days > 0:
                span_hours = tail_history[newest]['hours'] - tail_history[oldest]['hours']
                avg_daily = span_hours / span_days
        if avg_daily is not None:
            projection_weekly  = avg_daily * 7
            projection_monthly = avg_daily * 30
        stats[tail] = {
            'current_hours': current_hours, 'daily': daily_data,
            'weekly': weekly_hours, 'monthly': monthly_hours,
            'avg_daily': avg_daily,
            'projection_weekly': projection_weekly,
            'projection_monthly': projection_monthly,
        }
    return stats


# ── POSITIONS (ADSB) ──────────────────────────────────────────────────────────

def load_positions(positions_path):
    if not positions_path.exists():
        return {}
    try:
        with open(positions_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return {}

    # ── NEW FORMAT: SkyRouter ─────────────────────────────────────────────────
    if 'aircraft_detail' in data:
        bases_meta   = data.get('bases', {})
        last_checked = data.get('last_checked', '')
        aircraft_positions = {}
        for tail, detail in data.get('aircraft_detail', {}).items():
            status          = detail.get('status', 'UNKNOWN')
            closest_base_id = detail.get('closest_base')
            dist_miles      = detail.get('dist_miles')
            dist_nm         = round(dist_miles * 0.868976, 1) if dist_miles is not None else None
            base_name       = (bases_meta.get(closest_base_id, {}).get('name', closest_base_id)
                               if closest_base_id else None)
            nearest = ({'id': closest_base_id, 'name': base_name, 'dist_nm': dist_nm}
                       if closest_base_id else None)
            aircraft_positions[tail] = {
                'status':                status,
                'current_base':          nearest if status == 'AT_BASE' else None,
                'nearest_base':          nearest,
                'last_alt_ft':           detail.get('alt_ft', ''),
                'last_gs_kts':           detail.get('speed_kts', ''),
                'last_updated':          last_checked,
                'flights_today':         [],
                'total_flight_hrs_today': 0.0,
                'closest_base':          closest_base_id,
                'dist_miles':            dist_miles,
                'lat':                   detail.get('lat'),
                'lon':                   detail.get('lon'),
                'utc':                   detail.get('utc', ''),
            }
        return aircraft_positions

    # ── OLD FORMAT: ADS-B ─────────────────────────────────────────────────────
    assignments  = data.get('assignments', {})
    bases_meta   = data.get('bases', {})
    last_updated = data.get('last_updated', '')
    aircraft_positions = {}

    for base_id, base_data in assignments.items():
        if base_id == 'unassigned':
            ac_list = base_data if isinstance(base_data, list) else []
            for ac in ac_list:
                tail = ac.get('tail') or ac.get('registration', '')
                if not tail:
                    continue
                aircraft_positions[tail] = {
                    'status': 'AWAY', 'current_base': None, 'nearest_base': None,
                    'last_alt_ft': ac.get('altitude', ''), 'last_gs_kts': ac.get('ground_speed', ''),
                    'last_updated': last_updated, 'flights_today': [], 'total_flight_hrs_today': 0.0,
                }
        else:
            ac_list   = base_data.get('aircraft', []) if isinstance(base_data, dict) else []
            base_name = bases_meta.get(base_id, {}).get('name', base_id)
            for ac in ac_list:
                tail = ac.get('tail') or ac.get('registration', '')
                if not tail:
                    continue
                status_raw = str(ac.get('status', '')).upper()
                if 'AIRBORNE' in status_raw or 'IN_FLIGHT' in status_raw:
                    status = 'AIRBORNE'; curr_base = None
                else:
                    status = 'AT_BASE'
                    curr_base = {'id': base_id, 'name': base_name,
                                 'dist_nm': round(ac.get('distance_miles', 0) * 0.868976, 1)}
                aircraft_positions[tail] = {
                    'status': status, 'current_base': curr_base, 'nearest_base': None,
                    'last_alt_ft': ac.get('altitude', ''), 'last_gs_kts': ac.get('ground_speed', ''),
                    'last_updated': last_updated, 'flights_today': [], 'total_flight_hrs_today': 0.0,
                }
    return aircraft_positions


def get_location_badge(tail, positions):
    ac = positions.get(tail, {})
    if not ac:
        return ''
    status    = ac.get('status', '').upper()
    curr_base = ac.get('current_base')
    near_base = ac.get('nearest_base')
    if status == 'AIRBORNE':
        last_alt = ac.get('last_alt_ft', '')
        alt_str  = f" {last_alt}ft" if last_alt else ''
        return f'<span class="location-badge location-active">AIRBORNE{alt_str}</span>'
    if status == 'AT_BASE':
        base_name = curr_base.get('name', '') if curr_base else ''
        label = f'AT BASE' + (f' · {base_name}' if base_name else '')
        return f'<span class="location-badge location-at-base">{label}</span>'
    if status == 'AWAY':
        near_str = ''
        if near_base:
            near_str = f" · {near_base.get('dist_nm', '?')}nm from {near_base.get('name', '?')}"
        return f'<span class="location-badge location-away">AWAY{near_str}</span>'
    if status == 'NO_SIGNAL':
        return '<span class="location-badge location-unknown">NO SIGNAL</span>'
    return ''


def get_flights_today(tail, positions):
    ac = positions.get(tail, {})
    return ac.get('flights_today', [])


def get_hours_today(tail, positions):
    ac = positions.get(tail, {})
    return ac.get('total_flight_hrs_today', 0.0)


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
    with open(filepath, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)

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


def parse_due_list(daily_path, weekly_path=None):
    daily_meta, daily_raw, daily_components, daily_certs, daily_rpt_dt = parse_due_list_parts(daily_path)
    weekly_meta   = {}
    weekly_raw    = {}
    weekly_certs  = {}
    weekly_rpt_dt = None
    if weekly_path and Path(weekly_path).exists():
        weekly_meta, weekly_raw, _, weekly_certs, weekly_rpt_dt = parse_due_list_parts(weekly_path)

    merged_raw = merge_inspections(weekly_raw, daily_raw)
    merged_certs = {}
    for reg in set(weekly_certs.keys()) | set(daily_certs.keys()):
        merged_certs[reg] = {}
        if reg in weekly_certs:
            merged_certs[reg].update(weekly_certs[reg])
        if reg in daily_certs:
            merged_certs[reg].update(daily_certs[reg])

    all_regs = sorted(set(weekly_meta.keys()) | set(daily_meta.keys()))
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


# ── BUILD HTML ────────────────────────────────────────────────────────────────

def build_html(report_date, aircraft_list, components, flight_hours_stats, positions, source_filename):

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
        if cert_entry is None:
            return '<span class="hr-na">—</span>'
        rem_days = cert_entry.get("rem_days")
        status   = cert_entry.get("status", "")
        if rem_days is not None:
            due_dt  = datetime.today() + timedelta(days=rem_days)
            due_str = due_dt.strftime("%m-%d-%Y")
            if rem_days < 0:
                cls = 'overdue'; label = f'CERT OD {due_str}'
            elif rem_days <= 30:
                cls = 'red';    label = f'24M CERT DUE {due_str}'
            elif rem_days <= 90:
                cls = 'amber';  label = f'24M CERT DUE {due_str}'
            else:
                cls = 'green';  label = f'24M CERT DUE {due_str}'
        else:
            cls   = classify_from_status(status)
            label = f'24M CERT — {status[:10]}' if status else '24M CERT — ?'
        badge_map = {'overdue':'hr-overdue','red':'hr-red','amber':'hr-amber','green':'hr-green'}
        badge_cls = badge_map.get(cls, 'hr-na')
        if cls == 'na' or cls not in badge_map:
            return f'<span class="hr-na">{label}</span>'
        pulse = 'animation:pulse 2s ease-in-out infinite;' if cls == 'overdue' else ''
        return f'<span class="hr-badge {badge_cls}" style="min-width:126px;font-size:10px;letter-spacing:0;{pulse}">{label}</span>'

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
  <div style="display:flex;align-items:center;gap:18px;">
    <div>
      <div class="logo">IHC <span>HEALTH</span> SERVICES</div>
      <div class="subtitle">AW109SP Fleet &nbsp;—&nbsp; Maintenance Due List</div>
    </div>
    <img src="data:image/jpeg;base64,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"
         style="height:60px;border-radius:3px;opacity:0.88;object-fit:cover;" alt="AW109SP">
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
    <button class="tab-btn" onclick="switchTab('bases',this)">Aircraft Location</button>
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
    var STORAGE_KEY = 'ihc_cal_notes';

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
    """Build a month-view calendar with projected maintenance due dates."""
    import calendar as cal_mod

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



def _bearing_deg(lat1, lon1, lat2, lon2):
    import math
    dlon = math.radians(lon2 - lon1)
    lat1r, lat2r = math.radians(lat1), math.radians(lat2)
    y = math.sin(dlon) * math.cos(lat2r)
    x = math.cos(lat1r) * math.sin(lat2r) - math.sin(lat1r) * math.cos(lat2r) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360

def _cardinal(deg):
    return ['N','NE','E','SE','S','SW','W','NW'][round(deg / 45) % 8]

def _build_bases_tab(aircraft_list, positions):
    ALL_TAILS = ["N251HC","N261HC","N271HC","N281HC","N291HC",
                 "N431HC","N531HC","N631HC","N731HC"]
    BASES_COORDS = {
        "LOGAN":      {"name":"Logan",      "lat":41.7912,  "lon":-111.8522},
        "MCKAY":      {"name":"McKay-Dee",  "lat":41.2545,  "lon":-112.0126},
        "IMED":       {"name":"IMed",       "lat":40.2338,  "lon":-111.6585},
        "PROVO":      {"name":"Provo",      "lat":40.2192,  "lon":-111.7233},
        "ROOSEVELT":  {"name":"Roosevelt",  "lat":40.2765,  "lon":-110.0518},
        "CEDAR_CITY": {"name":"Cedar City", "lat":37.7010,  "lon":-113.0989},
        "ST_GEORGE":  {"name":"St George",  "lat":37.0365,  "lon":-113.5101},
        "KSLC":       {"name":"KSLC",       "lat":40.7884,  "lon":-111.9778},
    }
    ac_hrs = {ac['tail']: ac['airframe_hrs'] for ac in aircraft_list}

    def _location_line(tail, pos):
        if not pos:
            return '<span class="ac-loc-unknown">NO DATA</span>'
        status  = pos.get('status', 'UNKNOWN').upper()
        base_id = pos.get('closest_base') or (pos.get('current_base') or {}).get('id', '')
        base_nm = ((pos.get('nearest_base') or pos.get('current_base') or {}).get('name', '')
                   or BASES_COORDS.get(base_id, {}).get('name', base_id))
        dist_mi = (pos.get('dist_miles') or
                   (pos.get('nearest_base') or pos.get('current_base') or {}).get('dist_nm'))
        direction = ''
        lat, lon = pos.get('lat'), pos.get('lon')
        if lat and lon and base_id in BASES_COORDS:
            b = BASES_COORDS[base_id]
            direction = _cardinal(_bearing_deg(b['lat'], b['lon'], lat, lon))
        if status == 'AT_BASE':
            return f'<span class="ac-loc-base">AT {base_nm.upper()}</span>'
        if status == 'AIRBORNE':
            alt_ft  = pos.get('last_alt_ft') or ''
            spd_kts = pos.get('last_gs_kts') or ''
            alt_str = f'{int(alt_ft):,} ft' if alt_ft else ''
            spd_str = f'{int(spd_kts)} kts' if spd_kts else ''
            dist_str = (f'{dist_mi:.0f} mi {direction} of {base_nm}' if direction else
                        f'{dist_mi:.0f} mi from {base_nm}') if dist_mi and base_nm else ''
            detail = ' · '.join(p for p in [dist_str, alt_str, spd_str] if p)
            return (f'<span class="ac-loc-air">AIRBORNE</span>'
                    + (f'<span class="ac-loc-detail"> {detail}</span>' if detail else ''))
        if status == 'AWAY':
            dist_str = ((f'{dist_mi:.0f} mi {direction} of {base_nm}' if direction else
                         f'{dist_mi:.0f} mi from {base_nm}') if dist_mi and base_nm
                        else base_nm or 'unknown location')
            return f'<span class="ac-loc-away">AWAY</span><span class="ac-loc-detail"> · {dist_str}</span>'
        return '<span class="ac-loc-unknown">UNKNOWN</span>'

    cards_html = ''
    for tail in ALL_TAILS:
        pos     = positions.get(tail)
        hrs     = ac_hrs.get(tail)
        hrs_str = f'{hrs:,.1f} TT' if hrs else 'N/A'
        status  = pos.get('status', 'UNKNOWN').upper() if pos else 'NO DATA'
        card_cls = {'AT_BASE':'ac-card-base','AIRBORNE':'ac-card-air','AWAY':'ac-card-away'}.get(status,'ac-card-nodata')
        age_str = ''
        last_utc = (pos.get('utc') or pos.get('last_updated','')) if pos else ''
        if last_utc:
            try:
                from datetime import timezone
                dt  = datetime.fromisoformat(last_utc.replace('Z','+00:00'))
                age = (datetime.now(timezone.utc) - dt).total_seconds() / 60
                age_str = f'{int(age)}m ago' if age < 60 else f'{age/60:.1f}h ago'
            except Exception:
                pass
        loc_html = _location_line(tail, pos)
        cards_html += f'''
        <div class="ac-card {card_cls}">
          <div class="ac-card-header">
            <div class="ac-tail">{tail}</div>
            <div class="ac-hours">{hrs_str}</div>
          </div>
          <div class="ac-card-body">
            <div class="ac-loc">{loc_html}</div>
            {f'<div class="ac-age">{age_str}</div>' if age_str else ''}
          </div>
        </div>'''

    last_checked = ''
    for v in positions.values():
        if isinstance(v, dict):
            last_checked = v.get('last_updated', '') or v.get('utc', '')
            if last_checked:
                break

    css = '''<style>
      .ac-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px;margin-top:16px;}
      .ac-card{background:var(--surface);border:1px solid var(--border);border-radius:4px;overflow:hidden;}
      .ac-card-base{border-color:rgba(0,230,118,0.35);}
      .ac-card-air{border-color:rgba(41,182,246,0.4);}
      .ac-card-away{border-color:rgba(255,171,0,0.35);}
      .ac-card-nodata{opacity:.55;}
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
      .ac-age{font-family:var(--mono);font-size:9px;color:var(--muted);margin-top:6px;opacity:.6;}
    </style>'''

    return f'''{css}
    <div class="section-label">Aircraft Location</div>
    <div style="font-family:var(--mono);font-size:10px;color:var(--muted);margin-bottom:4px;">
      Live positions via SkyRouter GPS &nbsp;·&nbsp; auto-refreshes every 60 s
      {f"&nbsp;·&nbsp; last checked {last_checked}" if last_checked else ""}
    </div>
    <div class="ac-grid" id="ac-location-grid">{cards_html}</div>
    <script>
    (function(){{
      function refreshPositions(){{
        fetch('base_assignments.json?t=' + Date.now())
          .then(function(r){{return r.json();}})
          .catch(function(){{return null;}})
          .then(function(data){{
            if(!data) return;
            var grid = document.getElementById('ac-location-grid');
            if(grid) grid.setAttribute('data-refreshed', new Date().toISOString());
          }});
      }}
      setInterval(refreshPositions, 60000);
    }})();
    </script>'''


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    data_dir       = Path(OUTPUT_FOLDER)
    input_path     = data_dir / INPUT_FILENAME
    weekly_path    = data_dir / WEEKLY_FILENAME
    output_path    = Path(OUTPUT_FOLDER) / OUTPUT_FILENAME
    history_path   = Path(OUTPUT_FOLDER) / HISTORY_FILENAME
    positions_path = Path(OUTPUT_FOLDER) / POSITIONS_FILENAME
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


if __name__ == '__main__':
    main()
