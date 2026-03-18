// Google Apps Script — AOG Gmail Sync
// Deploy from script.google.com under the Gmail account that receives Veryon emails.
//
// Script Properties required (Project Settings → Script Properties):
//   GITHUB_TOKEN  — Fine-grained PAT with Contents: Read & Write on this repo only
//   GITHUB_REPO   — e.g. "natehull/ihc-fleet-dashboard"
//   GITHUB_BRANCH — e.g. "main"
const GMAIL_QUERY = 'from:(veryon) subject:"New Discrepancy Reported" newer_than:60d';
const CONTENTS_API = 'https://api.github.com/repos/{REPO}/contents/data/aog_status.json';
const RAW_URL      = 'https://raw.githubusercontent.com/{REPO}/{BRANCH}/data/aog_status.json';

// ── Entry point (also the time-trigger target) ─────────────────────────────
function syncAOGEmails() {
  const props  = PropertiesService.getScriptProperties();
  const token  = props.getProperty('GITHUB_TOKEN');
  const repo   = props.getProperty('GITHUB_REPO');
  const branch = props.getProperty('GITHUB_BRANCH') || 'main';

  if (!token || !repo) {
    Logger.log('ERROR: GITHUB_TOKEN and GITHUB_REPO must be set in Script Properties.');
    return;
  }

  // 1. Fetch current aog_status.json from GitHub
  const rawUrl  = RAW_URL.replace('{REPO}', repo).replace('{BRANCH}', branch);
  const rawResp = UrlFetchApp.fetch(rawUrl, { muteHttpExceptions: true });
  let state = { active: [], history: [], lastUpdated: null };
  if (rawResp.getResponseCode() === 200) {
    state = JSON.parse(rawResp.getContentText());
  }

  // 2. Search Gmail for Veryon discrepancy emails
  const threads = GmailApp.search(GMAIL_QUERY, 0, 200);
  let added = 0;
  for (const thread of threads) {
    for (const msg of thread.getMessages()) {
      const event = parseVeryonEmail(msg);
      if (!event) continue;  // not grounded or parse failed
      const inActive  = state.active.find(e => e.discId === event.discId);
      const inHistory = state.history.find(e => e.discId === event.discId);
      if (inActive || inHistory) continue;  // already known
      state.active.push(event);
      added++;
    }
  }

  Logger.log('New AOG events found: ' + added);
  if (added === 0) return;

  // 3. Commit updated aog_status.json to GitHub
  state.lastUpdated = new Date().toISOString();
  const content = Utilities.base64Encode(
    Utilities.newBlob(JSON.stringify(state, null, 2)).getBytes()
  );
  const apiUrl  = CONTENTS_API.replace('{REPO}', repo);
  const headers = {
    Authorization: 'token ' + token,
    Accept: 'application/vnd.github+json',
    'Content-Type': 'application/json'
  };

  // GitHub requires the current file SHA to update
  const shaResp = UrlFetchApp.fetch(apiUrl + '?ref=' + branch, {
    headers, muteHttpExceptions: true
  });
  const sha = shaResp.getResponseCode() === 200
    ? JSON.parse(shaResp.getContentText()).sha
    : null;

  const payload = {
    message: 'AOG update: ' + state.lastUpdated,
    content,
    branch
  };
  if (sha) payload.sha = sha;

  const putResp = UrlFetchApp.fetch(apiUrl, {
    method: 'put',
    headers,
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  });

  Logger.log('GitHub response: ' + putResp.getResponseCode());
  Logger.log('Committed ' + added + ' new AOG event(s).');
}

// ── Debug helper — run this once to diagnose a "0 events" result ──────────
function debugAOG() {
  const threads = GmailApp.search(GMAIL_QUERY, 0, 5);
  Logger.log('Threads found: ' + threads.length);
  if (!threads.length) {
    Logger.log('Try a broader query — check sender address and subject line in Gmail.');
    return;
  }
  const msg  = threads[0].getMessages()[0];
  const text = msg.getBody()
    .replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');

  Logger.log('Subject: ' + msg.getSubject());
  Logger.log('From: ' + msg.getFrom());
  Logger.log('--- Stripped body (first 1000 chars) ---');
  Logger.log(text.substring(0, 1000));
  Logger.log('--- Regex checks ---');
  Logger.log('Grounded:    ' + /Aircraft Grounded\s+Yes/i.test(text));
  Logger.log('Tail:        ' + JSON.stringify(text.match(/\bAircraft\s+(N\d{3}HC)\b/i)));
  Logger.log('DiscId:      ' + JSON.stringify(text.match(/Non-Routine Maintenance\s+(\d{14})/i)));
  Logger.log('Description: ' + JSON.stringify(text.match(/Description\s+(.{5,100}?)\s+Aircraft Grounded/i)));
  Logger.log('Hours:       ' + JSON.stringify(text.match(/Reported Hours\s+([\d.]+)/i)));
  Logger.log('Landings:    ' + JSON.stringify(text.match(/Reported Landings\s+(\d+)/i)));
}

// ── Email parser ───────────────────────────────────────────────────────────
function parseVeryonEmail(msg) {
  // Strip HTML tags and entities to get clean plain text for reliable matching
  const text = msg.getBody()
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ');

  // Only process grounded aircraft
  if (!/Aircraft Grounded\s+Yes/i.test(text)) return null;

  // Tail number: "Aircraft N281HC" (won't match "Aircraft Grounded")
  const tailMatch = text.match(/\bAircraft\s+(N\d{3}HC)\b/i);
  if (!tailMatch) return null;

  // Discrepancy ID: "Non-Routine Maintenance 20260317084159"
  const discMatch = text.match(/Non-Routine Maintenance\s+(\d{14})/i);
  if (!discMatch) return null;

  // Description: text between "Description" and "Aircraft Grounded"
  const descMatch = text.match(/Description\s+(.{5,400?}?)\s+Aircraft Grounded/i);
  const desc = descMatch ? descMatch[1].trim() : '';

  // Reported Hours / Landings
  const hoursMatch = text.match(/Reported Hours\s+([\d.]+)/i);
  const landMatch  = text.match(/Reported Landings\s+(\d+)/i);

  return {
    id:               'email-' + discMatch[1],
    tail:             tailMatch[1],
    desc,
    discId:           discMatch[1],
    start:            msg.getDate().toISOString(),
    reportedHours:    hoursMatch ? hoursMatch[1] : null,
    reportedLandings: landMatch  ? landMatch[1]  : null,
    source:           'email',
    end:              null,
    duration:         null
  };
}
