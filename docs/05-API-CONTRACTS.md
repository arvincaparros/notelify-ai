# Notelify AI — API Contracts

**Status:** PARTIALLY APPROVED
- **Round 1 — API architecture, conventions, authentication transport, refresh-token
  concurrency, general idempotency mechanism: APPROVED.**
- Per-endpoint contracts (Rounds 2–8: Authentication, Meeting Management, Audio Chunk
  Processing endpoint-level detail, Transcript & Meeting Intelligence, Notes & Action
  Items, Usage/Quota/Search/History, final consistency review): **NOT YET DESIGNED.**

**Last updated:** 2026-11-09

This document is split into two parts: Part A is the architecture and conventions every
endpoint will follow (approved, below), and Part B is the per-endpoint surface (not yet
designed — see "Recommended next step" at the end). Nothing in Part B should be built
against until it goes through the same round-by-round review Part A did.

---

# Part A — API Architecture (APPROVED)

## A.1 API-wide conventions

| Aspect | Decision |
|---|---|
| Base URL | `/api/v1/...` — version in the URL path |
| JSON field naming | `snake_case` everywhere, matching DB column names directly |
| Datetime format | ISO 8601, UTC, e.g. `2026-11-09T14:32:00Z` |
| IDs | UUIDs as strings |
| Resource nesting | Meeting-scoped resources nest under `/meetings/{meeting_id}/...`; account-scoped resources live under `/account/...` |
| Single-resource success | The resource object directly as the JSON body — no `{"data": ...}` wrapper |
| List success | `{"items": [...], "next_cursor": "<opaque-string>|null"}` |
| Error response | `{"error": {"code": "...", "message": "...", "details": {}}}` |
| Pagination | Cursor-based everywhere (never offset/limit) |
| `GET /meetings` | Absorbs search, date filter, status filter, sort, and pagination via query parameters — no separate search endpoint |

### Error codes vs. chunk-processing reasons — kept structurally separate

`error.code` describes why the **request itself** failed (`unauthorized`,
`validation_error`, `not_found`, `rate_limited`, `internal_error`, `idempotency_key_reused_with_different_payload`,
`request_in_progress`, `refresh_token_reuse_detected`, `refresh_token_grace_expired`, ...).
`chunk_status` / `failure_reason` (chunk-upload responses only) describe the state of a
**chunk resource** — `quota_exceeded`, `meeting_closed`, `reconciliation_timeout`,
`max_attempts_exceeded`, `transcription_error`. A string may coincidentally appear in
both vocabularies, but they are never populated from the same code path: an API error
means "I couldn't process your request"; a `failure_reason` means "I processed your
request and durably recorded that this chunk didn't make it" — a success from the HTTP
layer's point of view.

### Status code conventions

| Status | Used for |
|---|---|
| 200 / 201 | Successful GET / successful creation |
| 202 | Chunk upload: an existing chunk currently has a live lease held by another in-flight attempt |
| 204 | Successful DELETE |
| 400 | Business-rule-level bad input that passes schema validation but is semantically invalid |
| 401 | Missing, invalid, or expired access token; also invalid/expired refresh token |
| 404 | Resource doesn't exist **or** exists but belongs to another user (never 403 for ownership — avoids leaking existence) |
| 409 | Resource-state conflicts outside the chunk/idempotency mechanisms (e.g. duplicate email on register); also a concurrent idempotent request still in flight |
| 422 | Request-schema validation failure (FastAPI/Pydantic default); also idempotency key reused with a different payload |
| 429 | Rate limit exceeded |
| 500 | Unhandled server error, generic body only — no internal exception detail ever serialized |

**201 responses include a `Location` header** pointing at the newly created resource —
a stated convention, not optional.

### Pagination requirements

- Stable ordering with a unique tie-breaker (e.g. `(started_at DESC, id DESC)` for
  meetings; `(created_at DESC, id DESC)` for notes; `(order_index ASC, id ASC)` for
  action items).
- Opaque cursors: base64-encoded `{sort_value, id}`, not signed — the authorization
  boundary (`user_id = current_user.id`) is enforced independently of cursor content,
  so tampering with a cursor cannot expose another user's data; signing would add
  complexity without closing a real vulnerability here.
- Maximum page size: capped (proposed 100), default (proposed 20) if omitted — **PROPOSED**,
  mechanism approved, numbers pending.
- The active filter/sort parameters are encoded into the cursor itself, so reusing a
  cursor with different filters is detected and rejected (400) rather than silently
  producing inconsistent results.
- Every paginated query is implicitly scoped by `user_id = current_user.id`.

## A.2 Authentication transport

### Dashboard
- Refresh token: `Set-Cookie: refresh_token=<token>; HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth/refresh; Max-Age=<refresh_ttl>`.
- Access token: returned in the response body, held in memory (not `localStorage`), sent via `Authorization: Bearer` on every call — identical handling to the extension.

### Chrome extension
- Refresh token: returned in the response body, stored in `chrome.storage.local`.
- Access token: identical `Authorization: Bearer` handling to the dashboard.

### Client-type detection
`POST /api/v1/auth/{register,login,refresh}` inspects the request's `Origin` header
against two explicit, server-configured allow-lists (dashboard origin(s), extension
origin(s) — `chrome-extension://<id>`). Matching the dashboard origin sets the cookie
and omits the refresh token from the body; matching an extension origin returns the
refresh token in the body and sets no cookie. The refresh endpoint itself accepts the
token from whichever transport is present — cookie first, falling back to a
`refresh_token` body field — so its core logic never branches on client type, only the
response-writing logic does.

### CORS
`Access-Control-Allow-Origin` echoes back only an allow-listed origin (never a
wildcard); `Access-Control-Allow-Credentials: true` for the dashboard's origin.
**Assumption, stated explicitly**: the dashboard and API are deployed as subdomains of
the same registrable domain (or both on `localhost` in local Docker Compose dev), which
is required for `SameSite=Strict` to deliver the cookie on cross-origin dashboard→API
calls. If a future production deployment puts them on genuinely different domains, this
assumption breaks and needs revisiting — not a concern for the current local-only v1
deployment target (`00-PRODUCT-OVERVIEW.md`).

### CSRF
`SameSite=Strict` is the primary defense. As defense-in-depth, the refresh/login/register
endpoints additionally require `Content-Type: application/json`, which a plain HTML
form (the classic no-CORS CSRF vector) cannot send.

### Logging hygiene (cross-cutting)
The `refresh_token` field is never logged on any response (login, register, refresh) by
request/response logging middleware, on any client.

## A.3 Refresh-token rotation and concurrency

### Rotation with reuse detection
Every successful `POST /auth/refresh` revokes the token just used and issues a new one.
Presenting an already-revoked token is a theft signal, **unless** it falls within a
short legitimate-concurrency grace window (below).

### Encrypted grace-period mechanism (chosen over client-side cross-tab coordination)
A hashed token (`token_hash`) cannot be reconstructed to hand back to a legitimate
concurrent racer. The chosen fix stores a short-lived, **reversibly encrypted** copy of
each newly-issued token (`grace_ciphertext`, `grace_expires_at`) on that token's own
row, readable only by application code holding a server-side symmetric key that never
appears in SQL or logs. This was chosen over client-side `BroadcastChannel`/Web-Locks
coordination because that alternative doesn't remove the need for this same
server-side logic (it only reduces how often it's exercised), while adding real
client-only complexity (leader-election, crash/missed-broadcast fallback) and covering
the dashboard only, not the extension.

**Grace window: 10 seconds — PROPOSED.** **Residual risk, explicit, not hidden**: the
mechanism hands the decrypted value to whoever asks within the window, with no identity
check beyond timing — if an attacker's replay of a stolen pre-rotation token and the
legitimate user's own next refresh land in the same ~10-second window, both receive the
same live replacement. A short window bounds the probability of this overlap; it cannot
make it zero. Outside the window, any reuse still triggers full family revocation, so a
stolen token's useful life is bounded to at most one rotation cycle plus this window,
never indefinite.

### Family-scoped advisory locking (closes a race discovered during review)

A family-wide revocation's `UPDATE ... WHERE family_id = :family_id AND revoked_at IS NULL`
scans at statement start and does not discover a successor row created by a concurrent
rotation *after* that scan began — meaning a compromised family's live, attacker-facing
token could survive the exact revocation meant to kill it. **Fix**: every operation that
touches a family — normal rotation, grace-period resolution, and family-wide revocation —
acquires a transaction-scoped advisory lock **first**, before reading or writing any
token row:

```sql
SELECT pg_advisory_xact_lock(hashtextextended(:family_id::text, 0));
```

Because only one of these three operation types can hold a given family's lock at a
time, whichever acquires it first runs to full completion before another can even begin
reading that family's state — eliminating the window entirely.

**Bootstrapping**: a family can't be locked before it's known which family it is, so
every flow starts with a deliberately unlocked, bootstrap-only lookup of `family_id`
from the presented token's row — never acted on directly — followed by the lock, then an
authoritative re-read that is what every subsequent decision is actually based on.

**Lock order for this subsystem**: (1) unlocked `family_id` bootstrap lookup, (2) the
advisory lock, (3) plain reads/writes — no per-row `FOR UPDATE` anywhere in this
subsystem; the family lock alone makes every read after it safe. This subsystem has no
lock-ordering interaction with any other part of the system (`idempotency_keys` is a
separate mutex scope; the `meeting → user → chunk` order in `04-DATABASE-DESIGN.md` is
an unrelated subsystem).

### Family-membership validation during chain traversal
At every hop of the chain-walk below, the newly-followed token's `family_id` is checked
against the originally-locked `family_id`. By construction (rotation always copies
`family_id` forward), this should never fail — the check exists as defense-in-depth
against a data-integrity bug. **A mismatch is treated as equivalent to reuse detection**
(the original family is revoked, the request fails) rather than silently trusted or
ignored, since encountering it means something is wrong enough not to trust the chain
further, and the conservative response is appropriate on a security-sensitive path.

### Bounded chain-walk for resolving a grace replay through multiple rotations

If the token a grace-period replay should resolve to has itself already been rotated
again (a second legitimate refresh happened before the first racer's reply caught up),
the walk follows `replaced_by_token_id` forward, bounded to **3 hops — PROPOSED**, with
three distinct outcomes:

- **`SUCCESS`** — found a currently-live token with a still-valid, still-decryptable
  grace copy. Returned, paired with a freshly minted access token.
- **`FAIL_GRACE_EXPIRED`** — benign: the live token naturally expired mid-walk, or its
  grace copy is no longer retrievable, or the hop budget was exhausted. **No security
  action taken.** The client re-authenticates normally, same as any ordinary expired
  session.
- **`FAIL_REUSE_DETECTED`** — a hop's own revocation fell outside *its* grace window, or
  it was revoked with no successor, or a family-membership mismatch was found (above).
  **Triggers full family revocation.**

Keeping these outcomes structurally distinct matters: a legitimate, slow-arriving racer
in an unlucky multi-hop scenario must not be logged out of every device the way a real
theft event would.

### Timestamp consistency within one rotation event

`now()` (`transaction_timestamp()`) is frozen at transaction start and does not advance
even if that transaction later blocks on a lock — a real risk for any comparison
evaluated right after a `SELECT ... FOR UPDATE`/lock wait. **Rule applied**: ordinary
audit timestamps (`created_at`-style fields, day/month-scale expiries) keep `now()`;
any short, second-scale comparison or anchor that a possibly-blocked transaction
measures elapsed time against uses `clock_timestamp()` instead. Additionally, one
rotation event captures `clock_timestamp()` **exactly once**, via a single leading
`SELECT`, and reuses that one value (`:rotation_ts`) for the old token's `revoked_at`
and the new token's `created_at`/`expires_at`/`grace_expires_at` — never four separate
evaluations for one logical moment.

### Corrected transaction orderings

**Normal rotation** (new row inserted *before* the old row references it, to satisfy
the `replaced_by_token_id → refresh_tokens(id)` foreign key within the same transaction):

```sql
BEGIN;
SELECT family_id FROM refresh_tokens WHERE token_hash = :presented_hash;
SELECT pg_advisory_xact_lock(hashtextextended(:family_id::text, 0));
SELECT clock_timestamp() AS rotation_ts;

SELECT id, revoked_at, expires_at FROM refresh_tokens WHERE id = :found_id;
-- revoked_at IS NULL AND expires_at > :rotation_ts -> genuinely live, proceed:

INSERT INTO refresh_tokens (id, user_id, family_id, token_hash, expires_at,
                            grace_ciphertext, grace_expires_at, created_at)
VALUES (:new_token_id, :user_id, :family_id, :new_token_hash,
        :rotation_ts + interval '30 days',
        :encrypted_grace, :rotation_ts + interval '10 seconds', :rotation_ts);

UPDATE refresh_tokens SET revoked_at = :rotation_ts, replaced_by_token_id = :new_token_id
WHERE id = :found_id;
COMMIT;
-- Return raw_new_token (held in application memory, never decrypted) + fresh access token.
```

`new_token_id`, the raw token, its hash, and its encrypted grace copy are all generated
in application code *before* this transaction opens.

**Grace-period chain-walk** (family lock already held; no per-row locking needed):

```sql
BEGIN;
SELECT family_id FROM refresh_tokens WHERE token_hash = :presented_hash;
-- not found at all -> 401 "invalid token", no family action.
SELECT pg_advisory_xact_lock(hashtextextended(:family_id::text, 0));

current := SELECT id, family_id, revoked_at, expires_at, replaced_by_token_id,
                  grace_ciphertext, grace_expires_at
           FROM refresh_tokens WHERE token_hash = :presented_hash;
hops := 0
loop:
    if current.family_id != :family_id:         -- defense-in-depth, see above
        UPDATE refresh_tokens SET revoked_at = clock_timestamp()
        WHERE family_id = :family_id AND revoked_at IS NULL
        COMMIT; return FAIL_REUSE_DETECTED

    if current.revoked_at IS NULL:
        if current.expires_at <= clock_timestamp():
            COMMIT; return FAIL_GRACE_EXPIRED
        if current.grace_ciphertext IS NOT NULL AND current.grace_expires_at > clock_timestamp():
            COMMIT; return SUCCESS(decrypt(current.grace_ciphertext))
        COMMIT; return FAIL_GRACE_EXPIRED
    else:
        if clock_timestamp() - current.revoked_at > interval '10 seconds':
            UPDATE refresh_tokens SET revoked_at = clock_timestamp()
            WHERE family_id = :family_id AND revoked_at IS NULL
            COMMIT; return FAIL_REUSE_DETECTED
        if current.replaced_by_token_id IS NULL:
            UPDATE refresh_tokens SET revoked_at = clock_timestamp()
            WHERE family_id = :family_id AND revoked_at IS NULL
            COMMIT; return FAIL_REUSE_DETECTED
        hops += 1
        if hops > 3:
            COMMIT; return FAIL_GRACE_EXPIRED
        current := SELECT id, family_id, revoked_at, expires_at, replaced_by_token_id,
                           grace_ciphertext, grace_expires_at
                    FROM refresh_tokens WHERE id = current.replaced_by_token_id
        continue
```

**Family-wide revocation** (single-timestamp, defensive against a theoretical multi-row match):

```sql
-- Family advisory lock already held by the calling flow.
WITH ts AS (SELECT clock_timestamp() AS now_ts)
UPDATE refresh_tokens SET revoked_at = ts.now_ts
FROM ts
WHERE family_id = :family_id AND revoked_at IS NULL;
```

## A.4 Chunk-upload response conventions

| Status | When |
|---|---|
| 201 | Any new `transcript_chunks` row — regardless of outcome (`transcribed`, retryably `failed`, or terminally rejected `quota_exceeded`/`meeting_closed`/`reconciliation_timeout`). Resource creation, not outcome, is the criterion. |
| 200 | Existing chunk resolution — cached `transcribed` result, or current state. |
| 202 | Existing chunk, live lease held by another in-flight attempt. |
| 400/422 | Invalid request (semantic / schema). |
| 401 | Invalid authentication. |
| 404 | Meeting missing or not owned by the caller. |

Response body shape, used uniformly regardless of status:

```json
{
  "chunk_id": "c1a2...",
  "sequence_number": 42,
  "source": "tab",
  "chunk_status": "transcribed",
  "text": "...transcribed text..." ,
  "failure_reason": null,
  "attempt_count": 1,
  "is_retryable": false
}
```

`chunk_status` ∈ {`transcribed`, `failed`, `processing`}. When `failed`,
`failure_reason` ∈ {`quota_exceeded`, `meeting_closed`, `reconciliation_timeout`,
`max_attempts_exceeded`, `transcription_error`}. `is_retryable` is `true` only for a
`transcription_error` that hasn't exhausted `max_attempts` — the extension's retry logic
acts on this single boolean field, not on string-matching `failure_reason`.

## A.5 General idempotency mechanism

Scope: `POST /meetings`, `POST /meetings/{meeting_id}/notes`,
`POST /meetings/{meeting_id}/action-items` only. Chunk upload and finalize keep their
own, already-approved, purpose-built idempotency from `04-DATABASE-DESIGN.md`
(`chunk_id` uniqueness + lease mechanics) — this mechanism does not apply there.

**Required header**: `Idempotency-Key`, required (not optional) on the three endpoints
above.

**Scope**: `(user_id, endpoint, resource_scope, key)`. `resource_scope` is the parent
resource id (`meeting_id`) for notes/action-items, or the sentinel `''` (never `NULL` —
Postgres treats every `NULL` as distinct in a `UNIQUE` constraint, which would silently
defeat the mechanism) for `create_meeting`, which has no parent.

| Endpoint | `endpoint` value | `resource_scope` |
|---|---|---|
| `POST /meetings` | `create_meeting` | `''` |
| `POST /meetings/{meeting_id}/notes` | `create_note` | `:meeting_id` |
| `POST /meetings/{meeting_id}/action-items` | `create_action_item` | `:meeting_id` |

**Fingerprint**: SHA-256 over a canonical JSON object containing both the relevant path
parameters and the normalized request body — a complete, self-contained description of
"what was actually requested," not just the body.

**Ownership checked before the idempotency transaction**: an invalid `meeting_id` is
rejected (404) before touching `idempotency_keys` at all, so a doomed request can never
burn a legitimate key for the full expiration window.

**Single-transaction design — why, precisely**: Postgres does not let one transaction
observe another's uncommitted row (no dirty read). A conflicting `INSERT`/`INSERT ...
ON CONFLICT` **blocks** until the other transaction concludes, then either fails (if it
committed) or succeeds as if first (if it rolled back). Putting reservation, resource
creation, and response storage in **one transaction** means a racing request only ever
observes one of two states: "doesn't exist" (safe to proceed) or "fully committed with a
stored response" (safe to replay) — there is no third, "in progress" state to handle,
which is also what makes crash recovery automatic: a dropped connection mid-transaction
triggers Postgres's own rollback, freeing the key with no separate lease/timeout
mechanism required.

```sql
BEGIN;
WITH attempt AS (
  INSERT INTO idempotency_keys (
    user_id, endpoint, resource_scope, key, request_fingerprint,
    response_status, response_body, response_headers, created_at, expires_at
  ) VALUES (
    :user_id, :endpoint, :resource_scope, :key, :fingerprint,
    NULL, NULL, NULL, now(), now() + interval '24 hours'
  )
  ON CONFLICT (user_id, endpoint, resource_scope, key) DO UPDATE SET
    request_fingerprint = EXCLUDED.request_fingerprint,
    response_status = NULL, response_body = NULL, response_headers = NULL,
    created_at = EXCLUDED.created_at, expires_at = EXCLUDED.expires_at
  WHERE idempotency_keys.expires_at < clock_timestamp()   -- expiry correctness, not cleanup-dependent
  RETURNING id
)
SELECT id FROM attempt;

-- Row returned (fresh key, or a reclaimed expired one) -> execute the real operation,
-- same transaction:
INSERT INTO meetings (...) VALUES (...) RETURNING id, ...;   -- or notes / action_items
UPDATE idempotency_keys SET response_status = :http_status, response_body = :response_json,
       response_headers = :response_headers_json
WHERE user_id = :user_id AND endpoint = :endpoint AND resource_scope = :resource_scope AND key = :key;
COMMIT;
-- Return :response_json (with :response_headers_json, e.g. Location) to the caller.

-- 0 rows returned -> a valid, non-expired reservation already exists, guaranteed fully
-- committed (never half-done, by the blocking behavior above):
SELECT response_status, response_body, response_headers, request_fingerprint
FROM idempotency_keys
WHERE user_id = :user_id AND endpoint = :endpoint AND resource_scope = :resource_scope AND key = :key;
COMMIT;  -- read-only
-- fingerprint matches  -> return the stored response verbatim.
-- fingerprint differs   -> 422, error.code = 'idempotency_key_reused_with_different_payload';
--                          original reservation and its stored response are left untouched.
```

**Expiration correctness, not cleanup-dependent**: the `WHERE expires_at < clock_timestamp()`
clause on the `DO UPDATE` *is* the correctness mechanism — a key reused after its logical
expiry, even while the row still physically exists, is correctly reclaimed and treated as
brand-new. The background cleanup job (same pattern as `08-SECURITY-AND-AUTHENTICATION.md`'s
token cleanup) is purely table-size maintenance and can run on any schedule, or be delayed,
with no behavioral difference.

**Response guarantees — semantic, not byte-identical**: JSONB does not preserve exact
JSON serialization (whitespace, numeric formatting, in some cases key order), so a
replay guarantees the same HTTP status, the same response data (equivalent structure),
no duplicate resource creation, and no re-execution of the original operation — not
byte-for-byte identity.

**`response_headers`**: stores any headers that must replay identically — in practice,
`Location` on a 201. Added specifically because storing status + body alone would silently
drop it on replay.

**Which outcomes persist vs. roll back**: a deliberate, well-formed failure the
application explicitly constructs (e.g. a 400/422 from business-rule validation inside
the operation) is caught, stored, and committed exactly like a success — a retry with
the same key+fingerprint correctly gets the same well-formed error back. An unhandled
exception is never caught into a response; it propagates and the transaction (reservation
included) rolls back automatically, so a retry is correctly treated as brand-new.

**Expiration window: 24 hours — PROPOSED.**

## A.6 Required schema additions (NOT YET APPLIED to `04-DATABASE-DESIGN.md`)

Per `CLAUDE.md`, the approved database design is not silently modified. The two
additions below are required to support this document's approved mechanisms and are
presented here for visibility; they are only merged into `04-DATABASE-DESIGN.md` on a
separate, explicit request to revisit that document.

```sql
-- Recommended shape for refresh_tokens, folded into migration 0003_users_and_auth's
-- original CREATE TABLE (not a later ALTER) -- the project has not been implemented yet,
-- so refresh_tokens has never held real rows; there is no backfill-safety concern to
-- design around, and ALTER TABLE ... ADD COLUMN ... DEFAULT gen_random_uuid() would in
-- any case assign a DIFFERENT value per existing row on a live table, which is wrong
-- for this field even in the abstract (family_id has no semantically correct default --
-- it's always either "new" at login or "copied from parent" at rotation).
CREATE TABLE refresh_tokens (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id              UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    family_id            UUID NOT NULL,                -- no column default; always application-supplied
    token_hash           TEXT NOT NULL,
    expires_at           TIMESTAMPTZ NOT NULL,
    revoked_at           TIMESTAMPTZ,
    replaced_by_token_id UUID REFERENCES refresh_tokens(id) ON DELETE SET NULL,
    grace_ciphertext     BYTEA,                         -- reversibly encrypted, short-lived only
    grace_expires_at     TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_refresh_tokens_user ON refresh_tokens(user_id);
CREATE INDEX idx_refresh_tokens_hash ON refresh_tokens(token_hash);
CREATE INDEX idx_refresh_tokens_family ON refresh_tokens(family_id);

-- New table, own migration (e.g. 0010_idempotency_keys) -- no pre-existing-row concern
-- since nothing has been deployed.
CREATE TABLE idempotency_keys (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id              UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    endpoint             TEXT NOT NULL,
    resource_scope       TEXT NOT NULL DEFAULT '',   -- parent resource id, or '' sentinel -- never NULL
    key                  TEXT NOT NULL,
    request_fingerprint  TEXT NOT NULL,
    response_status      INTEGER,
    response_body        JSONB,
    response_headers     JSONB,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at           TIMESTAMPTZ NOT NULL,
    UNIQUE (user_id, endpoint, resource_scope, key)
);
CREATE INDEX idx_idempotency_expiry ON idempotency_keys(expires_at);
```

Encryption key for `grace_ciphertext`: a server-side AES-256-GCM symmetric key from
environment/secrets config, loaded at startup, never written to the database and never
appearing in a SQL statement string. Encrypt/decrypt happen in application code only.

## A.7 Deferred — not part of this round, not applied

`04-DATABASE-DESIGN.md`'s existing `locked_until < now()` (three occurrences: Flow 3's
retry-claim, the reconciliation sweep, and by reference in the unified dispatch) and
`now() >= reconciliation_deadline_at` (two occurrences: the unified dispatch, the Groq
write-back guard) share the same `now()`-after-a-possible-lock-wait pattern identified
and fixed in this document's auth/idempotency flows. The paired assignments
(`locked_until = now() + interval '30 seconds'`, `reconciliation_deadline_at = now() +
interval '60 seconds'`) would need the same `clock_timestamp()` treatment for full
consistency. **This is flagged for a future, separately-requested revision of
`04-DATABASE-DESIGN.md` — it is not applied here, and `04-DATABASE-DESIGN.md` has not
been modified by this task.**

---

# Part B — Per-endpoint contracts (NOT YET DESIGNED)

Endpoint groups to be designed in upcoming rounds, each producing concrete
request/response schemas under the conventions in Part A:

- **Round 2** — Authentication & account management
- **Round 3** — Meeting management
- **Round 4** — Audio chunk processing (endpoint-level detail beyond Part A.4's conventions)
- **Round 5** — Transcript & meeting intelligence
- **Round 6** — Notes & action items
- **Round 7** — Usage, quota, search & history
- **Round 8** — Complete API consistency review

## Recommended next step

Begin Round 2 (Authentication APIs) once explicitly approved — not before.
