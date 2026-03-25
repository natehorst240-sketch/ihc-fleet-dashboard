/**
 * Calendar event persistence via Azure Blob Storage REST API.
 *
 * Uses only Node.js built-in modules (https, crypto) — no extra npm packages.
 * Events are stored as a JSON array in:
 *   container : fleetcalendar
 *   blob      : notes.json
 *
 * GET    /api/calendar        — list all saved events
 * POST   /api/calendar        — upsert an event (create or update by id)
 * DELETE /api/calendar/{id}   — delete an event
 */

const { app }  = require('@azure/functions');
const https    = require('https');
const crypto   = require('crypto');

const CONTAINER   = 'fleetcalendar';
const BLOB        = 'notes.json';
const API_VERSION = '2020-10-02';

// ── Azure SharedKey auth ───────────────────────────────────────────────────────
function makeAuth(account, key, method, reqHeaders, canonResource) {
  // Build sorted x-ms-* canonicalized headers (each line ends with \n)
  const xms = Object.entries(reqHeaders)
    .filter(([k]) => k.toLowerCase().startsWith('x-ms-'))
    .map(([k, v]) => `${k.toLowerCase()}:${String(v).trim()}`)
    .sort()
    .join('\n') + '\n';

  // Content-Length: skip when 0 (matches Azure SDK behavior)
  const cl = reqHeaders['Content-Length'];
  const clStr = (cl !== undefined && cl !== null && cl !== 0 && cl !== '0') ? String(cl) : '';

  const stringToSign = [
    method.toUpperCase(),
    '',           // Content-Encoding
    '',           // Content-Language
    clStr,        // Content-Length (empty if 0)
    '',           // Content-MD5
    reqHeaders['Content-Type'] || '',
    '',           // Date (empty — using x-ms-date instead)
    '',           // If-Modified-Since
    '',           // If-Match
    '',           // If-None-Match
    '',           // If-Unmodified-Since
    '',           // Range
  ].join('\n') + '\n' + xms + canonResource;

  const sig = crypto
    .createHmac('sha256', Buffer.from(key, 'base64'))
    .update(stringToSign, 'utf8')
    .digest('base64');

  return `SharedKey ${account}:${sig}`;
}

// ── Raw HTTPS helper ──────────────────────────────────────────────────────────
function blobReq(account, method, urlPath, headers, body) {
  return new Promise((resolve, reject) => {
    const req = https.request(
      { hostname: `${account}.blob.core.windows.net`, port: 443, path: urlPath, method, headers },
      res => {
        const chunks = [];
        res.on('data', c => chunks.push(c));
        res.on('end', () => resolve({ status: res.statusCode, body: Buffer.concat(chunks).toString('utf8') }));
      }
    );
    req.on('error', reject);
    if (body) req.write(body);
    req.end();
  });
}

// ── Storage helpers ───────────────────────────────────────────────────────────
async function ensureContainer(account, key) {
  const date = new Date().toUTCString();
  const h = { 'Content-Length': 0, 'x-ms-date': date, 'x-ms-version': API_VERSION };
  h['Authorization'] = makeAuth(account, key, 'PUT', h, `/${account}/${CONTAINER}\nrestype:container`);
  const res = await blobReq(account, 'PUT', `/${CONTAINER}?restype=container`, h);
  if (res.status !== 201 && res.status !== 409) {
    throw new Error(`Create container failed: HTTP ${res.status}: ${res.body}`);
  }
}

async function readEvents(account, key) {
  const date = new Date().toUTCString();
  const h = { 'x-ms-date': date, 'x-ms-version': API_VERSION };
  h['Authorization'] = makeAuth(account, key, 'GET', h, `/${account}/${CONTAINER}/${BLOB}`);
  const res = await blobReq(account, 'GET', `/${CONTAINER}/${BLOB}`, h);
  if (res.status === 404) return [];
  if (res.status !== 200) throw new Error(`Read blob failed: HTTP ${res.status}: ${res.body}`);
  return JSON.parse(res.body);
}

async function writeEvents(account, key, events) {
  await ensureContainer(account, key);
  const body = Buffer.from(JSON.stringify(events, null, 2), 'utf8');
  const date = new Date().toUTCString();
  const h = {
    'Content-Type': 'application/json',
    'Content-Length': body.length,
    'x-ms-blob-type': 'BlockBlob',
    'x-ms-date': date,
    'x-ms-version': API_VERSION,
  };
  h['Authorization'] = makeAuth(account, key, 'PUT', h, `/${account}/${CONTAINER}/${BLOB}`);
  const res = await blobReq(account, 'PUT', `/${CONTAINER}/${BLOB}`, h, body);
  if (res.status < 200 || res.status > 299) {
    throw new Error(`Write blob failed: HTTP ${res.status}: ${res.body}`);
  }
}

// ── Shared helpers ─────────────────────────────────────────────────────────────
function getCredentials() {
  const account = process.env.AZURE_STORAGE_ACCOUNT;
  const key     = process.env.AZURE_STORAGE_KEY;
  if (!account || !key) throw new Error('AZURE_STORAGE_ACCOUNT and AZURE_STORAGE_KEY must be set');
  return { account, key };
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
      const { account, key } = getCredentials();
      const events = await readEvents(account, key);
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
      const { account, key } = getCredentials();
      const events = await readEvents(account, key);
      const idx = events.findIndex(e => e.id === id);
      const event = {
        id, tail: tail || '', intervalLabel: intervalLabel || '', dueDate,
        endDate: endDate || '', note: note || '', color: color || '#29b6f6',
        type: type || 'override', updatedAt: new Date().toISOString()
      };
      if (idx >= 0) events[idx] = event; else events.push(event);
      await writeEvents(account, key, events);
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
      const { account, key } = getCredentials();
      const events = await readEvents(account, key);
      const filtered = events.filter(e => e.id !== id);
      if (filtered.length === events.length) {
        return { status: 404, headers: cors(), body: JSON.stringify({ error: 'Not found' }) };
      }
      await writeEvents(account, key, filtered);
      return { status: 200, headers: cors(), body: JSON.stringify({ ok: true }) };
    } catch (err) {
      context.error('DeleteCalendarEvent error:', err);
      return { status: 500, headers: cors(), body: JSON.stringify({ error: err.message }) };
    }
  }
});
