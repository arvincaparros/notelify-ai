# Notelify AI — Technology Stack

**Status:** APPROVED
**Last updated:** 2026-11-10

## Given (specified by product owner, not negotiated)

| Layer | Technology |
|---|---|
| Extension UI / Dashboard UI | React, TypeScript |
| Extension platform | Chrome Manifest V3 |
| UI component library | Mantine UI |
| Backend framework | Python, FastAPI |
| Database | PostgreSQL |
| ORM | SQLAlchemy |
| Migrations | Alembic |
| Transcription provider | Groq Whisper |
| Containerization | Docker |

## Decided during architecture brainstorming

- **PostgreSQL version: 15 or later is required.** The schema relies on
  column-scoped `ON DELETE SET NULL (column)` on composite foreign keys,
  added in Postgres 15.
- **Summarization/LLM provider: Groq-hosted LLM (e.g. Llama 3.3) by default,
  behind a provider interface.** Not explicitly specified in the original
  stack, so it was resolved during brainstorming. The summarization call is
  abstracted behind a small interface so swapping to Anthropic Claude or
  another provider later is a configuration change, not a rewrite. Same
  pattern applies to the transcription provider (Groq Whisper today, behind
  an equivalent interface) per explicit requirement.
- **No Redis, no Celery, no distributed worker infrastructure in v1.**
  Summarization job scheduling and retry/lease logic live entirely in
  PostgreSQL (see `04-DATABASE-DESIGN.md`), designed to extend to a real
  queue later without a schema change, but not built now.
- **Authentication: JWT access tokens (short-lived) + hashed refresh tokens
  stored in Postgres (revocable).** Resolved during the security/auth
  discussion to support multi-user SaaS with the ability to log a user out
  / revoke a compromised session, which a purely stateless JWT scheme
  wouldn't allow.
- **Deployment: Docker Compose, local only, for v1.** No cloud target
  (AWS/GCP/Fly.io/etc.) is in scope yet — explicitly deferred.
- **Password hashing: Argon2id — APPROVED.** OWASP's current recommended default for
  new systems. Exact parameters (memory cost, iterations) remain unresolved, below.
- **Email sending: an `EmailProvider` interface — APPROVED as an approach**, mirroring
  the same provider-interface pattern already used for Groq Whisper/LLM. For local
  development, a self-hosted catch-all SMTP tool (e.g. Mailpit) runs as another Docker
  Compose service, sending nothing real. The production vendor (e.g. SendGrid,
  Postmark, Amazon SES, Resend) is a separate, deferred decision — none of it changes
  the API contracts, since it's entirely behind the interface. Required because
  registration, password reset, and resend-verification all depend on *something*
  sending mail; previously this project had no document even flagging that gap.
- **Backend test framework: pytest — APPROVED**, minimum scope for Phase 1; see
  `09-TESTING-STRATEGY.md`.
- **Database connectivity: async SQLAlchemy — APPROVED** (Phase 0 technical
  review). The FastAPI application uses async SQLAlchemy sessions throughout,
  via the `asyncpg` driver, for all application database operations. Alembic
  migrations run separately, synchronously, via the `psycopg` driver — Alembic
  itself is not async, so it connects directly with its own sync engine rather
  than through the app's async session machinery. `Settings.sync_database_url`
  (`backend/app/config.py`) derives the Alembic URL from the same
  `DATABASE_URL`, swapping only the driver scheme, so the two are never
  configured independently. This does not change the approved database
  architecture (schema, transaction flows, lock ordering) — it fixes the
  driver/runtime pairing used to reach it.

### Revision history

- 2026-11-10: Added the async SQLAlchemy (`asyncpg`) / sync Alembic
  (`psycopg`) driver decision above, per Phase 0 technical review. No prior
  entry existed for this; it was an implementation detail that had not yet
  been recorded as an approved decision.

## Unresolved / not yet decided

- Argon2id work-factor parameters (memory cost, iterations).
- Specific JWT signing algorithm/library; access-token lifetime (proposed 15 min),
  refresh-token lifetime (proposed 30 days) — mechanism approved, numbers not.
- Production email-provider vendor selection (interface approach is approved, above).
- Frontend build tooling (Vite vs. other) for the extension and dashboard —
  not yet decided; React + TypeScript + Mantine are fixed, the bundler is
  not.
- JS/TS test runner for extension/dashboard — not yet chosen; see
  `09-TESTING-STRATEGY.md`.
