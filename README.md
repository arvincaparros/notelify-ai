# Notelify AI

AI-powered meeting assistant -- Chrome extension, web dashboard, FastAPI backend,
PostgreSQL, Groq-based transcription/summarization. Full product and architecture
documentation lives in [`docs/`](./docs); process rules for working on this repo are
in [`CLAUDE.md`](./CLAUDE.md).

**Current state: Phase 0 (project scaffolding) only.** No authentication, meeting
management, audio capture, transcription, or summarization is implemented yet --
see `docs/10-IMPLEMENTATION-ROADMAP.md` for the phase plan.

## Prerequisites

- Docker and Docker Compose
- Node.js 20+ (for the dashboard and, later, the extension)
- Python 3.12+ (only needed if running the backend outside Docker)

## First-time setup

```bash
cp .env.example .env
cp dashboard/.env.example dashboard/.env.local
```

Edit `.env` if you want different local Postgres credentials or ports -- the
defaults work as-is for local development.

## Running the backend + database

```bash
docker compose up --build
```

This starts:
- `postgres` on `localhost:5432` (credentials from `.env`)
- `backend` (FastAPI) on `http://localhost:8000`

Verify it's up:

```bash
curl http://localhost:8000/health
# {"status":"ok","database":"connected"}
```

## Running the dashboard

The dashboard runs on the host via Vite's dev server, not inside Docker --
simpler hot-reload, and nothing about it needs containerizing yet.

```bash
cd dashboard
npm install
npm run dev
```

Opens on `http://localhost:5173`.

## Loading the Chrome extension

Phase 0 only provides the manifest and placeholder entry points (no capture or
auth logic yet):

1. Open `chrome://extensions`
2. Enable Developer mode
3. "Load unpacked" -> select the `extension/` directory

## Running backend tests

Requires Postgres to be reachable (via `docker compose up -d postgres`, or the
full stack):

```bash
cd backend
pip install -e ".[dev]"
pytest
```

## Database migrations

Alembic is configured but **no migrations exist yet** -- Phase 0 deliberately
stops short of defining any application tables (see `docs/10-IMPLEMENTATION-ROADMAP.md`,
Phase 1). Once Phase 1 adds models:

```bash
cd backend
alembic revision --autogenerate -m "..."
alembic upgrade head
```

## Project layout

```
backend/     FastAPI app, SQLAlchemy models, Alembic migrations, pytest tests
dashboard/   React + TypeScript + Vite web dashboard
extension/   Chrome Manifest V3 extension (service worker, offscreen doc, popup, side panel)
docs/        Approved specifications -- read before changing any of the above
```
