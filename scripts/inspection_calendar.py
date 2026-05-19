"""
Projected Inspection Calendar — drop-in module
==============================================

Self-contained extract of the "Calendar" tab from the IHC fleet dashboard,
designed to be reusable across aircraft-type repos.

What this module does:
  1. Projects the next due date for each inspection interval on each aircraft
     using whichever limit (hours-remaining or calendar-remaining) hits first.
  2. Serialises those projections into JSON for the front-end.
  3. Returns a self-contained HTML/CSS/JS block that renders a FullCalendar
     view with hover detail, an estimated-inspection sidebar, and click-to-
     schedule modals backed by Supabase.

Usage from your dashboard generator
-----------------------------------
    from inspection_calendar import build_calendar_tab

    calendar_tab_html = build_calendar_tab(
        aircraft_list       = aircraft_list,        # see "Inputs" below
        flight_hours_stats  = flight_hours_stats,
        interval_cfg        = cfg['inspection_intervals'],
        tracked_tails       = ['N251HC', 'N261HC', ...],
        supabase_url        = 'https://<project>.supabase.co',
        supabase_anon_key   = 'eyJ...',
    )

Then inject `calendar_tab_html` into your page and make sure the page
includes FullCalendar 6 from a CDN:

    <script src="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.10/index.global.min.js"></script>

Inputs
------
aircraft_list: list of dicts. Each entry:
    {
        'tail':         'N251HC',
        'airframe_hrs': 1234.5,             # None to skip the aircraft
        'intervals':    {                   # keyed by interval_key(iv)
            50:   {'rem_hrs': 12.3,  'rem_days': None, 'rem_months': None},
            100:  {'rem_hrs': 47.8,  'rem_days': None, 'rem_months': None},
            ...
        },
    }

flight_hours_stats: dict keyed by tail. Each entry:
    { 'avg_daily': 1.7 }                    # average flight hrs / day

interval_cfg: list of dicts (typically from configs/<aircraft>.json):
    [
        {'label': '50 Hr', 'hours': 50, 'days': None,
         'color': '#00897b', 'calendar_duration_days': 1},
        ...
    ]

Supabase tables expected (PostgREST defaults, RLS-permitted for anon):
    scheduled_inspections (
        id text primary key,
        tail text, inspection_type text, color text,
        start_date date, end_date date, note text
    )
    watchlist_notes (
        id text primary key,
        tail text, note text,
        timestamp timestamptz default now()
    )

If you don't want Supabase, the `api/src/functions/calendar.js` Azure
Function in the original repo provides Gist-backed storage with the same
event shape — swap the supaFetch() calls for fetch('/api/calendar', ...).
"""

import json
from datetime import datetime, timedelta


def interval_key(iv):
    """Canonical dict key for an interval: hours int when available, else 'd{days}'."""
    return iv['hours'] if iv.get('hours') is not None else f"d{iv['days']}"


def build_calendar_tab(
    aircraft_list,
    flight_hours_stats,
    interval_cfg=None,
    tracked_tails=None,
    supabase_url='',
    supabase_anon_key='',
):
    today_dt  = datetime.today()
    today     = today_dt.date()

    if interval_cfg:
        INTERVAL_COLOR = {interval_key(iv): iv.get('color', '#4a5568') for iv in interval_cfg}
        INTERVAL_LABEL = {interval_key(iv): iv.get('label', str(interval_key(iv))) for iv in interval_cfg}
        INTERVAL_DURATION_DAYS = {interval_key(iv): max(1, int(iv.get('calendar_duration_days', 1) or 1)) for iv in interval_cfg}
    else:
        INTERVAL_COLOR = {
            50:   '#00897b',
            100:  '#1e88e5',
            200:  '#8e24aa',
            400:  '#e53935',
            800:  '#fb8c00',
            2400: '#43a047',
            3200: '#6d4c41',
        }
        INTERVAL_LABEL = {k: f"{k} HR" for k in INTERVAL_COLOR}
        INTERVAL_DURATION_DAYS = {
            50: 1, 100: 1, 200: 3, 400: 4, 800: 4, 2400: 7, 3200: 21,
        }

    # ── Projected next due math ───────────────────────────────────────────────
    maint_events = []
    for ac in aircraft_list:
        tail = ac['tail']
        if ac['airframe_hrs'] is None:
            continue
        avg_daily = flight_hours_stats.get(tail, {}).get('avg_daily')
        if not avg_daily or avg_daily <= 0:
            continue

        for interval in list(INTERVAL_COLOR.keys()):
            v = ac['intervals'].get(interval)
            if v is None:
                continue
            rem_hrs    = v.get('rem_hrs')
            rem_days   = v.get('rem_days')
            rem_months = v.get('rem_months')

            # Convert months + days into a single total_days value.
            # rem_months = whole months remaining, rem_days = days beyond those months.
            if rem_months is not None or rem_days is not None:
                total_days = (rem_months or 0) * 30 + (rem_days or 0)
            else:
                total_days = None

            if rem_hrs is None and total_days is None:
                continue

            due_candidates = []
            due_reasons = []

            if rem_hrs is not None:
                if rem_hrs < 0:
                    due_candidates.append(today)
                    due_reasons.append(('hours_past_due', rem_hrs, 0.0))
                else:
                    days_away = rem_hrs / avg_daily
                    due_candidates.append(today + timedelta(days=days_away))
                    due_reasons.append(('hours_remaining', rem_hrs, days_away))

            if total_days is not None:
                due_candidates.append(today + timedelta(days=total_days))
                due_reasons.append(('days_remaining', total_days, total_days))

            due_idx = min(range(len(due_candidates)), key=lambda idx: due_candidates[idx])
            due = due_candidates[due_idx].date() if isinstance(due_candidates[due_idx], datetime) else due_candidates[due_idx]
            reason_kind, reason_value, reason_days = due_reasons[due_idx]

            def _months_days_label(td):
                mo = int(td) // 30
                dy = int(abs(td)) % 30
                if td < 0:
                    return f'{abs(int(td))} days PAST LIMIT'
                if mo > 0 and dy > 0:
                    return f'~{mo} mo {dy} days remaining'
                if mo > 0:
                    return f'~{mo} month{"s" if mo != 1 else ""} remaining'
                return f'~{dy} days remaining'

            if reason_kind == 'hours_past_due':
                rem_label = f'{abs(reason_value):.1f} hrs PAST LIMIT'
            elif reason_kind == 'days_remaining':
                rem_label = _months_days_label(reason_value)
                if rem_hrs is not None and rem_hrs >= 0:
                    rem_label += f' · {rem_hrs:.1f} hrs remaining'
            else:
                rem_label = f'{reason_value:.1f} hrs remaining (~{reason_days:.1f} days)'
                if total_days is not None and total_days >= 0:
                    rem_label += f' · earlier than {_months_days_label(total_days)}'

            maint_events.append({
                'tail': tail,
                'interval': interval,
                'intervalLabel': INTERVAL_LABEL.get(interval, f'{interval} HR'),
                'dueDate': due.isoformat(),
                'durationDays': INTERVAL_DURATION_DAYS.get(interval, 1),
                'remLabel': rem_label,
                'color': INTERVAL_COLOR.get(interval, '#4a5568'),
            })

    events_json = json.dumps(maint_events)

    # JS-side aircraft list (for the "Schedule Inspection" modal dropdown)
    tails_js = json.dumps(sorted(tracked_tails or [ac['tail'] for ac in aircraft_list]))

    legend_items = []
    for key in sorted(INTERVAL_COLOR.keys(), key=lambda x: (isinstance(x, str), x)):
        legend_items.append(
            f'<span class="cal-leg-item"><span class="cal-leg-bar" style="background:{INTERVAL_COLOR[key]}"></span>{INTERVAL_LABEL.get(key, str(key))}</span>'
        )
    legend_html = ''.join(legend_items)

    return f"""
<style>
#cal-shell {{
  display: grid;
  grid-template-columns: 1.8fr 1fr;
  gap: 12px;
  align-items: start;
}}
@media (max-width: 1100px) {{
  #cal-shell {{ grid-template-columns: 1fr; }}
}}
@media (max-width: 760px) {{
  #calendar-wrap {{ padding: 4px 2px; min-height: 0; }}
  #maint-calendar {{ min-height: 0; }}
  .fc .fc-daygrid-body,
  .fc .fc-scrollgrid-sync-table,
  .fc table {{ width: 100% !important; min-width: 0 !important; }}
  .fc .fc-col-header-cell-cushion {{ font-size: 9px; padding: 2px 1px; }}
  .fc .fc-daygrid-day-number {{ font-size: 10px; padding: 2px 3px; }}
  .fc .fc-daygrid-event {{ padding: 1px 3px; }}
  .fc-maint-pill {{ gap: 2px; font-size: 8px; }}
  .fc-maint-pill strong, .fc-maint-pill span {{ max-width: 34px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .fc .fc-toolbar-title {{ font-size: 16px; }}
  .fc .fc-button {{ font-size: 9px; padding: 3px 5px; }}
}}
#calendar-wrap {{
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface);
  min-height: 720px;
  padding: 12px;
}}
#maint-calendar {{
  min-height: 680px;
  max-width: 100%;
}}
.fc .fc-toolbar-title {{
  font-family: 'Barlow Condensed', sans-serif;
  letter-spacing: 1.2px;
  font-size: 24px;
}}
.fc .fc-button {{
  background: #1e88e5;
  border-color: #1e88e5;
  text-transform: uppercase;
  font-family: 'Share Tech Mono', monospace;
  font-size: 10px;
  letter-spacing: 1px;
}}
.fc .fc-button:disabled {{ opacity: .55; }}
.fc .fc-daygrid-event {{
  border-radius: 999px;
  padding: 2px 8px;
  border: none !important;
}}
.fc .fc-daygrid-event-dot {{ display: none; }}
.fc-maint-pill {{
  display: inline-flex; align-items: center; gap: 6px;
  font-family: 'Share Tech Mono', monospace; font-size: 10px;
}}
.fc-projected {{ opacity: 0.38; cursor: default !important; }}
.fc-projected * {{ pointer-events: none; }}
.fc-maint-hover {{
  position: fixed; z-index: 9999; pointer-events: none;
  background: #0f1720; color: #e8edf2;
  border: 1px solid #263445; border-radius: 6px;
  padding: 8px 10px; min-width: 220px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.35);
}}
.fc-hover-title {{ font-family: 'Barlow Condensed', sans-serif; font-size: 14px; line-height: 1.2; }}
.fc-hover-sub {{ font-family: 'Share Tech Mono', monospace; font-size: 10px; color: #8fa2b8; margin-top: 2px; }}
.fc-hover-chart {{ margin-top: 8px; height: 8px; width: 100%; border-radius: 999px; overflow: hidden; background: #1e2a38; }}
.fc-hover-chart > span {{ display: block; height: 100%; }}
.fc-edit-note {{ margin-bottom: 8px; font-family: 'Share Tech Mono', monospace; font-size: 10px; color: #8fa2b8; }}
/* FullCalendar dark theme overrides */
.fc-theme-standard td, .fc-theme-standard th {{ border-color: #1e2530; }}
.fc-theme-standard .fc-scrollgrid {{ border-color: #1e2530; }}
.fc .fc-daygrid-day {{ background: transparent; }}
.fc .fc-daygrid-day:hover .fc-daygrid-day-frame {{ background: rgba(41,182,246,0.04); cursor: pointer; }}
.fc .fc-day-today {{ background: rgba(41,182,246,0.07) !important; }}
.fc .fc-day-today .fc-daygrid-day-number {{
  background: #29b6f6; color: #0a0c0f; border-radius: 50%;
  width: 22px; height: 22px; display: flex; align-items: center; justify-content: center;
  font-weight: 700; padding: 0;
}}
.fc .fc-col-header-cell {{ background: #0f1318; border-color: #1e2530; }}
.fc .fc-col-header-cell-cushion {{
  font-family: 'Barlow Condensed', sans-serif; font-size: 11px; letter-spacing: 2px;
  text-transform: uppercase; color: #4a5568; font-weight: 600; padding: 6px 8px; text-decoration: none;
}}
.fc .fc-daygrid-day-number {{
  font-family: 'Share Tech Mono', monospace; font-size: 11px;
  color: #637080; padding: 4px 6px; text-decoration: none;
}}
.fc .fc-daygrid-day-top {{ flex-direction: row; }}
.fc .fc-scrollgrid-section-header th {{ background: #0f1318; }}
.fc .fc-popover {{ background: #111418; border: 1px solid #1e2530; border-radius: 6px; box-shadow: 0 8px 24px rgba(0,0,0,0.5); }}
.fc .fc-popover-header {{
  background: #181c22; border-radius: 6px 6px 0 0; padding: 6px 10px;
  font-family: 'Barlow Condensed', sans-serif; font-size: 12px; color: #cdd6e0; border-bottom: 1px solid #1e2530;
}}
.fc .fc-popover-title {{ font-family: 'Barlow Condensed', sans-serif; letter-spacing: 1px; }}
.fc .fc-popover-close {{ color: #4a5568; opacity: 1; }}
.fc .fc-more-link {{
  font-family: 'Share Tech Mono', monospace; font-size: 9px;
  color: #29b6f6; letter-spacing: 0.5px; text-decoration: none; padding: 1px 4px;
}}
.fc .fc-more-link:hover {{ color: #81d4fa; background: rgba(41,182,246,0.1); border-radius: 2px; }}
.fc th {{ font-weight: normal; }}
.fc .fc-toolbar.fc-header-toolbar {{ margin-bottom: 14px; gap: 8px; flex-wrap: wrap; }}
.fc .fc-button {{ padding: 5px 14px; border-radius: 3px !important; font-size: 10px; }}
.fc .fc-button-group {{ gap: 2px; }}
.fc .fc-button-primary:not(:disabled).fc-button-active,
.fc .fc-button-primary:not(:disabled):active {{ background: #0d47a1; border-color: #0d47a1; }}
.fc .fc-button:focus, .fc .fc-button-primary:focus {{ box-shadow: 0 0 0 2px rgba(29,136,229,0.3) !important; }}
.fc .fc-daygrid-more-link {{ font-family: 'Share Tech Mono', monospace; font-size: 9px; }}
.fc .fc-daygrid-day-events {{ padding-bottom: 2px; }}
.fc .fc-scrollgrid-liquid {{ height: 100%; }}
#estimated-inspection-panel {{
  border: 1px solid var(--border); border-radius: 6px;
  background: var(--surface2); padding: 12px;
  max-height: 720px; overflow: auto;
}}
.cal-legend {{
  display: flex; gap: 14px; flex-wrap: wrap;
  margin-bottom: 12px; align-items: center;
  font-family: 'Share Tech Mono', monospace; font-size: 10px; color: #4a5568;
}}
.cal-leg-item {{ display: flex; align-items: center; gap: 6px; }}
.cal-leg-bar {{ width: 28px; height: 8px; border-radius: 2px; flex-shrink: 0; }}
.cal-date-group {{ border-top: 1px solid var(--border); padding: 10px 0; }}
.cal-date-group:first-child {{ border-top: none; padding-top: 0; }}
.cal-date-title {{ font-family: 'Barlow Condensed', sans-serif; font-size: 16px; color: #e8edf2; letter-spacing: .8px; }}
.cal-date-sub {{ font-family: 'Share Tech Mono', monospace; font-size: 10px; color: #4a5568; margin-bottom: 6px; }}
.cal-ev {{ border-left: 4px solid #4a5568; padding-left: 8px; margin-bottom: 7px; }}
.cal-ev-title {{ font-family: 'Barlow Condensed', sans-serif; color: #e8edf2; font-size: 14px; }}
.cal-ev-sub {{ font-family: 'Share Tech Mono', monospace; color: #4a5568; font-size: 10px; }}
/* ── Calendar modal ── */
.cal-modal-overlay{{position:fixed;inset:0;background:rgba(0,0,0,0.65);z-index:10000;display:none;}}
.cal-modal{{position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:10001;display:none;flex-direction:column;background:#0d1822;border:1px solid #263445;border-radius:8px;min-width:340px;max-width:480px;width:90%;box-shadow:0 16px 48px rgba(0,0,0,0.6);}}
.cal-modal-title{{padding:14px 18px 10px;font-family:'Barlow Condensed',sans-serif;font-size:18px;letter-spacing:1px;color:#e8edf2;border-bottom:1px solid #1e2a38;display:flex;align-items:center;gap:8px;}}
.cal-modal-body{{padding:14px 18px;color:#8fa2b8;font-family:'Share Tech Mono',monospace;font-size:12px;}}
.cal-modal-note-date{{font-size:10px;color:#4a5568;margin-bottom:8px;}}
.cal-modal-textarea{{width:100%;box-sizing:border-box;background:#0a1018;border:1px solid #263445;border-radius:4px;color:#e8edf2;font-family:'Share Tech Mono',monospace;font-size:12px;padding:8px 10px;resize:vertical;min-height:80px;outline:none;}}
.cal-modal-textarea:focus{{border-color:#1e88e5;}}
.cal-modal-desc{{margin:0 0 8px;color:#e8edf2;}}
.cal-modal-err{{margin:0;color:#ef5350;}}
.cal-modal-footer{{padding:10px 18px 14px;display:flex;gap:8px;justify-content:flex-end;border-top:1px solid #1e2a38;}}
.cal-modal-btn{{font-family:'Share Tech Mono',monospace;font-size:11px;letter-spacing:1px;text-transform:uppercase;padding:7px 16px;border-radius:4px;border:1px solid #263445;background:#1a2535;color:#8fa2b8;cursor:pointer;}}
.cal-modal-btn:hover{{background:#263445;color:#e8edf2;}}
.cal-modal-btn-primary{{background:#1565a8;border-color:#1e88e5;color:#e8edf2;}}
.cal-modal-btn-primary:hover{{background:#1e88e5;}}
.cal-modal-btn-danger{{background:#7b1a1a;border-color:#ef5350;color:#ef5350;}}
.cal-modal-btn-danger:hover{{background:#ef5350;color:#fff;}}
</style>

<div class="section-label">PROJECTED MAINTENANCE CALENDAR</div>
<div class="cal-legend">{legend_html}</div>

<div id="cal-shell">
  <div id="calendar-wrap">
    <div class="fc-edit-note">Faded pills are CSV projections (read-only). Click a date to schedule an inspection &mdash; saved inspections sync across all devices.
      <span id="cal-sync-status" style="margin-left:10px;font-size:10px;color:var(--muted);opacity:0;transition:opacity 0.4s;max-width:600px;display:inline-block;vertical-align:middle;word-break:break-all;"></span>
      <span onclick="document.getElementById('cal-debug-panel').style.display=document.getElementById('cal-debug-panel').style.display==='none'?'block':'none'" style="margin-left:10px;font-size:10px;color:#4a5568;cursor:pointer;text-decoration:underline;user-select:none;">debug</span>
    </div>
    <div id="cal-debug-panel" style="display:none;margin-top:6px;background:#060d14;border:1px solid #1e2a38;border-radius:4px;padding:8px 10px;">
      <pre id="cal-debug-log" style="margin:0;font-family:'Share Tech Mono',monospace;font-size:10px;color:#4a9eca;white-space:pre-wrap;max-height:150px;overflow-y:auto;">(no requests yet)</pre>
    </div>
    <div id="maint-calendar"></div>
  </div>
  <div id="estimated-inspection-panel">
    <div class="section-label" style="margin-top:0;">Estimated Inspection Dates</div>
    <div id="estimated-inspection-list"></div>
  </div>
</div>

<!-- Calendar modal -->
<div id="cal-modal-overlay" onclick="calModalClose()"></div>
<div id="cal-modal" class="cal-modal" role="dialog" aria-modal="true">
  <div class="cal-modal-title" id="cal-modal-title"></div>
  <div class="cal-modal-body" id="cal-modal-body"></div>
  <div class="cal-modal-footer" id="cal-modal-footer"></div>
</div>

<script>
(function () {{
  var MAINT = {events_json};
  var calEl = document.getElementById('maint-calendar');
  var listEl = document.getElementById('estimated-inspection-list');
  var hoverEl = null;

  function clamp(num, min, max) {{ return Math.max(min, Math.min(max, num)); }}

  function getChartPct(remLabel) {{
    var match = /(~?)(\d+(?:\.\d+)?)\s*days remaining/i.exec(remLabel || '');
    if (!match) return 100;
    var days = Number(match[2]);
    if (!isFinite(days)) return 100;
    return clamp((days / 30) * 100, 4, 100);
  }}

  function fmtDate(dateStr) {{
    var d = new Date(dateStr + 'T00:00:00');
    if (isNaN(d.getTime())) return dateStr;
    return d.toLocaleDateString('en-US', {{ weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' }});
  }}

  function renderInspectionList() {{
    if (!listEl) return;
    if (!Array.isArray(MAINT) || !MAINT.length) {{
      listEl.innerHTML = '<div class="cal-date-sub">No estimated inspection dates available.</div>';
      return;
    }}
    MAINT.sort(function(a,b) {{
      if (a.dueDate === b.dueDate) return String(a.tail).localeCompare(String(b.tail));
      return String(a.dueDate).localeCompare(String(b.dueDate));
    }});
    var byDate = MAINT.reduce(function(acc, ev) {{
      var key = ev.dueDate || 'Unknown';
      if (!acc[key]) acc[key] = [];
      acc[key].push(ev);
      return acc;
    }}, {{}});
    listEl.innerHTML = Object.keys(byDate).map(function(dateKey) {{
      var evs = byDate[dateKey];
      return '<div class="cal-date-group">' +
        '<div class="cal-date-title">' + fmtDate(dateKey) + '</div>' +
        '<div class="cal-date-sub">' + evs.length + ' projected event' + (evs.length === 1 ? '' : 's') + '</div>' +
        evs.map(function(ev) {{
          return '<div class="cal-ev" style="border-left-color:' + (ev.color || '#4a5568') + '">' +
            '<div class="cal-ev-title">' + ev.tail + ' · ' + ev.intervalLabel + '</div>' +
            '<div class="cal-ev-sub">' + (ev.remLabel || '') + '</div>' +
          '</div>';
        }}).join('') +
      '</div>';
    }}).join('');
  }}

  function removeHover() {{
    if (hoverEl && hoverEl.parentNode) hoverEl.parentNode.removeChild(hoverEl);
    hoverEl = null;
  }}

  function showHover(ev, e) {{
    removeHover();
    var pct = getChartPct(ev.remLabel);
    hoverEl = document.createElement('div');
    hoverEl.className = 'fc-maint-hover';
    hoverEl.innerHTML =
      '<div class="fc-hover-title">' + ev.tail + ' · ' + ev.intervalLabel + '</div>' +
      '<div class="fc-hover-sub">' + (ev.remLabel || 'Projected maintenance event') + '</div>' +
      '<div class="fc-hover-chart"><span style="width:' + pct + '%;background:' + (ev.color || '#4a5568') + ';"></span></div>';
    document.body.appendChild(hoverEl);
    moveHover(e);
  }}

  function showNoteHover(ev, e) {{
    removeHover();
    var rangeText = ev._rangeText ? ('<div class="fc-hover-sub" style="margin-top:2px;">' + escHtml(ev._rangeText) + '</div>') : '';
    hoverEl = document.createElement('div');
    hoverEl.className = 'fc-maint-hover';
    hoverEl.innerHTML =
      '<div class="fc-hover-title" style="color:#f59e0b;">&#128196; Note</div>' +
      rangeText +
      '<div class="fc-hover-sub" style="color:#e8edf2;margin-top:6px;white-space:pre-wrap;max-width:220px;line-height:1.4;">'
        + (ev.note || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') + '</div>';
    document.body.appendChild(hoverEl);
    moveHover(e);
  }}

  function moveHover(e) {{
    if (!hoverEl || !e) return;
    hoverEl.style.left = (e.clientX + 14) + 'px';
    hoverEl.style.top  = (e.clientY + 14) + 'px';
  }}

  function addDaysYmd(ymd, deltaDays) {{
    if (!ymd) return '';
    var d = new Date(ymd + 'T00:00:00Z');
    if (isNaN(d.getTime())) return '';
    d.setUTCDate(d.getUTCDate() + deltaDays);
    return d.toISOString().slice(0, 10);
  }}
  function toExclusiveEndDate(inclusiveEndYmd) {{ return inclusiveEndYmd ? addDaysYmd(inclusiveEndYmd, 1) : null; }}

  function escHtml(t) {{ return String(t || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }}
  var _calOverlay = document.getElementById('cal-modal-overlay');
  var _calModal   = document.getElementById('cal-modal');
  var _calMTitle  = document.getElementById('cal-modal-title');
  var _calMBody   = document.getElementById('cal-modal-body');
  var _calMFooter = document.getElementById('cal-modal-footer');

  function calModalClose() {{
    _calOverlay.style.display = 'none';
    _calModal.style.display   = 'none';
  }}
  window.calModalClose = calModalClose;

  function calModalOpen(title, bodyHtml, buttons) {{
    _calMTitle.innerHTML  = title;
    _calMBody.innerHTML   = bodyHtml;
    _calMFooter.innerHTML = '';
    buttons.forEach(function(btn) {{
      var b = document.createElement('button');
      b.className = 'cal-modal-btn' + (btn.cls ? ' ' + btn.cls : '');
      b.innerHTML = btn.label;
      b.onclick   = btn.action;
      _calMFooter.appendChild(b);
    }});
    _calOverlay.style.display = 'block';
    _calModal.style.display   = 'flex';
    var inp = document.getElementById('cal-modal-input');
    if (inp) {{ inp.focus(); inp.setSelectionRange(inp.value.length, inp.value.length); }}
  }}

  document.addEventListener('keydown', function(e) {{
    if (e.key === 'Escape' && _calModal && _calModal.style.display === 'flex') calModalClose();
  }});

  // ── Debug logger ──────────────────────────────────────────────────────────
  var _calDebugLog = [];
  function calDebugLog(method, url, status, body) {{
    var ts = new Date().toLocaleTimeString();
    _calDebugLog.unshift('[' + ts + '] ' + method + ' ' + url + ' → ' + status + (body ? ': ' + body : ''));
    if (_calDebugLog.length > 20) _calDebugLog.pop();
    var el = document.getElementById('cal-debug-log');
    if (el) el.textContent = _calDebugLog.join('\\n');
  }}

  // ── Supabase config (injected by Python) ─────────────────────────────────
  var SUPA_URL = '{supabase_url}';
  var SUPA_KEY = '{supabase_anon_key}';

  var INSPECTION_TYPES = {json.dumps([
        {'label': INTERVAL_LABEL.get(k, str(k)),
         'color': INTERVAL_COLOR.get(k, '#29b6f6'),
         'defaultDays': INTERVAL_DURATION_DAYS.get(k, 1)}
        for k in sorted(INTERVAL_COLOR.keys(), key=lambda x: (isinstance(x, str), x))
   ])};

  var AIRCRAFT_TAILS = {tails_js};

  function supaFetch(path, method, body, extraHdrs) {{
    var url = SUPA_URL + '/rest/v1/' + path;
    var opts = {{
      method: method || 'GET',
      headers: Object.assign({{
        'apikey': SUPA_KEY,
        'Authorization': 'Bearer ' + SUPA_KEY,
        'Content-Type': 'application/json'
      }}, extraHdrs || {{}})
    }};
    if (body !== undefined) opts.body = JSON.stringify(body);
    return fetch(url, opts).then(function(r) {{
      return r.text().then(function(txt) {{
        calDebugLog(method || 'GET', url, r.status, txt.slice(0, 200));
        if (!r.ok) throw new Error('HTTP ' + r.status + ': ' + txt.slice(0, 300));
        return txt ? JSON.parse(txt) : null;
      }});
    }});
  }}

  function supaUpsertInspection(rec) {{
    return supaFetch('scheduled_inspections', 'POST', rec,
      {{ 'Prefer': 'resolution=merge-duplicates,return=minimal' }});
  }}
  function supaDeleteInspection(id) {{
    return supaFetch('scheduled_inspections?id=eq.' + encodeURIComponent(id), 'DELETE',
      undefined, {{ 'Prefer': 'return=minimal' }});
  }}

  function calOpenAddInspectionModal(dateStr) {{
    var tailOpts = AIRCRAFT_TAILS.map(function(t) {{
      return '<option value="' + t + '">' + t + '</option>';
    }}).join('');
    var typeOpts = INSPECTION_TYPES.map(function(iv) {{
      return '<option value="' + iv.label + '" data-color="' + iv.color
        + '" data-days="' + iv.defaultDays + '">' + iv.label + '</option>';
    }}).join('');
    var inputHtml =
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px;">'
      + '<label style="font-size:12px;color:var(--muted);">Aircraft<br>'
      + '<select id="insp-tail" style="width:100%;padding:5px 8px;background:var(--surface2);'
      + 'border:1px solid var(--border);border-radius:4px;color:var(--text);font-size:13px;margin-top:2px;">'
      + tailOpts + '</select></label>'
      + '<label style="font-size:12px;color:var(--muted);">Inspection Type<br>'
      + '<select id="insp-type" style="width:100%;padding:5px 8px;background:var(--surface2);'
      + 'border:1px solid var(--border);border-radius:4px;color:var(--text);font-size:13px;margin-top:2px;">'
      + typeOpts + '</select></label>'
      + '<label style="font-size:12px;color:var(--muted);">Start Date<br>'
      + '<input type="date" id="insp-start" value="' + dateStr + '" '
      + 'style="width:100%;padding:5px 8px;background:var(--surface2);border:1px solid var(--border);'
      + 'border-radius:4px;color:var(--text);font-size:13px;margin-top:2px;"></label>'
      + '<label style="font-size:12px;color:var(--muted);">End Date<br>'
      + '<input type="date" id="insp-end" '
      + 'style="width:100%;padding:5px 8px;background:var(--surface2);border:1px solid var(--border);'
      + 'border-radius:4px;color:var(--text);font-size:13px;margin-top:2px;"></label>'
      + '</div>'
      + '<label style="font-size:12px;color:var(--muted);">Notes<br>'
      + '<textarea id="insp-note" class="cal-modal-textarea" rows="3" '
      + 'placeholder="Optional notes…" style="margin-top:4px;"></textarea></label>';
    setTimeout(function() {{
      var sel = document.getElementById('insp-type');
      var startEl = document.getElementById('insp-start');
      var endEl   = document.getElementById('insp-end');
      function updateEnd() {{
        var opt = sel ? sel.options[sel.selectedIndex] : null;
        var days = opt ? parseInt(opt.dataset.days || '1', 10) : 1;
        var startVal = startEl ? startEl.value : dateStr;
        if (!startVal) return;
        var d = new Date(startVal + 'T00:00:00');
        d.setDate(d.getDate() + days - 1);
        if (endEl) endEl.value = d.toISOString().slice(0, 10);
      }}
      if (sel) sel.addEventListener('change', updateEnd);
      if (startEl) startEl.addEventListener('change', updateEnd);
      updateEnd();
    }}, 0);
    calModalOpen(
      'Schedule Inspection',
      inputHtml,
      [
        {{ label: 'Cancel', cls: '', action: calModalClose }},
        {{ label: 'Save', cls: 'cal-modal-btn-primary', action: function() {{
            var tail  = (document.getElementById('insp-tail') || {{}}).value || '';
            var sel   = document.getElementById('insp-type');
            var iType = sel ? sel.value : '';
            var opt   = sel ? sel.options[sel.selectedIndex] : null;
            var color = opt ? (opt.dataset.color || '#29b6f6') : '#29b6f6';
            var start = (document.getElementById('insp-start') || {{}}).value || dateStr;
            var end   = (document.getElementById('insp-end')   || {{}}).value || '';
            var note  = (document.getElementById('insp-note')  || {{}}).value || '';
            if (!tail || !iType || !start) return;
            calModalClose();
            calShowStatus('Saving…');
            var id = 'insp-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6);
            supaUpsertInspection({{ id: id, tail: tail, inspection_type: iType, color: color,
                                    start_date: start, end_date: end || null, note: note }})
              .then(function() {{
                calShowStatus('Saved');
                calendar.addEvent({{
                  id: id,
                  title: tail + ' — ' + iType,
                  start: start,
                  end: toExclusiveEndDate(end),
                  allDay: true,
                  editable: false,
                  backgroundColor: color,
                  borderColor: color,
                  extendedProps: {{ _scheduled: true, tail: tail, inspType: iType,
                                   color: color, startDate: start, endDate: end || null, note: note }}
                }});
              }})
              .catch(function(err) {{ calShowStatus('Save failed: ' + (err.message || err), true); }});
        }} }}
      ]
    );
  }}

  function calShowStatus(msg, isErr) {{
    var el = document.getElementById('cal-sync-status');
    if (!el) return;
    el.textContent = msg;
    el.style.color = isErr ? 'var(--red)' : 'var(--muted)';
    el.style.opacity = '1';
    clearTimeout(el._t);
    el._t = setTimeout(function() {{ el.style.opacity = '0'; }}, isErr ? 15000 : 3000);
  }}

  var calendar;

  function renderCalendar() {{
    if (!calEl || !window.FullCalendar) return;

    var maintEventMap = {{}};
    var maintEvents = MAINT.map(function(ev, idx) {{
      var durationDays = Math.max(1, Number(ev.durationDays) || 1);
      var endDate = null;
      if (durationDays > 1) {{
        var d = new Date(ev.dueDate + 'T00:00:00');
        if (!isNaN(d.getTime())) {{
          d.setDate(d.getDate() + durationDays);
          endDate = d.toISOString().slice(0, 10);
        }}
      }}
      var azId = 'maint-' + (ev.tail || '').replace(/\s+/g,'') + '-' + (ev.intervalLabel || '').replace(/\s+/g,'');
      maintEventMap[azId] = idx;
      return {{
        id: azId,
        title: 'Projected — ' + ev.tail + ' ' + ev.intervalLabel,
        start: ev.dueDate,
        end: endDate,
        allDay: true,
        editable: false,
        classNames: ['fc-projected'],
        backgroundColor: ev.color,
        borderColor: ev.color,
        extendedProps: Object.assign({{}}, ev, {{ _azId: azId, _projected: true }})
      }};
    }});

    calendar = new FullCalendar.Calendar(calEl, {{
      initialView: 'dayGridMonth',
      height: 'auto',
      editable: false,
      navLinks: true,
      dayMaxEvents: 3,
      headerToolbar: {{ left: 'prev,next today', center: 'title', right: 'dayGridMonth,listMonth' }},
      eventSources: [
        {{ events: maintEvents, id: 'maintenance' }},
        {{
          id: 'scheduled',
          events: function(fetchInfo, successCb, failureCb) {{
            if (!SUPA_URL) {{ successCb([]); return; }}
            supaFetch('scheduled_inspections?select=*&order=start_date.asc')
              .then(function(rows) {{
                if (!Array.isArray(rows)) {{ successCb([]); return; }}
                var evs = rows.map(function(r) {{
                  return {{
                    id: r.id,
                    title: r.tail + ' — ' + r.inspection_type,
                    start: r.start_date,
                    end: toExclusiveEndDate(r.end_date),
                    allDay: true,
                    editable: false,
                    backgroundColor: r.color,
                    borderColor: r.color,
                    extendedProps: {{ _scheduled: true, tail: r.tail, inspType: r.inspection_type,
                                     color: r.color, startDate: r.start_date,
                                     endDate: r.end_date, note: r.note }}
                  }};
                }});
                successCb(evs);
              }})
              .catch(function(err) {{ console.warn('Supabase load:', err); successCb([]); }});
          }}
        }}
      ],
      eventContent: function(arg) {{
        var ev = arg.event.extendedProps || {{}};
        var hasNote = ev.note && ev.note.trim();
        var node = document.createElement('div');
        node.className = 'fc-maint-pill';
        if (ev._projected) {{
          node.innerHTML = '<span style="opacity:0.6;font-style:italic;font-size:10px;">Projected</span>'
            + ' <strong>' + (ev.tail || '') + '</strong>'
            + '<span>' + (ev.intervalLabel || '') + '</span>';
        }} else {{
          node.innerHTML = '<strong>' + (ev.tail || '') + '</strong>'
            + '<span>' + (ev.inspType || ev.intervalLabel || '') + '</span>'
            + (hasNote ? '<span style="opacity:0.7;font-size:9px;margin-left:4px;">&#128196;</span>' : '');
        }}
        return {{ domNodes: [node] }};
      }},
      eventMouseEnter: function(info) {{
        var props = info.event.extendedProps || {{}};
        if (props._projected) {{ showHover(props, info.jsEvent); return; }}
        if (props._scheduled) {{
          var rangeText = props.endDate ? (props.startDate + ' → ' + props.endDate) : props.startDate;
          showNoteHover(Object.assign({{}}, props, {{ _rangeText: rangeText }}), info.jsEvent);
          return;
        }}
        showHover(props, info.jsEvent);
      }},
      eventMouseLeave: function() {{ removeHover(); }},
      eventClick: function(info) {{
        var props = info.event.extendedProps || {{}};
        if (props._projected) return;
        if (!props._scheduled) return;
        var id = info.event.id;
        var currentNote = props.note || '';
        calModalOpen(
          props.tail + ' — ' + props.inspType,
          '<p class="cal-modal-desc">' + props.startDate
            + (props.endDate ? ' → ' + props.endDate : '') + '</p>'
            + '<p class="cal-modal-note-date">Notes:</p>'
            + '<textarea id="cal-modal-input" class="cal-modal-textarea" rows="4">'
            + currentNote.replace(/</g,'&lt;') + '</textarea>',
          [
            {{ label: 'Cancel', cls: '', action: calModalClose }},
            {{ label: 'Delete', cls: 'cal-modal-btn-danger', action: function() {{
                calModalClose();
                calShowStatus('Deleting…');
                supaDeleteInspection(id)
                  .then(function() {{
                    calShowStatus('Deleted');
                    var ev = calendar.getEventById(id);
                    if (ev) ev.remove();
                  }})
                  .catch(function(err) {{ calShowStatus('Delete failed: ' + (err.message || err), true); }});
            }} }},
            {{ label: 'Save Note', cls: 'cal-modal-btn-primary', action: function() {{
                var txt = (document.getElementById('cal-modal-input') || {{}}).value || '';
                calModalClose();
                calShowStatus('Saving…');
                supaUpsertInspection({{ id: id, tail: props.tail, inspection_type: props.inspType,
                                        color: props.color, start_date: props.startDate,
                                        end_date: props.endDate || null, note: txt }})
                  .then(function() {{
                    calShowStatus('Saved');
                    var ev = calendar.getEventById(id);
                    if (ev) ev.setExtendedProp('note', txt);
                  }})
                  .catch(function(err) {{ calShowStatus('Save failed: ' + (err.message || err), true); }});
            }} }}
          ]
        );
      }},
      dateClick: function(info) {{ calOpenAddInspectionModal(info.dateStr); }},
      navLinkDayClick: function(date, jsEvent) {{
        jsEvent.preventDefault();
        var y = date.getFullYear();
        var m = String(date.getMonth() + 1).padStart(2, '0');
        var d = String(date.getDate()).padStart(2, '0');
        calOpenAddInspectionModal(y + '-' + m + '-' + d);
      }}
    }});

    calendar.render();
    window.addEventListener('fleet:calendar:shown', function() {{ calendar.updateSize(); }});
    document.addEventListener('mousemove', moveHover);
  }}

  renderInspectionList();
  renderCalendar();
}})();
</script>
"""
