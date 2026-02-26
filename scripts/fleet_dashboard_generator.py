"""
Fleet Maintenance Dashboard Generator (CSV)
==========================================
Reads Due-List_Latest.csv from your OneDrive folder and writes
fleet_dashboard.html to the same folder.

Run this script manually or via Windows Task Scheduler after
Selenium downloads the file each day.
"""

import sys
import csv
import re
import json
from datetime import datetime, timedelta
from pathlib import Path

# ── CONFIGURATION ─────────────────────────────────────────────────────────────

OUTPUT_FOLDER = "data"

INPUT_FILENAME  = "Due-List_Latest.csv"
WEEKLY_FILENAME = "Due-List_BIG_WEEKLY.csv"  
OUTPUT_FILENAME = "fleet_dashboard.html"
HISTORY_FILENAME = "flight_hours_history.json"
SKYROUTER_FILENAME = "skyrouter_status.json"
BASE_ASSIGNMENTS_FILENAME = "base_assignments.json"

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

# Component panel: show items within this many hours of retire/overhaul
COMPONENT_WINDOW_HRS = 200

# Keywords that identify retirement/overhaul component items
RETIREMENT_KEYWORDS = [
    'RETIRE', 'OVERHAUL', 'DISCARD', 'LIFE LIMIT', 'TBO',
    'REPLACEMENT', 'REPLACE', 'CHANGE OIL', 'NOZZLE'
]

# ── COLUMN INDICES (0-based, from CAMP export) ────────────────────────────────
COL_REG          = 0
COL_AIRFRAME_RPT = 2   # Airframe Report Date
COL_AIRFRAME_HRS = 3
COL_ATA          = 5   # Column F wording (ATA and Code)
COL_EQUIP_HRS    = 7
COL_ITEM_TYPE    = 11
COL_DISPOSITION  = 13
COL_DESC         = 15
COL_INTERVAL_HRS = 30
COL_REM_DAYS     = 50
COL_REM_MONTHS   = 52
COL_REM_HRS      = 54
COL_STATUS       = 63  # Next Due Status


# ── HELPERS ───────────────────────────────────────────────────────────────────

def safe_float(val):
    """Convert a value to float, return None on failure."""
    if val is None:
        return None
    s = str(val).strip()
    if s == "":
        return None
    try:
        s = s.replace(",", "")
        return float(s)
    except (ValueError, TypeError):
        return None


def classify(hrs):
    """Return a status class based on remaining hours."""
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
    """Fall back classification from CAMP's Next Due Status text."""
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
    """Try to interpret the Airframe Report Date column from CSV."""
    if not val:
        return None
    s = str(val).strip()
    if not s:
        return None

    fmts = [
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%Y-%m-%d %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y %H:%M:%S",
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
    """Load existing flight hours history from JSON file."""
    if not history_path.exists():
        return {}
    
    try:
        with open(history_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_flight_hours_history(history_path, history_data):
    """Save flight hours history to JSON file."""
    try:
        with open(history_path, 'w', encoding='utf-8') as f:
            json.dump(history_data, f, indent=2)
    except Exception as e:
        print(f"Warning: Could not save flight hours history: {e}")


def update_flight_hours_history(history_data, aircraft_list, report_date_dt):
    """
    Update flight hours history with today's data.
    
    Structure:
    {
        "N123AB": {
            "2025-02-25": {"hours": 1234.5, "date": "2025-02-25"},
            "2025-02-24": {"hours": 1230.0, "date": "2025-02-24"},
            ...
        },
        ...
    }
    """
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
        
        # Only update if this date doesn't exist or hours are different
        if date_key not in history_data[tail] or history_data[tail][date_key]['hours'] != hours:
            history_data[tail][date_key] = {
                'hours': hours,
                'date': date_key
            }
    
    # Clean up old entries (keep last 90 days)
    cutoff_date = (datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d")
    for tail in history_data:
        history_data[tail] = {
            date: data for date, data in history_data[tail].items()
            if date >= cutoff_date
        }
    
    return history_data


def calculate_flight_hours_stats(history_data, aircraft_list):
    """
    Calculate weekly and monthly flight hours for each aircraft.
    
    Returns dict with structure:
    {
        "N123AB": {
            "current_hours": 1234.5,
            "daily": [...],  # last 7 days
            "weekly": 12.5,
            "monthly": 45.0,
            "avg_daily": 1.8,
            "projection_weekly": 12.6,
            "projection_monthly": 54.0
        },
        ...
    }
    """
    from datetime import timedelta
    
    today = datetime.today()
    seven_days_ago = today - timedelta(days=7)
    thirty_days_ago = today - timedelta(days=30)
    
    stats = {}
    
    for ac in aircraft_list:
        tail = ac['tail']
        current_hours = ac['airframe_hrs']
        
        if tail not in history_data or current_hours is None:
            stats[tail] = {
                'current_hours': current_hours,
                'daily': [],
                'weekly': None,
                'monthly': None,
                'avg_daily': None,
                'projection_weekly': None,
                'projection_monthly': None
            }
            continue
        
        # Get sorted history for this aircraft
        tail_history = history_data[tail]
        sorted_dates = sorted(tail_history.keys(), reverse=True)
        
        # Build daily data for chart
        daily_data = []
        for date_str in sorted_dates[:7]:
            daily_data.insert(0, {
                'date': date_str,
                'hours': tail_history[date_str]['hours']
            })
        
        # Calculate weekly hours (7 days)
        weekly_hours = None
        if len(sorted_dates) >= 2:
            latest_date = sorted_dates[0]
            latest_hours = tail_history[latest_date]['hours']
            
            # Find entry from ~7 days ago
            seven_days_ago_str = seven_days_ago.strftime("%Y-%m-%d")
            week_ago_hours = None
            
            for date_str in sorted_dates:
                if date_str <= seven_days_ago_str:
                    week_ago_hours = tail_history[date_str]['hours']
                    break
            
            if week_ago_hours is not None:
                weekly_hours = latest_hours - week_ago_hours
        
        # Calculate monthly hours (30 days)
        monthly_hours = None
        if len(sorted_dates) >= 2:
            latest_date = sorted_dates[0]
            latest_hours = tail_history[latest_date]['hours']
            
            # Find entry from ~30 days ago
            thirty_days_ago_str = thirty_days_ago.strftime("%Y-%m-%d")
            month_ago_hours = None
            
            for date_str in sorted_dates:
                if date_str <= thirty_days_ago_str:
                    month_ago_hours = tail_history[date_str]['hours']
                    break
            
            if month_ago_hours is not None:
                monthly_hours = latest_hours - month_ago_hours
        
        # Calculate average daily hours and projections
        avg_daily = None
        projection_weekly = None
        projection_monthly = None
        
        if monthly_hours is not None:
            days_of_data = (today - datetime.strptime(thirty_days_ago_str, "%Y-%m-%d")).days
            if days_of_data > 0:
                avg_daily = monthly_hours / days_of_data
                projection_weekly = avg_daily * 7
                projection_monthly = avg_daily * 30
        
        stats[tail] = {
            'current_hours': current_hours,
            'daily': daily_data,
            'weekly': weekly_hours,
            'monthly': monthly_hours,
            'avg_daily': avg_daily,
            'projection_weekly': projection_weekly,
            'projection_monthly': projection_monthly
        }
    
    return stats


def load_skyrouter_status(skyrouter_path):
    """Load aircraft location status from SkyRouter scraper output."""
    if not skyrouter_path.exists():
        return {}
    
    try:
        with open(skyrouter_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('aircraft', {})
    except Exception:
        return {}


def load_base_assignments(assignments_path):
    """Load base assignments from JSON."""
    if not assignments_path.exists():
        return None
    
    try:
        with open(assignments_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def merge_inspections(weekly_raw: dict, daily_raw: dict) -> dict:
    """
    Both dicts look like: aircraft_raw[tail][interval_key] = {...}
    Return merged where DAILY overrides WEEKLY for each interval_key.
    """
    merged = {}

    tails = set(weekly_raw.keys()) | set(daily_raw.keys())
    for tail in tails:
        merged[tail] = {}
        # start with weekly
        if tail in weekly_raw:
            merged[tail].update(weekly_raw[tail])
        # overwrite with daily
        if tail in daily_raw:
            merged[tail].update(daily_raw[tail])

    return merged


def parse_due_list_parts(filepath):
    """
    Same logic as parse_due_list, but returns the internal pieces so we can merge.
    Returns:
      aircraft_meta, aircraft_raw, components_raw, report_date_dt
    """
    with open(filepath, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)

    if not rows or len(rows) < 2:
        raise ValueError(f"CSV appears empty or missing data rows: {filepath}")

    data_rows = rows[1:]

    aircraft_raw = {}
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
        rpt_date_val = row[COL_AIRFRAME_RPT]
        rpt_date_dt = parse_report_date(rpt_date_val)

        if reg not in aircraft_meta:
            aircraft_meta[reg] = {
                "airframe_hrs": airframe_hrs,
                "report_date": rpt_date_dt,
            }
            if report_date_dt is None and rpt_date_dt:
                report_date_dt = rpt_date_dt

        ata_text   = row[COL_ATA].strip() if row[COL_ATA] else ""
        item_type  = row[COL_ITEM_TYPE].strip() if row[COL_ITEM_TYPE] else ""
        desc       = row[COL_DESC].strip() if row[COL_DESC] else ""
        rem_hrs    = safe_float(row[COL_REM_HRS])
        rem_days   = safe_float(row[COL_REM_DAYS])
        status     = row[COL_STATUS].strip() if row[COL_STATUS] else ""

        # ---- Phase inspections ----
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
                        "rem_hrs": rem_hrs,
                        "rem_days": rem_days,
                        "status": status,
                        "desc": desc,
                    }

        # ---- Components ----
        is_part = (item_type.upper() == "PART")
        is_retirement_insp = (item_type.upper() == "INSPECTION" and has_retirement_keyword(desc))

        if is_part or is_retirement_insp:
            rem_days_val = safe_float(row[COL_REM_DAYS])

            hrs_in_window  = rem_hrs is not None and rem_hrs <= COMPONENT_WINDOW_HRS
            days_in_window = rem_hrs is None and rem_days_val is not None and rem_days_val <= 60
            past_due       = status.strip().upper() == "PAST DUE"

            if hrs_in_window or days_in_window or past_due:
                if reg not in components_raw:
                    components_raw[reg] = []

                clean_desc = desc
                clean_desc = re.sub(r"^\(RII\)\s*", "", clean_desc, flags=re.IGNORECASE)
                clean_desc = re.sub(r"^RII\s+", "", clean_desc, flags=re.IGNORECASE)
                clean_desc = re.sub(r"\n.*", "", clean_desc)
                clean_desc = clean_desc.strip().title()

                disposition = row[COL_DISPOSITION] if row[COL_DISPOSITION] else ""
                rii_flag = ("RII" in str(disposition).upper()) or ("RII" in desc.upper())

                if rem_hrs is not None:
                    sort_key = rem_hrs
                elif rem_days_val is not None:
                    sort_key = rem_days_val * 0.5
                else:
                    sort_key = 9999

                components_raw[reg].append({
                    "name": clean_desc,
                    "rem_hrs": rem_hrs,
                    "rem_days": rem_days_val,
                    "status": status,
                    "rii": rii_flag,
                    "sort_key": sort_key,
                })

    # Sort/dedupe components
    for reg in components_raw:
        seen_names = set()
        deduped = []
        for c in sorted(components_raw[reg], key=lambda x: x["sort_key"]):
            key = c["name"][:40]
            if key not in seen_names:
                seen_names.add(key)
                deduped.append(c)
        components_raw[reg] = deduped

    return aircraft_meta, aircraft_raw, components_raw, report_date_dt


# ── PARSE CSV ────────────────────────────────────────────────────────────────

def parse_due_list(daily_path, weekly_path=None):
    """
    DAILY overrides WEEKLY for inspection buckets.
    Components come from DAILY (so they reflect current urgent items).
    """
    daily_meta, daily_raw, daily_components, daily_rpt_dt = parse_due_list_parts(daily_path)

    weekly_meta = {}
    weekly_raw = {}
    weekly_rpt_dt = None

    if weekly_path and Path(weekly_path).exists():
        weekly_meta, weekly_raw, _weekly_components, weekly_rpt_dt = parse_due_list_parts(weekly_path)

    # Merge inspection buckets: daily wins
    merged_raw = merge_inspections(weekly_raw, daily_raw)

    # Aircraft list: prefer daily meta (hours/report date). If an aircraft only exists in weekly, include it too.
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
                    "rem_hrs": entry.get("rem_hrs"),
                    "rem_days": entry.get("rem_days"),
                    "status": entry.get("status", ""),
                }
            else:
                intervals[i] = None

        aircraft_list.append({
            "tail": reg,
            "airframe_hrs": meta.get("airframe_hrs"),
            "report_date": meta.get("report_date"),
            "intervals": intervals
        })

    # Report date: prefer daily, else weekly, else today
    report_date_dt = daily_rpt_dt or weekly_rpt_dt
    if isinstance(report_date_dt, datetime):
        report_date_str = report_date_dt.strftime("%d %b %Y").upper()
    else:
        report_date_str = datetime.today().strftime("%d %b %Y").upper()

    # Components: DAILY only
    return report_date_str, aircraft_list, daily_components

# ── BUILD HTML ────────────────────────────────────────────────────────────────
def build_html(report_date, aircraft_list, components, flight_hours_stats, skyrouter_status, base_assignments):

    def fmt_hrs(val_dict):
        """Render a table cell badge from an interval dict."""
        if val_dict is None:
            return '<span class="hr-na">—</span>'

        hrs = val_dict['rem_hrs']
        status = val_dict['status']

        if hrs is not None:
            cls = classify(hrs)
            label = f'OVRD {abs(hrs):.0f}' if hrs < 0 else f'{hrs:.1f}'
        else:
            cls = classify_from_status(status)
            days = val_dict.get('rem_days')
            if days is not None:
                label = f'OVRD {abs(days):.0f}d' if days < 0 else f'{days:.0f}d'
            else:
                label = status[:8] if status else '?'

        badge_cls = {
            'overdue': 'hr-overdue',
            'red':     'hr-red',
            'amber':   'hr-amber',
            'green':   'hr-green',
            'na':      'hr-na',
        }.get(cls, 'hr-na')

        if cls == 'na':
            return f'<span class="hr-na">{label}</span>'
        return f'<span class="hr-badge {badge_cls}">{label}</span>'

    # Summary stats
    total_ac = len(aircraft_list)
    crit_count = 0
    coming_count = 0
    comp_overdue = 0

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

    # Table rows
    table_rows_html = ''
    for ac in aircraft_list:
        ah = f"{ac['airframe_hrs']:,.1f}" if ac['airframe_hrs'] else 'N/A'
        
        # Get location status from SkyRouter
        tail = ac['tail']
        location_status = skyrouter_status.get(tail, {})
        
        # Determine location badge
        location_badge = ''
        if location_status:
            at_base = location_status.get('at_base', False)
            status = location_status.get('status', '').upper()
            
            if at_base:
                location_badge = '<span class="location-badge location-at-base">AT BASE</span>'
            elif 'ACTIVE' in status or 'TAKE-OFF' in status or 'LANDING' in status:
                location_badge = '<span class="location-badge location-active">ACTIVE</span>'
            elif 'INACTIVE' in status:
                location_badge = '<span class="location-badge location-away">AWAY</span>'
            else:
                location_badge = f'<span class="location-badge location-unknown">{status[:8]}</span>'
        
        cells = f'''<td>
          <div class="tail-number">{ac['tail']}{location_badge}</div>
          <div class="airframe-hrs">{ah} TT</div>
        </td>'''
        for i in TARGET_INTERVALS:
            cells += f'<td class="hr-cell">{fmt_hrs(ac["intervals"].get(i))}</td>'
        table_rows_html += f'<tr data-tail="{ac["tail"]}">{cells}</tr>\n'

    # Component panels
    comp_panels_html = ''
    for ac in aircraft_list:
        reg = ac['tail']
        comps = components.get(reg, [])
        if not comps:
            continue

        ah = f"{ac['airframe_hrs']:.1f}" if ac['airframe_hrs'] else 'N/A'
        rows_html = ''
        for c in comps:
            rem = c['rem_hrs']
            rem_days = c.get('rem_days')
            status = c.get('status', '')

            if rem is not None:
                cls = classify(rem)
            elif rem_days is not None:
                cls = 'overdue' if rem_days < 0 else ('red' if rem_days <= 7 else ('amber' if rem_days <= 30 else 'green'))
            else:
                cls = classify_from_status(status)

            ind_cls  = {'overdue':'comp-overdue','red':'comp-red','amber':'comp-amber','green':'comp-green'}.get(cls,'comp-green')
            txt_color = {'overdue':'var(--overdue)','red':'var(--red)','amber':'var(--amber)','green':'var(--green)'}.get(cls,'var(--green)')
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

    # --- BUILD FLIGHT HOURS TAB ---
    flight_hours_cards = []
    
    # Create mini chart data for each aircraft
    mini_charts_data = {}
    
    for ac in aircraft_list:
        tail = ac['tail']
        stats = flight_hours_stats.get(tail, {})
        
        current_hrs = stats.get('current_hours')
        weekly = stats.get('weekly')
        monthly = stats.get('monthly')
        avg_daily = stats.get('avg_daily')
        daily_data = stats.get('daily', [])
        
        # Format current hours
        current_hrs_str = f"{current_hrs:,.1f}" if current_hrs else 'N/A'
        
        # Weekly hours
        if weekly is not None:
            weekly_str = f"{weekly:.1f}"
            weekly_class = "positive" if weekly > 5 else ("low" if weekly > 0 else "")
        else:
            weekly_str = "—"
            weekly_class = ""
        
        # Monthly hours
        if monthly is not None:
            monthly_str = f"{monthly:.1f}"
            monthly_class = "positive" if monthly > 20 else ("low" if monthly > 0 else "")
        else:
            monthly_str = "—"
            monthly_class = ""
        
        # Average daily
        if avg_daily is not None:
            avg_daily_str = f"{avg_daily:.2f} hrs/day"
        else:
            avg_daily_str = "—"
        
        # Build mini chart data
        if daily_data and len(daily_data) >= 2:
            chart_dates = [d['date'][-5:] for d in daily_data]  # MM-DD
            chart_hours = [d['hours'] for d in daily_data]
            
            mini_charts_data[tail] = {
                'dates': chart_dates,
                'hours': chart_hours
            }
            
            chart_id = f"chart-{tail.replace(' ', '-')}"
            mini_chart_html = f'<canvas id="{chart_id}" class="mini-chart"></canvas>'
        else:
            mini_chart_html = '<div style="font-family:var(--mono);font-size:11px;color:var(--muted);padding:20px;text-align:center;">Insufficient data (need 2+ days)</div>'
        
        card_html = f'''
        <div class="hours-card">
          <div class="hours-card-header">
            <div class="hours-card-tail">{tail}</div>
            <div class="hours-card-current">{current_hrs_str} TT</div>
          </div>
          <div class="hours-card-body">
            <div class="hours-stat-row">
              <div class="hours-stat-label">Last 7 Days</div>
              <div>
                <div class="hours-stat-value {weekly_class}">{weekly_str}</div>
              </div>
            </div>
            <div class="hours-stat-row">
              <div class="hours-stat-label">Last 30 Days</div>
              <div>
                <div class="hours-stat-value {monthly_class}">{monthly_str}</div>
              </div>
            </div>
            <div class="hours-stat-row">
              <div class="hours-stat-label">Average Daily</div>
              <div>
                <div class="hours-stat-value" style="font-size:18px;">{avg_daily_str}</div>
              </div>
            </div>
            {mini_chart_html}
          </div>
        </div>'''
        
        flight_hours_cards.append(card_html)
    
    if flight_hours_cards:
        flight_hours_tab_html = f'''
    <div class="section-label">Weekly & Monthly Flight Hours by Aircraft</div>
    <div class="hours-grid">
{''.join(flight_hours_cards)}
    </div>'''
    else:
        flight_hours_tab_html = '<div style="font-family:var(--mono);font-size:12px;color:var(--muted);padding:20px;">No flight hours data available yet. Data will accumulate as daily reports are processed.</div>'
    
    # Generate mini chart initialization scripts
    mini_chart_scripts = []
    for tail, data in mini_charts_data.items():
        chart_id = f"chart-{tail.replace(' ', '-')}"
        dates_js = "[" + ",".join([f"'{d}'" for d in data['dates']]) + "]"
        hours_js = "[" + ",".join([f"{h:.1f}" for h in data['hours']]) + "]"
        
        script = f"""
    if (document.getElementById('{chart_id}')) {{
      new Chart(document.getElementById('{chart_id}'), {{
        type: 'line',
        data: {{
          labels: {dates_js},
          datasets: [{{
            label: 'Total Hours',
            data: {hours_js},
            borderColor: '#29b6f6',
            backgroundColor: 'rgba(41, 182, 246, 0.1)',
            borderWidth: 2,
            tension: 0.4,
            pointRadius: 3,
            pointBackgroundColor: '#29b6f6'
          }}]
        }},
        options: {{
          responsive: true,
          maintainAspectRatio: false,
          plugins: {{ 
            legend: {{ display: false }},
            tooltip: {{
              callbacks: {{
                label: function(context) {{
                  return context.parsed.y.toFixed(1) + ' hrs';
                }}
              }}
            }}
          }},
          scales: {{
            y: {{ 
              ticks: {{ color: '#4a5568', font: {{ size: 9 }} }},
              grid: {{ color: 'rgba(30, 37, 48, 0.5)' }}
            }},
            x: {{ 
              ticks: {{ color: '#4a5568', font: {{ size: 9 }} }},
              grid: {{ display: false }}
            }}
          }}
        }}
      }});
    }}"""
        mini_chart_scripts.append(script)
    
    mini_charts_js = '\n'.join(mini_chart_scripts)

    # --- BUILD BASES TAB ---
    bases_tab_html = ''
    
    if base_assignments and 'assignments' in base_assignments:
        assignments = base_assignments['assignments']
        bases_info = base_assignments.get('bases', {})
        
        # Build base cards
        base_cards = []
        for base_id in ['LOGAN', 'MCKAY', 'IMED', 'PROVO', 'ROOSEVELT', 'CEDAR_CITY', 'ST_GEORGE', 'KSLC']:
            if base_id not in assignments:
                continue
            
            base_data = assignments[base_id]
            base_info = bases_info.get(base_id, {})
            base_name = base_info.get('name', base_id)
            
            aircraft_list_html = ''
            status_class = 'available'
            
            if base_data['aircraft']:
                status_class = 'occupied'
                for aircraft in base_data['aircraft']:
                    tail = aircraft['tail']
                    hours = aircraft.get('hours')
                    at_base = aircraft.get('at_base', True)
                    distance = aircraft.get('distance', 0)
                    
                    hours_str = f"{hours:,.1f} TT" if hours else "N/A"
                    status_badge_class = 'base-status-at' if at_base else 'base-status-away'
                    status_text = 'AT BASE' if at_base else 'AWAY'
                    aircraft_class = '' if at_base else 'away'
                    
                    aircraft_list_html += f'''
                    <div class="base-aircraft {aircraft_class}">
                      <div class="base-aircraft-tail">{tail}</div>
                      <span class="base-status-badge {status_badge_class}">{status_text}</span>
                      <div class="base-aircraft-hours">{hours_str}</div>
                    </div>'''
            else:
                aircraft_list_html = '<div class="base-empty">No aircraft assigned</div>'
            
            current_count = len(base_data['aircraft'])
            count_text = f"{current_count} aircraft" if current_count != 1 else "1 aircraft"
            
            base_cards.append(f'''
            <div class="base-card {status_class}">
              <div class="base-header">
                <div class="base-name">{base_name}</div>
                <div class="base-capacity">{count_text}</div>
              </div>
              <div class="base-body">
                {aircraft_list_html}
              </div>
            </div>''')
        
        # Build unassigned aircraft section
        unassigned_html = ''
        if 'unassigned' in assignments and assignments['unassigned']:
            unassigned_cards = []
            for aircraft in assignments['unassigned']:
                tail = aircraft['tail']
                hours = aircraft.get('hours')
                closest_base = aircraft.get('closest_base', 'Unknown')
                distance = aircraft.get('distance_from_closest')
                
                hours_str = f"{hours:,.1f} TT" if hours else "N/A"
                distance_str = f"{distance:.1f} mi from {closest_base}" if distance else "Position unknown"
                
                unassigned_cards.append(f'''
                <div class="unassigned-aircraft">
                  <div class="unassigned-tail">{tail}</div>
                  <div class="unassigned-info">{hours_str}</div>
                  <div class="unassigned-info" style="margin-top:4px;">{distance_str}</div>
                </div>''')
            
            unassigned_html = f'''
            <div class="unassigned-section">
              <div class="section-label">Aircraft Away From Base</div>
              <div class="unassigned-grid">
                {''.join(unassigned_cards)}
              </div>
            </div>'''
        
        bases_tab_html = f'''
    <div class="section-label">Aircraft Base Assignments</div>
    <div class="bases-grid">
{''.join(base_cards)}
    </div>
    {unassigned_html}'''
    else:
        bases_tab_html = '<div style="font-family:var(--mono);font-size:12px;color:var(--muted);padding:20px;">No base assignment data available. Run the base assignment generator first.</div>'

    # --- BAR CHART DATA: hours remaining to 200 hour ---
    chart_rows = []
    for ac in aircraft_list:
        v200 = ac["intervals"].get(200)
        if not v200:
            continue
        rem = v200.get("rem_hrs")
        if rem is None:
            continue
        chart_rows.append((ac["tail"], float(rem)))

    # Sort closest first (most urgent)
    chart_rows.sort(key=lambda x: x[1])

    chart_labels = [t for t, _ in chart_rows]
    chart_values = [v for _, v in chart_rows]

    labels_js = "[" + ",".join([f"'{x}'" for x in chart_labels]) + "]"
    values_js = "[" + ",".join([f"{x:.2f}" for x in chart_values]) + "]"

    chart_css = """
.chart-card{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 14px;
  margin-bottom: 16px;
}
.chart-title{
  font-family: var(--sans);
  font-weight: 800;
  letter-spacing: 2px;
  text-transform: uppercase;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 10px;
}
.chart-card canvas{
  display:block;
  width:100% !important;
  height:320px !important;
}
"""
    
    chart_html = """
<div class="chart-card">
  <div class="chart-title">200 Hr Remaining (Bar)</div>
  <canvas id="bar200"></canvas>
</div>
"""
    
    chart_script = f"""
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
  const labels200 = {labels_js};
  const values200 = {values_js};

  if (!labels200 || labels200.length === 0) {{
    document.getElementById('bar200').parentElement.innerHTML =
      "<div style='font-family:var(--mono);font-size:12px;color:var(--muted);padding:10px;'>No numeric 200-hr remaining hours found today.</div>";
  }} else {{
    new Chart(document.getElementById('bar200'), {{
      type: 'bar',
      data: {{
        labels: labels200,
        datasets: [{{ label: 'Hours remaining to 200 Hr', data: values200 }}]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{ legend: {{ display: true }} }},
        scales: {{
          y: {{ title: {{ display: true, text: 'Hours Remaining' }} }},
          x: {{ title: {{ display: true, text: 'Aircraft (closest first)' }} }}
        }}
      }}
    }});
  }}

  // Mini charts for flight hours tracking
  {mini_charts_js}
</script>
"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>IHC Health Services — Fleet Due List</title>
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Barlow+Condensed:wght@300;400;600;700;900&family=Barlow:wght@300;400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #0a0c0f; --surface: #111418; --surface2: #181c22; --border: #1e2530;
    --green: #00e676; --amber: #ffab00; --red: #ff1744; --overdue: #ff6d00;
    --blue: #29b6f6; --text: #cdd6e0; --muted: #4a5568; --heading: #e8edf2;
    --mono: 'Share Tech Mono', monospace;
    --sans: 'Barlow Condensed', sans-serif;
    --body: 'Barlow', sans-serif;
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:var(--bg); color:var(--text); font-family:var(--body); min-height:100vh; overflow-x:hidden; }}
  body::before {{ content:''; position:fixed; inset:0; background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,0,0,0.03) 2px,rgba(0,0,0,0.03) 4px); pointer-events:none; z-index:1000; }}

  header {{ background:var(--surface); border-bottom:1px solid var(--border); padding:18px 32px; display:flex; align-items:center; justify-content:space-between; position:sticky; top:0; z-index:100; }}
  .logo {{ font-family:var(--sans); font-weight:900; font-size:22px; letter-spacing:3px; color:var(--heading); text-transform:uppercase; }}
  .logo span {{ color:var(--blue); }}
  .subtitle {{ font-family:var(--mono); font-size:11px; color:var(--muted); letter-spacing:2px; text-transform:uppercase; margin-top:3px; }}
  .header-meta {{ font-family:var(--mono); font-size:11px; color:var(--muted); text-align:right; line-height:1.8; }}
  .header-meta .date {{ color:var(--blue); }}

  .legend {{ display:flex; gap:20px; padding:10px 32px; background:var(--surface2); border-bottom:1px solid var(--border); font-family:var(--mono); font-size:11px; flex-wrap:wrap; align-items:center; }}
  .legend-item {{ display:flex; align-items:center; gap:6px; color:var(--muted); text-transform:uppercase; letter-spacing:1px; }}
  .dot {{ width:8px; height:8px; border-radius:50%; flex-shrink:0; }}
  .dot-green  {{ background:var(--green);   box-shadow:0 0 6px var(--green); }}
  .dot-amber  {{ background:var(--amber);   box-shadow:0 0 6px var(--amber); }}
  .dot-red    {{ background:var(--red);     box-shadow:0 0 6px var(--red); }}
  .dot-overdue{{ background:var(--overdue); box-shadow:0 0 6px var(--overdue); }}

  main {{ padding:24px 32px; max-width:1600px; margin:0 auto; }}

  .tabs {{ display:flex; gap:0; margin-bottom:24px; border-bottom:2px solid var(--border); }}
  .tab-btn {{ font-family:var(--sans); font-size:13px; font-weight:700; letter-spacing:2px; text-transform:uppercase; padding:12px 24px; background:transparent; border:none; color:var(--muted); cursor:pointer; transition:all 0.2s; border-bottom:3px solid transparent; }}
  .tab-btn:hover {{ color:var(--text); background:rgba(255,255,255,0.02); }}
  .tab-btn.active {{ color:var(--blue); border-bottom-color:var(--blue); }}
  .tab-content {{ display:none; }}
  .tab-content.active {{ display:block; }}

  .summary-bar {{ display:flex; gap:16px; margin-bottom:24px; flex-wrap:wrap; }}
  
  .summary-stat {{ background:var(--surface); border:1px solid var(--border); border-radius:4px; padding:12px 20px; min-width:130px; }}
  .stat-value {{ font-family:var(--sans); font-size:32px; font-weight:900; line-height:1; margin-bottom:4px; }}
  .stat-label {{ font-family:var(--mono); font-size:10px; color:var(--muted); letter-spacing:1.5px; text-transform:uppercase; }}
  .divider-line {{ width:40px; height:2px; margin:8px 0; border-radius:1px; }}

  .section-label {{ font-family:var(--sans); font-size:11px; font-weight:600; letter-spacing:4px; text-transform:uppercase; color:var(--muted); margin-bottom:12px; margin-top:28px; padding-bottom:6px; border-bottom:1px solid var(--border); }}

  .filter-row {{ display:flex; gap:8px; margin-bottom:16px; flex-wrap:wrap; }}
  .filter-btn {{ font-family:var(--sans); font-size:12px; font-weight:600; letter-spacing:2px; text-transform:uppercase; padding:5px 14px; border:1px solid var(--border); background:transparent; color:var(--muted); border-radius:2px; cursor:pointer; transition:all 0.15s; }}
  .filter-btn:hover, .filter-btn.active {{ background:var(--blue); border-color:var(--blue); color:#000; }}

{chart_css}

  .insp-table-wrap {{ overflow-x:auto; border:1px solid var(--border); border-radius:4px; }}
  table {{ width:100%; border-collapse:collapse; font-family:var(--mono); font-size:12px; min-width:900px; }}
  thead th {{ background:var(--surface2); padding:10px 14px; text-align:left; font-family:var(--sans); font-weight:700; font-size:11px; letter-spacing:2px; text-transform:uppercase; color:var(--muted); border-bottom:1px solid var(--border); white-space:nowrap; }}
  thead th:first-child {{ color:var(--heading); min-width:110px; }}
  tbody tr {{ border-bottom:1px solid var(--border); transition:background 0.15s; }}
  tbody tr:hover {{ background:rgba(255,255,255,0.02); }}
  tbody td {{ padding:11px 14px; vertical-align:middle; }}
  .tail-number {{ font-family:var(--sans); font-weight:700; font-size:16px; letter-spacing:1px; color:var(--heading); }}
  .airframe-hrs {{ font-size:10px; color:var(--muted); margin-top:1px; }}
  .location-badge {{ display:inline-block; padding:2px 8px; border-radius:2px; font-size:9px; font-family:var(--mono); margin-left:8px; letter-spacing:0.5px; vertical-align:middle; }}
  .location-at-base {{ background:rgba(0,230,118,0.15); color:var(--green); border:1px solid rgba(0,230,118,0.3); }}
  .location-away {{ background:rgba(255,23,68,0.12); color:var(--red); border:1px solid rgba(255,23,68,0.3); }}
  .location-active {{ background:rgba(41,182,246,0.12); color:var(--blue); border:1px solid rgba(41,182,246,0.3); }}
  .location-unknown {{ background:rgba(74,85,104,0.2); color:var(--muted); border:1px solid rgba(74,85,104,0.3); }}
  .hr-cell {{ text-align:center; min-width:80px; }}
  .hr-badge {{ display:inline-block; padding:4px 10px; border-radius:3px; font-size:12px; text-align:center; min-width:56px; letter-spacing:0.5px; }}
  .hr-green   {{ background:rgba(0,230,118,0.08);   color:var(--green);   border:1px solid rgba(0,230,118,0.2); }}
  .hr-amber   {{ background:rgba(255,171,0,0.10);   color:var(--amber);   border:1px solid rgba(255,171,0,0.25); }}
  .hr-red     {{ background:rgba(255,23,68,0.10);   color:var(--red);     border:1px solid rgba(255,23,68,0.25); }}
  .hr-overdue {{ background:rgba(255,109,0,0.12);   color:var(--overdue); border:1px solid rgba(255,109,0,0.3); animation:pulse 2s ease-in-out infinite; }}
  .hr-na      {{ color:var(--muted); font-size:11px; letter-spacing:1px; }}
  @keyframes pulse {{ 0%,100% {{ opacity:1; }} 50% {{ opacity:0.55; }} }}

  .components-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(340px,1fr)); gap:16px; }}
  .aircraft-panel {{ background:var(--surface); border:1px solid var(--border); border-radius:4px; overflow:hidden; }}
  .panel-header {{ display:flex; align-items:center; justify-content:space-between; padding:10px 16px; background:var(--surface2); border-bottom:1px solid var(--border); }}
  .panel-tail {{ font-family:var(--sans); font-weight:900; font-size:18px; letter-spacing:1px; color:var(--heading); }}
  .panel-hours {{ font-family:var(--mono); font-size:10px; color:var(--muted); }}
  .component-row {{ display:flex; align-items:center; padding:9px 16px; border-bottom:1px solid rgba(30,37,48,0.8); gap:12px; }}
  .component-row:last-child {{ border-bottom:none; }}
  .comp-indicator {{ width:3px; height:32px; border-radius:2px; flex-shrink:0; }}
  .comp-green   {{ background:var(--green); }}
  .comp-amber   {{ background:var(--amber); }}
  .comp-red     {{ background:var(--red); }}
  .comp-overdue {{ background:var(--overdue); animation:pulse 2s ease-in-out infinite; }}
  .comp-info {{ flex:1; min-width:0; }}
  .comp-name {{ font-family:var(--body); font-size:12px; font-weight:500; color:var(--text); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; line-height:1.3; }}
  .comp-hrs {{ font-family:var(--mono); font-size:11px; margin-top:2px; }}
  .rii-badge {{ display:inline-block; padding:1px 5px; font-size:9px; font-family:var(--mono); background:rgba(255,171,0,0.15); color:var(--amber); border:1px solid rgba(255,171,0,0.3); border-radius:2px; vertical-align:middle; margin-left:4px; letter-spacing:1px; }}

  .hours-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(380px,1fr)); gap:16px; }}
  .hours-card {{ background:var(--surface); border:1px solid var(--border); border-radius:4px; overflow:hidden; }}
  .hours-card-header {{ padding:14px 18px; background:var(--surface2); border-bottom:1px solid var(--border); display:flex; justify-content:space-between; align-items:center; }}
  .hours-card-tail {{ font-family:var(--sans); font-weight:900; font-size:18px; letter-spacing:1px; color:var(--heading); }}
  .hours-card-current {{ font-family:var(--mono); font-size:11px; color:var(--muted); }}
  .hours-card-body {{ padding:18px; }}
  .hours-stat-row {{ display:flex; justify-content:space-between; align-items:baseline; margin-bottom:16px; padding-bottom:12px; border-bottom:1px solid rgba(30,37,48,0.6); }}
  .hours-stat-row:last-child {{ border-bottom:none; margin-bottom:0; }}
  .hours-stat-label {{ font-family:var(--mono); font-size:10px; color:var(--muted); letter-spacing:1px; text-transform:uppercase; }}
  .hours-stat-value {{ font-family:var(--sans); font-size:24px; font-weight:900; color:var(--heading); }}
  .hours-stat-value.positive {{ color:var(--green); }}
  .hours-stat-value.low {{ color:var(--amber); }}
  .hours-stat-sub {{ font-family:var(--mono); font-size:10px; color:var(--muted); margin-top:2px; }}
  .mini-chart {{ height:80px; margin-top:12px; }}

  .bases-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:16px; margin-bottom:24px; }}
  .base-card {{ background:var(--surface); border:1px solid var(--border); border-radius:4px; overflow:hidden; transition:all 0.2s; }}
  .base-card.occupied {{ border-color:var(--green); box-shadow:0 0 0 1px var(--green); }}
  .base-card.available {{ border-color:var(--border); }}
  .base-header {{ padding:12px 16px; background:var(--surface2); border-bottom:1px solid var(--border); display:flex; justify-content:space-between; align-items:center; }}
  .base-name {{ font-family:var(--sans); font-weight:900; font-size:18px; letter-spacing:1px; color:var(--heading); }}
  .base-capacity {{ font-family:var(--mono); font-size:10px; color:var(--muted); }}
  .base-body {{ padding:16px; min-height:80px; }}
  .base-aircraft {{ display:flex; align-items:center; gap:10px; padding:10px; background:rgba(0,230,118,0.08); border:1px solid rgba(0,230,118,0.2); border-radius:3px; margin-bottom:8px; }}
  .base-aircraft.away {{ background:rgba(255,171,0,0.10); border-color:rgba(255,171,0,0.25); }}
  .base-aircraft-tail {{ font-family:var(--sans); font-weight:700; font-size:14px; color:var(--heading); }}
  .base-aircraft-hours {{ font-family:var(--mono); font-size:11px; color:var(--muted); margin-left:auto; }}
  .base-status-badge {{ display:inline-block; padding:4px 10px; border-radius:3px; font-family:var(--mono); font-size:10px; font-weight:600; letter-spacing:1px; }}
  .base-status-at {{ background:rgba(0,230,118,0.15); color:var(--green); border:1px solid rgba(0,230,118,0.3); }}
  .base-status-away {{ background:rgba(255,171,0,0.15); color:var(--amber); border:1px solid rgba(255,171,0,0.3); }}
  .base-empty {{ font-family:var(--mono); font-size:11px; color:var(--muted); text-align:center; padding:20px; }}
  .unassigned-section {{ margin-top:24px; }}
  .unassigned-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:12px; }}
  .unassigned-aircraft {{ background:var(--surface); border:1px solid var(--border); border-radius:3px; padding:12px; }}
  .unassigned-tail {{ font-family:var(--sans); font-weight:700; font-size:14px; color:var(--heading); margin-bottom:4px; }}
  .unassigned-info {{ font-family:var(--mono); font-size:10px; color:var(--muted); }}

  footer {{ margin-top:48px; padding:16px 32px; border-top:1px solid var(--border); font-family:var(--mono); font-size:10px; color:var(--muted); display:flex; justify-content:space-between; letter-spacing:1px; }}
</style>
</head>
<body>
<header>
  <div>
    <div class="logo">IHC <span>HEALTH</span> SERVICES</div>
    <div class="subtitle">AW109SP Fleet &nbsp;—&nbsp; Maintenance Due List</div>
  </div>
  <div class="header-meta">
    <div class="date">REPORT DATE: {report_date}</div>
    <div>FLEET: {total_ac} AIRCRAFT &nbsp;|&nbsp; GENERATED: {datetime.today().strftime('%d %b %Y %H:%M').upper()}</div>
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
    <button class="tab-btn active" onclick="switchTab('maintenance', this)">Maintenance Due List</button>
    <button class="tab-btn" onclick="switchTab('flight-hours', this)">Flight Hours Tracking</button>
    <button class="tab-btn" onclick="switchTab('bases', this)">Bases</button>
  </div>

  <!-- MAINTENANCE TAB -->
  <div id="tab-maintenance" class="tab-content active">
  <div class="summary-bar">
    <div class="summary-stat">
      <div class="stat-value" style="color:var(--blue)">{total_ac}</div>
      <div class="divider-line" style="background:var(--blue)"></div>
      <div class="stat-label">Aircraft</div>
    </div>
    <div class="summary-stat">
      <div class="stat-value" style="color:var(--red)">{crit_count}</div>
      <div class="divider-line" style="background:var(--red)"></div>
      <div class="stat-label">Insp. Critical / OD</div>
    </div>
    <div class="summary-stat">
      <div class="stat-value" style="color:var(--amber)">{coming_count}</div>
      <div class="divider-line" style="background:var(--amber)"></div>
      <div class="stat-label">Insp. Coming Due</div>
    </div>
    <div class="summary-stat">
      <div class="stat-value" style="color:var(--overdue)">{comp_overdue}</div>
      <div class="divider-line" style="background:var(--overdue)"></div>
      <div class="stat-label">Components Overdue</div>
    </div>
  </div>

{chart_html}

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
          <th class="hr-cell">50 Hr</th>
          <th class="hr-cell">100 Hr</th>
          <th class="hr-cell">200 Hr</th>
          <th class="hr-cell">400 Hr</th>
          <th class="hr-cell">800 Hr</th>
          <th class="hr-cell">2400 Hr</th>
          <th class="hr-cell">3200 Hr</th>
        </tr>
      </thead>
      <tbody id="insp-tbody">
{table_rows_html}
      </tbody>
    </table>
  </div>

  <div class="section-label" style="margin-top:36px;">Component Retirement / Overhaul — Within {COMPONENT_WINDOW_HRS} Hours</div>
  <div class="components-grid">
{comp_panels_html}
  </div>
  </div>
  <!-- END MAINTENANCE TAB -->

  <!-- FLIGHT HOURS TAB -->
  <div id="tab-flight-hours" class="tab-content">
{flight_hours_tab_html}
  </div>
  <!-- END FLIGHT HOURS TAB -->

  <!-- BASES TAB -->
  <div id="tab-bases" class="tab-content">
{bases_tab_html}
  </div>
  <!-- END BASES TAB -->

</main>

<footer>
  <span>SOURCE: CAMP MAINTENANCE TRACKING &nbsp;|&nbsp; {INPUT_FILENAME}</span>
  <span>IHC HEALTH SERVICES — AVIATION MAINTENANCE</span>
</footer>

<script>
  function switchTab(tabName, btn) {{
    // Update button states
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    
    // Update content visibility
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
</script>
{chart_script}
</body>
</html>"""
    
    return html


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    input_path  = Path(OUTPUT_FOLDER) / INPUT_FILENAME
    output_path = Path(OUTPUT_FOLDER) / OUTPUT_FILENAME
    history_path = Path(OUTPUT_FOLDER) / HISTORY_FILENAME
    skyrouter_path = Path(OUTPUT_FOLDER) / SKYROUTER_FILENAME
    log_path = Path(__file__).with_name("dashboard_log.txt")

    def log(msg):
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        line = f"[{timestamp}] {msg}"
        print(line)
        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
        except Exception:
            pass

    log("Dashboard generator started.")

    if not input_path.exists():
        log(f"WARNING: Input file not found: {input_path}")
        log("Previous dashboard left in place. Will retry next run.")
        sys.exit(0)

    file_age_hrs = (datetime.now().timestamp() - input_path.stat().st_mtime) / 3600
    if file_age_hrs > 36:
        log(f"WARNING: Input file is {file_age_hrs:.1f} hours old. May not be today's data.")

    try:
        log(f"Parsing {input_path} ...")
        weekly_path = Path(OUTPUT_FOLDER) / WEEKLY_FILENAME
        
        if not weekly_path.exists():
            log(f"WARNING: Weekly big file not found: {weekly_path} (missing long-range inspections will stay blank)")
        
        report_date, aircraft_list, components = parse_due_list(input_path, weekly_path)
        log(f"Parsed {len(aircraft_list)} aircraft.")

        # Load and update flight hours history
        log("Loading flight hours history...")
        history_data = load_flight_hours_history(history_path)
        
        # Get report date as datetime for history tracking
        report_date_dt = None
        for ac in aircraft_list:
            if ac.get('report_date'):
                report_date_dt = ac['report_date']
                break
        
        history_data = update_flight_hours_history(history_data, aircraft_list, report_date_dt)
        save_flight_hours_history(history_path, history_data)
        log(f"Updated flight hours history with {len(aircraft_list)} aircraft entries.")
        
        # Calculate flight hours statistics
        flight_hours_stats = calculate_flight_hours_stats(history_data, aircraft_list)
        log("Calculated flight hours statistics.")

        # Load SkyRouter status
        log("Loading SkyRouter status...")
        skyrouter_status = load_skyrouter_status(skyrouter_path)
        if skyrouter_status:
            log(f"Loaded SkyRouter status for {len(skyrouter_status)} aircraft.")
        else:
            log("No SkyRouter status data available (will show unknown status).")

        # Load base assignments
        log("Loading base assignments...")
        assignments_path = Path(OUTPUT_FOLDER) / BASE_ASSIGNMENTS_FILENAME
        base_assignments = load_base_assignments(assignments_path)
        if base_assignments:
            log(f"Loaded base assignments (last updated: {base_assignments.get('last_updated', 'unknown')})")
        else:
            log("No base assignments data available (Bases tab will be empty).")

        html = build_html(report_date, aircraft_list, components, flight_hours_stats, skyrouter_status, base_assignments)

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
