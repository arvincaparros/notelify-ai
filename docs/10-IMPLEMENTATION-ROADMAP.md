# Notelify AI — Implementation Roadmap

**Status:** DRAFT / PROPOSED — this phasing has not been negotiated with the
product owner the way the database design was. It is a reasonable sequencing
derived from dependency order among the already-approved pieces, offered as
a starting point for review, not an approved plan. **No phase should be
started without explicit sign-off**, per `11-CLAUDE-DEVELOPMENT-GUIDELINES.md`.
**Last updated:** 2026-11-09

## Phase 0 — Project scaffolding

**Depends on:** nothing.
**Work:** repository structure, Docker Compose (Postgres + backend
containers), Alembic configuration, base FastAPI app skeleton, lint/format
tooling, CI skeleton (even if it only runs lint at first).
**Completion criteria:** `docker compose up` brings up an empty backend that
can connect to Postgres; Alembic can run (zero migrations yet) against it.
**Testing:** smoke test that the stack starts and the backend can reach the
database.

## Phase 1 — Database and authentication backend

**Depends on:** Phase 0.
**Work:** all nine Alembic migrations from `04-DATABASE-DESIGN.md`; seed the
`free` plan tier; implement signup, email verification, login, token
refresh, logout/revoke, password reset — against whatever
`05-API-CONTRACTS.md` says once that document is resolved (**blocked on
API-contracts review** — see below).
**Completion criteria:** a user can register, verify, log in, refresh a
token, and reset a password, end to end, against a real database.
**Testing:** the full concurrency test suite for quota/chunk mechanics
cannot run yet (no chunks exist without Phase 2), but the monthly-reset race
test and auth-flow tests can and should run here. Security tests for
ownership isolation begin here too.

## Phase 2 — Chunk ingestion and transcription pipeline

**Depends on:** Phase 1.
**Work:** meeting creation; the unified chunk accept/retry dispatch and
Transaction Flows 1–4 from `04-DATABASE-DESIGN.md`; the Groq Whisper provider
interface and its write-back transaction with stale-worker protection;
quota charging and the atomic monthly reset.
**Completion criteria:** a chunk can be uploaded, transcribed, and its text
returned to the caller; retries, quota exhaustion, and lease recovery all
behave as specified in `04-DATABASE-DESIGN.md`.
**Testing:** this phase is where the bulk of the database concurrency test
suite from `09-TESTING-STRATEGY.md` applies — chunk idempotency, new-chunk
race, lease/retry correctness, quota-exceeded persistence and recovery.

## Phase 3 — Finalization and summarization

**Depends on:** Phase 2.
**Work:** the finalize endpoint, the reconciliation sweep (opportunistic and
deadline-forced), the summarization job lifecycle (claim/success/retry/
exhaustion/startup-recovery), and the Groq LLM provider interface producing
`summary_text`, `summary_structured`, decisions, and action items (with
best-effort evidence-chunk linking).
**Completion criteria:** stopping a recording reliably reaches a terminal
meeting state (`completed` or `failed`) within the reconciliation window
plus job processing time, with a regression test specifically for the
deadline-forced-sweep exhaustion bug caught in design review.
**Testing:** reconciliation and job-lifecycle tests from
`09-TESTING-STRATEGY.md`; the end-to-end pipeline test becomes possible for
the first time at the end of this phase (backend-only, no extension yet).

## Phase 4 — Chrome extension

**Depends on:** Phase 2 (needs working chunk-upload and finalize endpoints
to integrate against).
**Work:** service worker (lifecycle coordination, restart recovery),
offscreen document (dual `MediaRecorder`, chunking, upload queue,
retry/backoff, IndexedDB durable state), popup/side panel UI (start/stop,
live transcript, failure indicator).
**Completion criteria:** a real meeting in a browser tab can be captured,
transcribed live in the extension UI, and finalized, end to end against the
Phase 2/3 backend.
**Testing:** extension integration tests from `09-TESTING-STRATEGY.md`
(service-worker-restart survival, chunk ordering, finalize-flush behavior).

## Phase 5 — Web dashboard

**Depends on:** Phase 3 (needs finalized meetings with summaries to display)
and `05-API-CONTRACTS.md` / `07-DASHBOARD-UI-UX-SPECIFICATION.md` being
resolved.
**Work:** meeting history list, meeting detail view (transcript, summary,
decisions, action items, notes), account/usage view, auth screens.
**Completion criteria:** a user can review any of their completed meetings
and manage notes/action-item status through the dashboard without touching
the extension.
**Testing:** dashboard-level contract tests against the (by-then-resolved)
API contracts; ownership-isolation security tests from the dashboard's
perspective.

## Phase 6 — Hardening pass

**Depends on:** Phases 1–5.
**Work:** full concurrency/race test suite run under load, security review
pass, review of all provisional constants
(`01-PRODUCT-REQUIREMENTS.md`'s "Outstanding" list), deployment polish for
Docker Compose.
**Completion criteria:** the full test suite from `09-TESTING-STRATEGY.md`
passes; provisional constants have been either confirmed or revised with a
documented reason.

## Blocking dependencies outside this roadmap

- **`05-API-CONTRACTS.md` must be resolved before Phase 1's auth endpoints or
  Phase 5's dashboard work can be implemented against a stable contract.**
  This is the most significant outstanding planning item blocking
  implementation.
- `07-DASHBOARD-UI-UX-SPECIFICATION.md` needs a dedicated design pass before
  Phase 5.
- `09-TESTING-STRATEGY.md` needs product-owner review before being treated
  as the binding test plan referenced above.

## Unresolved

- This entire roadmap needs explicit approval, including whether the phase
  boundaries and dependencies above match the product owner's priorities
  (e.g., whether the extension or the dashboard should come first is a real
  open choice — Phase 4 was sequenced before Phase 5 here only because it
  can start one phase earlier, not because of a stated priority).
