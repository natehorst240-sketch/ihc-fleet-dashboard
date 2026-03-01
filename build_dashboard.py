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
OUTPUT_FILENAME    = "fleet_dashboard.html"
HISTORY_FILENAME   = "flight_hours_history.json"
POSITIONS_FILENAME = "positions_aw109sp.json"

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
    """
    Load aircraft positions from positions_aw109sp.json produced by fetch_positions.py.
    Returns dict keyed by tail number.
    """
    if not positions_path.exists():
        return {}
    try:
        with open(positions_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('aircraft', {})
    except Exception:
        return {}


def get_location_badge(tail, positions):
    """
    Return HTML badge for aircraft location status using ADSB positions data.
    Statuses: AIRBORNE, AT_BASE, AWAY, NO_SIGNAL, UNKNOWN
    """
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
    """Return list of flights today for a tail from positions data."""
    ac = positions.get(tail, {})
    return ac.get('flights_today', [])


def get_hours_today(tail, positions):
    """Return total flight hours today from positions data."""
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

        # Phase inspections
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

        # Components
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

    return aircraft_meta, aircraft_raw, components_raw, report_date_dt


def parse_due_list(daily_path, weekly_path=None):
    daily_meta, daily_raw, daily_components, daily_rpt_dt = parse_due_list_parts(daily_path)
    weekly_meta = {}
    weekly_raw  = {}
    weekly_rpt_dt = None
    if weekly_path and Path(weekly_path).exists():
        weekly_meta, weekly_raw, _, weekly_rpt_dt = parse_due_list_parts(weekly_path)

    merged_raw = merge_inspections(weekly_raw, daily_raw)
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
        })

    report_date_dt = daily_rpt_dt or weekly_rpt_dt
    if isinstance(report_date_dt, datetime):
        report_date_str = report_date_dt.strftime("%d %b %Y").upper()
    else:
        report_date_str = datetime.today().strftime("%d %b %Y").upper()

    return report_date_str, aircraft_list, daily_components


# ── BUILD HTML ────────────────────────────────────────────────────────────────

def build_html(report_date, aircraft_list, components, flight_hours_stats, positions):

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

    # Summary stats
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

    # Count airborne / at base from positions
    airborne_count = sum(1 for t in aircraft_list if positions.get(t['tail'], {}).get('status') == 'AIRBORNE')
    at_base_count  = sum(1 for t in aircraft_list if positions.get(t['tail'], {}).get('status') == 'AT_BASE')

    # Table rows
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

    # Flight hours tab
    flight_hours_cards = []
    mini_charts_data   = {}
    for ac in aircraft_list:
        tail  = ac['tail']
        stats = flight_hours_stats.get(tail, {})
        current_hrs  = stats.get('current_hours')
        weekly       = stats.get('weekly')
        monthly      = stats.get('monthly')
        avg_daily    = stats.get('avg_daily')
        daily_data   = stats.get('daily', [])
        current_hrs_str = f"{current_hrs:,.1f}" if current_hrs else 'N/A'
        weekly_str  = f"{weekly:.1f}"  if weekly  is not None else "—"
        monthly_str = f"{monthly:.1f}" if monthly is not None else "—"
        avg_daily_str = f"{avg_daily:.2f} hrs/day" if avg_daily is not None else "—"
        weekly_class  = "positive" if weekly  and weekly  > 5  else ("low" if weekly  and weekly  > 0 else "")
        monthly_class = "positive" if monthly and monthly > 20 else ("low" if monthly and monthly > 0 else "")

        # ADSB hours today
        hrs_today = get_hours_today(tail, positions)
        flights_today = get_flights_today(tail, positions)
        adsb_html = ''
        if hrs_today or flights_today:
            adsb_html = f'''
            <div class="hours-stat-row">
              <div class="hours-stat-label">ADSB Today</div>
              <div>
                <div class="hours-stat-value" style="font-size:18px;color:var(--blue);">{hrs_today:.1f} hrs</div>
                <div class="hours-stat-sub">{len(flights_today)} flight(s)</div>
              </div>
            </div>'''

        if daily_data and len(daily_data) >= 2:
            chart_id = f"chart-{tail.replace(' ', '-')}"
            mini_charts_data[tail] = {
                'dates': [d['date'][-5:] for d in daily_data],
                'hours': [d['hours'] for d in daily_data],
            }
            mini_chart_html = f'<canvas id="{chart_id}" class="mini-chart"></canvas>'
        else:
            mini_chart_html = '<div style="font-family:var(--mono);font-size:11px;color:var(--muted);padding:20px;text-align:center;">Insufficient data (need 2+ days)</div>'

        flight_hours_cards.append(f'''
        <div class="hours-card">
          <div class="hours-card-header">
            <div class="hours-card-tail">{tail}</div>
            <div class="hours-card-current">{current_hrs_str} TT</div>
          </div>
          <div class="hours-card-body">
            {adsb_html}
            <div class="hours-stat-row">
              <div class="hours-stat-label">Last 7 Days</div>
              <div><div class="hours-stat-value {weekly_class}">{weekly_str}</div></div>
            </div>
            <div class="hours-stat-row">
              <div class="hours-stat-label">Last 30 Days</div>
              <div><div class="hours-stat-value {monthly_class}">{monthly_str}</div></div>
            </div>
            <div class="hours-stat-row">
              <div class="hours-stat-label">Average Daily</div>
              <div><div class="hours-stat-value" style="font-size:18px;">{avg_daily_str}</div></div>
            </div>
            {mini_chart_html}
          </div>
        </div>''')

    flight_hours_tab_html = f'''
    <div class="section-label">Weekly & Monthly Flight Hours by Aircraft</div>
    <div class="hours-grid">{''.join(flight_hours_cards)}</div>''' if flight_hours_cards else \
    '<div style="font-family:var(--mono);font-size:12px;color:var(--muted);padding:20px;">No flight hours data available yet.</div>'

    # Mini chart scripts
    mini_charts_js = '\n'.join([f"""
    if (document.getElementById('chart-{tail.replace(" ", "-")}')) {{
      new Chart(document.getElementById('chart-{tail.replace(" ", "-")}'), {{
        type: 'line',
        data: {{
          labels: [{','.join([f"'{d}'" for d in data['dates']])}],
          datasets: [{{ label: 'Total Hours', data: [{','.join([f'{h:.1f}' for h in data['hours']])}],
            borderColor: '#29b6f6', backgroundColor: 'rgba(41,182,246,0.1)',
            borderWidth: 2, tension: 0.4, pointRadius: 3, pointBackgroundColor: '#29b6f6'
          }}]
        }},
        options: {{
          responsive: true, maintainAspectRatio: false,
          plugins: {{ legend: {{ display: false }},
            tooltip: {{ callbacks: {{ label: function(c) {{ return c.parsed.y.toFixed(1) + ' hrs'; }} }} }}
          }},
          scales: {{
            y: {{ ticks: {{ color: '#4a5568', font: {{ size: 9 }} }}, grid: {{ color: 'rgba(30,37,48,0.5)' }} }},
            x: {{ ticks: {{ color: '#4a5568', font: {{ size: 9 }} }}, grid: {{ display: false }} }}
          }}
        }}
      }});
    }}""" for tail, data in mini_charts_data.items()])

    # Bases tab — built from positions data
    bases_tab_html = _build_bases_tab(aircraft_list, positions)

    # Bar chart data
    chart_rows = sorted(
        [(ac['tail'], float(v['rem_hrs'])) for ac in aircraft_list
         if (v := ac['intervals'].get(200)) and v.get('rem_hrs') is not None],
        key=lambda x: x[1]
    )
    labels_js = "[" + ",".join([f"'{t}'" for t, _ in chart_rows]) + "]"
    values_js = "[" + ",".join([f"{v:.2f}" for _, v in chart_rows]) + "]"

    # ── HTML ──────────────────────────────────────────────────────────────────
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
  footer{{margin-top:48px;padding:16px 32px;border-top:1px solid var(--border);font-family:var(--mono);font-size:10px;color:var(--muted);display:flex;justify-content:space-between;letter-spacing:1px;}}
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

  <!-- BASES TAB -->
  <div id="tab-bases" class="tab-content">
{bases_tab_html}
  </div>
</main>
<footer>
  <span>SOURCE: VERYON MAINTENANCE TRACKING &nbsp;|&nbsp; {INPUT_FILENAME}</span>
  <span>IHC HEALTH SERVICES — AVIATION MAINTENANCE</span>
</footer>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
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
      data: {{ labels: labels200, datasets: [{{ label: 'Hours remaining to 200 Hr', data: values200 }}] }},
      options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{ legend: {{ display: true }} }},
        scales: {{
          y: {{ title: {{ display: true, text: 'Hours Remaining' }} }},
          x: {{ title: {{ display: true, text: 'Aircraft (closest first)' }} }}
        }}
      }}
    }});
  }}
  {mini_charts_js}
</script>
</body>
</html>"""


def _build_bases_tab(aircraft_list, positions):
    """Build the bases tab from live ADSB positions data."""
    if not positions:
        return '<div style="font-family:var(--mono);font-size:12px;color:var(--muted);padding:20px;">No position data available. Runs after fetch_positions.py completes.</div>'

    # Group aircraft by base
    base_buckets = {}   # base_id -> list of (tail, ac_pos, airframe_hrs)
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

    # Base cards
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

    # Airborne section
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

    # Away section
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


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    input_path     = Path(OUTPUT_FOLDER) / INPUT_FILENAME
    weekly_path    = Path(OUTPUT_FOLDER) / WEEKLY_FILENAME
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
        log(f"WARNING: Input file not found: {input_path}")
        log("Previous dashboard left in place. Will retry next run.")
        sys.exit(0)

    file_age_hrs = (datetime.now().timestamp() - input_path.stat().st_mtime) / 3600
    if file_age_hrs > 36:
        log(f"WARNING: Input file is {file_age_hrs:.1f} hours old. May not be today's data.")

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

        html = build_html(report_date, aircraft_list, components, flight_hours_stats, positions)

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
