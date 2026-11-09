# CLAUDE.md — Notelify AI Development Instructions

This file is the persistent instruction set for any AI-assisted work
(Claude Code, Qoder, or otherwise) on this repository. It governs *process*.
Technical content lives in `docs/` — see the hierarchy below.

## What Notelify AI is

An AI-powered meeting assistant: a Chrome extension, a web dashboard, a
Python FastAPI backend, PostgreSQL, and AI transcription/summarization
services. It captures audio from a meeting the user is already in, inside
their own browser tab — **no AI bot joins the call** — transcribes it live,
and produces a summary, decisions, and action items once the meeting ends.
Full product detail: `docs/00-PRODUCT-OVERVIEW.md` and
`docs/01-PRODUCT-REQUIREMENTS.md`.

## Specification-Driven Development (SDD) — required workflow

This project is built from written specifications, not from memory of past
conversations. The `docs/` directory is the source of truth.

- **Before any implementation task, read the relevant spec documents.**
  At minimum `docs/02-SYSTEM-ARCHITECTURE.md`, plus whichever of
  `03-TECHNOLOGY-STACK.md`, `04-DATABASE-DESIGN.md`, `05-API-CONTRACTS.md`,
  `06-CHROME-EXTENSION-SPECIFICATION.md`,
  `07-DASHBOARD-UI-UX-SPECIFICATION.md`, or `08-SECURITY-AND-AUTHENTICATION.md`
  bears on the task. Do not rely on recollection of an earlier chat — these
  files are authoritative, a summary of one is not.
- **Implement to the approved spec, not around it.** Follow the documented
  architecture, approved technology choices, the database design's exact
  transaction flows and lock ordering, and the API contracts (once
  `05-API-CONTRACTS.md` is resolved — it currently is not).
- **No unauthorized architectural changes or scope expansion.** If a task
  seems to need something undocumented (a new table, endpoint, dependency,
  permission, or a deviation from an approved flow), **stop and raise it**
  instead of deciding unilaterally and continuing. Several docs are marked
  `DRAFT`/`NOT YET DESIGNED`/`unresolved` in places — hitting one of those
  gaps mid-task is expected; surfacing it is the correct response, not
  quietly filling it in.
- **Tests are part of the task, not an afterthought.** Write them alongside
  the implementation, following `docs/09-TESTING-STRATEGY.md`. Run the
  relevant tests and observe them passing before reporting the task
  complete — this matters especially for the database's concurrency/
  idempotency guarantees, which were corrected multiple times during design
  review and must not silently regress.
- **Every completed task or phase gets an implementation report**: what was
  built, which tests ran and their results, any deviation from the specs
  (and why), and anything discovered that should update a doc.

## Phased development — explicit approval required

Phases are defined in `docs/10-IMPLEMENTATION-ROADMAP.md` (currently a
draft). Rules:

1. Implement only the current, explicitly approved phase.
2. Finishing a phase is **not** implicit permission to start the next one.
   Stop and wait for explicit sign-off before moving on — the same gating
   discipline used throughout this project's design review.
3. If the roadmap itself is still a draft when a phase is reached, that
   phase's scope must be explicitly approved before work starts, same as
   any other undocumented decision.

## Documentation hierarchy and conflict resolution

- `CLAUDE.md` (this file) governs **process**: workflow, phase gating,
  reporting, and how to resolve conflicts. It does not contain technical
  specifications.
- `docs/00`–`docs/10` govern **content**, roughly in dependency order:
  product vision → requirements → architecture → tech stack → database
  design → API contracts → extension spec → dashboard spec → security →
  testing → roadmap. A later-numbered doc builds on earlier ones; it does
  not override them.
- **Status matters more than order.** Each doc states its status at the
  top (`APPROVED`, `PARTIALLY APPROVED`, `DRAFT / PROPOSED`, or
  `NOT YET DESIGNED`). An `APPROVED` statement always takes precedence over
  a `DRAFT` one — a draft doc (currently `05`, `07`, `09`, `10`) is a
  starting point for review, never a substitute for an approval that hasn't
  happened.
- **If two documents appear to genuinely conflict** (not just differ in
  level of detail — a detailed doc like `04-DATABASE-DESIGN.md` naturally
  says more than the overview in `02-SYSTEM-ARCHITECTURE.md`, which is not a
  conflict): stop and surface the discrepancy for a decision, rather than
  picking a side. Do not silently resolve it in code.
- **If an approved decision changes**, update the specific `docs/` file in
  the same piece of work, and record *why* — see `04-DATABASE-DESIGN.md`'s
  "Revision history" section for the pattern to follow. Never edit history
  silently; append reasoning the way that document does.

## Git and documentation maintenance practices

- Keep documentation and code in sync: a change to approved architecture,
  database design, or API contracts is committed together with (or
  immediately alongside) the corresponding `docs/` update — docs must never
  be left describing a decision the code has already moved past.
- Commit messages should make clear which phase/doc area a change belongs
  to.
- No destructive git operations (force-push, history rewriting, hard resets
  discarding uncommitted work) without the user's explicit request for that
  specific action.
- Never skip hooks or verification steps to force a commit through — fix
  the underlying issue instead.
