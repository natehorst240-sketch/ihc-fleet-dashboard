/**
 * PUT    /api/events/{id}   — Update a SharePoint event
 * DELETE /api/events/{id}   — Delete a SharePoint event
 *
 * The {id} must be prefixed with sp- (e.g. sp-42).
 * Google Calendar events are read-only and cannot be updated or deleted here.
 */

const { app } = require('@azure/functions');
const { updateSharePointEvent, deleteSharePointEvent } = require('../shared/graphClient');

// PUT /api/events/{id}
app.http('UpdateEvent', {
  methods: ['PUT'],
  route: 'events/{id}',
  authLevel: 'anonymous',
  handler: async (req, context) => {
    const eventId = req.params.id;
    if (!eventId.startsWith('sp-')) {
      return { status: 400, body: JSON.stringify({ error: 'Only sp- prefixed event ids are supported' }) };
    }

    let payload;
    try {
      payload = await req.json();
    } catch {
      return { status: 400, body: JSON.stringify({ error: 'Invalid JSON body' }) };
    }

    try {
      await updateSharePointEvent(eventId.slice(3), payload);
      return { status: 200, body: JSON.stringify({ ok: true }) };
    } catch (err) {
      context.error('UpdateEvent error:', err);
      return { status: 500, body: JSON.stringify({ error: err.message }) };
    }
  }
});

// DELETE /api/events/{id}
app.http('DeleteEvent', {
  methods: ['DELETE'],
  route: 'events/{id}',
  authLevel: 'anonymous',
  handler: async (req, context) => {
    const eventId = req.params.id;
    if (!eventId.startsWith('sp-')) {
      return { status: 400, body: JSON.stringify({ error: 'Only sp- prefixed event ids are supported' }) };
    }

    try {
      await deleteSharePointEvent(eventId.slice(3));
      return { status: 200, body: JSON.stringify({ ok: true }) };
    } catch (err) {
      context.error('DeleteEvent error:', err);
      return { status: 500, body: JSON.stringify({ error: err.message }) };
    }
  }
});
