# Notelify AI — Product Requirements

**Status:** APPROVED (requirements and acceptance criteria below reflect decisions
made during architecture brainstorming; no new requirements have been invented
beyond what was discussed)
**Last updated:** 2026-11-09

## Functional Requirements

### FR1 — Bot-free audio capture
The system must capture meeting audio without an AI bot joining the meeting as
a participant. Capture uses Chrome's `tabCapture` API against the tab the user
is already in.

**Acceptance criteria**
- No participant entry, join request, or visible bot appears in the meeting
  for any supported platform.
- Capture works on any browser tab playing audio — not limited to a hardcoded
  list of meeting platforms.

### FR2 — User-initiated capture
The user explicitly starts and stops capture via a single control in the
extension (popup/side panel). There is no automatic or passive capture.

**Acceptance criteria**
- Capture never starts without an explicit user action.
- The user can stop capture at any time; stopping triggers finalization
  (see FR5).

### FR3 — Dual-stream audio capture
Tab audio and microphone audio are captured as two independent streams, not
mixed, so "me" (mic) and "meeting" (tab) can be attributed separately in the
transcript.

**Acceptance criteria**
- Each audio chunk is tagged with its source (`tab` or `mic`).
- A transcript segment's source attribution is preserved end-to-end into the
  stored data.

### FR4 — Live transcription
While recording, the extension shows a live transcript with a few seconds of
latency per chunk (not word-level streaming).

**Acceptance criteria**
- Transcript text for a chunk appears in the extension UI within a few
  seconds of that chunk's audio ending, under normal network conditions.
- Transcript segments render in correct chronological order even when
  chunk-processing responses arrive out of order.

### FR5 — Meeting finalization and summarization
When the user stops capture, the system finalizes the meeting once every
accepted chunk has reached a terminal state (transcribed or failed), then
generates a summary, decisions, and action items from the full transcript.

**Acceptance criteria**
- Summarization never starts while a chunk's transcription attempt is still
  genuinely in progress.
- Finalization completes (success or documented failure) within a bounded
  time window, not indefinitely.
- A meeting's summary includes a free-text summary and a structured output
  (decisions, action items) derived from the same transcript.

### FR6 — Decision and action item extraction
Decisions and action items are extracted from the transcript as part of
summarization, each optionally linked back to the transcript evidence it was
derived from.

**Acceptance criteria**
- Each decision/action item can carry an evidence excerpt and, when a
  confident match exists, a link to the specific transcript chunk it came
  from.
- Action items support an owner (free text) and due date, both optional.

### FR7 — Web dashboard for meeting management
Users manage their meeting history — view transcripts, summaries, decisions,
action items, and their own notes — through a separate web dashboard from the
extension.

**Acceptance criteria**
- The dashboard is a read/write REST client over backend data; it does not
  require a live connection to an in-progress meeting.
- Users can add their own freeform notes to a meeting, distinct from the
  AI-generated summary.

### FR8 — Meeting history and transcript storage
Meeting history and transcripts are stored durably; raw audio is not.

**Acceptance criteria**
- A completed meeting's transcript, summary, decisions, and action items
  remain available after the browser/extension session ends.
- No raw audio bytes are persisted beyond the point of transcription.

### FR9 — User accounts
The product is multi-user from v1: each user has their own account, with
email verification and password reset support.

**Acceptance criteria**
- A user only ever sees their own meetings and data.
- Account creation requires email verification before full access (exact
  enforcement point is an implementation detail for the API contracts phase).

### FR10 — Usage quota enforcement
Each user has a plan-tier-defined monthly quota (minutes of billable audio).
The system enforces this quota and stops accepting further audio once
exhausted for a given meeting.

**Acceptance criteria**
- Quota is based on actual meeting duration (derived from the `tab` stream),
  not the sum of both streams' durations.
- Once a meeting trips the quota limit, both tab and microphone chunks for
  that specific meeting are rejected going forward; other meetings and other
  users are unaffected.
- Quota resets automatically at the start of each UTC calendar month.

### FR11 — Future platform extensibility (architectural, not built in v1)
The architecture must not preclude adding Zoom/Teams/Meet-specific behavior
later (e.g., platform detection, participant names) without a redesign, even
though v1 ships only the generic, platform-agnostic trigger.

**Acceptance criteria**
- No v1 design decision hardcodes assumptions that would block adding a
  platform-specific content-script layer later as an additive change.

## Non-Functional Requirements

### NFR1 — Credential security
Groq API credentials are held exclusively by the backend. They are never sent
to or embedded in the extension or dashboard client code.

### NFR2 — Data privacy
Audio is discarded after transcription; only text transcripts are retained.
This is a deliberate reduction of the sensitive-data surface for a product
that processes private conversations.

### NFR3 — Idempotency and retry safety
Chunk uploads, quota charges, and finalization requests must be safe to
retry — a retried operation must never duplicate a chunk's processing or
double-charge quota. (Full mechanics in `04-DATABASE-DESIGN.md`.)

### NFR4 — Concurrency correctness
All quota, chunk-claiming, and finalization logic must behave correctly under
concurrent chunk uploads, including out-of-order network responses and
retried requests racing fresh ones.

### NFR5 — Recoverability
Summarization jobs must survive a backend process restart (picked back up,
not lost or silently abandoned). Extension-side capture state must survive a
Manifest V3 service worker restart (which can happen at any time, not just on
crash).

### NFR6 — Latency expectations
Live transcript updates should appear within roughly the audio-chunk duration
plus Groq processing time (on the order of a few seconds) — explicitly not a
word-by-word live captioning experience.

### NFR7 — Deployment simplicity (v1)
The entire system must run via Docker Compose on a local machine with no
external infrastructure dependency other than the Groq API itself.

## Explicitly out of scope for v1

(See `00-PRODUCT-OVERVIEW.md` for the full list.) In particular: native
desktop app capture, platform-specific detection, multi-client real-time
sync, and any distributed queue/worker infrastructure (Redis/Celery).

## Outstanding / unresolved items

- Exact enforcement point and flow for email verification (block login
  entirely vs. allow with reduced functionality) — not yet decided.
- Exact free-tier quota minute value and additional plan tiers' values — only
  the *mechanism* (a `plan_tiers` lookup table) is approved; actual numbers
  are a product decision still pending.
- Exact chunk duration (approved as "~7 seconds" conceptually), lease
  duration (30s), and retry/attempt caps (3 for chunks, 5 for summarization
  jobs) are provisional engineering constants, not yet validated against
  real-world Groq latency or product testing.
