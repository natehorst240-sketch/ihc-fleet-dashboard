(function () {
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
      '.mcx-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:2px;}',
      '.mcx-dow{font-family:' + theme.fontMono + ';font-size:9px;text-align:center;letter-spacing:1px;color:' + theme.muted + ';padding:4px 0;}',
      '.mcx-empty{min-height:84px;}',
      '.mcx-day{min-height:84px;padding:6px;border:1px solid ' + theme.border + ';border-radius:3px;background:#0d1117;overflow:hidden;}',
      '.mcx-day.is-today{border-color:' + theme.blue + ';}',
      '.mcx-num{font-family:' + theme.fontMono + ';font-size:10px;color:' + theme.muted + ';margin-bottom:4px;}',
      '.mcx-pill{font-family:' + theme.fontMono + ';font-size:9px;border-radius:2px;padding:1px 4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:2px;}',
      '.mcx-pill.red{background:#c0392b;color:#fff;}',
      '.mcx-pill.amber{background:#e67e22;color:#000;}',
      '.mcx-pill.blue{background:#2980b9;color:#fff;}',
      '.mcx-legend{display:flex;gap:14px;flex-wrap:wrap;font-family:' + theme.fontMono + ';font-size:10px;color:' + theme.muted + ';margin-bottom:10px;}',
      '.mcx-leg-dot{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:4px;vertical-align:middle;}',
      '.mcx-empty-state{font-family:' + theme.fontMono + ';font-size:11px;color:' + theme.muted + ';padding:10px 0;}'
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
      if (!map[ev.dueDate]) map[ev.dueDate] = [];
      map[ev.dueDate].push(ev);
    });
    return map;
  }

  function colorClass(ev) {
    var hrs = Number(ev.hoursRemaining);
    if (!isFinite(hrs) || hrs > 100) return 'blue';
    if (hrs <= 50) return 'red';
    return 'amber';
  }

  window.renderMaintenanceCalendar = function (root, payload) {
    if (!root) return;
    payload = payload || {};
    var theme = payload.themeResolved || {
      text: '#cdd6e0', muted: '#fff', heading: '#e8edf2', border: '#1e2530', blue: '#29b6f6',
      fontBody: 'Barlow, sans-serif', fontMono: 'Share Tech Mono, monospace', fontSans: 'Barlow Condensed, sans-serif'
    };
    ensureStyles(theme);

    var events = Array.isArray(payload.initialEvents) ? payload.initialEvents.slice() : [];
    var date = payload.initialDate ? new Date(payload.initialDate + 'T00:00:00') : new Date();
    if (isNaN(date.getTime())) date = new Date();
    date.setDate(1);

    var todayIso = iso(new Date());

    function render() {
      var byDay = buildMap(events);
      var year = date.getFullYear();
      var month = date.getMonth();
      var first = new Date(year, month, 1);
      var firstDowMon = (first.getDay() + 6) % 7;
      var lastDay = new Date(year, month + 1, 0).getDate();

      var html = '';
      html += '<div class="mcx">';
      html += '<div class="mcx-toolbar">';
      html += '<div class="mcx-title">' + esc(monthLabel(date)) + '</div>';
      html += '<div class="mcx-btns">';
      html += '<button class="mcx-btn" data-act="today">TODAY</button>';
      html += '<button class="mcx-btn" data-act="prev">◀</button>';
      html += '<button class="mcx-btn" data-act="next">▶</button>';
      html += '</div></div>';
      html += '<div class="mcx-legend">'
        + '<span><span class="mcx-leg-dot" style="background:#c0392b"></span>≤ 50 HRS</span>'
        + '<span><span class="mcx-leg-dot" style="background:#e67e22"></span>≤ 100 HRS</span>'
        + '<span><span class="mcx-leg-dot" style="background:#2980b9"></span>> 100 HRS</span>'
        + '</div>';
      html += '<div class="mcx-grid">';
      ['MON','TUE','WED','THU','FRI','SAT','SUN'].forEach(function(d){ html += '<div class="mcx-dow">'+d+'</div>'; });
      for (var i = 0; i < firstDowMon; i++) html += '<div class="mcx-empty"></div>';

      for (var day = 1; day <= lastDay; day++) {
        var key = year + '-' + String(month + 1).padStart(2, '0') + '-' + String(day).padStart(2, '0');
        var list = byDay[key] || [];
        var isToday = key === todayIso;
        html += '<div class="mcx-day' + (isToday ? ' is-today' : '') + '">';
        html += '<div class="mcx-num">' + day + '</div>';
        list.slice(0, 4).forEach(function(ev){
          html += '<div class="mcx-pill ' + colorClass(ev) + '" title="' + esc(ev.inspectionType || '') + '">' + esc((ev.registration || '') + ' ' + (ev.inspectionType || '')) + '</div>';
        });
        if (list.length > 4) html += '<div class="mcx-pill blue">+' + (list.length - 4) + ' more</div>';
        html += '</div>';
      }
      html += '</div>';
      if (!events.length) html += '<div class="mcx-empty-state">No projected events available.</div>';
      html += '</div>';

      root.innerHTML = html;

      root.querySelectorAll('.mcx-btn').forEach(function(btn){
        btn.addEventListener('click', function(){
          var act = btn.getAttribute('data-act');
          if (act === 'today') {
            var t = new Date();
            date = new Date(t.getFullYear(), t.getMonth(), 1);
          } else if (act === 'prev') {
            date = new Date(date.getFullYear(), date.getMonth() - 1, 1);
          } else if (act === 'next') {
            date = new Date(date.getFullYear(), date.getMonth() + 1, 1);
          }
          render();
        });
      });
    }

    render();
  };
})();
