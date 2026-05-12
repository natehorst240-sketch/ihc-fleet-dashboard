/**
 * Aircraft Watch List notes via GitHub Gist.
 *
 * Notes for each aircraft tail are stored in the same Gist as calendar notes,
 * in a separate file: fleet-watchlist-notes.json
 *
 * GET    /api/watchlist?tail={tail}  — list notes for an aircraft
 * POST   /api/watchlist              — add a note { id, tail, note }
 * DELETE /api/watchlist/{id}         — delete a note by id
 */

const { app } = require('@azure/functions');
const https   = require('https');

const GIST_FILE = 'fleet-watchlist-notes.json';

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

async function readAll(token, gistId) {
  const res = await ghRequest('GET', `/gists/${gistId}`, token);
  if (res.status !== 200) throw new Error(`Gist read failed: HTTP ${res.status}: ${res.body.slice(0, 300)}`);
  let gist;
  try { gist = JSON.parse(res.body); }
  catch { throw new Error(`Gist response not JSON (HTTP ${res.status})`); }
  const file = gist.files[GIST_FILE];
  if (!file) return [];
  try { const d = JSON.parse(file.content); return Array.isArray(d) ? d : []; } catch { return []; }
}

async function writeAll(token, gistId, notes) {
  const res = await ghRequest('PATCH', `/gists/${gistId}`, token, {
    files: { [GIST_FILE]: { content: JSON.stringify(notes, null, 2) } }
  });
  if (res.status !== 200) throw new Error(`Gist write failed: HTTP ${res.status}: ${res.body.slice(0, 300)}`);
}

function cors() {
  return { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', 'Access-Control-Allow-Origin': '*' };
}

// ── GET /api/watchlist?tail={tail} ────────────────────────────────────────────
app.http('GetWatchlistNotes', {
  methods: ['GET'],
  route: 'watchlist',
  authLevel: 'anonymous',
  handler: async (req, context) => {
    const tail = req.query.get('tail');
    try {
      const { token, gistId } = getConfig();
      const all = await readAll(token, gistId);
      const result = tail ? all.filter(n => n.tail === tail) : all;
      return { status: 200, headers: cors(), body: JSON.stringify(result) };
    } catch (err) {
      context.error('GetWatchlistNotes error:', err);
      return { status: 500, headers: cors(), body: JSON.stringify({ error: err.message }) };
    }
  }
});

// ── POST /api/watchlist ───────────────────────────────────────────────────────
app.http('AddWatchlistNote', {
  methods: ['POST'],
  route: 'watchlist',
  authLevel: 'anonymous',
  handler: async (req, context) => {
    let payload;
    try { payload = await req.json(); }
    catch { return { status: 400, headers: cors(), body: JSON.stringify({ error: 'Invalid JSON' }) }; }

    const { id, tail, note } = payload;
    if (!id || !tail || !note) {
      return { status: 400, headers: cors(), body: JSON.stringify({ error: 'id, tail, and note are required' }) };
    }

    try {
      const { token, gistId } = getConfig();
      const all = await readAll(token, gistId);
      all.push({ id, tail, note: note.slice(0, 1000), timestamp: new Date().toISOString() });
      await writeAll(token, gistId, all);
      const notes = all.filter(n => n.tail === tail);
      return { status: 200, headers: cors(), body: JSON.stringify({ ok: true, id, notes }) };
    } catch (err) {
      context.error('AddWatchlistNote error:', err);
      return { status: 500, headers: cors(), body: JSON.stringify({ error: err.message }) };
    }
  }
});

// ── DELETE /api/watchlist/{id} ────────────────────────────────────────────────
app.http('DeleteWatchlistNote', {
  methods: ['DELETE'],
  route: 'watchlist/{id}',
  authLevel: 'anonymous',
  handler: async (req, context) => {
    const id = req.params.id;
    if (!id) return { status: 400, headers: cors(), body: JSON.stringify({ error: 'id is required' }) };

    try {
      const { token, gistId } = getConfig();
      const all = await readAll(token, gistId);
      const target = all.find(n => n.id === id);
      if (!target) {
        return { status: 404, headers: cors(), body: JSON.stringify({ error: 'Not found' }) };
      }
      const filtered = all.filter(n => n.id !== id);
      await writeAll(token, gistId, filtered);
      const notes = filtered.filter(n => n.tail === target.tail);
      return { status: 200, headers: cors(), body: JSON.stringify({ ok: true, notes }) };
    } catch (err) {
      context.error('DeleteWatchlistNote error:', err);
      return { status: 500, headers: cors(), body: JSON.stringify({ error: err.message }) };
    }
  }
});
