#!/usr/bin/env node
/**
 * One-time Google Calendar OAuth2 token acquisition.
 * Opens a local browser auth flow and prints the refresh token to copy
 * into Azure Static Web Apps Application Settings.
 *
 * Run this ONCE locally:
 *
 *   node scripts/get-google-refresh-token.js
 *
 * Prerequisites — set up Google Cloud first:
 *   1. Go to https://console.cloud.google.com
 *   2. Create a new project (or select existing)
 *   3. APIs & Services → Library → enable "Google Calendar API"
 *   4. APIs & Services → Credentials → Create Credentials → OAuth client ID
 *      - Application type: Desktop app
 *      - Name: IHC Fleet Dashboard (or anything)
 *   5. Download the JSON → copy client_id and client_secret below
 *   6. APIs & Services → OAuth consent screen
 *      - User type: External (or Internal if Google Workspace)
 *      - Add your Gmail address as a test user
 *      - Scopes: add .../auth/calendar.readonly
 *
 * After running this script, add these three values to Azure SWA
 * Application Settings (portal.azure.com → your SWA → Configuration):
 *   GOOGLE_CLIENT_ID
 *   GOOGLE_CLIENT_SECRET
 *   GOOGLE_REFRESH_TOKEN   ← printed by this script
 */

// ─── FILL THESE IN ────────────────────────────────────────────────────────────
const CLIENT_ID     = process.env.GOOGLE_CLIENT_ID     || 'YOUR_GOOGLE_CLIENT_ID';
const CLIENT_SECRET = process.env.GOOGLE_CLIENT_SECRET || 'YOUR_GOOGLE_CLIENT_SECRET';
// ─────────────────────────────────────────────────────────────────────────────

const http    = require('http');
const https   = require('https');

const REDIRECT_URI = 'http://localhost:8080/oauth2callback';
const SCOPE        = 'https://www.googleapis.com/auth/calendar.readonly';
const AUTH_URL     = 'https://accounts.google.com/o/oauth2/v2/auth';
const TOKEN_URL    = 'https://oauth2.googleapis.com/token';

function buildAuthUrl() {
  const params = new URLSearchParams({
    client_id:     CLIENT_ID,
    redirect_uri:  REDIRECT_URI,
    response_type: 'code',
    scope:         SCOPE,
    access_type:   'offline',
    prompt:        'consent'   // force refresh_token to be returned
  });
  return `${AUTH_URL}?${params}`;
}

function exchangeCode(code) {
  return new Promise((resolve, reject) => {
    const body = new URLSearchParams({
      code,
      client_id:     CLIENT_ID,
      client_secret: CLIENT_SECRET,
      redirect_uri:  REDIRECT_URI,
      grant_type:    'authorization_code'
    }).toString();

    const req = https.request(TOKEN_URL, {
      method: 'POST',
      headers: {
        'Content-Type':   'application/x-www-form-urlencoded',
        'Content-Length': Buffer.byteLength(body)
      }
    }, res => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); } catch { reject(new Error(data)); }
      });
    });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

async function main() {
  if (CLIENT_ID === 'YOUR_GOOGLE_CLIENT_ID' || CLIENT_SECRET === 'YOUR_GOOGLE_CLIENT_SECRET') {
    console.error('\n  Fill in CLIENT_ID and CLIENT_SECRET at the top of this script\n  (or set env vars GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET).\n');
    process.exit(1);
  }

  const authUrl = buildAuthUrl();
  console.log('\n  Open this URL in your browser to authorize Google Calendar access:\n');
  console.log('  ' + authUrl + '\n');
  console.log('  Waiting for redirect on http://localhost:8080 ...\n');

  // Try to open browser automatically (best-effort)
  try {
    const { execSync } = require('child_process');
    const cmd = process.platform === 'darwin' ? 'open'
              : process.platform === 'win32'  ? 'start'
              : 'xdg-open';
    execSync(`${cmd} "${authUrl}"`);
  } catch { /* ignore — user can open manually */ }

  // Start a one-shot local server to capture the OAuth redirect
  const code = await new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      const url  = new URL(req.url, 'http://localhost:8080');
      const code = url.searchParams.get('code');
      const err  = url.searchParams.get('error');

      if (err) {
        res.end('<h1>Authorization failed: ' + err + '</h1>');
        server.close();
        reject(new Error('Authorization failed: ' + err));
        return;
      }

      if (code) {
        res.end('<h1>Authorization complete — you can close this tab.</h1>');
        server.close();
        resolve(code);
      }
    });

    server.listen(8080, () => {});
    server.on('error', reject);
  });

  console.log('  Authorization code received. Exchanging for tokens...\n');

  const tokens = await exchangeCode(code);

  if (!tokens.refresh_token) {
    console.error('  No refresh_token in response. Make sure you:\n' +
      '  1. Used prompt=consent in the auth URL (already handled)\n' +
      '  2. Added your Gmail as a test user in Google OAuth consent screen\n');
    console.error('Response was:', tokens);
    process.exit(1);
  }

  console.log('  Tokens received!\n');
  console.log('  Add these three values to Azure SWA Application Settings:\n');
  console.log('  GOOGLE_CLIENT_ID     =', CLIENT_ID);
  console.log('  GOOGLE_CLIENT_SECRET =', CLIENT_SECRET);
  console.log('  GOOGLE_REFRESH_TOKEN =', tokens.refresh_token);
  console.log('');
}

main().catch(err => { console.error(err); process.exit(1); });
