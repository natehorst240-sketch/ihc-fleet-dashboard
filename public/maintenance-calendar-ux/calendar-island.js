(function () {
  var STORAGE_KEY = 'maintenance-calendar-user-overrides-v1';

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function ensureStyles(theme) {
    if (document.getElementById('mcx-styles')) return;
    var style = document.createElement('style');
    style.id = 'mcx-styles';
    style.textContent = [
      '.mcx{font-family:' + theme.fontBody + ';color:' + theme.text + ';}',
      '.mcx-toolbar{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:12px;}',
      '.mcx-title{font-family:' + theme.fontSans + ';letter-spacing:2px;text-transform:uppercase;font-weight:700;font-size:14px;color:' + theme.heading + ';}',
      '.mcx-btns{display:flex;gap:8px;}',
      '.mcx-btn{background:transparent;border:1px solid ' + theme.border + ';color:' + theme.muted + ';padding:6px 10px;border-radius:3px;cursor:pointer;font-family:' + theme.fontMono + ';font-size:11px;}',
      '.mcx-btn:hover{border-color:' + theme.blue + ';color:' + theme.blue + ';}',
      '.mcx-filters{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:10px;}',
      '.mcx-filter-label{font-family:' + theme.fontMono + ';font-size:10px;color:' + theme.muted + ';letter-spacing:1px;}',
      '.mcx-select{background:#0d1117;border:1px solid ' + theme.border + ';color:' + theme.text + ';padding:6px 8px;border-radius:3px;font-family:' + theme.fontMono + ';font-size:11px;min-width:155px;}',
      '.mcx-select:focus{outline:none;border-color:' + theme.blue + ';}',
      '.mcx-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:0;}',
      '.mcx-dow{font-family:' + theme.fontMono + ';font-size:9px;text-align:center;letter-spacing:1px;color:' + theme.muted + ';padding:4px 0;}',
      '.mcx-empty{min-height:84px;}',
      '.mcx-day{min-height:84px;padding:6px;border:1px solid ' + theme.border + ';border-radius:3px;background:#0d1117;overflow:visible;}',
      '.mcx-day.is-today{border-color:' + theme.blue + ';}',
      '.mcx-num{font-family:' + theme.fontMono + ';font-size:10px;color:' + theme.muted + ';margin-bottom:4px;}',
      '.mcx-pill{font-family:' + theme.fontMono + ';font-size:9px;border-radius:2px;padding:1px 4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:1px;cursor:pointer;border:none;text-align:left;width:100%;}',
      '.mcx-pill.segment{position:relative;z-index:2;width:calc(100% + 14px);margin-left:-7px;margin-right:-7px;border-radius:0;}',
      '.mcx-pill.seg-start{border-top-left-radius:2px;border-bottom-left-radius:2px;}',
      '.mcx-pill.seg-end{border-top-right-radius:2px;border-bottom-right-radius:2px;}',
      '.mcx-pill.seg-single{border-radius:2px;}',
      '.mcx-pill.red{background:#c0392b;color:#fff;}',
      '.mcx-pill.green{background:#27ae60;color:#fff;}',
      '.mcx-pill.amber{background:#e67e22;color:#000;}',
      '.mcx-pill.blue{background:#2980b9;color:#fff;}',
      '.mcx-pill.purple{background:#8e44ad;color:#fff;}',
      '.mcx-pill.user-edited{box-shadow:inset 2px 0 0 #f6ad55;}',
      '.mcx-pill:hover{opacity:0.92;}',
      '.mcx-hovercard{position:fixed;z-index:9999;min-width:220px;max-width:300px;background:#111826;border:1px solid ' + theme.border + ';border-radius:4px;padding:8px;box-shadow:0 10px 30px rgba(0,0,0,0.45);pointer-events:none;opacity:0;transform:translateY(4px);transition:opacity .12s ease,transform .12s ease;}',
      '.mcx-hovercard.is-visible{opacity:1;transform:translateY(0);}',
      '.mcx-hovercard-title{font-family:' + theme.fontSans + ';font-size:11px;font-weight:700;color:' + theme.heading + ';margin-bottom:6px;}',
      '.mcx-hovercard-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:4px;}',
      '.mcx-hovercard-list li{font-family:' + theme.fontMono + ';font-size:10px;color:' + theme.text + ';line-height:1.35;}',
      '.mcx-hovercard-list li.muted{color:' + theme.muted + ';}',
      '.mcx-meta{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;font-family:' + theme.fontMono + ';font-size:10px;color:' + theme.muted + ';margin-bottom:10px;}',
      '.mcx-legend{display:flex;gap:14px;flex-wrap:wrap;font-family:' + theme.fontMono + ';font-size:10px;color:' + theme.muted + ';margin-bottom:10px;}',
      '.mcx-leg-dot{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:4px;vertical-align:middle;}',
      '.mcx-empty-state{font-family:' + theme.fontMono + ';font-size:11px;color:' + theme.muted + ';padding:10px 0;}',
      '.mcx-editor{margin-top:12px;border:1px solid ' + theme.border + ';border-radius:4px;padding:10px;background:#0d1117;}',
      '.mcx-editor-head{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px;}',
      '.mcx-editor-title{font-family:' + theme.fontSans + ';font-size:12px;font-weight:700;letter-spacing:1px;color:' + theme.heading + ';}',
      '.mcx-editor-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px;}',
      '.mcx-field{display:flex;flex-direction:column;gap:4px;}',
      '.mcx-field label{font-family:' + theme.fontMono + ';font-size:10px;color:' + theme.muted + ';}',
      '.mcx-input,.mcx-textarea{background:#111826;border:1px solid ' + theme.border + ';color:' + theme.text + ';border-radius:3px;padding:6px 8px;font-family:' + theme.fontMono + ';font-size:11px;}',
      '.mcx-textarea{min-height:64px;resize:vertical;}',
      '.mcx-footnote{font-family:' + theme.fontMono + ';font-size:10px;color:' + theme.muted + ';margin-top:6px;}'
    ].join('');
    document.head.appendChild(style);
  }

  function iso(d) {
    var m = String(d.getMonth() + 1).padStart(2, '0');
    var day = String(d.getDate()).padStart(2, '0');
    return d.getFullYear() + '-' + m + '-' + day;
  }

  function monthLabel(d) {
    return d.toLocaleString('en-US', { month: 'long', year: 'numeric' }).toUpperCase();
  }

  function buildMap(events) {
    var map = {};
    events.forEach(function (ev) {
      if (!ev || !ev.dueDate) return;
      var spanDays = Math.max(1, Math.ceil(Number(ev.durationDays) || 1));
      var start = new Date(ev.dueDate + 'T00:00:00');
      if (!isFinite(start.getTime())) return;
      for (var i = 0; i < spanDays; i++) {
        var day = new Date(start);
        day.setDate(start.getDate() + i);
        var key = iso(day);
        if (!map[key]) map[key] = [];
        map[key].push(ev);
      }
    });
    return map;
  }

  function inspectionHours(ev) {
    var label = String((ev && ev.inspectionType) || '');
    var match = label.match(/(\d+)/);
    return match ? Number(match[1]) : NaN;
  }

  function getInspectionDurationDays(ev) {
    var interval = inspectionHours(ev);
    if (interval === 50 || interval === 100) return 1;
    if (interval === 200) return 3.5;
    if (interval === 400 || interval === 800) return 5;
    if (interval === 3200) return 21;
    return 1;
  }

  function colorClass(ev) {
    var interval = inspectionHours(ev);
    if (interval === 50 || interval === 100) return 'green';
    if (interval === 200) return 'amber';
    if (interval === 400 || interval === 800) return 'blue';
    if (interval === 3200) return 'purple';
    return 'red';
  }

  function segmentClass(ev, dayKey) {
    var spanDays = Math.max(1, Math.ceil(Number(ev.durationDays) || 1));
    if (!ev || !ev.dueDate || spanDays <= 1) return 'seg-single';

    var start = new Date(ev.dueDate + 'T00:00:00');
    var current = new Date(dayKey + 'T00:00:00');
    if (!isFinite(start.getTime()) || !isFinite(current.getTime())) return 'seg-single';

    var end = new Date(start);
    end.setDate(start.getDate() + spanDays - 1);

    var isStart = iso(current) === iso(start);
    var isEnd = iso(current) === iso(end);

    if (isStart && isEnd) return 'seg-single';
    if (isStart) return 'seg-start';
    if (isEnd) return 'seg-end';
    return 'seg-mid';
  }

  function parseSafe(str, fallback) {
    try {
      return JSON.parse(str);
    } catch (_err) {
      return fallback;
    }
  }

  function loadOverrides() {
    if (!window.localStorage) return {};
    return parseSafe(window.localStorage.getItem(STORAGE_KEY) || '{}', {});
  }

  function saveOverrides(overrides) {
    if (!window.localStorage) return;
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(overrides || {}));
  }

  function formatDuration(days) {
    var n = Number(days);
    if (!isFinite(n) || n <= 0) return '1';
    return Number.isInteger(n) ? String(n) : String(n);
  }

  function detailTitle(ev) {
    var lines = [];
    lines.push((ev.registration || ev.aircraftId || 'Aircraft') + ' — ' + (ev.inspectionType || 'Inspection'));
    lines.push('Due: ' + (ev.dueDate || '—'));
    lines.push('Projected next due: ' + (ev.projectedDueDate || ev.dueDate || '—'));
    lines.push('Estimated downtime: ' + (ev.durationDays || getInspectionDurationDays(ev)) + ' day(s)');
    lines.push('Hours remaining: ' + (ev.hoursRemaining != null ? ev.hoursRemaining : '—'));
    if (ev.notes) lines.push('Notes: ' + ev.notes);
    if (ev.userEdited) lines.push('User-edited from calendar tab');
    return lines.join('\n');
  }

  function hoverCardContent(ev) {
    return [
      '<div class="mcx-hovercard-title">' + esc((ev.registration || ev.aircraftId || 'Aircraft') + ' — ' + (ev.inspectionType || 'Inspection')) + '</div>',
      '<ul class="mcx-hovercard-list">',
      '<li><strong>Due:</strong> ' + esc(ev.dueDate || '—') + '</li>',
      '<li><strong>Projected:</strong> ' + esc(ev.projectedDueDate || ev.dueDate || '—') + '</li>',
      '<li><strong>Hours Remaining:</strong> ' + esc(ev.hoursRemaining == null ? '—' : ev.hoursRemaining) + '</li>',
      '<li class="muted">' + esc(ev.notes || 'No notes added') + '</li>',
      '</ul>'
    ].join('');
  }

  window.renderMaintenanceCalendar = function (root, payload) {
    if (!root) return;
    payload = payload || {};
    var theme = payload.themeResolved || {
      text: '#cdd6e0', muted: '#fff', heading: '#e8edf2', border: '#1e2530', blue: '#29b6f6',
      fontBody: 'Barlow, sans-serif', fontMono: 'Share Tech Mono, monospace', fontSans: 'Barlow Condensed, sans-serif'
    };
    ensureStyles(theme);

    var sourceEvents = Array.isArray(payload.initialEvents) ? payload.initialEvents.slice() : [];
    var date = payload.initialDate ? new Date(payload.initialDate + 'T00:00:00') : new Date();
    if (isNaN(date.getTime())) date = new Date();
    date.setDate(1);

    var filters = { aircraft: 'all', inspection: 'all' };
    var editor = { selectedId: null };

    var allAircraft = Array.from(new Set(sourceEvents.map(function (ev) { return ev.aircraftId || ev.registration || ''; }).filter(Boolean))).sort();
    var allInspections = Array.from(new Set(sourceEvents.map(function (ev) { return ev.inspectionType || ''; }).filter(Boolean))).sort();

    var overrides = loadOverrides();

    function mergedEvents() {
      return sourceEvents.map(function (ev) {
        var merged = Object.assign({}, ev);
        merged.projectedDueDate = ev.projectedDueDate || ev.dueDate;
        merged.durationDays = Number(ev.durationDays) || getInspectionDurationDays(ev);
        if (overrides[ev.id]) {
          merged = Object.assign(merged, overrides[ev.id], { userEdited: true });
          if (!merged.projectedDueDate) merged.projectedDueDate = ev.dueDate;
          merged.durationDays = Number(merged.durationDays) || getInspectionDurationDays(merged);
        }
        return merged;
      });
    }

    function selectedEvent(events) {
      if (!editor.selectedId) return null;
      for (var i = 0; i < events.length; i++) {
        if (events[i].id === editor.selectedId) return events[i];
      }
      return null;
    }

    function filteredEvents(events) {
      return events.filter(function (ev) {
        var aircraftId = ev.aircraftId || ev.registration || '';
        var inspection = ev.inspectionType || '';
        var aircraftMatch = filters.aircraft === 'all' || aircraftId === filters.aircraft;
        var inspectionMatch = filters.inspection === 'all' || inspection === filters.inspection;
        return aircraftMatch && inspectionMatch;
      });
    }

    function onSaveEdit() {
      var id = editor.selectedId;
      if (!id) return;
      var dueInput = root.querySelector('[data-editor="dueDate"]');
      var hoursInput = root.querySelector('[data-editor="hoursRemaining"]');
      var notesInput = root.querySelector('[data-editor="notes"]');
      var durationInput = root.querySelector('[data-editor="durationDays"]');
      if (!dueInput || !hoursInput || !notesInput || !durationInput) return;
      var hoursValue = Number(hoursInput.value);
      var durationValue = Number(durationInput.value);
      var fallbackDuration = 1;
      for (var i = 0; i < sourceEvents.length; i++) {
        if (sourceEvents[i] && sourceEvents[i].id === id) {
          fallbackDuration = getInspectionDurationDays(sourceEvents[i]);
          break;
        }
      }
      overrides[id] = {
        dueDate: dueInput.value,
        hoursRemaining: isFinite(hoursValue) ? hoursValue : hoursInput.value,
        durationDays: isFinite(durationValue) && durationValue > 0 ? durationValue : fallbackDuration,
        notes: notesInput.value
      };
      saveOverrides(overrides);
      render();
    }

    function onResetEdit() {
      var id = editor.selectedId;
      if (!id) return;
      delete overrides[id];
      saveOverrides(overrides);
      render();
    }

    function render() {
      var events = mergedEvents();
      var filtered = filteredEvents(events);
      var eventsById = {};
      filtered.forEach(function (ev) {
        eventsById[ev.id] = ev;
      });
      var byDay = buildMap(filtered);
      var year = date.getFullYear();
      var month = date.getMonth();
      var first = new Date(year, month, 1);
      var firstDowMon = (first.getDay() + 6) % 7;
      var lastDay = new Date(year, month + 1, 0).getDate();
      var selected = selectedEvent(events);

      var html = '';
      html += '<div class="mcx">';
      html += '<div class="mcx-toolbar">';
      html += '<div class="mcx-title">' + esc(monthLabel(date)) + '</div>';
      html += '<div class="mcx-btns">';
      html += '<button class="mcx-btn" data-act="today">TODAY</button>';
      html += '<button class="mcx-btn" data-act="prev">◀</button>';
      html += '<button class="mcx-btn" data-act="next">▶</button>';
      html += '</div></div>';

      html += '<div class="mcx-filters">';
      html += '<span class="mcx-filter-label">FILTER:</span>';
      html += '<select class="mcx-select" data-filter="aircraft"><option value="all">All Aircraft</option>';
      allAircraft.forEach(function (ac) {
        html += '<option value="' + esc(ac) + '"' + (filters.aircraft === ac ? ' selected' : '') + '>' + esc(ac) + '</option>';
      });
      html += '</select>';
      html += '<select class="mcx-select" data-filter="inspection"><option value="all">All Inspections</option>';
      allInspections.forEach(function (insp) {
        html += '<option value="' + esc(insp) + '"' + (filters.inspection === insp ? ' selected' : '') + '>' + esc(insp) + '</option>';
      });
      html += '</select>';
      if (filters.aircraft !== 'all' || filters.inspection !== 'all') {
        html += '<button class="mcx-btn" data-act="clear-filters">CLEAR</button>';
      }
      html += '</div>';

      html += '<div class="mcx-meta">';
      html += '<span>Showing ' + filtered.length + ' of ' + events.length + ' projected events</span>';
      html += '<span>Hover an item for due-date details. Click an item to edit.</span>';
      html += '</div>';

      html += '<div class="mcx-legend">'
        + '<span><span class="mcx-leg-dot" style="background:#27ae60"></span>50/100 HR · 1 day</span>'
        + '<span><span class="mcx-leg-dot" style="background:#e67e22"></span>200 HR · 3.5 days</span>'
        + '<span><span class="mcx-leg-dot" style="background:#2980b9"></span>400/800 HR · 5 days</span>'
        + '<span><span class="mcx-leg-dot" style="background:#8e44ad"></span>3200 HR · 3 weeks</span>'
        + '<span><span class="mcx-leg-dot" style="background:#f6ad55"></span>User-edited</span>'
        + '</div>';

      html += '<div class="mcx-grid">';
      ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'].forEach(function (d) { html += '<div class="mcx-dow">' + d + '</div>'; });
      for (var i = 0; i < firstDowMon; i++) html += '<div class="mcx-empty"></div>';

      for (var day = 1; day <= lastDay; day++) {
        var key = year + '-' + String(month + 1).padStart(2, '0') + '-' + String(day).padStart(2, '0');
        var list = byDay[key] || [];
        html += '<div class="mcx-day' + (key === iso(new Date()) ? ' is-today' : '') + '">';
        html += '<div class="mcx-num">' + day + '</div>';
        list.slice(0, 4).forEach(function (ev) {
          var segClass = segmentClass(ev, key);
          var isSegment = segClass !== 'seg-single';
          html += '<button class="mcx-pill ' + colorClass(ev) + (isSegment ? ' segment ' + segClass : ' seg-single') + (ev.userEdited ? ' user-edited' : '') + '" data-event-id="' + esc(ev.id) + '" title="' + esc(detailTitle(ev)) + '">' + esc((ev.registration || '') + ' ' + (ev.inspectionType || '') + ' · ' + (ev.durationDays || 1) + 'd') + '</button>';
        });
        if (list.length > 4) html += '<div class="mcx-pill blue seg-single">+' + (list.length - 4) + ' more</div>';
        html += '</div>';
      }
      html += '</div>';

      if (!filtered.length) {
        html += '<div class="mcx-empty-state">No projected events available for the active filters.</div>';
      }

      if (selected) {
        html += '<div class="mcx-editor">';
        html += '<div class="mcx-editor-head">';
        html += '<div class="mcx-editor-title">Edit Calendar Event</div>';
        html += '<div class="mcx-footnote">Projected next due: ' + esc(selected.projectedDueDate || selected.dueDate || '—') + '</div>';
        html += '</div>';
        html += '<div class="mcx-editor-grid">';
        html += '<div class="mcx-field"><label>Aircraft</label><input class="mcx-input" type="text" disabled value="' + esc(selected.registration || selected.aircraftId || '—') + '" /></div>';
        html += '<div class="mcx-field"><label>Inspection</label><input class="mcx-input" type="text" disabled value="' + esc(selected.inspectionType || '—') + '" /></div>';
        html += '<div class="mcx-field"><label>Due Date</label><input class="mcx-input" type="date" data-editor="dueDate" value="' + esc(selected.dueDate || '') + '" /></div>';
        html += '<div class="mcx-field"><label>Hours Remaining</label><input class="mcx-input" type="number" data-editor="hoursRemaining" value="' + esc(selected.hoursRemaining || 0) + '" /></div>';
        html += '<div class="mcx-field"><label>Downtime (days)</label><input class="mcx-input" type="number" min="0.5" step="0.5" data-editor="durationDays" value="' + esc(formatDuration(selected.durationDays || getInspectionDurationDays(selected))) + '" /></div>';
        html += '<div class="mcx-field" style="grid-column:1/-1;"><label>Notes</label><textarea class="mcx-textarea" data-editor="notes">' + esc(selected.notes || '') + '</textarea></div>';
        html += '</div>';
        html += '<div class="mcx-btns" style="margin-top:10px;">';
        html += '<button class="mcx-btn" data-act="close-editor">Cancel</button>';
        html += '<button class="mcx-btn" data-act="reset-editor">Reset to projected</button>';
        html += '<button class="mcx-btn" data-act="save-editor">Save edit</button>';
        html += '</div>';
        html += '</div>';
      }

      html += '</div>';

      root.innerHTML = html;

      var hoverCard = document.createElement('div');
      hoverCard.className = 'mcx-hovercard';
      root.appendChild(hoverCard);

      function positionHoverCard(x, y) {
        var pad = 12;
        var cardRect = hoverCard.getBoundingClientRect();
        var left = x + 14;
        var top = y + 14;
        if (left + cardRect.width + pad > window.innerWidth) {
          left = Math.max(pad, x - cardRect.width - 14);
        }
        if (top + cardRect.height + pad > window.innerHeight) {
          top = Math.max(pad, y - cardRect.height - 14);
        }
        hoverCard.style.left = left + 'px';
        hoverCard.style.top = top + 'px';
      }

      function showHoverCard(eventId, x, y) {
        var ev = eventsById[eventId];
        if (!ev) return;
        hoverCard.innerHTML = hoverCardContent(ev);
        hoverCard.classList.add('is-visible');
        positionHoverCard(x, y);
      }

      function hideHoverCard() {
        hoverCard.classList.remove('is-visible');
      }

      root.querySelectorAll('.mcx-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var act = btn.getAttribute('data-act');
          if (act === 'today') {
            var t = new Date();
            date = new Date(t.getFullYear(), t.getMonth(), 1);
          } else if (act === 'prev') {
            date = new Date(date.getFullYear(), date.getMonth() - 1, 1);
          } else if (act === 'next') {
            date = new Date(date.getFullYear(), date.getMonth() + 1, 1);
          } else if (act === 'clear-filters') {
            filters.aircraft = 'all';
            filters.inspection = 'all';
          } else if (act === 'save-editor') {
            onSaveEdit();
            return;
          } else if (act === 'reset-editor') {
            onResetEdit();
            return;
          } else if (act === 'close-editor') {
            editor.selectedId = null;
          }
          render();
        });
      });

      root.querySelectorAll('.mcx-select[data-filter]').forEach(function (input) {
        input.addEventListener('change', function () {
          var key = input.getAttribute('data-filter');
          filters[key] = input.value;
          render();
        });
      });

      root.querySelectorAll('[data-event-id]').forEach(function (el) {
        var eventId = el.getAttribute('data-event-id');
        el.addEventListener('mouseenter', function (evt) {
          showHoverCard(eventId, evt.clientX, evt.clientY);
        });
        el.addEventListener('mousemove', function (evt) {
          if (!hoverCard.classList.contains('is-visible')) return;
          positionHoverCard(evt.clientX, evt.clientY);
        });
        el.addEventListener('mouseleave', hideHoverCard);
        el.addEventListener('focus', function () {
          var rect = el.getBoundingClientRect();
          showHoverCard(eventId, rect.left + rect.width / 2, rect.top + rect.height / 2);
        });
        el.addEventListener('blur', hideHoverCard);
        el.addEventListener('click', function () {
          hideHoverCard();
          editor.selectedId = el.getAttribute('data-event-id');
          render();
        });
      });
    }

    render();
  };
})();
