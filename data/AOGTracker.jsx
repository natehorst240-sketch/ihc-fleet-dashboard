const { useState, useEffect, useMemo } = React;

// ── CONFIG ────────────────────────────────────────────────────────────────────
// Path to the JSON file Apps Script writes to your repo.
// On GitHub Pages this resolves relative to your repo root.
const AOG_JSON_URL = "./aog_status.json";

const storage = window.storage || {
  async get(key) {
    const value = localStorage.getItem(key);
    return value == null ? null : { value };
  },
  async set(key, value) {
    localStorage.setItem(key, value);
  }
};

const FLEET = [
  "N251HC","N261HC","N271HC","N281HC","N291HC",
  "N431HC","N531HC","N631HC","N731HC"
];

// ── HELPERS ───────────────────────────────────────────────────────────────────
function ts(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return (
    d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) +
    " " +
    d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" })
  );
}

// ── COMPONENT ─────────────────────────────────────────────────────────────────

function parseDateInput(tsLike) {
  if (tsLike instanceof Date) return new Date(tsLike.getTime());
  if (typeof tsLike === "number") return new Date(tsLike);
  if (typeof tsLike === "string") {
    const m = tsLike.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (m) return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
    return new Date(tsLike);
  }
  return new Date(tsLike);
}

function localDateKey(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function startOfWeek(tsLike) {
  const d = parseDateInput(tsLike);
  if (Number.isNaN(d.getTime())) return new Date(NaN);
  const start = new Date(d);
  start.setHours(0, 0, 0, 0);
  start.setDate(start.getDate() - start.getDay());
  return start;
}

function weekKey(tsLike) {
  const start = startOfWeek(tsLike);
  if (Number.isNaN(start.getTime())) return "";
  return localDateKey(start);
}

function weekRangeLabel(key) {
  const start = parseDateInput(key);
  if (Number.isNaN(start.getTime())) return "—";
  start.setHours(0, 0, 0, 0);
  const end = new Date(start);
  end.setDate(end.getDate() + 6);
  return `${start.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })} - ${end.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}`;
}

function isCsvResolved(event) {
  if (!event || typeof event !== "object") return false;
  const marker = [
    event.resolutionSource,
    event.resolvedSource,
    event.resolvedBy,
    event.closedBy,
    event.endSource,
  ]
    .filter(Boolean)
    .map((value) => String(value).toLowerCase());
  if (marker.some((value) => value.includes("csv") || value.includes("camp"))) return true;
  return Boolean(event.csvComplianceDate || event.complianceDate || event.resolvedFromCsvAt);
}

function AOGTracker() {
  const [active, setActive]     = useState([]);
  const [history, setHistory]   = useState([]);
  const [tab, setTab]           = useState("weekly");
  const [loaded, setLoaded]     = useState(false);
  const [lastSync, setLastSync] = useState(null);
  const [syncing, setSyncing]   = useState(false);
  const [locallyClearedIds, setLocallyClearedIds] = useState({});
  const [selectedWeek, setSelectedWeek] = useState("");

  // Load persisted local overrides (cleared events not yet in JSON)
  useEffect(() => {
    async function boot() {
      try {
        const [lh, lc] = await Promise.all([
          storage.get("aog:local_history"),
          storage.get("aog:locally_cleared_ids"),
        ]);

        const localHistory = lh?.value ? JSON.parse(lh.value) : [];
        const localCleared = lc?.value ? JSON.parse(lc.value) : {};

        setLocallyClearedIds(localCleared);

        // Load remote JSON and merge local overrides deterministically.
        await fetchJSON({ localHistory, localCleared });

        if (localHistory.length) {
          setHistory(prev => {
            const merged = [...localHistory];
            prev.forEach(h => {
              if (!merged.find(m => m.id === h.id)) merged.push(h);
            });
            return merged.sort((a, b) => new Date(b.end) - new Date(a.end));
          });
        }
      } catch (e) {}
      setLoaded(true);
    }
    boot();
  }, []);

  // Keep dashboard status current while the page stays open.
  useEffect(() => {
    const intervalId = window.setInterval(() => {
      fetchJSON();
    }, 60 * 1000);

    return () => window.clearInterval(intervalId);
  }, []);

  // ── FETCH remote JSON written by Apps Script ──────────────────────────────
  async function fetchJSON(localOverrides = {}) {
    setSyncing(true);
    try {
      const res = await fetch(AOG_JSON_URL + "?t=" + Date.now()); // cache-bust
      if (!res.ok) throw new Error("HTTP " + res.status);
      const data = await res.json();
      const remoteActiveFromFeed = Array.isArray(data)
        ? data
        : (data.active || data.active_events || data.activeEvents || []);
      const remoteHistory = Array.isArray(data)
        ? []
        : (data.history || data.resolved || data.resolved_events || data.resolvedEvents || []);
      const feedLastUpdated = Array.isArray(data)
        ? null
        : (data.lastUpdated || data.last_updated || data.updated_at || null);
      const localHistoryRaw = localOverrides.localHistory ? null : await storage.get("aog:local_history");
      const localClearedRaw = localOverrides.localCleared ? null : await storage.get("aog:locally_cleared_ids");
      let localHistory = localOverrides.localHistory || [];
      let localCleared = localOverrides.localCleared || locallyClearedIds;
      if (!localOverrides.localHistory && localHistoryRaw?.value) localHistory = JSON.parse(localHistoryRaw.value);
      if (!localOverrides.localCleared && localClearedRaw?.value) localCleared = JSON.parse(localClearedRaw.value);

      // Merge remote active with any we already know about locally
      const remoteActive = [...remoteActiveFromFeed];
      const remoteHistoryForUi = [];

      remoteHistory.forEach((event) => {
        if (!event?.id || localCleared[event.id]) {
          if (event?.end) remoteHistoryForUi.push(event);
          return;
        }

        const shouldRemainActive = event.source === "email" && !isCsvResolved(event);
        if (shouldRemainActive) {
          remoteActive.push({ ...event, end: null, duration: null });
          return;
        }

        if (event.end) remoteHistoryForUi.push(event);
      });

      setActive(() => {
        const merged = [];
        remoteActive.forEach((event) => {
          if (!event || !event.id || localCleared[event.id]) return;
          if (!merged.find((item) => item.id === event.id)) merged.push(event);
        });
        return merged;
      });

      setHistory(prev => {
        const merged = [...remoteHistoryForUi];
        prev.forEach(item => {
          if (!merged.find(m => m.id === item.id)) merged.push(item);
        });
        localHistory.forEach(item => {
          if (!merged.find(m => m.id === item.id)) merged.push(item);
        });
        return merged
          .filter(event => event.end)
          .sort((a, b) => new Date(b.end) - new Date(a.end));
      });

      setLocallyClearedIds(localCleared);

      if (feedLastUpdated) setLastSync(feedLastUpdated);
    } catch (e) {
      console.warn("Could not fetch aog_status.json:", e.message);
    }
    setSyncing(false);
  }

  const allEvents = useMemo(() => {
    return [...active, ...history]
      .filter(event => event && event.start)
      .sort((a, b) => new Date(b.start) - new Date(a.start));
  }, [active, history]);

  const currentWeekKey = weekKey(Date.now());
  const weekEventsByKey = allEvents.reduce((acc, event) => {
    const key = weekKey(event.start);
    if (!key) return acc;
    if (!acc[key]) acc[key] = [];
    acc[key].push(event);
    return acc;
  }, {});

  if (currentWeekKey && active.some((event) => event && event.start && weekKey(event.start) !== currentWeekKey)) {
    weekEventsByKey[currentWeekKey] = [
      ...(weekEventsByKey[currentWeekKey] || []),
      ...active.filter((event) => event && event.start && weekKey(event.start) !== currentWeekKey),
    ];
  }

  const weeksByTail = Object.keys(weekEventsByKey)
    .sort((a, b) => new Date(b) - new Date(a))
    .map((week) => {
      const tails = FLEET.map((tail) => {
        const events = weekEventsByKey[week]
          .filter((event) => event.tail === tail)
          .sort((a, b) => new Date(b.start) - new Date(a.start));
        return { tail, events, count: events.length };
      }).filter((entry) => entry.count > 0);

      return { week, tails, count: tails.reduce((sum, entry) => sum + entry.count, 0) };
    })
    .filter((entry) => entry.count > 0);

  useEffect(() => {
    if (!weeksByTail.length) {
      if (selectedWeek) setSelectedWeek("");
      return;
    }

    if (selectedWeek && weeksByTail.some((entry) => entry.week === selectedWeek)) return;

    const preferredWeek = weeksByTail.find((entry) => entry.week === currentWeekKey)?.week || weeksByTail[0].week;
    if (preferredWeek !== selectedWeek) setSelectedWeek(preferredWeek);
  }, [weeksByTail, selectedWeek, currentWeekKey]);

  const selectedWeekEntry = weeksByTail.find((entry) => entry.week === selectedWeek) || null;

  const sortedActive = FLEET.flatMap((tail) => active
    .filter((event) => event.tail === tail)
    .sort((a, b) => new Date(b.start) - new Date(a.start))
  );

  // ── STYLES ────────────────────────────────────────────────────────────────
  const btn = (col, bg) => ({
    background: bg || "transparent", border: `1px solid ${col}`, color: col,
    padding: "7px 14px", borderRadius: 2, cursor: "pointer",
    fontFamily: "'Courier New',monospace", fontSize: 10, letterSpacing: 2,
  });

  // ── RENDER ────────────────────────────────────────────────────────────────
  if (!loaded) return (
    <div style={{ background: "#08080f", color: "#ffffff", height: "100vh", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "monospace", fontSize: 11, letterSpacing: 4 }}>
      LOADING FLEET DATA...
    </div>
  );

  return (
    <div style={{ background: "#08080f", minHeight: "100vh", color: "#d0d0e0", fontFamily: "'Courier New',monospace" }}>

      {/* ── HEADER ── */}
      <div style={{ background: "#09090f", borderBottom: "1px solid #111125", padding: "13px 20px", display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{ width: 7, height: 7, borderRadius: "50%", background: active.length ? "#ff2222" : "#22cc55", boxShadow: active.length ? "0 0 10px #ff2222" : "0 0 10px #22cc55", animation: active.length ? "pulse 1.4s infinite" : "none" }} />
        <span style={{ fontSize: 10, letterSpacing: 4, color: "#ffffff" }}>IHC FLEET · AOG TRACKER</span>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 12 }}>
          {lastSync && (
            <span style={{ fontSize: 9, color: "#ffffff", letterSpacing: 1 }}>
              LAST EMAIL SYNC: {ts(lastSync)}
            </span>
          )}
          <button onClick={fetchJSON} disabled={syncing} style={btn("#ffffff", "#05050f")}>
            {syncing ? "CHECKING..." : "⟳ REFRESH"}
          </button>
          <span style={{ fontSize: 10, letterSpacing: 2, color: active.length ? "#ff4444" : "#33aa55" }}>
            {active.length ? `${active.length} AOG` : "ALL CLEAR"}
          </span>
        </div>
      </div>

      {/* ── TABS ── */}
      <div style={{ padding: "14px 20px 0", display: "flex", gap: 2, borderBottom: "1px solid #0e0e1e" }}>
        {[ ["live", `LIVE (${active.length})`], ["weekly", "AOG EVENTS BY WEEK"] ].map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)} style={{ background: "transparent", border: "none", borderBottom: tab === k ? "2px solid #ff3333" : "2px solid transparent", color: "#ffffff", padding: "7px 14px 9px", cursor: "pointer", fontFamily: "'Courier New',monospace", fontSize: 10, letterSpacing: 2 }}>
            {label}
          </button>
        ))}
      </div>

      {/* ── BODY ── */}
      <div style={{ padding: "14px 20px" }}>

        {/* Live: empty state */}
        {tab === "live" && !active.length && (
          <div style={{ textAlign: "center", padding: "60px 0", color: "#ffffff", fontSize: 11, letterSpacing: 4 }}>
            <div style={{ fontSize: 30, marginBottom: 10, color: "#1a331a" }}>✓</div>
            NO ACTIVE AOG EVENTS
            <div style={{ marginTop: 8, fontSize: 9, color: "#ffffff" }}>
              Auto-updates every 5 min via Google Apps Script · Gmail → GitHub → here
            </div>
          </div>
        )}

        {tab === "live" && active.length > 0 && (
          <div>
            <div style={{ fontSize: 9, letterSpacing: 4, color: "#ffffff", marginBottom: 14 }}>
              ACTIVE AOG EVENTS · SORTED BY HELICOPTER
            </div>
            {sortedActive.map(a => (
              <div key={a.id} style={{ background: "#090912", border: "1px solid #111122", borderRadius: 2, padding: "12px 14px", marginBottom: 8 }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                  <div>
                    <div style={{ fontSize: 17, fontWeight: "bold", color: "#ffffff", letterSpacing: 2 }}>{a.tail}</div>
                    <div style={{ fontSize: 9, color: "#ff8888", marginTop: 3 }}>Discovered: {ts(a.start)}</div>
                  </div>
                  <div style={{ fontSize: 8, color: "#ffffff" }}>{a.source === "email" ? "📧 via email" : "✎ manual"}</div>
                </div>
                {a.desc && <div style={{ fontSize: 10, color: "#ffffff", marginTop: 8, fontStyle: "italic" }}>{a.desc}</div>}
                {(a.discId || a.reportedHours) && (
                  <div style={{ fontSize: 9, color: "#8d8da3", marginTop: 6 }}>
                    {a.discId ? `Discrepancy ${a.discId}` : ""}
                    {a.discId && a.reportedHours ? " · " : ""}
                    {a.reportedHours ? `Airframe hrs: ${a.reportedHours}${a.reportedLandings ? ` · Landings: ${a.reportedLandings}` : ""}` : ""}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Weekly event list tab */}
        {tab === "weekly" && (
          <div>
            <div style={{ fontSize: 9, letterSpacing: 4, color: "#ffffff", marginBottom: 14 }}>
              SELECT A WEEK TO REVIEW ALL AOG EVENTS FOR THAT PERIOD
            </div>

            {!weeksByTail.length && <div style={{ textAlign: "center", padding: "60px 0", color: "#ffffff", fontSize: 11, letterSpacing: 4 }}>NO AOG EVENTS AVAILABLE</div>}

            {!!weeksByTail.length && (
              <div style={{ marginBottom: 18, display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center" }}>
                <label htmlFor="aog-week-select" style={{ fontSize: 10, color: "#8d8da3", letterSpacing: 2 }}>
                  WEEK
                </label>
                <select
                  id="aog-week-select"
                  value={selectedWeek}
                  onChange={(e) => setSelectedWeek(e.target.value)}
                  style={{
                    background: "#090912",
                    border: "1px solid #1a1a33",
                    color: "#ffffff",
                    padding: "8px 12px",
                    borderRadius: 2,
                    fontFamily: "'Courier New',monospace",
                    fontSize: 10,
                    letterSpacing: 1.5,
                    minWidth: 280,
                    cursor: "pointer",
                  }}
                >
                  {weeksByTail.map(({ week, count }) => (
                    <option key={week} value={week}>
                      {weekRangeLabel(week)} · {count} EVENT{count !== 1 ? "S" : ""}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {selectedWeekEntry && (
              <div key={selectedWeekEntry.week} style={{ marginBottom: 18 }}>
                <div style={{ fontSize: 12, color: "#4dc07f", letterSpacing: 2, marginBottom: 10 }}>
                  WEEK OF {weekRangeLabel(selectedWeekEntry.week).toUpperCase()} · {selectedWeekEntry.count} EVENT{selectedWeekEntry.count !== 1 ? "S" : ""}
                </div>
                {selectedWeekEntry.tails.map(x => (
                  <div key={`${selectedWeekEntry.week}-${x.tail}`} style={{ background: "#090912", border: "1px solid #111122", borderRadius: 2, padding: "12px 14px", marginBottom: 8 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                      <span style={{ fontSize: 17, fontWeight: "bold", color: "#ffffff", letterSpacing: 2 }}>{x.tail}</span>
                      <span style={{ fontSize: 9, color: "#ffffff", letterSpacing: 2 }}>{x.count} EVENT{x.count !== 1 ? "S" : ""}</span>
                    </div>
                    {x.events.map(e => (
                      <div key={e.id} style={{ fontSize: 10, color: "#ffffff", borderTop: "1px solid #0e0e1e", padding: "6px 0" }}>
                        <div style={{ fontSize: 9, color: "#4dc07f", marginTop: 2 }}>Discovered: {ts(e.start)}</div>
                        {e.desc && <div style={{ fontSize: 10, color: "#ffffff", marginTop: 3, fontStyle: "italic" }}>{e.desc}</div>}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
      <style>{`
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
        button:hover { opacity: 0.8; }
        input:focus, select:focus { border-color: #2a2a5a !important; }
      `}</style>
    </div>
  );
}

window.AOGTracker = AOGTracker;
ReactDOM.createRoot(document.getElementById('aog-root')).render(<AOGTracker />);
