# Notelify AI — Testing Strategy

**Status:** PARTIALLY APPROVED — a minimum testing foundation for Phase 1 (below) is
now approved. Everything else in this document (full coverage targets, extension/
dashboard-specific testing, end-to-end testing beyond Phase 1's minimum) remains
DRAFT/PROPOSED, not negotiated round-by-round the way the database design was.
**Last updated:** 2026-11-10

## Minimum Phase 1 Testing Foundation (APPROVED)

This section exists specifically to unblock Phase 1 (`10-IMPLEMENTATION-ROADMAP.md`)
without re-litigating the entire draft strategy below — it approves the minimum needed
to start, and explicitly leaves the rest open.

- **Backend test framework: pytest — APPROVED.**
- **PostgreSQL-backed integration tests — APPROVED.** Tests hit a real Postgres, never
  a mock — consistent with how much of this project's correctness is about actual
  row-level locking and advisory-lock behavior, which a mock cannot exercise
  meaningfully.
- **Real ephemeral Postgres for transaction/concurrency tests — APPROVED**, with a
  concrete isolation strategy: a single Postgres database is created once per test
  session (via Docker, migrated once with Alembic at session start), not once per test.
  Ordinary tests wrap each test in a transaction rolled back at the end (fast, isolated
  — the standard pytest+SQLAlchemy pattern). **Concurrency tests cannot use that
  pattern** — testing real lock contention requires multiple independently-committing
  connections interacting, which a wrapping transaction would prevent by construction.
  Concurrency tests get their own explicit setup/teardown (truncating the relevant
  tables, not relying on rollback) and should be clearly separated — e.g. a
  `tests/concurrency/` directory or a `@pytest.mark.concurrency` marker — so they're
  never accidentally run under the fast-rollback fixture meant for everything else.
- **Authentication tests — APPROVED as a required minimum for Phase 1 sign-off**:
  registration (including the email-uniqueness race), login (including a **dedicated
  regression test for the login/password-reset/logout-all concurrency fix** in
  `05-API-CONTRACTS.md` §A.3 — this closed a real race found during design review, and
  silently regressing it would be worse than not having found it), logout and
  logout-all, refresh-token rotation (normal rotation, the grace-period chain-walk, and
  family-wide reuse-detection revocation), and the email-verification/password-reset
  token lifecycle (expiry, and the deliberate replay-semantics difference between the
  two — idempotent-success for verification, hard error for reset).
- **Database migration tests — APPROVED, minimum scope**: migrations apply cleanly,
  forward-only, to an empty database — consistent with `04-DATABASE-DESIGN.md`'s
  additive-only migration philosophy. Full up/down (`downgrade`) testing is
  **explicitly deferred**, not required for v1.
- **API contract tests — APPROVED, minimum scope**: once endpoints are implemented,
  validate request/response shapes against the contracts documented in
  `05-API-CONTRACTS.md`. Exact tooling (e.g. schemathesis vs. hand-written
  Pydantic-model assertions) is **left open**, not decided by this approval.

**Explicitly kept open, per instruction, not silently resolved**: full test coverage
targets/thresholds, and all end-to-end/extension/dashboard testing detail beyond what
layer 3/4 below already sketch — these remain DRAFT, to be refined later, not part of
this Phase 1 minimum.

## Why the rest of this document is still a draft

The database design in `04-DATABASE-DESIGN.md` went through seven rounds of
explicit correction and approval. The remainder of this testing strategy has not — it
is a first pass proposing how the broader architecture should be verified beyond the
Phase 1 minimum above, written so there is something concrete to react to rather than
starting implementation with no test plan at all.

## Proposed testing layers

### 1. Database concurrency and correctness tests (highest priority)

The approved design in `04-DATABASE-DESIGN.md` makes specific, falsifiable
claims that should be tested directly against a real Postgres instance (not
mocked), covering the concurrency scenarios already enumerated in that
document's revision history and flow descriptions:

- Chunk idempotency: uploading the same `(meeting_id, source, chunk_id)`
  twice never creates two rows and never double-charges quota.
- Monthly quota reset race: two concurrent tab-chunk charges for the same
  user at a simulated UTC month boundary never double-reset or lose a
  charge.
- New-chunk race: two simultaneous uploads of the same unseen `chunk_id`
  never both succeed down the "new chunk" path.
- Lease/retry correctness: a `transcribed` chunk can never be reclaimed; an
  expired lease with exhausted attempts can never be reclaimed; a live lease
  blocks a concurrent claim.
- Stale Groq write-back: a response from a superseded attempt (lost lease),
  a response arriving after reconciliation timeout, and a response arriving
  after the meeting has moved past `finalizing` are all discarded as no-ops,
  never corrupting a newer result.
- Reconciliation: `all_resolved` only becomes true once every chunk is
  `transcribed` or genuinely `is_exhausted`; the deadline-forced sweep
  correctly makes a forced-failed chunk exhausted (this was a real bug
  caught in review — see revision history round 6 — and deserves a
  regression test specifically).
- Quota-exceeded persistence: once `quota_exceeded_at` is set on a meeting,
  both new tab and new mic chunks are rejected, while chunks already
  accepted before exhaustion remain fully recoverable.
- Deadlock-freedom: the global lock-ordering invariant (meeting → user →
  chunk) should be exercised under concurrent load without producing a
  deadlock.

### 2. Backend contract tests

`05-API-CONTRACTS.md`'s architecture (Round 1) and Authentication endpoints (Round 2)
are now approved, so authentication contract tests are in scope for Phase 1 (see the
Phase 1 minimum above). The remaining endpoint groups (meetings, chunks, transcript/
intelligence, notes/action items, usage/search) are still not designed — contract tests
for those stay deferred until each round is approved. Once in scope: request/response
shape validation, auth/ownership enforcement (a user cannot read/write another user's
meeting), and quota-exceeded/meeting-closed/reconciliation-timeout response handling.

### 3. Extension integration tests

- Offscreen document lifecycle: chunk generation, upload, retry/backoff, and
  IndexedDB persistence survive a simulated service-worker restart.
- Chunk ordering: out-of-order server responses still render in correct
  sequence in the popup.
- Finalize flow: the failed-chunk buffer is flushed before `finalize` is
  called.

### 4. End-to-end pipeline test

A full happy-path run: start capture → upload several chunks (both sources)
→ stop → reconciliation completes → summarization job runs → summary,
decisions, and action items are persisted and retrievable.

### 5. Security tests

- A user cannot access another user's meeting, notes, decisions, or action
  items via any endpoint, once each respective endpoint group is designed and
  implemented (authentication's ownership rules are already approved and in scope now).
- Groq credentials never appear in any extension or dashboard bundle/network
  request (static check, part of CI).

## Per-phase testing requirements

See `10-IMPLEMENTATION-ROADMAP.md` (also a draft) — each phase there lists
which of the layers above apply to it.

## Unresolved

- **Resolved by the Phase 1 minimum above**: backend framework (pytest) and the
  ephemeral-Postgres question for concurrency tests — no longer open.
- JS/TS test runner for the extension and dashboard — not yet decided (also noted in
  `03-TECHNOLOGY-STACK.md`).
- Coverage targets/thresholds, if any.
- Full end-to-end, extension integration, and dashboard testing detail beyond the
  Phase 1 minimum and the sketches in layers 3/4 below — needs explicit product-owner
  review before being treated as approved, the same way Phase 1's minimum just was.
