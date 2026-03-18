/**
 * IHC Fleet – AOG Status Sync
 * Google Apps Script  (copy this entire file into a new Apps Script project)
 *
 * SETUP
 * ─────
 * 1. In the Apps Script editor open Extensions → Apps Script (or script.google.com)
 * 2. Paste this file as Code.gs
 * 3. Project Settings → Script Properties → Add:
 *      GITHUB_PAT       – GitHub Personal Access Token (repo scope)
 *      ANTHROPIC_API_KEY – Claude API key (used to parse email bodies)
 * 4. Run syncAOG() once manually to grant Gmail permission
 * 5. Triggers → Add Trigger → syncAOG → Time-driven → Hour timer → Every hour
 *
 * The script will update data/aog_status.json in the repo automatically.
 * No secrets ever touch the browser.
 */

// ── Config ──────────────────────────────────────────────────────────────────
const REPO      = "natehorst240-sketch/ihc-fleet-dashboard";
const FILE_PATH = "data/aog_status.json";
const BRANCH    = "main";

// How far back to search Gmail on each run (overlap prevents gaps).
const LOOK_BACK_HOURS = 25;

// ── Entry point ─────────────────────────────────────────────────────────────
function syncAOG() {
  const props       = PropertiesService.getScriptProperties();
  const githubPat   = props.getProperty("GITHUB_PAT");
  const anthropicKey = props.getProperty("ANTHROPIC_API_KEY");

  if (!githubPat)    throw new Error("GITHUB_PAT not set in Script Properties.");
  if (!anthropicKey) throw new Error("ANTHROPIC_API_KEY not set in Script Properties.");

  // 1. Fetch emails.
  const emails = fetchAOGEmails_();
  Logger.log(`Found ${emails.length} candidate email(s).`);
  if (!emails.length) return;

  // 2. Parse with Claude.
  const parsed = parseEmailsWithClaude_(emails, anthropicKey);
  Logger.log(`Claude returned ${parsed.length} AOG event(s).`);
  if (!parsed.length) return;

  // 3. Load current JSON from GitHub.
  const { data: current, sha } = loadFromGitHub_(githubPat);

  // 4. Merge (skip duplicates by discId).
  const { active, added } = mergeActive_(current.active || [], parsed);
  Logger.log(`${added} new event(s) added.`);
  if (!added) return;

  // 5. Push updated JSON back to GitHub.
  pushToGitHub_(githubPat, sha, {
    active,
    history:     current.history || [],
    lastUpdated: new Date().toISOString(),
  });

  Logger.log("aog_status.json updated successfully.");
}

// ── Gmail ────────────────────────────────────────────────────────────────────
function fetchAOGEmails_() {
  const since = new Date(Date.now() - LOOK_BACK_HOURS * 3600 * 1000);
  const dateStr = Utilities.formatDate(since, "UTC", "yyyy/MM/dd");
  const query = `from:veryon subject:"New AOG Discrepancy Reported" after:${dateStr}`;

  const threads = GmailApp.search(query, 0, 50);
  const emails = [];
  for (const thread of threads) {
    for (const msg of thread.getMessages()) {
      if (msg.getDate() < since) continue;
      emails.push({
        subject:  msg.getSubject(),
        body:     msg.getPlainBody(),
        received: msg.getDate().toISOString(),
      });
    }
  }
  return emails;
}

// ── Claude parsing ───────────────────────────────────────────────────────────
function parseEmailsWithClaude_(emails, apiKey) {
  const emailsText = emails.map((e, i) =>
    `--- EMAIL ${i + 1} ---\nSubject: ${e.subject}\nReceived: ${e.received}\n\n${e.body}`
  ).join("\n\n");

  const systemPrompt = `You parse Veryon Tracking Notification emails about aircraft discrepancies.
For each email where "Aircraft Grounded" is Yes, extract:
  - tail:             Aircraft tail number (format like N251HC)
  - desc:             Discrepancy description (first sentence or up to 80 chars)
  - discId:           Discrepancy ID (14-digit number like 20260312121446)
  - start:            ISO 8601 date/time the email was received
  - reportedHours:    Aircraft total time as a string (e.g. "3326.10"), or null
  - reportedLandings: Aircraft total landings as a string (e.g. "11088"), or null

Respond ONLY with a valid JSON array. If no grounded aircraft, respond with [].
Do not include markdown fences or any explanation.`;

  const body = JSON.stringify({
    model:      "claude-sonnet-4-6",
    max_tokens: 2048,
    system:     systemPrompt,
    messages:   [{ role: "user", content: emailsText }],
  });

  const res = UrlFetchApp.fetch("https://api.anthropic.com/v1/messages", {
    method:  "post",
    headers: {
      "Content-Type":      "application/json",
      "x-api-key":         apiKey,
      "anthropic-version": "2023-06-01",
    },
    payload:            body,
    muteHttpExceptions: true,
  });

  if (res.getResponseCode() !== 200) {
    throw new Error(`Claude API error ${res.getResponseCode()}: ${res.getContentText()}`);
  }

  const text = JSON.parse(res.getContentText())
    .content.filter(b => b.type === "text")
    .map(b => b.text)
    .join("");

  let parsed;
  try {
    parsed = JSON.parse(text.replace(/```json|```/g, "").trim());
  } catch (e) {
    Logger.log("Claude response could not be parsed as JSON:\n" + text);
    return [];
  }

  // Normalise into the shape aog_status.json expects.
  return (Array.isArray(parsed) ? parsed : []).map(e => ({
    id:               `email-${e.discId || Date.now()}`,
    tail:             e.tail,
    desc:             e.desc,
    discId:           String(e.discId || ""),
    start:            e.start,
    reportedHours:    e.reportedHours   || null,
    reportedLandings: e.reportedLandings || null,
    source:           "email",
    end:              null,
    duration:         null,
  }));
}

// ── Merge ────────────────────────────────────────────────────────────────────
function mergeActive_(existing, incoming) {
  const seen = new Set(existing.map(e => e.discId));
  let added = 0;
  const merged = [...existing];
  for (const event of incoming) {
    if (!seen.has(event.discId)) {
      seen.add(event.discId);
      merged.push(event);
      added++;
    }
  }
  return { active: merged, added };
}

// ── GitHub API ───────────────────────────────────────────────────────────────
function loadFromGitHub_(pat) {
  const url = `https://api.github.com/repos/${REPO}/contents/${FILE_PATH}?ref=${BRANCH}`;
  const res = UrlFetchApp.fetch(url, {
    headers:            { Authorization: `Bearer ${pat}`, Accept: "application/vnd.github+json" },
    muteHttpExceptions: true,
  });

  if (res.getResponseCode() === 404) {
    return { data: { active: [], history: [] }, sha: null };
  }
  if (res.getResponseCode() !== 200) {
    throw new Error(`GitHub load failed ${res.getResponseCode()}: ${res.getContentText()}`);
  }

  const json    = JSON.parse(res.getContentText());
  const decoded = Utilities.newBlob(
    Utilities.base64Decode(json.content.replace(/\n/g, ""))
  ).getDataAsString();

  return { data: JSON.parse(decoded), sha: json.sha };
}

function pushToGitHub_(pat, sha, payload) {
  const url     = `https://api.github.com/repos/${REPO}/contents/${FILE_PATH}`;
  const content = Utilities.base64Encode(
    JSON.stringify(payload, null, 2),
    Utilities.Charset.UTF_8
  );

  const body = {
    message: `ci: sync aog_status.json from Gmail [${new Date().toISOString()}]`,
    content,
    branch: BRANCH,
  };
  if (sha) body.sha = sha;

  const res = UrlFetchApp.fetch(url, {
    method:  "put",
    headers: {
      Authorization:  `Bearer ${pat}`,
      Accept:         "application/vnd.github+json",
      "Content-Type": "application/json",
    },
    payload:            JSON.stringify(body),
    muteHttpExceptions: true,
  });

  if (res.getResponseCode() >= 300) {
    throw new Error(`GitHub push failed ${res.getResponseCode()}: ${res.getContentText()}`);
  }
}
