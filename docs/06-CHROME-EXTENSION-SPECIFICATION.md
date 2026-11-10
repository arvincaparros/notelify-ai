# Notelify AI — Chrome Extension Specification

**Status:** PARTIALLY APPROVED — component responsibilities, MV3 constraints,
durable-state requirements, and authentication ownership (this round) are approved;
exact manifest permissions, message-passing schemas, and UI layout are not yet specified
(see "Unresolved" below).
**Last updated:** 2026-11-10

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

### Service Worker — lifecycle and session coordinator
- Obtains the `tabCapture` stream ID, but only after an explicit user
  interaction (required by the `tabCapture` API).
- Creates and closes the Offscreen Document.
- Relays commands and status messages between the popup and the offscreen
  document.
- **Owns authentication coordination and refresh-token rotation** (approved
  this round — see "Authentication ownership" below). This extends, rather
  than contradicts, "coordinator, not business logic": holding and refreshing
  session credentials is session-lifecycle coordination, not audio/chunk
  processing — and it genuinely belongs here rather than in the offscreen
  document, because an auth session spans many recording sessions, while an
  offscreen document's lifetime is scoped to one.
- **Recovers coordination state after its own restarts** — it must never
  assume continuity. On wake, it re-reads persisted state (current
  `meeting_id`, whether a capture session is active, and the current tokens
  from `chrome.storage.local`) rather than relying on in-memory variables
  that a restart would have wiped.
- Does **not** touch `MediaRecorder`, audio streams, chunk generation,
  upload execution, or chunk-retry logic — all of that belongs to the
  offscreen document.

### Offscreen Document — owns all capture and upload execution
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

This store holds capture/upload state only — **not** auth tokens. The refresh token
lives separately in `chrome.storage.local`, owned by the service worker (see
"Authentication ownership" below), not in the offscreen document's IndexedDB store.

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

## Authentication ownership (APPROVED, this round)

**The gap this closes**: a recording session routinely outlives a single access token
(proposed 15-minute lifetime, `05-API-CONTRACTS.md` §B.1) — a normal meeting can easily
run longer. Until this round, no document said which extension component is responsible
for noticing that, refreshing the token, or handling an upload that fails because it
didn't.

### Responsibility model

- **Refresh token**: lives in `chrome.storage.local`, read and written **only** by the
  service worker. This is an architectural convention, not a hard OS-level permission
  boundary — Chrome's `storage.local` is shared across the whole extension, so nothing
  technically stops the offscreen document from reading that key directly; the
  guarantee here is "nothing else ever does," enforced by code discipline. The offscreen
  document never sees the refresh token at all, which bounds the blast radius if its
  context were ever compromised.
- **Access token**: held by the service worker (in memory, backed by the refresh token
  in storage — never persisted on its own). The offscreen document holds no long-lived
  copy; it asks the service worker for a current token **before every upload attempt**
  via `chrome.runtime.sendMessage`. This is a local message-pass, not a network call,
  so asking every ~7 seconds (one chunk interval) is cheap — simpler and more robust
  than the offscreen document trying to track its own token's expiry independently.
  **PROPOSED**: an alternative where the offscreen document caches the token locally and
  only re-asks on a 401 was considered and not chosen, for this reason — flagging the
  choice itself as approved, not the specific "ask every time" cadence as the only
  possible design.
- **Refresh trigger**: the service worker refreshes proactively when a request for the
  current token finds it within a buffer window of expiry (**PROPOSED**: 30 seconds),
  rather than waiting for a 401 to occur in the common case.

### Single-flight refresh (no client-side rotation races)

The offscreen document never calls `POST /auth/refresh` itself — every access-token
request goes through the service worker's message handler, which holds a single
in-memory "refresh in progress" promise: a concurrent request for a token while a
refresh is already in flight awaits that same promise rather than starting a second
one. This fully eliminates *client-side* rotation races for this extension instance.
**What this does and doesn't cover**: it doesn't need to cover a user also having the
dashboard open in a browser tab, refreshing independently — that cross-context race is
already handled server-side by the family-lock and grace-period mechanism in
`05-API-CONTRACTS.md` §A.3, which this design deliberately leans on rather than
re-solving client-side.

**Why losing this in-memory promise on a service-worker restart is safe, not a gap**:
if the service worker is killed mid-refresh — after sending the HTTP request but before
processing the response — the backend's own rotation may have already committed. On
restart, the service worker's only record of the old (now possibly-already-rotated)
refresh token is whatever is in storage. The *next* refresh attempt using that token
lands exactly on the already-approved grace-period path in `05-API-CONTRACTS.md` §A.3:
if the restart was quick (within the grace window), the legitimate client transparently
receives the live replacement; if not, it gets `FAIL_GRACE_EXPIRED` — a benign
re-authentication prompt, not a security event. No extension-side recovery logic needs
to be built for this case — it's already covered by a mechanism designed for exactly
this kind of race.

### 401 handling and safe retry

If an upload attempt still receives a 401 despite the pre-emptive refresh above (clock
skew, or a revocation event — logout, logout-all, password-reset, or reuse-detection —
having happened elsewhere):
1. The offscreen document does **not** retry with the same access token.
2. It asks the service worker for a fresh one, which triggers a refresh attempt.
3. If that succeeds, it retries the **same** chunk upload once with the new token —
   safe because chunk uploads are already idempotent by `chunk_id`
   (`04-DATABASE-DESIGN.md`); a retry after a token swap is indistinguishable from any
   other retried upload.
4. If the refresh itself fails (the refresh token is dead — logged out or reuse-detected
   elsewhere), this is treated as an **unrecoverable auth failure**: uploads stop, the
   `MediaRecorder` instances stop (continuing to record without any ability to upload
   just grows the buffer unboundedly), the IndexedDB retry buffer is **preserved, not
   deleted** (same treatment as `quota_exceeded` in `04-DATABASE-DESIGN.md`), and the
   popup is signaled to prompt a fresh login. This mirrors the extension's existing
   quota-exceeded shutdown behavior rather than inventing a new failure pattern.

### Service-worker restart and offscreen-document disconnection

- **Service worker restart**: it is never assumed to hold any in-memory auth state
  across a restart — on waking, it reads the current tokens from `chrome.storage.local`
  on demand, the same "never assume continuity" principle already established for its
  lifecycle-coordination role. No explicit recovery step is needed beyond this, since it
  was already stateless with respect to anything not durably stored.
- **Offscreen document losing its connection to the service worker**: `chrome.runtime
  .sendMessage` to a currently-dead service worker causes Chrome to wake it automatically
  — this is platform behavior, not something this design needs to build. The offscreen
  document's own responsibility is limited to a reasonable timeout and retry on the
  message-pass call (mirroring its existing chunk-upload retry pattern), in case the
  wake-and-respond cycle takes a moment — not a bespoke reconnection protocol.

### `GET_ACCESS_TOKEN` timeout — no response received at all

Distinct from a 401 (§"401 handling and safe retry" above), which assumes a response
*was* received saying the token didn't work: this covers the offscreen document asking
the service worker for a token and getting nothing back — a timeout, not an answer.

- **Bounded timeout**: the `GET_ACCESS_TOKEN` message-pass is given a timeout
  (**PROPOSED**, a few seconds) — if Chrome's automatic wake-up and the service worker's
  response don't land within it, the attempt is treated as failed, not left open
  indefinitely.
- **Bounded retry**: the offscreen document retries the message-pass a limited number
  of times with backoff (**PROPOSED** values — reusing the same backoff shape already
  defined for chunk-upload retries, rather than inventing a second retry policy), not
  an unbounded loop.
- **The chunk being uploaded when this happens is never lost**: it stays in the existing
  IndexedDB pending-upload/retry buffer ("Durable extension-side state" above) exactly
  as any other not-yet-acknowledged chunk would — this failure mode doesn't need its own
  storage handling, it falls straight into the mechanism that already exists for "upload
  didn't succeed yet."
- **No duplicate-upload risk**: however many `GET_ACCESS_TOKEN` attempts preceded it, a
  chunk retried once a token is eventually obtained is just an ordinary retried upload —
  already safe by construction, since chunk uploads are idempotent by `chunk_id`
  (`04-DATABASE-DESIGN.md`). Nothing new is required here beyond relying on that
  existing guarantee.
- **No indefinite retries**: once the bounded retry count above is exhausted without a
  single successful response, this funnels into the **same unrecoverable-auth-failure
  state already defined** in "401 handling and safe retry" (step 4) — uploads and
  `MediaRecorder` stop, the IndexedDB buffer is preserved rather than deleted, and the
  popup is signaled to prompt a fresh login. This is a deliberate reuse of an existing
  terminal state, not a second failure mode to design and maintain separately.

### Unresolved within this model

- The 30-second pre-emptive-refresh buffer and the "ask before every upload" cadence —
  **PROPOSED**, not validated against real usage.
- The `GET_ACCESS_TOKEN` message-pass timeout and its retry count/backoff — **PROPOSED**,
  not validated against real usage.
- Exact `chrome.runtime` message shapes for `GET_ACCESS_TOKEN` and its response — not
  yet designed, same category as the other message-passing schemas already listed below.

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
