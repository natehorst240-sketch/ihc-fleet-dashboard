#!/usr/bin/env node
/**
 * One-time Microsoft 365 OAuth2 token acquisition using Device Code Flow.
 *
 * Run this ONCE locally to get a refresh token, then push it to your API:
 *
 *   node scripts/get-refresh-token.js
 *
 * Prerequisites:
 *   npm install node-fetch (or: node >= 18 which has global fetch)
 *
 * What you need first (see SETUP_GUIDE.md for step-by-step):
 *   1. Go to https://portal.azure.com → Microsoft Entra ID → App registrations
 *   2. Click "New registration", name it "IHC Fleet Dashboard"
 *   3. Under "Supported account types" select "Single tenant"
 *   4. No redirect URI needed for device code flow
 *   5. After creating: copy the Application (client) ID and Directory (tenant) ID
 *   6. Under "API permissions":
 *      - Add → Microsoft Graph → Delegated → Sites.ReadWrite.All (needs admin consent)
 *      - Add → Microsoft Graph → Delegated → offline_access
 *   7. Under "Authentication" → Advanced settings → enable "Allow public client flows"
 *   8. Fill in the config below and run this script
 */

// ─── FILL THESE IN ────────────────────────────────────────────────────────────
const TENANT_ID = process.env.AZURE_TENANT_ID || 'YOUR_TENANT_ID';
const CLIENT_ID = process.env.AZURE_CLIENT_ID || 'YOUR_CLIENT_ID';

// URL of your deployed Azure Static Web Apps API
// e.g. https://lemon-glacier-0a1b2c3d.azurestaticapps.net/api/setup-token
const SWA_API_URL = process.env.SWA_API_URL || 'YOUR_SWA_API_URL/api/setup-token';

// A shared secret you set as SETUP_SECRET in Azure SWA Application Settings
const SETUP_SECRET = process.env.SETUP_SECRET || 'YOUR_SETUP_SECRET';
// ─────────────────────────────────────────────────────────────────────────────

const SCOPES = [
  'https://graph.microsoft.com/Sites.ReadWrite.All',
  'offline_access'
].join(' ');

const DEVICE_CODE_URL = `https://login.microsoftonline.com/${TENANT_ID}/oauth2/v2.0/devicecode`;
const TOKEN_URL = `https://login.microsoftonline.com/${TENANT_ID}/oauth2/v2.0/token`;

async function fetchJson(url, opts) {
  const fetchFn = typeof fetch !== 'undefined' ? fetch : (await import('node-fetch')).default;
  const res = await fetchFn(url, opts);
  const text = await res.text();
  try { return JSON.parse(text); } catch { return text; }
}

async function main() {
  if (TENANT_ID === 'YOUR_TENANT_ID' || CLIENT_ID === 'YOUR_CLIENT_ID') {
    console.error('\nFill in TENANT_ID and CLIENT_ID at the top of this script (or set env vars AZURE_TENANT_ID and AZURE_CLIENT_ID).\n');
    process.exit(1);
  }

  console.log('\nRequesting device code...\n');

  const dcResponse = await fetchJson(DEVICE_CODE_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ client_id: CLIENT_ID, scope: SCOPES }).toString()
  });

  if (!dcResponse.device_code) {
    console.error('Failed to get device code:', dcResponse);
    process.exit(1);
  }

  console.log('────────────────────────────────────────────────────────────────');
  console.log(dcResponse.message);
  console.log('────────────────────────────────────────────────────────────────\n');
  console.log('Waiting for you to complete sign-in...\n');

  const interval = (dcResponse.interval || 5) * 1000;
  const expiresAt = Date.now() + dcResponse.expires_in * 1000;
  let tokenResponse;

  while (Date.now() < expiresAt) {
    await new Promise(r => setTimeout(r, interval));

    tokenResponse = await fetchJson(TOKEN_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        grant_type: 'urn:ietf:params:oauth:grant-type:device_code',
        client_id: CLIENT_ID,
        device_code: dcResponse.device_code
      }).toString()
    });

    if (tokenResponse.access_token) break;

    if (tokenResponse.error === 'authorization_pending') {
      process.stdout.write('.');
      continue;
    }

    if (tokenResponse.error === 'authorization_declined') {
      console.error('\nAuthorization was declined.');
      process.exit(1);
    }

    console.error('\nUnexpected error:', tokenResponse);
    process.exit(1);
  }

  if (!tokenResponse?.refresh_token) {
    console.error('\nDid not receive a refresh token. Check that offline_access scope is included.');
    process.exit(1);
  }

  console.log('\n\nGot tokens!\n');

  if (SWA_API_URL === 'YOUR_SWA_API_URL/api/setup-token') {
    console.log('SWA_API_URL not configured — printing token for manual entry:\n');
    console.log('Refresh Token:', tokenResponse.refresh_token);
    console.log('\nStore this as the INITIAL value in Azure Table Storage, or set SWA_API_URL and re-run.\n');
    return;
  }

  console.log(`Pushing refresh token to ${SWA_API_URL}...\n`);
  const setupRes = await fetchJson(SWA_API_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'x-setup-secret': SETUP_SECRET },
    body: JSON.stringify({ refreshToken: tokenResponse.refresh_token })
  });

  if (setupRes.ok) {
    console.log('Refresh token stored successfully. Your API is ready!');
    console.log('\nNext: set these in Azure SWA Application Settings (portal.azure.com):');
    console.log('  AZURE_TENANT_ID                  =', TENANT_ID);
    console.log('  AZURE_CLIENT_ID                  =', CLIENT_ID);
    console.log('  AZURE_STORAGE_CONNECTION_STRING  = (from your storage account)');
    console.log('  SHAREPOINT_SITE_ID               = (from Graph Explorer: /sites/{hostname}:{path})');
    console.log('  SHAREPOINT_LIST_ID               = (from Graph Explorer: /sites/{id}/lists)');
    console.log('  SETUP_SECRET                     = (same value you used above)\n');
  } else {
    console.error('Failed to store token:', setupRes);
  }
}

main().catch(err => { console.error(err); process.exit(1); });
