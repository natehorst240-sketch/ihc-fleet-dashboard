/**
 * Calendar event persistence via Azure Table Storage.
 *
 * Stores user-created notes, inspection date overrides, and custom events
 * so they sync across all computers viewing the dashboard.
 *
 * GET    /api/calendar          — list all saved events
 * POST   /api/calendar          — upsert an event (create or update by id)
 * DELETE /api/calendar/{id}     — delete an event
 */

const { app }         = require('@azure/functions');
const { TableClient } = require('@azure/data-tables');

const TABLE_NAME   = 'fleetCalendarEvents';
const PARTITION    = 'events';

function getClient() {
  const connStr = process.env.AZURE_STORAGE_CONNECTION_STRING;
  if (!connStr) throw new Error('AZURE_STORAGE_CONNECTION_STRING is not set');
  return TableClient.fromConnectionString(connStr, TABLE_NAME);
}

async function ensureTable(client) {
  try { await client.createTable(); }
  catch (err) { if (err.statusCode !== 409) throw err; }
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
      const client = getClient();
      await ensureTable(client);

      const events = [];
      const iter = client.listEntities({ queryOptions: { filter: `PartitionKey eq '${PARTITION}'` } });
      for await (const entity of iter) {
        events.push({
          id:            entity.rowKey,
          tail:          entity.tail          || null,
          intervalLabel: entity.intervalLabel || null,
          dueDate:       entity.dueDate       || null,
          endDate:       entity.endDate       || null,
          note:          entity.note          || '',
          color:         entity.color         || '#29b6f6',
          type:          entity.type          || 'override',
          updatedAt:     entity.updatedAt     || null
        });
      }

      return { status: 200, headers: corsHeaders(), body: JSON.stringify(events) };
    } catch (err) {
      context.error('GetCalendarEvents error:', err);
      return { status: 500, headers: corsHeaders(), body: JSON.stringify({ error: err.message }) };
    }
  }
});

// ── POST /api/calendar ────────────────────────────────────────────────────────
// Body: { id, tail, intervalLabel, dueDate, note, color, type }
// Uses upsert so the same call handles both create and update.
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
      const client = getClient();
      await ensureTable(client);

      const entity = {
        partitionKey:  PARTITION,
        rowKey:        String(id),
        tail:          tail          || '',
        intervalLabel: intervalLabel || '',
        dueDate:       dueDate,
        endDate:       endDate       || '',
        note:          note          || '',
        color:         color         || '#29b6f6',
        type:          type          || 'override',
        updatedAt:     new Date().toISOString()
      };

      await client.upsertEntity(entity, 'Replace');
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
      const client = getClient();
      await ensureTable(client);
      await client.deleteEntity(PARTITION, String(id));
      return { status: 200, headers: corsHeaders(), body: JSON.stringify({ ok: true }) };
    } catch (err) {
      if (err.statusCode === 404) {
        return { status: 404, headers: corsHeaders(), body: JSON.stringify({ error: 'Not found' }) };
      }
      context.error('DeleteCalendarEvent error:', err);
      return { status: 500, headers: corsHeaders(), body: JSON.stringify({ error: err.message }) };
    }
  }
});
