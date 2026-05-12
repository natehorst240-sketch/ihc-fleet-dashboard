#!/usr/bin/env node
//
// FlightDocs "Work Completed" (component change) report fetcher.
//
// Logs into FlightDocs with Playwright, exports the prior calendar month's
// work-completed report, converts the download to CSV and merges the rows into
// data/ComponentChangeReport_109SP.csv (the file the dashboard generator reads).
//
// It's a JS port of the local "due list" exporter, generalised so the same
// script can drive either report via env vars:
//
//   FLIGHTDOCS_USERNAME / FLIGHTDOCS_USER   (required)
//   FLIGHTDOCS_PASSWORD / FLIGHTDOCS_PASS   (required)
//   FD_REPORT_URL          report URL (default: AW109SP work-completed report).
//                          If it contains LogDate=/LogDateSecondary=, those are
//                          rewritten to the date window below.
//   FD_LOG_DATE            window start  YYYY-MM-DD  (default: first of last month)
//   FD_LOG_DATE_SECONDARY  window end    YYYY-MM-DD  (default: first of this month, exclusive)
//   FD_OUTPUT_PATH         output CSV (default: data/ComponentChangeReport_109SP.csv)
//   FD_MERGE               "false" to overwrite the output instead of dedup-merging
//   FD_LOGIN_URL           login page URL
//   FD_HEADLESS            "false" to run with a visible browser
//   FD_MAX_ATTEMPTS        retry count (default 3)
//
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import XLSX from 'xlsx';

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const LOGIN_URL =
  process.env.FD_LOGIN_URL ||
  process.env.FLIGHTDOCS_LOGIN_URL ||
  'https://auth.flightdocs.com/Account/Login';

const REPORT_URL_TEMPLATE =
  process.env.FD_REPORT_URL ||
  'https://app2.flightdocs.com/#/maintenance/work-completed?LogDateConstraint=2&LogHoursConstraint=1&LogLandingsConstraint=1&LogCyclesConstraint=1&IntervalMonthsConstraint=1&IntervalDaysConstraint=1&IntervalHoursConstraint=1&IntervalLandingsConstraint=1&IntervalCyclesConstraint=1&TimeLtd=false&MaintenanceItemTypeId=1&GroupingCriteria=0&AircraftIds=4345&AircraftIds=4348&AircraftIds=4351&AircraftIds=4353&AircraftIds=4431&AircraftIds=17517&AircraftIds=23110&AircraftIds=34361&AircraftIds=34200&SortProperty=complied&LogRINConstraint=1&IntervalRINConstraint=1&LogDateSecondary=2026-05-01&LogDate=2026-04-01';

const OUTPUT_PATH = path.resolve(
  REPO_ROOT,
  process.env.FD_OUTPUT_PATH || 'data/ComponentChangeReport_109SP.csv',
);

const MERGE = process.env.FD_MERGE !== 'false';
const MAX_ATTEMPTS = Number(process.env.FD_MAX_ATTEMPTS || 3);
const HEADLESS = process.env.FD_HEADLESS !== 'false';

class NonRetryableError extends Error {}

// ---------------------------------------------------------------------------
// Date window: the prior calendar month, [first-of-last-month, first-of-this-month).
// ---------------------------------------------------------------------------
function pad2(n) {
  return String(n).padStart(2, '0');
}

function priorMonthWindow() {
  const now = new Date();
  const y = now.getUTCFullYear();
  const m = now.getUTCMonth(); // 0-based
  const startY = m === 0 ? y - 1 : y;
  const startM = m === 0 ? 12 : m; // 1-based month of "last month"
  return {
    logDate: `${startY}-${pad2(startM)}-01`,
    logDateSecondary: `${y}-${pad2(m + 1)}-01`,
  };
}

const { logDate: defLogDate, logDateSecondary: defLogDateSecondary } = priorMonthWindow();
const LOG_DATE = process.env.FD_LOG_DATE || defLogDate;
const LOG_DATE_SECONDARY = process.env.FD_LOG_DATE_SECONDARY || defLogDateSecondary;

function buildReportUrl() {
  let u = REPORT_URL_TEMPLATE;
  if (/[?&]LogDate=/.test(u)) {
    u = u.replace(/([?&]LogDate=)[^&#]*/, `$1${LOG_DATE}`);
  }
  if (/[?&]LogDateSecondary=/.test(u)) {
    u = u.replace(/([?&]LogDateSecondary=)[^&#]*/, `$1${LOG_DATE_SECONDARY}`);
  }
  return u;
}

// ---------------------------------------------------------------------------
// Small helpers (ported from the local exporter).
// ---------------------------------------------------------------------------
function timestamp() {
  return new Date().toISOString();
}

function log(message) {
  console.log(`[${timestamp()}] ${message}`);
}

async function ensureDir(dirPath) {
  await fs.mkdir(dirPath, { recursive: true });
}

async function getLocatorIfPresent(page, selector) {
  const locator = page.locator(selector).first();
  if ((await locator.count()) === 0) return null;
  return locator;
}

async function isClickable(locator) {
  try {
    return (await locator.isVisible()) && (await locator.isEnabled());
  } catch {
    return false;
  }
}

async function isEditable(locator) {
  try {
    return (await locator.isVisible()) && (await locator.isEnabled()) && (await locator.isEditable());
  } catch {
    return false;
  }
}

async function hasAnyEditableSelector(page, selectors) {
  for (const selector of selectors) {
    const locator = await getLocatorIfPresent(page, selector);
    if (locator && (await isEditable(locator))) return true;
  }
  return false;
}

async function waitForAnyEditableSelector(page, selectors, timeoutMs) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    for (const selector of selectors) {
      const locator = await getLocatorIfPresent(page, selector);
      if (locator && (await isEditable(locator))) return selector;
    }
    await page.waitForTimeout(300);
  }
  throw new Error(`Timed out waiting for any editable selector: ${selectors.join(', ')}`);
}

async function clickFirst(page, selectors) {
  for (const selector of selectors) {
    const locator = await getLocatorIfPresent(page, selector);
    if (locator && (await isClickable(locator))) {
      await locator.click({ timeout: 10_000 });
      return selector;
    }
  }
  throw new Error(`Unable to click any selector: ${selectors.join(', ')}`);
}

async function fillFirst(page, selectors, value) {
  for (const selector of selectors) {
    const locator = await getLocatorIfPresent(page, selector);
    if (locator && (await isEditable(locator))) {
      await locator.fill(value, { timeout: 10_000 });
      return selector;
    }
  }
  throw new Error(`Unable to fill any editable selector: ${selectors.join(', ')}`);
}

// ---------------------------------------------------------------------------
// FlightDocs login (handles single-page and "enter email, then password" flows).
// ---------------------------------------------------------------------------
async function login(page, username, password) {
  log('Navigating to login page');
  await page.goto(LOGIN_URL, { waitUntil: 'domcontentloaded', timeout: 60_000 });

  const usernameSelectors = [
    'input[name="username"]',
    'input[name="Username"]',
    'input[name="email"]',
    'input[name="Email"]',
    'input[name="EmailAddress"]',
    'input[id="username"]',
    'input[id="Email"]',
    'input[id="email"]',
    'input[id="EmailAddress"]',
    'input[autocomplete="username"]',
    'input[type="email"]',
    'input[placeholder*="email" i]',
    'input[placeholder*="user" i]',
  ];

  const continueSelectors = [
    'button:has-text("Continue")',
    'button:has-text("Next")',
    'button:has-text("Proceed")',
    'input[type="submit"][value*="Continue" i]',
    'input[type="submit"][value*="Next" i]',
  ];

  const passwordSelectors = [
    'input[name="password"]',
    'input[name="Password"]',
    'input[id="password"]',
    'input[id="Password"]',
    'input[autocomplete="current-password"]',
    'input[autocomplete="password"]',
    'input[type="password"]',
  ];

  await waitForAnyEditableSelector(page, usernameSelectors, 20_000);
  const userSelector = await fillFirst(page, usernameSelectors, username);
  log(`Filled username using ${userSelector}`);

  if (!(await hasAnyEditableSelector(page, passwordSelectors))) {
    const continueSelector = await clickFirst(page, continueSelectors);
    log(`Clicked intermediate continue/next using ${continueSelector}`);
  }

  await waitForAnyEditableSelector(page, passwordSelectors, 30_000);
  const passSelector = await fillFirst(page, passwordSelectors, password);
  log(`Filled password using ${passSelector}`);

  const submitSelector = await clickFirst(page, [
    'button:has-text("Log in")',
    'button:has-text("Login")',
    'button:has-text("Sign in")',
    'input[type="submit"][value*="Sign in" i]',
    'input[type="submit"][value*="Log in" i]',
    'button[type="submit"]',
    'input[type="submit"]',
  ]);
  log(`Submitted login form using ${submitSelector}`);

  await page.waitForLoadState('networkidle', { timeout: 60_000 });
  log(`Post-login URL: ${page.url()}`);
}

// ---------------------------------------------------------------------------
// Open the report page and trigger the Export download.
// ---------------------------------------------------------------------------
async function exportReport(page, reportUrl) {
  log(`Navigating to report page: ${reportUrl}`);
  await page.goto(reportUrl, { waitUntil: 'domcontentloaded', timeout: 90_000 });
  await page.waitForLoadState('networkidle', { timeout: 90_000 });

  const triggerSelectors = [
    'button:has-text("Export")',
    'a:has-text("Export")',
    '[aria-label="Export"]',
    '[title="Export"]',
  ];

  let triggerLocator = null;
  let triggerSel = null;
  for (const selector of triggerSelectors) {
    const locator = await getLocatorIfPresent(page, selector);
    if (locator && (await isClickable(locator))) {
      triggerLocator = locator;
      triggerSel = selector;
      break;
    }
  }
  if (!triggerLocator) {
    throw new Error(`Unable to find Export trigger with selectors: ${triggerSelectors.join(', ')}`);
  }
  log(`Export trigger found using ${triggerSel}`);

  // Arm the download listener before any click so we never miss it.
  const downloadPromise = page.waitForEvent('download', { timeout: 120_000 });
  await triggerLocator.click({ timeout: 10_000 });

  // The trigger may download directly, open a confirmation modal, or open a
  // format menu. Poll briefly for a confirm/format control and click it.
  const confirmSelectors = [
    '[role="dialog"] button:has-text("Export")',
    '.modal-footer button:has-text("Export")',
    '.modal button:has-text("Export")',
    '[role="dialog"] button:has-text("Download")',
    '[role="dialog"] button:has-text("OK")',
    '[role="menuitem"]:has-text("Excel")',
    '[role="menuitem"]:has-text("CSV")',
    'a:has-text("Export to Excel")',
    'button:has-text("Export to Excel")',
    'a:has-text("Export to CSV")',
    'button:has-text("Export to CSV")',
  ];

  const start = Date.now();
  while (Date.now() - start < 8_000) {
    for (const selector of confirmSelectors) {
      const locator = await getLocatorIfPresent(page, selector);
      if (locator && (await isClickable(locator))) {
        log(`Confirm control appeared (${selector}) — clicking to fire download`);
        await locator.click({ timeout: 10_000 });
        return await downloadPromise;
      }
    }
    await page.waitForTimeout(250);
  }

  try {
    return await downloadPromise;
  } catch (err) {
    const ts = Date.now();
    const shotPath = path.join(os.tmpdir(), `flightdocs-export-fail-${ts}.png`);
    const htmlPath = path.join(os.tmpdir(), `flightdocs-export-fail-${ts}.html`);
    await page.screenshot({ path: shotPath, fullPage: true }).catch(() => {});
    await fs.writeFile(htmlPath, await page.content(), 'utf8').catch(() => {});
    throw new Error(
      `Export click on ${triggerSel} did not produce a download or recognized confirm control. ` +
        `Screenshot: ${shotPath} — DOM: ${htmlPath}. Underlying: ${err instanceof Error ? err.message : err}`,
    );
  }
}

// ---------------------------------------------------------------------------
// Download -> CSV text.
// ---------------------------------------------------------------------------
async function downloadToCsvText(download, downloadDir) {
  const suggested = download.suggestedFilename() || 'report.xlsx';
  const ext = (path.extname(suggested) || '.xlsx').toLowerCase();
  const savedPath = path.join(downloadDir, `report${ext}`);
  await download.saveAs(savedPath);
  log(`Downloaded ${suggested} -> ${savedPath}`);

  if (ext === '.csv' || ext === '.txt') {
    let text = await fs.readFile(savedPath, 'utf8');
    if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
    return text;
  }

  const workbook = XLSX.readFile(savedPath, { cellDates: true });
  const sheetName = workbook.SheetNames[0];
  if (!sheetName) throw new Error('Downloaded workbook contained no sheets.');
  return XLSX.utils.sheet_to_csv(workbook.Sheets[sheetName]);
}

// ---------------------------------------------------------------------------
// Merge new CSV rows into the existing file (header from the new export, data
// rows deduped by exact line, existing rows kept first). FD_MERGE=false just
// overwrites instead.
// ---------------------------------------------------------------------------
function splitLines(text) {
  const lines = text.replace(/^﻿/, '').replace(/\r\n?/g, '\n').split('\n');
  while (lines.length && lines[lines.length - 1].trim() === '') lines.pop();
  return lines;
}

async function writeOutput(newCsvText, outputPath, merge) {
  const newLines = splitLines(newCsvText);
  if (newLines.length === 0) {
    throw new NonRetryableError('Export produced an empty file — refusing to overwrite the report.');
  }
  const header = newLines[0];
  const newData = newLines.slice(1).filter((l) => l.trim() !== '');

  let outData = newData;
  if (merge) {
    let existingData = [];
    try {
      const existingLines = splitLines(await fs.readFile(outputPath, 'utf8'));
      if (existingLines.length) {
        if (existingLines[0].trim() !== header.trim()) {
          log(
            'WARNING: existing CSV header differs from the export header — keeping existing rows anyway.\n' +
              `  existing: ${existingLines[0]}\n  export:   ${header}`,
          );
        }
        existingData = existingLines.slice(1).filter((l) => l.trim() !== '');
      }
    } catch {
      log('No existing report file — creating a new one.');
    }
    const seen = new Set();
    outData = [];
    for (const line of [...existingData, ...newData]) {
      if (seen.has(line)) continue;
      seen.add(line);
      outData.push(line);
    }
    const added = outData.length - existingData.filter((l, i, a) => a.indexOf(l) === i).length;
    log(`Merged report: ${existingData.length} existing + ${newData.length} fetched -> ${outData.length} rows (${added} new).`);
  } else {
    log(`Overwriting report with ${newData.length} rows.`);
  }

  await ensureDir(path.dirname(outputPath));
  const tmpPath = `${outputPath}.tmp`;
  await fs.writeFile(tmpPath, `${header}\n${outData.join('\n')}\n`, 'utf8');
  await fs.rename(tmpPath, outputPath);
  const stats = await fs.stat(outputPath);
  log(`Wrote ${outputPath} (${stats.size} bytes).`);
}

// ---------------------------------------------------------------------------
function getFirstEnv(names) {
  for (const name of names) {
    if (process.env[name]) return process.env[name];
  }
  return undefined;
}

function requireCredential(label, names) {
  const value = getFirstEnv(names);
  if (!value) {
    throw new NonRetryableError(`Missing ${label} credential. Set one of: ${names.join(', ')}.`);
  }
  return value;
}

async function runOnce() {
  const username = requireCredential('username', ['FLIGHTDOCS_USERNAME', 'FLIGHTDOCS_USER', 'FD_USERNAME']);
  const password = requireCredential('password', ['FLIGHTDOCS_PASSWORD', 'FLIGHTDOCS_PASS', 'FD_PASSWORD']);

  const reportUrl = buildReportUrl();
  log(`Date window: LogDate=${LOG_DATE} LogDateSecondary=${LOG_DATE_SECONDARY} (merge=${MERGE})`);

  const downloadDir = await fs.mkdtemp(path.join(os.tmpdir(), 'flightdocs-component-'));
  const browser = await chromium.launch({ headless: HEADLESS });
  const context = await browser.newContext({ acceptDownloads: true });
  const page = await context.newPage();

  try {
    await login(page, username, password);
    const download = await exportReport(page, reportUrl);
    const csvText = await downloadToCsvText(download, downloadDir);
    await writeOutput(csvText, OUTPUT_PATH, MERGE);
  } finally {
    await context.close();
    await browser.close();
    await fs.rm(downloadDir, { recursive: true, force: true }).catch(() => {});
  }
}

async function runWithRetries() {
  let attempt = 0;
  while (attempt < MAX_ATTEMPTS) {
    attempt += 1;
    try {
      log(`Attempt ${attempt}/${MAX_ATTEMPTS}`);
      await runOnce();
      log('Success');
      return;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      log(`Attempt ${attempt} failed: ${message}`);
      if (error instanceof NonRetryableError || attempt >= MAX_ATTEMPTS) throw error;
      await new Promise((resolve) => setTimeout(resolve, 5000));
    }
  }
}

runWithRetries().catch((error) => {
  console.error(`[${timestamp()}] Fatal error:`, error);
  process.exit(1);
});
