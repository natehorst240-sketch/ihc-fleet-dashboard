const { useState, useEffect, useCallback } = React;

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
function dur(ms) {
  if (!ms || ms < 0) return "—";
  const h = Math.floor(ms / 3600000);
  const m = Math.floor((ms % 3600000) / 60000);
  if (h === 0 && m === 0) return "< 1m";
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

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

function AOGTracker() {
  const [active, setActive]     = useState([]);
  const [history, setHistory]   = useState([]);
  const [tab, setTab]           = useState("live");
  const [form, setForm]         = useState({ tail: FLEET[0], desc: "", discId: "" });
  const [adding, setAdding]     = useState(false);
  const [clearing, setClearing] = useState(null);
  const [now, setNow]           = useState(Date.now());
  const [loaded, setLoaded]     = useState(false);
  const [lastSync, setLastSync] = useState(null);
  const [syncing, setSyncing]   = useState(false);
  const [selectedWeek, setSelectedWeek] = useState("current");
  const [savedWeeklyReports, setSavedWeeklyReports] = useState([]);
  const [locallyClearedIds, setLocallyClearedIds] = useState({});

  // Live duration ticker
  useEffect(() => {
    const i = setInterval(() => setNow(Date.now()), 15000);
    return () => clearInterval(i);
  }, []);

  // Load persisted local overrides (cleared events not yet in JSON)
  useEffect(() => {
    async function boot() {
      // First load the remote JSON from the repo
      await fetchJSON();
      // Then overlay any local history stored in persistent storage
      try {
        const [lh, sw, lc] = await Promise.all([
          storage.get("aog:local_history"),
          storage.get("aog:saved_weekly_reports"),
          storage.get("aog:locally_cleared_ids"),
        ]);

        if (lh) {
          const localHistory = JSON.parse(lh.value);
          setHistory(prev => {
            const merged = [...localHistory];
            prev.forEach(h => {
              if (!merged.find(m => m.id === h.id)) merged.push(h);
            });
            return merged.sort((a, b) => new Date(b.end) - new Date(a.end));
          });
        }
        if (sw) setSavedWeeklyReports(JSON.parse(sw.value));
        if (lc) setLocallyClearedIds(JSON.parse(lc.value));
      } catch (e) {}
      setLoaded(true);
    }
    boot();
  }, []);

  // ── FETCH remote JSON written by Apps Script ──────────────────────────────
  async function fetchJSON() {
    setSyncing(true);
    try {
      const res = await fetch(AOG_JSON_URL + "?t=" + Date.now()); // cache-bust
      if (!res.ok) throw new Error("HTTP " + res.status);
      const data = await res.json();
      const remoteHistory = data.history || [];
      const localHistoryRaw = await storage.get("aog:local_history");
      const localClearedRaw = await storage.get("aog:locally_cleared_ids");

      let localHistory = [];
      let localCleared = locallyClearedIds;
      if (localHistoryRaw?.value) localHistory = JSON.parse(localHistoryRaw.value);
      if (localClearedRaw?.value) localCleared = JSON.parse(localClearedRaw.value);

      // Merge remote active with any we already know about locally
      setActive(prev => {
        const merged = [...(data.active || [])].filter(a => !localCleared[a.id]);
        prev.forEach(p => {
          if (!merged.find(m => m.id === p.id) && !localCleared[p.id]) merged.push(p);
        });
        return merged;
      });

      setHistory(prev => {
        const merged = [...remoteHistory];
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

      if (data.lastUpdated) setLastSync(data.lastUpdated);
    } catch (e) {
      console.warn("Could not fetch aog_status.json:", e.message);
    }
    setSyncing(false);
  }

  // ── SAVE local history to persistent storage ──────────────────────────────
  const saveLocalHistory = useCallback(async (h) => {
    try {
      await storage.set("aog:local_history", JSON.stringify(h));
    } catch (e) {}
  }, []);

  const saveLocalClearedIds = useCallback(async (ids) => {
    try {
      await storage.set("aog:locally_cleared_ids", JSON.stringify(ids));
    } catch (e) {}
  }, []);

  // ── MANUAL ADD ────────────────────────────────────────────────────────────
  function addAOG() {
    if (!form.desc.trim()) return;
    const entry = {
      id: "manual-" + Date.now(),
      tail: form.tail,
      desc: form.desc,
      discId: form.discId,
      start: new Date().toISOString(),
      source: "manual",
    };
    setActive(prev => [...prev, entry]);
    setAdding(false);
    setForm({ tail: FLEET[0], desc: "", discId: "" });
  }

  // ── CLEAR AOG (records end time + duration) ───────────────────────────────
  function clearAOG(id) {
    const item = active.find(a => a.id === id);
    if (!item) return;
    const resolved = {
      ...item,
      end: new Date().toISOString(),
      duration: Date.now() - new Date(item.start).getTime(),
    };
    setActive(prev => prev.filter(a => a.id !== id));
    setHistory(prev => {
      const updated = [resolved, ...prev];
      saveLocalHistory(updated);
      return updated;
    });
    setLocallyClearedIds(prev => {
      const updated = { ...prev, [id]: resolved.end };
      saveLocalClearedIds(updated);
      return updated;
    });
    setClearing(null);
  }

  // ── WEEKLY REPORT (full history grouped by week) ─────────────────────────
  const currentWeekKey = weekKey(Date.now());
  const weekEventsByKey = history.reduce((acc, event) => {
    if (!event.end) return acc;
    const key = weekKey(event.end);
    if (!acc[key]) acc[key] = [];
    acc[key].push(event);
    return acc;
  }, {});

  const availableWeeks = Object.keys(weekEventsByKey)
    .sort((a, b) => new Date(b) - new Date(a));

  const effectiveWeekKey = selectedWeek === "current" ? currentWeekKey : selectedWeek;
  const weekEvents = weekEventsByKey[effectiveWeekKey] || [];

  const byTail = FLEET.map(t => {
    const events = weekEvents.filter(e => e.tail === t);
    const totalMs = events.reduce((s, e) => s + (e.duration || 0), 0);
    return { tail: t, count: events.length, totalMs, events };
  }).filter(x => x.count > 0);

  const totalWeekDownMs = byTail.reduce((sum, t) => sum + t.totalMs, 0);

  async function saveWeeklySnapshot() {
    const keyToSave = effectiveWeekKey;
    const snapshot = {
      id: `week-${keyToSave}-${Date.now()}`,
      weekKey: keyToSave,
      savedAt: new Date().toISOString(),
      totalDownMs: totalWeekDownMs,
      aircraft: byTail.map(x => ({
        tail: x.tail,
        count: x.count,
        totalMs: x.totalMs,
      })),
    };

    const next = [snapshot, ...savedWeeklyReports.filter(r => r.weekKey !== keyToSave)];
    setSavedWeeklyReports(next);
    try {
      await storage.set("aog:saved_weekly_reports", JSON.stringify(next));
    } catch (e) {}
  }

  // ── STYLES ────────────────────────────────────────────────────────────────
  const inp = {
    background: "#050509", border: "1px solid #1a1a2e", color: "#c8c8d8",
    padding: "9px 12px", borderRadius: 2, fontFamily: "'Courier New',monospace",
    fontSize: 12, width: "100%", boxSizing: "border-box", outline: "none",
  };
  const btn = (col, bg) => ({
    background: bg || "transparent", border: `1px solid ${col}`, color: col,
    padding: "7px 14px", borderRadius: 2, cursor: "pointer",
    fontFamily: "'Courier New',monospace", fontSize: 10, letterSpacing: 2,
  });

  // ── RENDER ────────────────────────────────────────────────────────────────
  if (!loaded) return (
    <div style={{ background: "#08080f", color: "#333", height: "100vh", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "monospace", fontSize: 11, letterSpacing: 4 }}>
      LOADING FLEET DATA...
    </div>
  );

  return (
    <div style={{ background: "#08080f", minHeight: "100vh", color: "#d0d0e0", fontFamily: "'Courier New',monospace" }}>

      {/* ── HEADER ── */}
      <div style={{ background: "#09090f", borderBottom: "1px solid #111125", padding: "13px 20px", display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{ width: 7, height: 7, borderRadius: "50%", background: active.length ? "#ff2222" : "#22cc55", boxShadow: active.length ? "0 0 10px #ff2222" : "0 0 10px #22cc55", animation: active.length ? "pulse 1.4s infinite" : "none" }} />
        <span style={{ fontSize: 10, letterSpacing: 4, color: "#3a3a5a" }}>IHC FLEET · AOG TRACKER</span>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 12 }}>
          {lastSync && (
            <span style={{ fontSize: 9, color: "#2a2a44", letterSpacing: 1 }}>
              LAST EMAIL SYNC: {ts(lastSync)}
            </span>
          )}
          <button onClick={fetchJSON} disabled={syncing} style={btn("#334466", "#05050f")}>
            {syncing ? "CHECKING..." : "⟳ REFRESH"}
          </button>
          <span style={{ fontSize: 10, letterSpacing: 2, color: active.length ? "#ff4444" : "#33aa55" }}>
            {active.length ? `${active.length} AOG` : "ALL CLEAR"}
          </span>
        </div>
      </div>

      {/* ── ACTIVE AOG BANNERS ── */}
      {active.length > 0 && (
        <div style={{ padding: "14px 20px 0" }}>
          {active.map(a => (
            <div key={a.id} style={{ background: "linear-gradient(135deg,#120000,#0a0005)", border: "1px solid #3d0000", borderLeft: "3px solid #ff2222", borderRadius: 2, padding: "12px 14px", marginBottom: 8 }}>
              <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
                <div style={{ minWidth: 90 }}>
                  <div style={{ fontSize: 22, fontWeight: "bold", color: "#ff3333", letterSpacing: 3, lineHeight: 1 }}>{a.tail}</div>
                  <div style={{ fontSize: 8, color: "#660000", letterSpacing: 3, marginTop: 3 }}>AOG</div>
                  <div style={{ fontSize: 8, color: "#222244", marginTop: 2 }}>{a.source === "email" ? "📧 via email" : "✎ manual"}</div>
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 12, color: "#ffbbbb", marginBottom: 5 }}>{a.desc}</div>
                  {a.discId && <div style={{ fontSize: 9, color: "#442222", letterSpacing: 1 }}>DISCREPANCY {a.discId}</div>}
                  {a.reportedHours && <div style={{ fontSize: 9, color: "#332222", marginTop: 2 }}>AIRFRAME HRS: {a.reportedHours} · LANDINGS: {a.reportedLandings}</div>}
                </div>
                <div style={{ textAlign: "right", minWidth: 130 }}>
                  <div style={{ fontSize: 8, color: "#442222", letterSpacing: 2, marginBottom: 3 }}>GROUNDED SINCE</div>
                  <div style={{ fontSize: 10, color: "#aa4444" }}>{ts(a.start)}</div>
                  <div style={{ fontSize: 17, color: "#ff5555", fontWeight: "bold", marginTop: 5 }}>
                    {dur(now - new Date(a.start).getTime())}
                  </div>
                </div>
              </div>
              <div style={{ marginTop: 10, borderTop: "1px solid #1a0000", paddingTop: 10, display: "flex", gap: 8, justifyContent: "flex-end" }}>
                {clearing === a.id ? (
                  <>
                    <span style={{ fontSize: 10, color: "#666", alignSelf: "center" }}>Confirm returned to service?</span>
                    <button onClick={() => clearAOG(a.id)} style={btn("#44cc44", "#001a00")}>✓ CONFIRM CLEAR</button>
                    <button onClick={() => setClearing(null)} style={btn("#333")}>CANCEL</button>
                  </>
                ) : (
                  <button onClick={() => setClearing(a.id)} style={btn("#44cc44", "#001500")}>CLEAR AOG</button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── TABS ── */}
      <div style={{ padding: "14px 20px 0", display: "flex", gap: 2, borderBottom: "1px solid #0e0e1e" }}>
        {[["live", `LIVE (${active.length})`], ["history", "HISTORY"], ["weekly", "WEEKLY REPORT"]].map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)} style={{ background: "transparent", border: "none", borderBottom: tab === k ? "2px solid #ff3333" : "2px solid transparent", color: tab === k ? "#cc3333" : "#2a2a44", padding: "7px 14px 9px", cursor: "pointer", fontFamily: "'Courier New',monospace", fontSize: 10, letterSpacing: 2 }}>
            {label}
          </button>
        ))}
        <div style={{ flex: 1 }} />
        <button onClick={() => setAdding(v => !v)} style={{ ...btn("#ff3333", "#0d0000"), marginBottom: 8 }}>
          {adding ? "CANCEL" : "+ MANUAL AOG"}
        </button>
      </div>

      {/* ── BODY ── */}
      <div style={{ padding: "14px 20px" }}>

        {/* Manual add form */}
        {adding && (
          <div style={{ background: "#090912", border: "1px solid #1a1a2e", borderRadius: 2, padding: 14, marginBottom: 14 }}>
            <div style={{ fontSize: 9, letterSpacing: 4, color: "#333355", marginBottom: 10 }}>MANUAL AOG ENTRY</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 8 }}>
              <div>
                <div style={{ fontSize: 9, color: "#333355", letterSpacing: 2, marginBottom: 4 }}>TAIL</div>
                <select value={form.tail} onChange={e => setForm({ ...form, tail: e.target.value })} style={{ ...inp, appearance: "none" }}>
                  {FLEET.map(t => <option key={t}>{t}</option>)}
                </select>
              </div>
              <div>
                <div style={{ fontSize: 9, color: "#333355", letterSpacing: 2, marginBottom: 4 }}>DISCREPANCY ID</div>
                <input placeholder="20260311161810" value={form.discId} onChange={e => setForm({ ...form, discId: e.target.value })} style={inp} />
              </div>
            </div>
            <div style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 9, color: "#333355", letterSpacing: 2, marginBottom: 4 }}>DESCRIPTION</div>
              <input placeholder="Broken roller on left sliding door" value={form.desc} onChange={e => setForm({ ...form, desc: e.target.value })} style={inp} onKeyDown={e => e.key === "Enter" && addAOG()} />
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button onClick={addAOG} disabled={!form.desc.trim()} style={{ ...btn("#ff3333", "#150000"), opacity: form.desc.trim() ? 1 : 0.4 }}>
                CONFIRM AOG
              </button>
            </div>
          </div>
        )}

        {/* Live: empty state */}
        {tab === "live" && !active.length && !adding && (
          <div style={{ textAlign: "center", padding: "60px 0", color: "#1a1a2a", fontSize: 11, letterSpacing: 4 }}>
            <div style={{ fontSize: 30, marginBottom: 10, color: "#1a331a" }}>✓</div>
            NO ACTIVE AOG EVENTS
            <div style={{ marginTop: 8, fontSize: 9, color: "#111122" }}>
              Auto-updates every 5 min via Google Apps Script · Gmail → GitHub → here
            </div>
          </div>
        )}

        {/* History tab */}
        {tab === "history" && (
          <div>
            {!history.length && <div style={{ textAlign: "center", padding: "60px 0", color: "#1a1a2a", fontSize: 11, letterSpacing: 4 }}>NO CLEARED AOG EVENTS YET</div>}
            {history.map(h => (
              <div key={h.id} style={{ border: "1px solid #111122", borderRadius: 2, padding: "10px 12px", marginBottom: 6, display: "flex", alignItems: "center", gap: 12 }}>
                <div style={{ minWidth: 78, fontSize: 14, fontWeight: "bold", color: "#44405a", letterSpacing: 2 }}>{h.tail}</div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 11, color: "#3a3a55" }}>{h.desc}</div>
                  {h.discId && <div style={{ fontSize: 9, color: "#222233", marginTop: 2 }}>#{h.discId}</div>}
                </div>
                <div style={{ textAlign: "right", fontSize: 10 }}>
                  <div style={{ color: "#2a2a44" }}>{ts(h.start)}</div>
                  <div style={{ color: "#2a2a44" }}>→ {ts(h.end)}</div>
                  <div style={{ color: "#44aa55", fontWeight: "bold", marginTop: 3, fontSize: 12 }}>↓ {dur(h.duration)}</div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Weekly report tab */}
        {tab === "weekly" && (
          <div>
            <div style={{ fontSize: 9, letterSpacing: 4, color: "#333355", marginBottom: 14 }}>
              WEEK-BY-WEEK OUT OF SERVICE REPORT · {weekRangeLabel(effectiveWeekKey)}
            </div>
            {/* Week controls */}
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 12, flexWrap: "wrap" }}>
              <select value={selectedWeek} onChange={e => setSelectedWeek(e.target.value)} style={{ ...inp, maxWidth: 320 }}>
                <option value="current">Current week ({weekRangeLabel(currentWeekKey)})</option>
                {availableWeeks.map(w => (
                  <option key={w} value={w}>{weekRangeLabel(w)}</option>
                ))}
              </select>
              <button onClick={saveWeeklySnapshot} style={btn("#225588", "#000b1a")}>SAVE THIS WEEK REPORT</button>
              {savedWeeklyReports.find(r => r.weekKey === effectiveWeekKey) && (
                <span style={{ fontSize: 9, color: "#335577", letterSpacing: 1 }}>
                  Saved snapshot exists for this week.
                </span>
              )}
            </div>

            {!byTail.length && <div style={{ textAlign: "center", padding: "60px 0", color: "#1a1a2a", fontSize: 11, letterSpacing: 4 }}>NO AOG EVENTS FOR THIS WEEK</div>}

            {/* Fleet summary row */}
            {byTail.length > 0 && (
              <div style={{ border: "1px solid #1a1a2e", borderRadius: 2, padding: "10px 14px", marginBottom: 14, display: "flex", gap: 16, flexWrap: "wrap" }}>
                <span style={{ fontSize: 9, color: "#333355", letterSpacing: 3, alignSelf: "center" }}>FLEET SUMMARY</span>
                <span style={{ fontSize: 10, color: "#44aa77" }}>TOTAL DOWN: <strong>{dur(totalWeekDownMs)}</strong></span>
                {byTail.map(x => (
                  <span key={x.tail} style={{ fontSize: 10, color: "#ffaa44" }}>
                    {x.tail}: <strong>{dur(x.totalMs)}</strong>
                  </span>
                ))}
              </div>
            )}

            {savedWeeklyReports.length > 0 && (
              <div style={{ border: "1px solid #142033", borderRadius: 2, padding: "10px 14px", marginBottom: 14 }}>
                <div style={{ fontSize: 9, color: "#335577", letterSpacing: 3, marginBottom: 6 }}>SAVED WEEKLY SNAPSHOTS</div>
                {savedWeeklyReports.slice(0, 6).map(r => (
                  <div key={r.id} style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: "#2a3a55", padding: "2px 0" }}>
                    <span>{weekRangeLabel(r.weekKey)}</span>
                    <span>SAVED {ts(r.savedAt)} · DOWN {dur(r.totalDownMs)}</span>
                  </div>
                ))}
              </div>
            )}

            {byTail.map(x => (
              <div key={x.tail} style={{ background: "#090912", border: "1px solid #111122", borderRadius: 2, padding: "12px 14px", marginBottom: 8 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                  <span style={{ fontSize: 17, fontWeight: "bold", color: "#6666aa", letterSpacing: 2 }}>{x.tail}</span>
                  <span style={{ fontSize: 9, color: "#333355", letterSpacing: 2 }}>{x.count} EVENT{x.count !== 1 ? "S" : ""}</span>
                  <span style={{ marginLeft: "auto", fontSize: 13, color: "#ffaa44", fontWeight: "bold" }}>
                    {dur(x.totalMs)} DOWN
                  </span>
                </div>
                {x.events.map(e => (
                  <div key={e.id} style={{ fontSize: 10, color: "#2a2a44", borderTop: "1px solid #0e0e1e", padding: "6px 0" }}>
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                      <span>{ts(e.start)}</span>
                      <span style={{ color: "#1a1a2a" }}>→</span>
                      <span>{ts(e.end)}</span>
                      <span style={{ marginLeft: "auto", color: "#44aa55", fontWeight: "bold" }}>{dur(e.duration)}</span>
                    </div>
                    {e.desc && <div style={{ fontSize: 9, color: "#22223a", marginTop: 3, fontStyle: "italic" }}>{e.desc}</div>}
                  </div>
                ))}
              </div>
            ))}
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
