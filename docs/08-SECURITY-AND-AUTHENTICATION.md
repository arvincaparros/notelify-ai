# Notelify AI — Security and Authentication

**Status:** PARTIALLY APPROVED — the auth model, token storage design, credential-
handling rules, password-hashing algorithm, refresh-token concurrency/reuse-detection
mechanisms, and registration/verification behavior are approved; remaining numeric
parameters are not yet decided (see "Unresolved" below).
**Last updated:** 2026-11-10

## Approved auth model

- **Multi-user SaaS from v1.** Each user has an account; a user only ever
  sees their own data. (Resolved explicitly over a single-user/personal-tool
  alternative during requirements discussion.)
- **JWT access tokens (short-lived) + hashed refresh tokens stored in
  Postgres (revocable).** A purely stateless JWT scheme was rejected because
  it would not allow revoking a session (logout, compromise) — the
  `refresh_tokens` table (`token_hash`, `expires_at`, `revoked_at`, plus
  `family_id`, `replaced_by_token_id`, `grace_ciphertext`, `grace_expires_at`
  — **approved this round**, `04-DATABASE-DESIGN.md` revision 7) exists
  specifically for this.
- **Refresh-token reuse detection with a bounded legitimate-concurrency grace
  period — APPROVED.** Rotation revokes the presented token and issues a new
  one; presenting an already-revoked token is a theft signal unless it falls
  within a short grace window, resolved via a short-lived, reversibly
  encrypted copy of the replacement token (never a plaintext value at rest)
  and a family-scoped advisory lock that closes a revocation-vs-concurrent-
  rotation race found during review. **Access-token revocation does not
  retroactively invalidate an already-issued access token** — only a bounded
  window (proposed 15 minutes) of exposure after a revocation event, an
  accepted trade-off against the added complexity and per-request cost of a
  denylist. Full mechanism, including the bounded chain-walk for resolving a
  grace replay through multiple rotations, is in `05-API-CONTRACTS.md` §A.3.
- **User-row locking for login, password-reset, and logout-all — APPROVED.**
  A second concurrency race, structurally identical to the one above but one
  level up: login's password check is a read-then-compare, and without this
  lock a session could be created on a credential (or a session set) that a
  concurrent password-reset or logout-all had just invalidated. Full flows in
  `05-API-CONTRACTS.md` §A.3.
- **Email verification and password reset are first-class, token-backed
  flows**, each with its own table (`email_verification_tokens`,
  `password_reset_tokens`) — single-use (`consumed_at`), short-lived
  (`expires_at`), and deliberately *not* reusing the `refresh_tokens` table,
  since the lifecycle and semantics differ. **A verification-token replay is
  idempotent-success; a reset-token replay is a hard error — deliberately
  different, since a reset token authorizes a credential mutation and a
  verification token only flips an informational flag.**
- **Registration auto-logs the user in; email verification is informational-
  only in v1 — APPROVED.** No feature is gated on `email_verified_at`. (This
  resolves the open question previously flagged in
  `01-PRODUCT-REQUIREMENTS.md`.) **Still open, product-level, not technical**:
  what verification is actually *for* in v1 given nothing is gated on it.
- **Password hashing: Argon2id — APPROVED.** OWASP's current recommended
  default for new systems. Exact parameters (memory cost, iterations) remain
  **PROPOSED**.
- **Token cleanup**: no DB-enforced purge of expired tokens. A scheduled job
  deletes rows from all three token tables where `expires_at` is more than
  30 days in the past, purely to keep tables small — expired tokens are
  already unusable at auth time regardless of whether they've been purged.
  The same job sweeps lingering expired `grace_ciphertext` values as routine
  hygiene — correctness there never depends on the sweep running on time
  (see `05-API-CONTRACTS.md` §A.3).

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
- **The same backend-only rule applies to email-provider credentials**
  (verification, password-reset, and resend-verification emails) — sent via
  an `EmailProvider` interface mirroring the Groq pattern, approved as an
  approach in `03-TECHNOLOGY-STACK.md`; the concrete production vendor is
  deferred, not a security-relevant decision in itself.

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

- Argon2id work-factor parameters (memory cost, iterations) — algorithm itself is now
  approved.
- JWT signing algorithm/library, and the exact access-token (proposed 15 min) /
  refresh-token (proposed 30 days) / grace-window (proposed 10s) / chain-walk-depth
  (proposed 3) numeric values — mechanisms approved, numbers pending.
- Rate-limiting numeric values — categories and the in-memory (no Redis/Celery)
  mechanism are now approved (`05-API-CONTRACTS.md` §B.1); exact limits are not.
- **Resolved this round**: email verification does not block login or gate any
  feature — see "Approved auth model" above. (Previously flagged as open in
  `01-PRODUCT-REQUIREMENTS.md`; now resolved there too.)
- **Resolved this round**: CORS policy and CSRF defenses for the dashboard — specified
  in `05-API-CONTRACTS.md` §A.2 (origin allow-listing, `SameSite=Strict`, the
  `Content-Type: application/json` requirement on cookie-setting endpoints).
- Whether Postgres row-level security (RLS) should be added later as
  defense-in-depth on top of the backend-level ownership checks — noted as a
  possible future hardening step, not required now.
- Production email-provider vendor selection (interface approach is approved; the
  vendor itself is deferred — see `03-TECHNOLOGY-STACK.md`).
