# Notelify AI — Chrome Extension Specification

**Status:** PARTIALLY APPROVED — component responsibilities, MV3 constraints,
and durable-state requirements are approved; exact manifest permissions,
message-passing schemas, and UI layout are not yet specified (see
"Unresolved" below).
**Last updated:** 2026-11-09

## Platform constraint driving this design

Manifest V3 service workers are **non-persistent** — they can be killed after
roughly 30 seconds of idle time and must never be assumed to remain alive for
the duration of a recording session. They also cannot run `MediaRecorder` or
hold long-lived media streams directly. This is why capture logic lives in a
Chrome **Offscreen Document** instead, which Chrome keeps alive for as long
as the extension needs it for an active purpose (not subject to the same
idle-kill behavior as the service worker).

## Component responsibilities (approved)

### Popup / Side Panel
UI only. Start/stop controls, live transcript display, upload-failure
indicator. Holds no audio-handling logic and no durable state of its own —
everything it shows is relayed to it by the service worker / offscreen
document.

### Service Worker — lifecycle coordinator only
- Obtains the `tabCapture` stream ID, but only after an explicit user
  interaction (required by the `tabCapture` API).
- Creates and closes the Offscreen Document.
- Relays commands and status messages between the popup and the offscreen
  document.
- **Recovers coordination state after its own restarts** — it must never
  assume continuity. On wake, it re-reads persisted state (current
  `meeting_id`, whether a capture session is active) rather than relying on
  in-memory variables that a restart would have wiped.
- Does **not** touch `MediaRecorder`, audio streams, chunk generation,
  uploads, or retry logic — all of that belongs to the offscreen document.

### Offscreen Document — owns all capture and upload work
- Microphone capture via `getUserMedia`.
- Tab audio capture via the stream ID handed off by the service worker.
- Two independent `MediaRecorder` instances (one per source), each
  stopped/restarted every ~7 seconds to produce a self-contained audio file
  per chunk. *Accepted trade-off*: a sub-200ms gap at each restart boundary,
  versus the complexity of a lossless continuous-capture approach (e.g. an
  `AudioWorklet`), which is deferred, not built in v1.
- Chunk generation and tagging: client-generated `chunk_id` (UUID), a
  monotonic `sequence_number` per `(meeting_id, source)`, `source`
  (`tab`|`mic`), and `started_at`/`ended_at` timestamps anchored to meeting
  start.
- Asynchronous chunk uploads, with up to 3 concurrent in-flight uploads, so a
  slow chunk never blocks the next recording segment.
- Upload retry and recovery coordination: exponential backoff (1s → 16s,
  capped at 5 client-side attempts) before a chunk moves to a durable
  failed-upload buffer with a manual-retry UI affordance.
- Lives for the whole capture session (unlike the service worker), which is
  why it — not the service worker — is the right place for this logic.

## Durable extension-side state (IndexedDB) — approved

The offscreen document persists the following to IndexedDB, so state survives
both its own and the service worker's restarts:

- Current `meeting_id`.
- Audio chunk IDs and sequence numbers (per source).
- Pending-upload chunks not yet acknowledged by the backend.
- Upload status and retry metadata (attempt count, last attempt time,
  backoff state) per chunk.
- Expected chunk counts per audio source, used when building the `finalize`
  request's manifest.

## Chunk lifecycle, from the extension's side (approved)

1. Record ~7s of audio per stream, restart `MediaRecorder` to seal the chunk.
2. Tag with `chunk_id`, `sequence_number`, `source`, `started_at`/`ended_at`.
3. Upload asynchronously (up to 3 concurrent), independent of ongoing
   recording.
4. On failure: retry with backoff, then buffer durably in IndexedDB.
5. On success: display the returned transcript text in the popup, buffered
   by `sequence_number` so out-of-order server responses still render in the
   correct chronological order.
6. On "stop": flush the failed-chunk buffer (bounded retry window), then
   call `finalize` with the expected chunk counts per source — this request
   never assumes every chunk has already been acknowledged; the backend's
   reconciliation sweep (see `04-DATABASE-DESIGN.md`) is what actually waits
   for and resolves in-flight work.

## Unresolved / not yet specified

- Exact `manifest.json` permissions list (`tabCapture`, `offscreen`,
  `storage`, host permissions, etc.) — the capabilities are implied by the
  design above, but the manifest itself hasn't been written.
- Exact message-passing protocol/schema between popup ↔ service worker ↔
  offscreen document (message shapes, command names).
- Exact IndexedDB schema (object store names, indexes) — the *contents*
  required are listed above; the physical schema is not yet designed.
- UI layout/wireframes for the popup or side panel.
- Final values for the retry backoff curve, concurrent-upload cap, and
  chunk duration — current numbers (3 concurrent, 1s–16s/5 attempts, ~7s
  chunks) are provisional engineering estimates from the architecture
  discussion, not validated against real usage.
- Whether the live transcript UI is a popup, a side panel, or configurable —
  "popup/side panel" was approved as the display *surface* (as opposed to
  the dashboard), without picking one of the two Chrome extension UI
  surfaces specifically.
