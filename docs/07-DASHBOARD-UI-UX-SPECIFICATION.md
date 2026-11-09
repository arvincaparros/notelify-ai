# Notelify AI — Dashboard UI/UX Specification

**Status:** LARGELY NOT YET DESIGNED. Only the technology choice, the
dashboard's architectural role, and the data it must surface (derived from
the approved database design) have been discussed. No UI/UX brainstorming
session has happened yet.
**Last updated:** 2026-11-09

## What is approved

- **Technology**: React, TypeScript, Mantine UI (given stack).
- **Architectural role**: a pure REST client over the backend. It does not
  hold a real-time connection to an in-progress meeting — live transcription
  is an extension-only surface (see `00-PRODUCT-OVERVIEW.md` and
  `02-SYSTEM-ARCHITECTURE.md`). The dashboard is where a user reviews
  meeting history *after* the fact.
- **Core purpose**: let users manage meeting notes and review meeting
  history through a surface separate from the extension.

## Data the dashboard will need to surface (derived from `04-DATABASE-DESIGN.md`)

This is not a UI design — it is the known data shape the eventual UI/UX work
must account for:

- Meeting list/history: title, start/end time, status
  (`recording`/`finalizing`/`summarizing`/`completed`/`failed`), per
  `meetings`.
- Meeting detail view: full transcript (ordered, with `tab`/`mic` source
  attribution), AI summary (`summary_text` and the structured
  `summary_structured` output), decisions and action items (each with
  optional evidence excerpt/link back to a transcript moment), and the
  user's own freeform notes (`meeting_notes`, distinct from the AI summary).
- Action item state: each action item has an owner (free text, optional),
  due date (optional), and an `open`/`done` status a user presumably needs
  to toggle.
- Account/usage surface: current quota usage relative to the plan tier's
  monthly limit (`quota_minutes_used` / `quota_minutes_per_period`), and
  whether a given meeting was cut short by `quota_exceeded_at`.
- Auth screens implied by `08-SECURITY-AND-AUTHENTICATION.md`: login,
  signup, email verification, password reset request/completion.

## Unresolved / not yet designed

Essentially everything about the actual UI/UX is open:

- Information architecture (navigation structure, how meeting history,
  meeting detail, and account/usage screens relate).
- Visual design, layout, and Mantine component choices for each screen.
- How a `failed` meeting (e.g., `failure_reason='summarization_failed: ...'`)
  or a quota-cut-short meeting is communicated to the user.
- How transcript evidence links for decisions/action items are presented
  (e.g., jump-to-transcript-moment interaction).
- Empty states, loading states, and error states for every screen.
- Whether/how a user edits or deletes a meeting from the dashboard, beyond
  what's implied by the API surface in `05-API-CONTRACTS.md` (itself
  unresolved).
- Accessibility requirements beyond what Mantine provides by default.
- Responsive/mobile-web behavior, if any is intended.

## Recommended next step

Run a dedicated UI/UX brainstorming session for the dashboard once
`05-API-CONTRACTS.md` has been resolved (the UI's shape should follow the
confirmed API surface, not precede it).
