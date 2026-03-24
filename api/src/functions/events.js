/**
 * GET  /api/events         — Returns merged Teams + SharePoint calendar events
 * POST /api/events         — Creates an event in both Teams and SharePoint
 * POST /api/setup-token    — Seeds the initial refresh token (run once after get-refresh-token.js)
 */

const { app } = require('@azure/functions');
const { setRefreshToken } = require('../shared/tokenStore');
const {
  getTeamsEvents, getSharePointEvents,
  createTeamsEvent, createSharePointEvent
} = require('../shared/graphClient');

// GET /api/events
app.http('GetEvents', {
  methods: ['GET'],
  route: 'events',
  authLevel: 'anonymous',
  handler: async (req, context) => {
    try {
      const [teamsEvents, spEvents] = await Promise.all([
        getTeamsEvents().catch(err => {
          context.warn('Teams fetch failed:', err.message);
          return [];
        }),
        getSharePointEvents().catch(err => {
          context.warn('SharePoint fetch failed:', err.message);
          return [];
        })
      ]);

      // Deduplicate: if the same event was created via the dashboard it will
      // appear in both calendars with a matching title + date. Keep the Teams
      // version as canonical and drop the duplicate SharePoint entry.
      const seen = new Set();
      const merged = [];
      for (const ev of teamsEvents) {
        const key = `${ev.title}|${ev.start}`;
        seen.add(key);
        merged.push(ev);
      }
      for (const ev of spEvents) {
        const key = `${ev.title}|${ev.start}`;
        if (!seen.has(key)) merged.push(ev);
      }

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
      // Write to both calendars in parallel; log failures but don't block
      const [teamsResult, spResult] = await Promise.allSettled([
        createTeamsEvent(payload),
        createSharePointEvent(payload)
      ]);

      if (teamsResult.status === 'rejected') {
        context.warn('Teams create failed:', teamsResult.reason?.message);
      }
      if (spResult.status === 'rejected') {
        context.warn('SharePoint create failed:', spResult.reason?.message);
      }

      // Return the Teams event as the canonical ID (used for updates/deletes)
      const created = teamsResult.status === 'fulfilled'
        ? teamsResult.value
        : (spResult.status === 'fulfilled' ? spResult.value : null);

      if (!created) {
        return { status: 502, body: JSON.stringify({ error: 'Failed to write to any calendar' }) };
      }

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
    // Protect with a shared secret to prevent unauthorized token replacement
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
