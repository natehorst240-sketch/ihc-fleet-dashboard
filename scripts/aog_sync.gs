/**
 * IHC Fleet – AOG Status Sync
 * Google Apps Script  (copy this entire file into a new Apps Script project)
 *
 * SETUP
 * ─────
 * 1. Go to script.google.com → New project → paste this file as Code.gs
 * 2. Project Settings → Script Properties → Add:
 *      GITHUB_PAT  – GitHub Personal Access Token (repo scope)
 * 3. Run syncAOG() once manually to grant Gmail permission
 * 4. Triggers → Add Trigger → syncAOG → Time-driven → Hour timer → Every hour
 *
 * The script updates data/aog_status.json in the repo automatically.
 * No secrets ever touch the browser.
 */

// ── Config ───────────────────────────────────────────────────────────────────
const REPO      = "natehorst240-sketch/ihc-fleet-dashboard";
const FILE_PATH = "data/aog_status.json";
const BRANCH    = "main";

// Overlap window prevents gaps between hourly runs.
const LOOK_BACK_HOURS = 25;

// ── Entry point ──────────────────────────────────────────────────────────────
function syncAOG() {
  const pat = PropertiesService.getScriptProperties().getProperty("GITHUB_PAT");
  if (!pat) throw new Error("GITHUB_PAT not set in Script Properties.");

  // 1. Search Gmail for Veryon AOG notifications.
  const emails = fetchAOGEmails_();
  Logger.log(`Found ${emails.length} candidate email(s).`);
  if (!emails.length) return;

  // 2. Parse each email directly — no external API needed.
  const parsed = emails.map(parseVeryonEmail_).filter(Boolean);
  Logger.log(`Parsed ${parsed.length} grounded-aircraft event(s).`);
  if (!parsed.length) return;

  // 3. Load current JSON from GitHub.
  const { data: current, sha } = loadFromGitHub_(pat);

  // 4. Merge, skipping events already tracked by discId.
  const { active, added } = mergeActive_(current.active || [], parsed);
  Logger.log(`${added} new event(s) to add.`);
  if (!added) return;

  // 5. Push updated JSON back to GitHub.
  pushToGitHub_(pat, sha, {
    active,
    history:     current.history || [],
    lastUpdated: new Date().toISOString(),
  });

  Logger.log("aog_status.json updated successfully.");
}

// ── Gmail ────────────────────────────────────────────────────────────────────
function fetchAOGEmails_() {
  const since   = new Date(Date.now() - LOOK_BACK_HOURS * 3600 * 1000);
  const dateStr = Utilities.formatDate(since, "UTC", "yyyy/MM/dd");
  const query   = `from:veryon subject:"New AOG Discrepancy Reported" after:${dateStr}`;

  const threads = GmailApp.search(query, 0, 50);
  const emails  = [];
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

// ── Email parser (Veryon plain-text format) ──────────────────────────────────
/**
 * Veryon "New AOG Discrepancy Reported" emails look roughly like:
 *
 *   Aircraft:           N531HC
 *   Discrepancy ID:     20260312121446
 *   Aircraft Grounded:  Yes
 *   Description:        #1 Engine Chip Detector magnetic prong broken off...
 *   Aircraft TT:        3326.10
 *   Aircraft Landings:  11088
 *
 * Field names and spacing vary slightly — the regexes are intentionally loose.
 */
function parseVeryonEmail_(email) {
  const body = email.body;

  // Must be grounded — skip if not.
  if (!/Aircraft\s+Grounded[^:]*:\s*Yes/i.test(body)) return null;

  // Tail number  e.g. N251HC, N1234AB
  const tailMatch = body.match(/\b(N\d{3,4}[A-Z]{2})\b/);
  if (!tailMatch) return null;
  const tail = tailMatch[1];

  // Discrepancy ID — 14-digit timestamp number Veryon uses as a unique ID.
  const discIdMatch = body.match(/Discrepancy(?:\s+ID)?[^:]*:\s*(\d{12,16})/i)
                   || body.match(/\b(\d{14})\b/);
  const discId = discIdMatch ? discIdMatch[1] : generateFallbackId_(email.received);

  // Description — grab the line after "Description:" (strip trailing whitespace).
  const descMatch = body.match(/Description[^:]*:\s*(.+)/i);
  const desc = descMatch ? descMatch[1].trim().substring(0, 120) : email.subject;

  // Aircraft total time (hours).
  const hoursMatch = body.match(/(?:Aircraft\s+)?(?:Total\s+)?(?:TT|Time)[^:]*:\s*([\d,]+\.?\d*)/i);
  const reportedHours = hoursMatch ? hoursMatch[1].replace(/,/g, "") : null;

  // Aircraft total landings.
  const landMatch = body.match(/(?:Aircraft\s+)?(?:Total\s+)?Landings?[^:]*:\s*([\d,]+)/i);
  const reportedLandings = landMatch ? landMatch[1].replace(/,/g, "") : null;

  return {
    id:               `email-${discId}`,
    tail,
    desc,
    discId,
    start:            email.received,
    reportedHours,
    reportedLandings,
    source:           "email",
    end:              null,
    duration:         null,
  };
}

function generateFallbackId_(isoDate) {
  // Build a 14-digit ID from the received timestamp as a last resort.
  return isoDate.replace(/\D/g, "").substring(0, 14);
}

// ── Merge ────────────────────────────────────────────────────────────────────
function mergeActive_(existing, incoming) {
  const seen = new Set(existing.map(e => e.discId));
  let added  = 0;
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
    branch:  BRANCH,
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
