# Notelify AI — Product Overview

**Status:** APPROVED
**Last updated:** 2026-11-09

## What it is

Notelify AI is an AI-powered meeting assistant made of five parts: a Chrome browser
extension, a web dashboard, a Python FastAPI backend, a PostgreSQL database, and
AI transcription/summarization services. It captures audio from a meeting the
user is already participating in in their browser, transcribes it live, and
produces a summary, decisions, and action items after the meeting ends —
**without an AI bot joining the call as a participant.**

## Core value proposition

- No bot joins the meeting — capture happens from the user's own browser tab.
- Capture is user-initiated: the user explicitly starts and stops it.
- A live transcript is visible while the meeting is happening.
- A summary, decisions, and action items are generated automatically once the
  meeting ends.
- A web dashboard gives a central place to review meeting history across
  sessions.

## v1 scope boundaries (approved)

These were resolved through explicit requirements discussion and apply unless
a later spec revision changes them:

- **Capture surface — browser tab only.** Audio capture uses Chrome's
  `tabCapture` API. Native desktop meeting apps (the standalone Zoom/Teams
  clients) are explicitly out of scope for v1 — supporting them would require
  a separate native helper application outside what a Chrome extension can do.
- **Platform support — generic, not platform-specific.** A single manual
  "start capture" control works on any tab, which already covers Meet,
  Zoom-web, and Teams-web today without per-platform code. There is no
  platform detection, DOM scraping, or per-platform content script in v1.
  Platform-specific smarts (auto-detecting a meeting, pulling participant
  names from the page) are an explicit future phase.
- **Two separate audio streams.** Tab audio and microphone audio are captured
  and processed independently (not mixed into one stream), enabling "me" vs.
  "meeting" speaker attribution.
- **Live transcription has a few seconds of lag, not word-level streaming.**
  This is a direct consequence of Groq Whisper being a batch/file-upload API
  rather than a persistent streaming socket. Chunks (~7s each) are uploaded
  and transcribed near-real-time.
- **Live transcript displays in the extension only.** The web dashboard is a
  post-hoc review surface; it does not receive a real-time feed of an
  in-progress meeting.
- **No raw audio retention.** Audio is discarded once transcribed. Only the
  text transcript is stored.
- **Multi-user SaaS from day one.** Each user has their own account and sees
  only their own data, even though initial usage may be a single person.
- **Local Docker Compose deployment only.** No cloud deployment or managed
  infrastructure in this phase.

## Explicitly deferred (not v1)

- Native desktop app audio capture (standalone Zoom/Teams clients).
- Platform-specific meeting detection / DOM scraping per platform.
- Multi-client real-time synchronization (e.g., the dashboard watching a live
  transcript as it's produced).
- Redis/Celery or any distributed task queue/worker infrastructure.
- Cloud deployment and its associated infrastructure (managed Postgres,
  secrets management, CI/CD pipelines).

## Document map

| Doc | Purpose |
|---|---|
| `01-PRODUCT-REQUIREMENTS.md` | Functional & non-functional requirements, acceptance criteria |
| `02-SYSTEM-ARCHITECTURE.md` | Components, data flow, chunk lifecycle, diagrams |
| `03-TECHNOLOGY-STACK.md` | Approved technology choices |
| `04-DATABASE-DESIGN.md` | Full schema, transaction flows, concurrency design |
| `05-API-CONTRACTS.md` | Backend API surface (**not yet designed** — see doc) |
| `06-CHROME-EXTENSION-SPECIFICATION.md` | Extension architecture and responsibilities |
| `07-DASHBOARD-UI-UX-SPECIFICATION.md` | Dashboard UI/UX (**largely not yet designed**) |
| `08-SECURITY-AND-AUTHENTICATION.md` | Auth model, token handling, ownership enforcement |
| `09-TESTING-STRATEGY.md` | Testing approach (**draft, pending approval**) |
| `10-IMPLEMENTATION-ROADMAP.md` | Phased roadmap (**draft, pending approval**) |

Process rules for AI-assisted implementation (Specification-Driven
Development, phase gating, conflict resolution between these documents) live
in the root-level `CLAUDE.md`, not in a numbered doc — it is read
automatically by Claude Code at the start of every session.
