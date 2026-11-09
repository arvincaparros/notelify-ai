# Notelify AI — Testing Strategy

**Status:** DRAFT / PROPOSED — unlike the database design, this strategy was
not negotiated round-by-round with the product owner. It is derived logically
from the already-approved architecture and database concurrency design, but
it requires explicit review and approval before being treated as binding.
**Last updated:** 2026-11-09

## Why this is a draft

The database design in `04-DATABASE-DESIGN.md` went through six rounds of
explicit correction and approval. This testing strategy has not — it is a
first pass proposing how that approved design (and the rest of the
architecture) should be verified, written so there is something concrete to
react to rather than starting implementation with no test plan at all.

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

Deferred until `05-API-CONTRACTS.md` is actually designed and approved —
there is no contract to test against yet. Once it exists: request/response
shape validation, auth/ownership enforcement (a user cannot read/write
another user's meeting), and quota-exceeded/meeting-closed/reconciliation-
timeout response handling.

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
  items via any endpoint, once `05-API-CONTRACTS.md` exists.
- Groq credentials never appear in any extension or dashboard bundle/network
  request (static check, part of CI).

## Per-phase testing requirements

See `10-IMPLEMENTATION-ROADMAP.md` (also a draft) — each phase there lists
which of the layers above apply to it.

## Unresolved

- Test framework choices (e.g. pytest for backend; a JS/TS test runner for
  extension and dashboard) — not yet decided (also noted in
  `03-TECHNOLOGY-STACK.md`).
- Whether concurrency tests run against a real ephemeral Postgres (e.g. via
  Docker in CI) or some other mechanism — a real instance is recommended
  given how much of the design's correctness is about actual row-level
  locking behavior, but this hasn't been agreed.
- Coverage targets/thresholds, if any.
- This entire document needs explicit product-owner review before being
  treated as approved, the same way the database design was reviewed round
  by round.
