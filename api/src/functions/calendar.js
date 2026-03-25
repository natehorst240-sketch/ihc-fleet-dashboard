/**
 * Calendar event persistence via Azure Blob Storage.
 *
 * All events are stored as a JSON array in a single blob:
 *   container: fleetcalendar
 *   blob:      notes.json
 *
 * GET    /api/calendar          — list all saved events
 * POST   /api/calendar          — upsert an event (create or update by id)
 * DELETE /api/calendar/{id}     — delete an event
 */

const { app }                                            = require('@azure/functions');
const { BlobServiceClient, StorageSharedKeyCredential } = require('@azure/storage-blob');

const CONTAINER = 'fleetcalendar';
const BLOB      = 'notes.json';

function getContainerClient() {
  const account = process.env.AZURE_STORAGE_ACCOUNT;
  const key     = process.env.AZURE_STORAGE_KEY;
  if (!account || !key) throw new Error('AZURE_STORAGE_ACCOUNT and AZURE_STORAGE_KEY must be set');
  const credential = new StorageSharedKeyCredential(account, key);
  const blobService = new BlobServiceClient(`https://${account}.blob.core.windows.net`, credential);
  return blobService.getContainerClient(CONTAINER);
}

async function readEvents(containerClient) {
  const blobClient = containerClient.getBlobClient(BLOB);
  try {
    const response = await blobClient.download(0);
    const chunks = [];
    for await (const chunk of response.readableStreamBody) {
      chunks.push(chunk instanceof Buffer ? chunk : Buffer.from(chunk));
    }
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch (err) {
    if (err.statusCode === 404) return [];
    throw err;
  }
}

async function writeEvents(containerClient, events) {
  try { await containerClient.create(); } catch (err) { if (err.statusCode !== 409) throw err; }
  const blobClient = containerClient.getBlockBlobClient(BLOB);
  const content = JSON.stringify(events, null, 2);
  const buf = Buffer.from(content, 'utf8');
  await blobClient.upload(buf, buf.length, {
    blobHTTPHeaders: { blobContentType: 'application/json' },
    overwrite: true
  });
}

function corsHeaders() {
  return {
    'Content-Type': 'application/json',
    'Cache-Control': 'no-store',
    'Access-Control-Allow-Origin': '*'
  };
}

// ── GET /api/calendar ─────────────────────────────────────────────────────────
app.http('GetCalendarEvents', {
  methods: ['GET'],
  route: 'calendar',
  authLevel: 'anonymous',
  handler: async (req, context) => {
    try {
      const events = await readEvents(getContainerClient());
      return { status: 200, headers: corsHeaders(), body: JSON.stringify(events) };
    } catch (err) {
      context.error('GetCalendarEvents error:', err);
      const acct = process.env.AZURE_STORAGE_ACCOUNT || '(not set)';
      return { status: 500, headers: corsHeaders(), body: JSON.stringify({
        error: err.message,
        account: acct,
        url: `https://${acct}.blob.core.windows.net`
      }) };
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
    catch { return { status: 400, headers: corsHeaders(), body: JSON.stringify({ error: 'Invalid JSON' }) }; }

    const { id, tail, intervalLabel, dueDate, endDate, note, color, type } = payload;
    if (!id || !dueDate) {
      return { status: 400, headers: corsHeaders(), body: JSON.stringify({ error: 'id and dueDate are required' }) };
    }

    try {
      const containerClient = getContainerClient();
      const events = await readEvents(containerClient);

      const idx = events.findIndex(e => e.id === id);
      const event = {
        id, tail: tail || '', intervalLabel: intervalLabel || '', dueDate,
        endDate: endDate || '', note: note || '', color: color || '#29b6f6',
        type: type || 'override', updatedAt: new Date().toISOString()
      };
      if (idx >= 0) events[idx] = event; else events.push(event);

      await writeEvents(containerClient, events);
      return { status: 200, headers: corsHeaders(), body: JSON.stringify({ ok: true, id }) };
    } catch (err) {
      context.error('UpsertCalendarEvent error:', err);
      return { status: 500, headers: corsHeaders(), body: JSON.stringify({ error: err.message }) };
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
    if (!id) {
      return { status: 400, headers: corsHeaders(), body: JSON.stringify({ error: 'id is required' }) };
    }

    try {
      const containerClient = getContainerClient();
      const events = await readEvents(containerClient);
      const filtered = events.filter(e => e.id !== id);
      if (filtered.length === events.length) {
        return { status: 404, headers: corsHeaders(), body: JSON.stringify({ error: 'Not found' }) };
      }
      await writeEvents(containerClient, filtered);
      return { status: 200, headers: corsHeaders(), body: JSON.stringify({ ok: true }) };
    } catch (err) {
      context.error('DeleteCalendarEvent error:', err);
      return { status: 500, headers: corsHeaders(), body: JSON.stringify({ error: err.message }) };
    }
  }
});
