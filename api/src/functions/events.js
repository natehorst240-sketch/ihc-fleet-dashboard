/**
 * GET /api/events — Returns Google Calendar events
 */

const { app } = require('@azure/functions');
const { getGoogleCalendarEvents } = require('../shared/googleCalendarClient');

app.http('GetEvents', {
  methods: ['GET'],
  route: 'events',
  authLevel: 'anonymous',
  handler: async (req, context) => {
    try {
      const events = await getGoogleCalendarEvents().catch(err => {
        context.warn('Google Calendar fetch failed:', err.message);
        return [];
      });

      return {
        status: 200,
        headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
        body: JSON.stringify(events)
      };
    } catch (err) {
      context.error('GetEvents error:', err);
      return { status: 500, body: JSON.stringify({ error: err.message }) };
    }
  }
});
