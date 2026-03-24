/**
 * Google Calendar API client (read-only, personal calendar).
 * Uses a stored OAuth2 refresh token — set GOOGLE_CLIENT_ID,
 * GOOGLE_CLIENT_SECRET, and GOOGLE_REFRESH_TOKEN in Azure app settings.
 *
 * Run scripts/get-google-refresh-token.js once locally to obtain the
 * refresh token, then add it to Azure Static Web Apps environment variables.
 *
 * Unlike Microsoft, Google does NOT rotate refresh tokens, so we just keep
 * the original value and only cache the short-lived access token.
 */

const GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token';
const GCAL_BASE = 'https://www.googleapis.com/calendar/v3';

// Fetch events this far into the past and future
const WINDOW_MONTHS_PAST   = 3;
const WINDOW_MONTHS_FUTURE = 6;

// Module-level access-token cache (reused within a single function invocation)
let _cachedAccessToken = null;
let _tokenExpiresAt    = 0;

async function getAccessToken() {
  const now = Date.now();
  if (_cachedAccessToken && now < _tokenExpiresAt - 60_000) {
    return _cachedAccessToken;
  }

  const { GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN } = process.env;
  if (!GOOGLE_REFRESH_TOKEN) {
    throw new Error(
      'GOOGLE_REFRESH_TOKEN is not configured. ' +
      'Run scripts/get-google-refresh-token.js locally to obtain one.'
    );
  }

  const { default: fetch } = await import('node-fetch');
  const res = await fetch(GOOGLE_TOKEN_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type:    'refresh_token',
      client_id:     GOOGLE_CLIENT_ID,
      client_secret: GOOGLE_CLIENT_SECRET,
      refresh_token: GOOGLE_REFRESH_TOKEN
    }).toString()
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Google token refresh failed (${res.status}): ${text}`);
  }

  const data = await res.json();
  _cachedAccessToken = data.access_token;
  _tokenExpiresAt    = now + data.expires_in * 1000;
  return _cachedAccessToken;
}

async function getGoogleCalendarEvents() {
  if (!process.env.GOOGLE_REFRESH_TOKEN) return [];

  const { default: fetch } = await import('node-fetch');
  const token = await getAccessToken();

  const now  = new Date();
  const past = new Date(now); past.setMonth(past.getMonth() - WINDOW_MONTHS_PAST);
  const fwd  = new Date(now); fwd.setMonth(fwd.getMonth()  + WINDOW_MONTHS_FUTURE);

  const params = new URLSearchParams({
    maxResults:    '500',
    singleEvents:  'true',
    orderBy:       'startTime',
    timeMin:       past.toISOString(),
    timeMax:       fwd.toISOString()
  });

  const res = await fetch(`${GCAL_BASE}/calendars/primary/events?${params}`, {
    headers: { Authorization: `Bearer ${token}` }
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Google Calendar fetch failed (${res.status}): ${text}`);
  }

  const data = await res.json();
  return (data.items || [])
    .filter(e => e.status !== 'cancelled')
    .map(normalizeGoogleEvent);
}

function normalizeGoogleEvent(e) {
  const isAllDay = !!(e.start && e.start.date);
  return {
    id:              `gcal-${e.id}`,
    title:           e.summary || '(no title)',
    start:           isAllDay ? e.start.date : e.start.dateTime,
    end:             isAllDay ? e.end.date   : e.end.dateTime,
    allDay:          isAllDay,
    backgroundColor: '#1f2d1a',
    borderColor:     '#34A853',
    extendedProps: {
      type:     'google',
      source:   'Google Calendar',
      noteText: e.description || '',
      editable: false
    }
  };
}

module.exports = { getGoogleCalendarEvents };
