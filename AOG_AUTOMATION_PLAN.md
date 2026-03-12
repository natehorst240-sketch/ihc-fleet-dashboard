# AOG Email-to-Flag Automation Plan

## Goal

Automatically set/clear aircraft AOG status on the **main dashboard** (`data/index.html`) when a Veryon AOG email arrives, without requiring a manual click in `data/aog.html`.

---

## Current State (Gap)

- `data/aog.html` is a standalone tool with browser-local persistence.
- Gmail ingestion is user-triggered via **SYNC GMAIL** button.
- `data/index.html` does not consume AOG state from a shared source.

This means email arrival does **not** automatically update the main site.

---

## Target Architecture

```text
Veryon email -> Gmail mailbox
             -> Gmail Watch / Poll Worker
             -> AOG Ingestion Service (parse + dedupe)
             -> Shared Store (active + history)
             -> Dashboard API
             -> data/index.html AOG banner/tail badges
```

### Components

1. **Mailbox listener**
   - Preferred: Gmail push notifications (watch + Pub/Sub webhook).
   - Fallback: periodic poll every 1-5 minutes.

2. **AOG ingestion service**
   - Filters on sender + subject (Veryon + "New AOG Discrepancy Reported").
   - Extracts tail, discrepancy ID, grounded state, description, received time.
   - Marks records idempotently using `discrepancy_id` (and message ID as fallback).

3. **Shared persistence**
   - `aog_events` table for immutable lifecycle history.
   - `aog_active` view/table for unresolved active events.

4. **Dashboard read API**
   - Main site fetches active AOG state at load + on interval.
   - Optional websocket/SSE for near-real-time updates.

5. **Operator actions**
   - Clear/resolve endpoint from AOG UI and/or main dashboard controls.
   - Resolution updates active + history consistently.

---

## Data Contract

## Canonical AOG Event

```json
{
  "id": "evt_01J...",
  "tail": "N251HC",
  "discrepancy_id": "20260311161810",
  "description": "Broken roller on left sliding door",
  "grounded": true,
  "source": "veryon_email",
  "email_message_id": "<gmail-message-id>",
  "received_at": "2026-03-11T16:18:10Z",
  "opened_at": "2026-03-11T16:18:10Z",
  "cleared_at": null,
  "clear_reason": null,
  "status": "active"
}
```

### Required fields

- `tail`
- `grounded`
- `received_at`
- one of: `discrepancy_id` or `email_message_id`

### Idempotency rule

- Upsert key: `(source, discrepancy_id)` when present.
- Else fallback key: `(source, email_message_id)`.

---

## API Contract (MVP)

## `GET /api/aog/active`

Returns active events.

Response:

```json
{
  "updated_at": "2026-03-12T01:05:00Z",
  "events": [
    {
      "id": "evt_01",
      "tail": "N251HC",
      "description": "Broken roller on left sliding door",
      "discrepancy_id": "20260311161810",
      "opened_at": "2026-03-11T16:18:10Z",
      "source": "veryon_email"
    }
  ]
}
```

## `POST /api/aog/events/ingest`

For worker use only (service token required).

Request:

```json
{
  "events": [
    {
      "tail": "N251HC",
      "description": "Broken roller on left sliding door",
      "discrepancy_id": "20260311161810",
      "grounded": true,
      "email_message_id": "18f7...",
      "received_at": "2026-03-11T16:18:10Z",
      "source": "veryon_email"
    }
  ]
}
```

Response:

```json
{
  "inserted": 1,
  "deduped": 0,
  "ignored": 0
}
```

## `POST /api/aog/events/{id}/clear`

Marks an active event as resolved.

Request:

```json
{
  "cleared_at": "2026-03-12T02:10:00Z",
  "clear_reason": "Returned to service"
}
```

Response:

```json
{
  "ok": true
}
```

---

## Main Dashboard Integration (`data/index.html`)

Add:

1. **AOG fetch routine**
   - Poll `GET /api/aog/active` every 60 seconds.
   - Keep a local map: `tail -> active event`.

2. **Visual indicators**
   - Header badge: `AOG: N`.
   - Tail row badge for affected aircraft.
   - Optional red border/glow for affected aircraft panel.

3. **Failure behavior**
   - If API unavailable, keep last good state and show stale indicator.
   - Do not block existing dashboard render path.

4. **Deep-link**
   - Add button/link to `data/aog.html` (operator view/history).

---

## AOG Page Integration (`data/aog.html`)

Refactor from local-only mode to API-backed mode:

- Replace `localStorage` reads/writes with API calls.
- Keep optional local fallback only for offline/dev.
- Move email sync logic to backend worker; remove browser API-key dependency.

---

## Security & Secrets

- Never expose Anthropic/Gmail tokens in browser JavaScript.
- Worker/service account credentials stored server-side only.
- Protect ingest endpoints with service auth (token or mTLS).
- Validate/normalize tail numbers against fleet allowlist.

---

## Rollout Plan

## Phase 1 — Backend foundation

- Create AOG schema + migration.
- Implement ingest, active read, and clear endpoints.
- Add structured logs + metrics.

## Phase 2 — Email automation

- Implement Gmail watch or poll worker.
- Parse and ingest Veryon emails.
- Add alerting for parser failures.

## Phase 3 — Frontend integration

- Add AOG fetch + badges to `data/index.html`.
- Convert `data/aog.html` to API mode.
- Keep manual clear action with audit trail.

## Phase 4 — Hardening

- Add E2E test with synthetic ingest payload.
- Add stale-data guardrails (e.g., warn if feed older than X min).
- Add runbook for incident response.

---

## Acceptance Criteria

1. A new qualifying Veryon AOG email appears and active AOG count increases on main dashboard within 2 minutes.
2. Duplicate email deliveries do not create duplicate active events.
3. Clearing an event from operator UI removes tail-level AOG flag on main dashboard within 1 minute.
4. All state transitions are auditable (`opened_at`, `cleared_at`, actor/source).
5. No client-side secret material exists in shipped frontend assets.

---

## Suggested First PR Sequence

1. Add backend API + schema + unit tests.
2. Integrate `data/index.html` read-only AOG badges.
3. Add worker ingest path from test fixture payloads.
4. Replace `data/aog.html` storage with API-backed read/write.
5. Enable Gmail watch in production environment.
