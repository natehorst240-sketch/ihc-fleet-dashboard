/**
 * Microsoft Graph API client with delegated token management.
 * Uses a stored refresh token to obtain short-lived access tokens,
 * then rotates the refresh token back into Azure Table Storage.
 */

const { getRefreshToken, setRefreshToken } = require('./tokenStore');

const GRAPH_BASE = 'https://graph.microsoft.com/v1.0';
const TOKEN_URL = `https://login.microsoftonline.com/${process.env.AZURE_TENANT_ID}/oauth2/v2.0/token`;
const SCOPES = [
  'https://graph.microsoft.com/Calendars.ReadWrite',
  'https://graph.microsoft.com/Sites.ReadWrite.All',
  'offline_access'
].join(' ');

// Module-level cache to avoid round-tripping Table Storage on every call
// within the same function invocation.
let _cachedAccessToken = null;
let _tokenExpiresAt = 0;

async function getAccessToken() {
  const now = Date.now();
  if (_cachedAccessToken && now < _tokenExpiresAt - 60_000) {
    return _cachedAccessToken;
  }

  const refreshToken = await getRefreshToken();
  if (!refreshToken) {
    throw new Error(
      'No refresh token found in Table Storage. ' +
      'Run scripts/get-refresh-token.js locally and call POST /api/setup-token to seed it.'
    );
  }

  const { default: fetch } = await import('node-fetch');
  const res = await fetch(TOKEN_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'refresh_token',
      client_id: process.env.AZURE_CLIENT_ID,
      refresh_token: refreshToken,
      scope: SCOPES
    }).toString()
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Token refresh failed (${res.status}): ${text}`);
  }

  const data = await res.json();

  // Rotate the refresh token (Microsoft issues a new one each time)
  if (data.refresh_token) {
    await setRefreshToken(data.refresh_token);
  }

  _cachedAccessToken = data.access_token;
  _tokenExpiresAt = now + data.expires_in * 1000;
  return _cachedAccessToken;
}

async function graphFetch(path, options = {}) {
  const { default: fetch } = await import('node-fetch');
  const token = await getAccessToken();
  const res = await fetch(`${GRAPH_BASE}${path}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      ...(options.headers || {})
    }
  });

  if (res.status === 204) return null;
  const text = await res.text();
  if (!res.ok) throw new Error(`Graph ${options.method || 'GET'} ${path} failed (${res.status}): ${text}`);
  return text ? JSON.parse(text) : null;
}

// ─── Teams group calendar ─────────────────────────────────────────────────────

function teamsPath(suffix = '') {
  const groupId = process.env.TEAMS_GROUP_ID;
  if (!groupId) throw new Error('TEAMS_GROUP_ID is not configured');
  return `/groups/${groupId}/calendar/events${suffix}`;
}

async function getTeamsEvents() {
  if (!process.env.TEAMS_GROUP_ID) return [];
  const { value } = await graphFetch(
    teamsPath() + '?$select=id,subject,start,end,isAllDay,body,categories&$top=200'
  );
  return (value || []).map(e => normalizeTeamsEvent(e));
}

async function createTeamsEvent(payload) {
  const body = buildTeamsEventBody(payload);
  const created = await graphFetch(teamsPath(), { method: 'POST', body: JSON.stringify(body) });
  return normalizeTeamsEvent(created);
}

async function updateTeamsEvent(teamsEventId, payload) {
  const body = buildTeamsEventBody(payload);
  const updated = await graphFetch(teamsPath(`/${teamsEventId}`), { method: 'PATCH', body: JSON.stringify(body) });
  return normalizeTeamsEvent(updated);
}

async function deleteTeamsEvent(teamsEventId) {
  await graphFetch(teamsPath(`/${teamsEventId}`), { method: 'DELETE' });
}

function buildTeamsEventBody(payload) {
  return {
    subject: payload.title,
    categories: ['Fleet Dashboard'],
    isAllDay: payload.allDay !== false,
    start: {
      dateTime: payload.allDay !== false ? `${payload.start}T00:00:00` : payload.start,
      timeZone: 'UTC'
    },
    end: {
      dateTime: payload.end
        ? (payload.allDay !== false ? `${payload.end}T00:00:00` : payload.end)
        : (payload.allDay !== false ? `${payload.start}T00:00:00` : payload.start),
      timeZone: 'UTC'
    },
    body: { contentType: 'text', content: payload.noteText || '' }
  };
}

function normalizeTeamsEvent(e) {
  const isFleetNote = (e.categories || []).includes('Fleet Dashboard');
  return {
    id: `teams-${e.id}`,
    title: e.subject,
    start: e.isAllDay ? e.start.dateTime.split('T')[0] : e.start.dateTime,
    end: e.isAllDay ? e.end.dateTime.split('T')[0] : e.end.dateTime,
    allDay: e.isAllDay,
    backgroundColor: isFleetNote ? '#1e3a4a' : '#1B5E20',
    borderColor: isFleetNote ? '#4a9eca' : '#4CAF50',
    extendedProps: {
      type: isFleetNote ? 'note' : 'teams',
      source: 'Teams',
      noteText: e.body?.content || '',
      editable: isFleetNote
    }
  };
}

// ─── SharePoint calendar list ─────────────────────────────────────────────────

function spPath(suffix = '') {
  const siteId = process.env.SHAREPOINT_SITE_ID;
  const listId = process.env.SHAREPOINT_LIST_ID;
  if (!siteId || !listId) throw new Error('SHAREPOINT_SITE_ID / SHAREPOINT_LIST_ID not configured');
  return `/sites/${siteId}/lists/${listId}/items${suffix}`;
}

async function getSharePointEvents() {
  if (!process.env.SHAREPOINT_SITE_ID || !process.env.SHAREPOINT_LIST_ID) return [];
  const { value } = await graphFetch(
    spPath() + '?expand=fields(select=Title,EventDate,EndDate,Description,fAllDayEvent,Category)&$top=200'
  );
  return (value || []).map(item => normalizeSpEvent(item));
}

async function createSharePointEvent(payload) {
  const body = { fields: buildSpFields(payload) };
  const created = await graphFetch(spPath(), { method: 'POST', body: JSON.stringify(body) });
  return normalizeSpEvent(created);
}

async function updateSharePointEvent(spItemId, payload) {
  await graphFetch(spPath(`/${spItemId}/fields`), {
    method: 'PATCH',
    body: JSON.stringify(buildSpFields(payload))
  });
}

async function deleteSharePointEvent(spItemId) {
  await graphFetch(spPath(`/${spItemId}`), { method: 'DELETE' });
}

function buildSpFields(payload) {
  return {
    Title: payload.title,
    EventDate: payload.allDay !== false ? `${payload.start}T00:00:00Z` : payload.start,
    EndDate: payload.end
      ? (payload.allDay !== false ? `${payload.end}T00:00:00Z` : payload.end)
      : (payload.allDay !== false ? `${payload.start}T00:00:00Z` : payload.start),
    fAllDayEvent: payload.allDay !== false,
    Description: payload.noteText || '',
    Category: 'Fleet Dashboard'
  };
}

function normalizeSpEvent(item) {
  const f = item.fields || {};
  const isFleetNote = f.Category === 'Fleet Dashboard';
  const startDate = (f.EventDate || '').split('T')[0];
  const endDate = (f.EndDate || '').split('T')[0];
  return {
    id: `sp-${item.id}`,
    title: f.Title || '(no title)',
    start: startDate,
    end: endDate !== startDate ? endDate : undefined,
    allDay: f.fAllDayEvent !== false,
    backgroundColor: isFleetNote ? '#1e3a4a' : '#0D47A1',
    borderColor: isFleetNote ? '#4a9eca' : '#2196F3',
    extendedProps: {
      type: isFleetNote ? 'note' : 'sharepoint',
      source: 'SharePoint',
      noteText: f.Description || '',
      editable: isFleetNote
    }
  };
}

module.exports = {
  getTeamsEvents, createTeamsEvent, updateTeamsEvent, deleteTeamsEvent,
  getSharePointEvents, createSharePointEvent, updateSharePointEvent, deleteSharePointEvent
};
