/**
 * GET  /api/events         — Returns merged SharePoint + Google Calendar events
 * POST /api/events         — Creates an event in SharePoint
 * POST /api/setup-token    — Seeds the initial refresh token (run once after get-refresh-token.js)
 */

const { app } = require('@azure/functions');
const { setRefreshToken } = require('../shared/tokenStore');
const { getSharePointEvents, createSharePointEvent } = require('../shared/graphClient');
const { getGoogleCalendarEvents } = require('../shared/googleCalendarClient');

// GET /api/events
app.http('GetEvents', {
  methods: ['GET'],
  route: 'events',
  authLevel: 'anonymous',
  handler: async (req, context) => {
    try {
      const [spEvents, googleEvents] = await Promise.all([
        getSharePointEvents().catch(err => {
          context.warn('SharePoint fetch failed:', err.message);
          return [];
        }),
        getGoogleCalendarEvents().catch(err => {
          context.warn('Google Calendar fetch failed:', err.message);
          return [];
        })
      ]);

      const merged = [...spEvents, ...googleEvents];

      return {
        status: 200,
        headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
        body: JSON.stringify(merged)
      };
    } catch (err) {
      context.error('GetEvents error:', err);
      return { status: 500, body: JSON.stringify({ error: err.message }) };
    }
  }
});

// POST /api/events
app.http('CreateEvent', {
  methods: ['POST'],
  route: 'events',
  authLevel: 'anonymous',
  handler: async (req, context) => {
    let payload;
    try {
      payload = await req.json();
    } catch {
      return { status: 400, body: JSON.stringify({ error: 'Invalid JSON body' }) };
    }

    if (!payload.title || !payload.start) {
      return { status: 400, body: JSON.stringify({ error: 'title and start are required' }) };
    }

    try {
      const created = await createSharePointEvent(payload);
      return {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(created)
      };
    } catch (err) {
      context.error('CreateEvent error:', err);
      return { status: 500, body: JSON.stringify({ error: err.message }) };
    }
  }
});

// POST /api/setup-token  — called once by the setup script to seed the refresh token
app.http('SetupToken', {
  methods: ['POST'],
  route: 'setup-token',
  authLevel: 'anonymous',
  handler: async (req, context) => {
    const secret = req.headers.get('x-setup-secret');
    if (!secret || secret !== process.env.SETUP_SECRET) {
      return { status: 401, body: JSON.stringify({ error: 'Unauthorized' }) };
    }

    let body;
    try {
      body = await req.json();
    } catch {
      return { status: 400, body: JSON.stringify({ error: 'Invalid JSON' }) };
    }

    if (!body.refreshToken) {
      return { status: 400, body: JSON.stringify({ error: 'refreshToken is required' }) };
    }

    await setRefreshToken(body.refreshToken);
    context.log('Refresh token seeded successfully');
    return { status: 200, body: JSON.stringify({ ok: true }) };
  }
});
