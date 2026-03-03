(function () {
  function esc(v) {
    return String(v ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function urgencyColor(hours, theme) {
    var h = Number(hours);
    if (!Number.isFinite(h)) return theme.blue;
    if (h <= 50) return theme.red;
    if (h <= 100) return theme.amber;
    return theme.blue;
  }

  function toDateKey(d) {
    var y = d.getFullYear();
    var m = String(d.getMonth() + 1).padStart(2, '0');
    var day = String(d.getDate()).padStart(2, '0');
    return y + '-' + m + '-' + day;
  }

  function ensureHoverCard(theme) {
    var card = document.getElementById('cal-hover-card');
    if (card) return card;

    card = document.createElement('div');
    card.id = 'cal-hover-card';
    card.style.position = 'fixed';
    card.style.zIndex = '10000';
    card.style.pointerEvents = 'none';
    card.style.display = 'none';
    card.style.maxWidth = '280px';
    card.style.background = theme.surface;
    card.style.border = '1px solid ' + theme.border;
    card.style.borderLeft = '3px solid ' + theme.blue;
    card.style.borderRadius = '4px';
    card.style.boxShadow = '0 8px 24px rgba(0,0,0,0.35)';
    card.style.padding = '10px';
    card.style.color = theme.text;
    card.style.fontFamily = theme.fontBody;
    card.innerHTML = '';
    document.body.appendChild(card);

    return card;
  }

  function positionHoverCard(card, clientX, clientY) {
    var pad = 14;
    var x = clientX + pad;
    var y = clientY + pad;

    var vw = window.innerWidth || document.documentElement.clientWidth;
    var vh = window.innerHeight || document.documentElement.clientHeight;
    var w = card.offsetWidth || 280;
    var h = card.offsetHeight || 150;

    if (x + w + 8 > vw) x = clientX - w - pad;
    if (y + h + 8 > vh) y = clientY - h - pad;

    if (x < 8) x = 8;
    if (y < 8) y = 8;

    card.style.left = x + 'px';
    card.style.top = y + 'px';
  }

  window.renderMaintenanceCalendar = function renderMaintenanceCalendar(root, payload) {
    if (!root) return;

    var theme = (payload && payload.themeResolved) || {
      bg: '#0a0c0f',
      surface: '#111418',
      surface2: '#181c22',
      border: '#1e2530',
      text: '#cdd6e0',
      muted: '#fff',
      heading: '#e8edf2',
      blue: '#29b6f6',
      amber: '#ffab00',
      red: '#ff1744',
      green: '#00e676',
      fontBody: 'Barlow, sans-serif',
      fontSans: 'Barlow Condensed, sans-serif',
      fontMono: 'Share Tech Mono, monospace'
    };

    var hoverCard = ensureHoverCard(theme);

    var events = Array.isArray(payload && payload.initialEvents) ? payload.initialEvents.slice() : [];
    var aircraftList = Array.isArray(payload && payload.aircraft) ? payload.aircraft : [];
    var inspectionTypes = Array.isArray(payload && payload.inspectionTypes) ? payload.inspectionTypes : [];

    var current = payload && payload.initialDate ? new Date(payload.initialDate + 'T00:00:00') : new Date();
    if (Number.isNaN(current.getTime())) current = new Date();

    var selectedAircraft = 'all';
    var selectedInspection = 'all';

    function hideHoverCard() {
      hoverCard.style.display = 'none';
    }

    function render() {
      var y = current.getFullYear();
      var m = current.getMonth();
      var first = new Date(y, m, 1);
      var daysInMonth = new Date(y, m + 1, 0).getDate();
      var firstDowMon = (first.getDay() + 6) % 7;
      var monthName = first.toLocaleString('en-US', { month: 'long', year: 'numeric' }).toUpperCase();

      var filtered = events.filter(function (ev) {
        if (selectedAircraft !== 'all' && ev.aircraftId !== selectedAircraft) return false;
        if (selectedInspection !== 'all' && ev.inspectionType !== selectedInspection) return false;
        return true;
      });

      var byDate = {};
      filtered.forEach(function (ev) {
        (byDate[ev.dueDate] = byDate[ev.dueDate] || []).push(ev);
      });

      var dayHeaders = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'];

      var html = '';
      html += '<div style="display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:12px;">';
      html += '<div style="font-family:' + theme.fontSans + ';font-weight:700;letter-spacing:2px;color:' + theme.heading + ';">' + esc(monthName) + '</div>';
      html += '<div style="display:flex;gap:8px;">';
      html += '<button data-cal-nav="prev" style="background:' + theme.surface2 + ';border:1px solid ' + theme.border + ';color:' + theme.text + ';padding:6px 10px;border-radius:3px;cursor:pointer;font-family:' + theme.fontMono + ';font-size:11px;">◀</button>';
      html += '<button data-cal-nav="today" style="background:' + theme.blue + ';border:1px solid ' + theme.blue + ';color:#000;padding:6px 10px;border-radius:3px;cursor:pointer;font-family:' + theme.fontMono + ';font-size:11px;font-weight:700;">TODAY</button>';
      html += '<button data-cal-nav="next" style="background:' + theme.surface2 + ';border:1px solid ' + theme.border + ';color:' + theme.text + ';padding:6px 10px;border-radius:3px;cursor:pointer;font-family:' + theme.fontMono + ';font-size:11px;">▶</button>';
      html += '</div></div>';

      html += '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px;">';
      html += '<select id="cal-aircraft" style="background:' + theme.surface2 + ';border:1px solid ' + theme.border + ';color:' + theme.text + ';padding:6px 8px;border-radius:3px;font-family:' + theme.fontMono + ';font-size:11px;">';
      html += '<option value="all">ALL AIRCRAFT</option>';
      aircraftList.forEach(function (a) {
        html += '<option value="' + esc(a.id) + '"' + (selectedAircraft === a.id ? ' selected' : '') + '>' + esc(a.registration || a.id) + '</option>';
      });
      html += '</select>';

      html += '<select id="cal-inspection" style="background:' + theme.surface2 + ';border:1px solid ' + theme.border + ';color:' + theme.text + ';padding:6px 8px;border-radius:3px;font-family:' + theme.fontMono + ';font-size:11px;">';
      html += '<option value="all">ALL INSPECTIONS</option>';
      inspectionTypes.forEach(function (i) {
        html += '<option value="' + esc(i) + '"' + (selectedInspection === i ? ' selected' : '') + '>' + esc(i) + '</option>';
      });
      html += '</select>';
      html += '</div>';

      html += '<div style="display:grid;grid-template-columns:repeat(7,1fr);gap:2px;">';
      dayHeaders.forEach(function (d) {
        html += '<div style="font-family:' + theme.fontMono + ';font-size:9px;color:' + theme.muted + ';text-align:center;padding:4px 0;letter-spacing:1px;">' + d + '</div>';
      });

      for (var i = 0; i < firstDowMon; i += 1) {
        html += '<div style="min-height:90px;"></div>';
      }

      var todayKey = toDateKey(new Date());
      for (var day = 1; day <= daysInMonth; day += 1) {
        var date = new Date(y, m, day);
        var key = toDateKey(date);
        var dayEvents = byDate[key] || [];
        var border = key === todayKey ? theme.blue : theme.border;
        html += '<div style="background:' + theme.bg + ';border:1px solid ' + border + ';border-radius:3px;min-height:90px;padding:4px;">';
        html += '<div style="font-family:' + theme.fontMono + ';font-size:10px;color:' + (key === todayKey ? theme.blue : theme.muted) + ';margin-bottom:3px;">' + day + '</div>';

        dayEvents.slice(0, 3).forEach(function (ev, idx) {
          var c = urgencyColor(ev.hoursRemaining, theme);
          var textColor = c === theme.amber ? '#000' : '#fff';
          var cardData = esc(JSON.stringify({
            registration: ev.registration || '',
            inspectionType: ev.inspectionType || '',
            dueDate: ev.dueDate || '',
            hoursRemaining: ev.hoursRemaining,
            notes: ev.notes || ''
          }));
          html += '<div data-hover-card="' + cardData + '" '
            + 'style="font-family:' + theme.fontMono + ';font-size:8px;padding:2px 4px;border-radius:2px;margin-bottom:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;background:' + c + ';color:' + textColor + ';cursor:default;">'
            + esc((ev.registration || '') + ' ' + (ev.inspectionType || '')) + '</div>';
        });

        if (dayEvents.length > 3) {
          html += '<div style="font-family:' + theme.fontMono + ';font-size:8px;color:' + theme.muted + ';">+' + (dayEvents.length - 3) + ' more</div>';
        }

        html += '</div>';
      }

      html += '</div>';

      root.innerHTML = html;

      root.querySelector('[data-cal-nav="prev"]').onclick = function () {
        hideHoverCard();
        current = new Date(current.getFullYear(), current.getMonth() - 1, 1);
        render();
      };
      root.querySelector('[data-cal-nav="next"]').onclick = function () {
        hideHoverCard();
        current = new Date(current.getFullYear(), current.getMonth() + 1, 1);
        render();
      };
      root.querySelector('[data-cal-nav="today"]').onclick = function () {
        hideHoverCard();
        var now = new Date();
        current = new Date(now.getFullYear(), now.getMonth(), 1);
        render();
      };
      root.querySelector('#cal-aircraft').onchange = function (e) {
        hideHoverCard();
        selectedAircraft = e.target.value;
        render();
      };
      root.querySelector('#cal-inspection').onchange = function (e) {
        hideHoverCard();
        selectedInspection = e.target.value;
        render();
      };

      var badges = root.querySelectorAll('[data-hover-card]');
      badges.forEach(function (badge) {
        badge.addEventListener('mouseenter', function (e) {
          var raw = badge.getAttribute('data-hover-card') || '{}';
          var data;
          try {
            data = JSON.parse(raw);
          } catch (_) {
            data = {};
          }

          var hrsText = Number.isFinite(Number(data.hoursRemaining))
            ? Number(data.hoursRemaining).toFixed(1) + ' hrs remaining'
            : 'Hours remaining: n/a';

          hoverCard.style.borderLeftColor = urgencyColor(data.hoursRemaining, theme);
          hoverCard.innerHTML = ''
            + '<div style="font-family:' + theme.fontSans + ';font-size:12px;font-weight:700;letter-spacing:1px;color:' + theme.heading + ';margin-bottom:6px;">'
            + esc((data.registration || 'UNKNOWN') + ' · ' + (data.inspectionType || 'Inspection'))
            + '</div>'
            + '<div style="font-family:' + theme.fontMono + ';font-size:10px;color:' + theme.muted + ';margin-bottom:4px;">DUE DATE: ' + esc(data.dueDate || 'N/A') + '</div>'
            + '<div style="font-family:' + theme.fontMono + ';font-size:10px;color:' + theme.text + ';margin-bottom:6px;">' + esc(hrsText) + '</div>'
            + '<div style="font-family:' + theme.fontBody + ';font-size:11px;color:' + theme.text + ';line-height:1.4;">' + esc(data.notes || 'No notes') + '</div>';

          hoverCard.style.display = 'block';
          positionHoverCard(hoverCard, e.clientX, e.clientY);
        });

        badge.addEventListener('mousemove', function (e) {
          if (hoverCard.style.display !== 'none') {
            positionHoverCard(hoverCard, e.clientX, e.clientY);
          }
        });

        badge.addEventListener('mouseleave', function () {
          hideHoverCard();
        });
      });
    }

    render();
  };
})();
