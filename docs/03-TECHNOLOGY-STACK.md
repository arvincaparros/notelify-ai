# Notelify AI — Technology Stack

**Status:** APPROVED
**Last updated:** 2026-11-09

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

## Unresolved / not yet decided

- Specific password-hashing algorithm (bcrypt vs. argon2, work factor) — not
  yet chosen.
- Specific JWT signing algorithm/library, access-token lifetime, and
  refresh-token lifetime — not yet numerically decided.
- Frontend build tooling (Vite vs. other) for the extension and dashboard —
  not yet decided; React + TypeScript + Mantine are fixed, the bundler is
  not.
- Testing frameworks (e.g., pytest for backend, a JS test runner for
  extension/dashboard) — not yet chosen; see `09-TESTING-STRATEGY.md`
  (draft).
