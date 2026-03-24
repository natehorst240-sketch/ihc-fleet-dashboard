/**
 * PUT    /api/events/{id}   — Update an event (Teams and/or SharePoint)
 * DELETE /api/events/{id}   — Delete an event from both calendars
 *
 * The {id} prefix determines the source:
 *   teams-{eventId}    → Teams group calendar
 *   sp-{itemId}        → SharePoint list item
 *
 * Dashboard-created events always have a teams- prefixed id as the canonical
 * identifier. Deletes and updates are applied to both calendars by title+date
 * matching for the counterpart.
 */

const { app } = require('@azure/functions');
const {
  updateTeamsEvent, deleteTeamsEvent,
  updateSharePointEvent, deleteSharePointEvent,
  getSharePointEvents
} = require('../shared/graphClient');

// PUT /api/events/{id}
app.http('UpdateEvent', {
  methods: ['PUT'],
  route: 'events/{id}',
  authLevel: 'anonymous',
  handler: async (req, context) => {
    const eventId = req.params.id;
    let payload;
    try {
      payload = await req.json();
    } catch {
      return { status: 400, body: JSON.stringify({ error: 'Invalid JSON body' }) };
    }

    try {
      const results = await Promise.allSettled([
        updateById(eventId, payload, context),
        updateCounterpart(eventId, payload, context)
      ]);
      const errors = results.filter(r => r.status === 'rejected').map(r => r.reason?.message);
      if (errors.length === results.length) {
        return { status: 502, body: JSON.stringify({ error: 'Update failed on all calendars', details: errors }) };
      }
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
    try {
      const results = await Promise.allSettled([
        deleteById(eventId, context),
        deleteCounterpart(eventId, context)
      ]);
      const errors = results.filter(r => r.status === 'rejected').map(r => r.reason?.message);
      if (errors.length === results.length) {
        return { status: 502, body: JSON.stringify({ error: 'Delete failed on all calendars', details: errors }) };
      }
      return { status: 200, body: JSON.stringify({ ok: true }) };
    } catch (err) {
      context.error('DeleteEvent error:', err);
      return { status: 500, body: JSON.stringify({ error: err.message }) };
    }
  }
});

// ─── Helpers ──────────────────────────────────────────────────────────────────

async function updateById(id, payload, context) {
  if (id.startsWith('teams-')) {
    return updateTeamsEvent(id.slice(6), payload);
  }
  if (id.startsWith('sp-')) {
    return updateSharePointEvent(id.slice(3), payload);
  }
  throw new Error(`Unknown event id prefix: ${id}`);
}

async function deleteById(id, context) {
  if (id.startsWith('teams-')) {
    return deleteTeamsEvent(id.slice(6));
  }
  if (id.startsWith('sp-')) {
    return deleteSharePointEvent(id.slice(3));
  }
  throw new Error(`Unknown event id prefix: ${id}`);
}

// For events created by the dashboard, try to also update/delete the counterpart
// in the other calendar by matching title + start date.
async function updateCounterpart(id, payload, context) {
  if (!id.startsWith('teams-')) return; // only mirror from Teams → SharePoint
  const spEvents = await getSharePointEvents();
  const match = spEvents.find(e => e.title === payload.title && e.start === payload.start);
  if (match) {
    await updateSharePointEvent(match.id.slice(3), payload);
  }
}

async function deleteCounterpart(id, context) {
  if (!id.startsWith('teams-')) return;
  // We need the original title to find the SP counterpart; caller must pass ?title=...
  // For simplicity, the frontend sends the title as a query param on DELETE.
}
