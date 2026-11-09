# Notelify AI — Security and Authentication

**Status:** PARTIALLY APPROVED — the auth model, token storage design, and
credential-handling rules are approved; specific algorithms and numeric
parameters are not yet decided (see "Unresolved" below).
**Last updated:** 2026-11-09

## Approved auth model

- **Multi-user SaaS from v1.** Each user has an account; a user only ever
  sees their own data. (Resolved explicitly over a single-user/personal-tool
  alternative during requirements discussion.)
- **JWT access tokens (short-lived) + hashed refresh tokens stored in
  Postgres (revocable).** A purely stateless JWT scheme was rejected because
  it would not allow revoking a session (logout, compromise) — the
  `refresh_tokens` table (`token_hash`, `expires_at`, `revoked_at`) exists
  specifically for this.
- **Email verification and password reset are first-class, token-backed
  flows**, each with its own table (`email_verification_tokens`,
  `password_reset_tokens`) — single-use (`consumed_at`), short-lived
  (`expires_at`), and deliberately *not* reusing the `refresh_tokens` table,
  since the lifecycle and semantics differ.
- **Token cleanup**: no DB-enforced purge of expired tokens. A scheduled job
  deletes rows from all three token tables where `expires_at` is more than
  30 days in the past, purely to keep tables small — expired tokens are
  already unusable at auth time regardless of whether they've been purged.

## Credential handling

- **Groq API credentials live exclusively on the backend.** They are never
  sent to, stored in, or embedded in the Chrome extension or the web
  dashboard. This was an explicit, non-negotiable requirement — the rejected
  "direct-to-provider from extension" architecture approach (see
  `02-SYSTEM-ARCHITECTURE.md`) was ruled out specifically because it would
  have leaked this credential client-side.
- The transcription provider (Groq Whisper) and the summarization LLM
  provider (Groq-hosted Llama by default) are both accessed through a
  provider interface on the backend, so credentials and provider choice stay
  server-side and swappable.

## Ownership and data-integrity enforcement

- **Backend-level enforcement, on every operation**: every meeting-scoped
  table reaches `user_id` transitively through `meeting_id → meetings.user_id`.
  The backend's authorization layer always joins through `meetings` and
  checks `meetings.user_id = current_user.id` — this is an application-level
  invariant applied consistently, not Postgres row-level security, for v1.
- **Database-level enforcement, structurally**: composite foreign keys make
  certain ownership violations physically impossible to store, independent
  of application correctness:
  - `meeting_notes (meeting_id, user_id) → meetings (id, user_id)` — a note
    cannot be stored with a `user_id` that disagrees with its meeting's
    owner.
  - `decisions`/`action_items` `(source_chunk_id, meeting_id) →
    transcript_chunks (id, meeting_id)` — an evidence link cannot point to a
    chunk belonging to a different meeting.
  
  See `04-DATABASE-DESIGN.md` for the full DDL and rationale.
- **Usage quota as an abuse-prevention boundary**: quota enforcement (see
  `04-DATABASE-DESIGN.md`'s concurrency design) doubles as a backend-enforced
  limit on resource consumption per user, independent of client behavior —
  the client's own shutdown-on-quota-exceeded behavior is a UX nicety, not
  the enforcement mechanism.

## Unresolved / not yet decided

- Specific password-hashing algorithm and parameters (bcrypt vs. argon2,
  work factor/cost).
- JWT signing algorithm/library and exact access-token / refresh-token
  lifetimes (numeric values).
- Rate limiting policy on auth endpoints (login attempts, password-reset
  requests, etc.) — not discussed at all yet.
- Whether email verification blocks login entirely or allows reduced access
  before verification (flagged also in `01-PRODUCT-REQUIREMENTS.md`).
- CORS policy and any CSRF considerations for the dashboard's interaction
  with the backend.
- Whether Postgres row-level security (RLS) should be added later as
  defense-in-depth on top of the backend-level ownership checks — noted as a
  possible future hardening step, not required now.
