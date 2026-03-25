/**
 * Calendar event persistence via GitHub Gist.
 *
 * All events are stored as a JSON array in a secret GitHub Gist file:
 *   fleet-calendar-notes.json
 *
 * Requires env vars:
 *   CALENDAR_GITHUB_TOKEN  — GitHub PAT with "gist" scope
 *   CALENDAR_GIST_ID       — ID of the secret gist (from gist URL)
 *
 * GET    /api/calendar        — list all saved events
 * POST   /api/calendar        — upsert an event (create or update by id)
 * DELETE /api/calendar/{id}   — delete an event
 */

const { app } = require('@azure/functions');
const https   = require('https');

const GIST_FILE = 'fleet-calendar-notes.json';

function getConfig() {
  const token  = process.env.CALENDAR_GITHUB_TOKEN;
  const gistId = process.env.CALENDAR_GIST_ID;
  if (!token || !gistId) throw new Error('CALENDAR_GITHUB_TOKEN and CALENDAR_GIST_ID must be set');
  return { token, gistId };
}

function ghRequest(method, path, token, body) {
  return new Promise((resolve, reject) => {
    const bodyBuf = body ? Buffer.from(JSON.stringify(body), 'utf8') : null;
    const headers = {
      'Authorization': `token ${token}`,
      'User-Agent': 'IHC-Fleet-Dashboard',
      'Accept': 'application/vnd.github.v3+json',
    };
    if (bodyBuf) {
      headers['Content-Type']   = 'application/json';
      headers['Content-Length'] = bodyBuf.length;
    }
    const req = https.request(
      { hostname: 'api.github.com', port: 443, path, method, headers },
      res => {
        const chunks = [];
        res.on('data', c => chunks.push(c));
        res.on('end', () => resolve({ status: res.statusCode, body: Buffer.concat(chunks).toString('utf8') }));
      }
    );
    req.on('error', reject);
    if (bodyBuf) req.write(bodyBuf);
    req.end();
  });
}

async function readEvents(token, gistId) {
  const res = await ghRequest('GET', `/gists/${gistId}`, token);
  if (res.status !== 200) throw new Error(`Gist read failed: HTTP ${res.status}: ${res.body.slice(0, 300)}`);
  const gist = JSON.parse(res.body);
  const file = gist.files[GIST_FILE];
  if (!file) return [];
  try { return JSON.parse(file.content); } catch { return []; }
}

async function writeEvents(token, gistId, events) {
  const res = await ghRequest('PATCH', `/gists/${gistId}`, token, {
    files: { [GIST_FILE]: { content: JSON.stringify(events, null, 2) } }
  });
  if (res.status !== 200) throw new Error(`Gist write failed: HTTP ${res.status}: ${res.body.slice(0, 300)}`);
}

function cors() {
  return { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', 'Access-Control-Allow-Origin': '*' };
}

// ── GET /api/calendar ─────────────────────────────────────────────────────────
app.http('GetCalendarEvents', {
  methods: ['GET'],
  route: 'calendar',
  authLevel: 'anonymous',
  handler: async (req, context) => {
    try {
      const { token, gistId } = getConfig();
      const events = await readEvents(token, gistId);
      return { status: 200, headers: cors(), body: JSON.stringify(events) };
    } catch (err) {
      context.error('GetCalendarEvents error:', err);
      return { status: 500, headers: cors(), body: JSON.stringify({ error: err.message }) };
    }
  }
});

// ── POST /api/calendar ────────────────────────────────────────────────────────
app.http('UpsertCalendarEvent', {
  methods: ['POST'],
  route: 'calendar',
  authLevel: 'anonymous',
  handler: async (req, context) => {
    let payload;
    try { payload = await req.json(); }
    catch { return { status: 400, headers: cors(), body: JSON.stringify({ error: 'Invalid JSON' }) }; }

    const { id, tail, intervalLabel, dueDate, endDate, note, color, type } = payload;
    if (!id || !dueDate) {
      return { status: 400, headers: cors(), body: JSON.stringify({ error: 'id and dueDate are required' }) };
    }

    try {
      const { token, gistId } = getConfig();
      const events = await readEvents(token, gistId);
      const idx = events.findIndex(e => e.id === id);
      const event = {
        id, tail: tail || '', intervalLabel: intervalLabel || '', dueDate,
        endDate: endDate || '', note: note || '', color: color || '#29b6f6',
        type: type || 'override', updatedAt: new Date().toISOString()
      };
      if (idx >= 0) events[idx] = event; else events.push(event);
      await writeEvents(token, gistId, events);
      return { status: 200, headers: cors(), body: JSON.stringify({ ok: true, id }) };
    } catch (err) {
      context.error('UpsertCalendarEvent error:', err);
      return { status: 500, headers: cors(), body: JSON.stringify({ error: err.message }) };
    }
  }
});

// ── DELETE /api/calendar/{id} ─────────────────────────────────────────────────
app.http('DeleteCalendarEvent', {
  methods: ['DELETE'],
  route: 'calendar/{id}',
  authLevel: 'anonymous',
  handler: async (req, context) => {
    const id = req.params.id;
    if (!id) return { status: 400, headers: cors(), body: JSON.stringify({ error: 'id is required' }) };

    try {
      const { token, gistId } = getConfig();
      const events = await readEvents(token, gistId);
      const filtered = events.filter(e => e.id !== id);
      if (filtered.length === events.length) {
        return { status: 404, headers: cors(), body: JSON.stringify({ error: 'Not found' }) };
      }
      await writeEvents(token, gistId, filtered);
      return { status: 200, headers: cors(), body: JSON.stringify({ ok: true }) };
    } catch (err) {
      context.error('DeleteCalendarEvent error:', err);
      return { status: 500, headers: cors(), body: JSON.stringify({ error: err.message }) };
    }
  }
});
