(function () {
  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function fmtMonth(d) {
    return d.toLocaleDateString(undefined, { month: 'long', year: 'numeric' }).toUpperCase();
  }

  function parseISO(iso) {
    var parts = String(iso || '').split('-').map(Number);
    if (parts.length !== 3 || parts.some(Number.isNaN)) return null;
    return new Date(parts[0], parts[1] - 1, parts[2]);
  }

  function daysInMonth(year, monthIndex) {
    return new Date(year, monthIndex + 1, 0).getDate();
  }

  function urgencyClass(hoursRemaining) {
    var v = Number(hoursRemaining);
    if (!Number.isFinite(v)) return 'ok';
    if (v <= 50) return 'critical';
    if (v <= 100) return 'coming';
    return 'ok';
  }

  function injectStyles(theme) {
    var id = 'maintenance-calendar-island-styles';
    if (document.getElementById(id)) return;

    var style = document.createElement('style');
    style.id = id;
    style.textContent = [
      '.mci-root{color:' + theme.text + ';font-family:' + theme.fontBody + ';}',
      '.mci-toolbar{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:12px;flex-wrap:wrap;}',
      '.mci-title{font-family:' + theme.fontSans + ';font-size:18px;font-weight:700;letter-spacing:2px;color:' + theme.heading + ';text-transform:uppercase;}',
      '.mci-actions{display:flex;gap:8px;}',
      '.mci-btn{border:1px solid ' + theme.border + ';background:' + theme.surface2 + ';color:' + theme.text + ';font-family:' + theme.fontMono + ';font-size:11px;padding:6px 10px;border-radius:3px;cursor:pointer;}',
      '.mci-btn:hover{border-color:' + theme.blue + ';color:' + theme.blue + ';}',
      '.mci-grid{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:2px;}',
      '.mci-dow{font-family:' + theme.fontMono + ';font-size:10px;letter-spacing:1px;text-align:center;color:' + theme.muted + ';padding:4px 0;}',
      '.mci-cell-empty{min-height:94px;}',
      '.mci-cell{min-height:94px;background:' + theme.bg + ';border:1px solid ' + theme.border + ';border-radius:3px;padding:6px;}',
      '.mci-cell.today{border-color:' + theme.blue + ';box-shadow:0 0 0 1px ' + theme.blue + ' inset;}',
      '.mci-day{font-family:' + theme.fontMono + ';font-size:10px;margin-bottom:4px;color:' + theme.muted + ';}',
      '.mci-event{font-family:' + theme.fontMono + ';font-size:10px;padding:2px 4px;border-radius:2px;margin-bottom:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
      '.mci-event.critical{background:' + theme.red + ';color:#fff;}',
      '.mci-event.coming{background:' + theme.amber + ';color:#000;}',
      '.mci-event.ok{background:' + theme.blue + ';color:#fff;}',
      '.mci-meta{margin-top:10px;font-family:' + theme.fontMono + ';font-size:10px;color:' + theme.muted + ';}'
    ].join('');
    document.head.appendChild(style);
  }

  window.renderMaintenanceCalendar = function renderMaintenanceCalendar(root, payload) {
    if (!root) return;

    var theme = Object.assign({
      bg: '#0a0c0f',
      surface: '#111418',
      surface2: '#181c22',
      border: '#1e2530',
      text: '#cdd6e0',
      muted: '#ffffff',
      heading: '#e8edf2',
      blue: '#29b6f6',
      amber: '#ffab00',
      red: '#ff1744',
      green: '#00e676',
      fontBody: 'Barlow, sans-serif',
      fontSans: 'Barlow Condensed, sans-serif',
      fontMono: 'Share Tech Mono, monospace'
    }, payload && payload.themeResolved ? payload.themeResolved : {});

    injectStyles(theme);

    var events = Array.isArray(payload && payload.initialEvents) ? payload.initialEvents.slice() : [];
    var current = parseISO(payload && payload.initialDate) || new Date();

    function draw() {
      root.innerHTML = '';
      var container = el('div', 'mci-root');

      var toolbar = el('div', 'mci-toolbar');
      toolbar.appendChild(el('div', 'mci-title', fmtMonth(current)));
      var actions = el('div', 'mci-actions');

      var prev = el('button', 'mci-btn', 'PREV');
      prev.type = 'button';
      prev.onclick = function () { current = new Date(current.getFullYear(), current.getMonth() - 1, 1); draw(); };

      var today = el('button', 'mci-btn', 'TODAY');
      today.type = 'button';
      today.onclick = function () { var n = new Date(); current = new Date(n.getFullYear(), n.getMonth(), 1); draw(); };

      var next = el('button', 'mci-btn', 'NEXT');
      next.type = 'button';
      next.onclick = function () { current = new Date(current.getFullYear(), current.getMonth() + 1, 1); draw(); };

      actions.appendChild(prev);
      actions.appendChild(today);
      actions.appendChild(next);
      toolbar.appendChild(actions);
      container.appendChild(toolbar);

      var grid = el('div', 'mci-grid');
      ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'].forEach(function (d) {
        grid.appendChild(el('div', 'mci-dow', d));
      });

      var first = new Date(current.getFullYear(), current.getMonth(), 1);
      var dow = (first.getDay() + 6) % 7;
      var days = daysInMonth(current.getFullYear(), current.getMonth());
      var now = new Date();

      for (var i = 0; i < dow; i++) grid.appendChild(el('div', 'mci-cell-empty'));

      for (var day = 1; day <= days; day++) {
        var cellDate = new Date(current.getFullYear(), current.getMonth(), day);
        var iso = [cellDate.getFullYear(), String(cellDate.getMonth() + 1).padStart(2, '0'), String(day).padStart(2, '0')].join('-');
        var cell = el('div', 'mci-cell');
        if (cellDate.toDateString() === now.toDateString()) cell.classList.add('today');
        cell.appendChild(el('div', 'mci-day', String(day)));

        events
          .filter(function (ev) { return ev && ev.dueDate === iso; })
          .slice(0, 4)
          .forEach(function (ev) {
            var badge = el('div', 'mci-event ' + urgencyClass(ev.hoursRemaining));
            badge.textContent = (ev.registration || ev.aircraftId || 'AC') + ' ' + (ev.inspectionType || 'Inspection');
            badge.title = (ev.notes || '') + (Number.isFinite(Number(ev.hoursRemaining)) ? (' | ' + ev.hoursRemaining + ' hrs remaining') : '');
            cell.appendChild(badge);
          });

        grid.appendChild(cell);
      }

      container.appendChild(grid);
      container.appendChild(el('div', 'mci-meta', 'Month view loaded from maintenance-calendar-ux/calendar-island.js'));
      root.appendChild(container);
    }

    draw();
  };
})();
