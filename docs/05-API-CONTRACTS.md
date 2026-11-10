# Notelify AI — API Contracts

**Status:** PARTIALLY APPROVED
- **Round 1 — API architecture, conventions, authentication transport, refresh-token
  concurrency, general idempotency mechanism: APPROVED.**
- **Round 2 — Authentication & account management endpoints: APPROVED.** See Part B.1.
- Per-endpoint contracts (Rounds 3–8: Meeting Management, Audio Chunk Processing
  endpoint-level detail, Transcript & Meeting Intelligence, Notes & Action Items,
  Usage/Quota/Search/History, final consistency review): **NOT YET DESIGNED.**

**Last updated:** 2026-11-10

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

**201 responses include a `Location` header** pointing at the newly created resource,
**unless an endpoint explicitly documents an exception** — such exceptions are
intentional (e.g. `POST /auth/register` in §B.1, where there is no single resource URL
to point at) and are not optional once documented: an endpoint either follows the
convention or explicitly states why it doesn't, never silently.

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
short legitimate-concurrency grace window (below). **Refresh-token lifetime: 30 days —
PROPOSED.** (This value appears throughout the flows below as a working assumption; it
was never separately surfaced as its own decision point before now — flagging that
explicitly rather than treating prior silence as approval.)

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

### User-row lock for login, password-reset, and logout-all (a second race, closed the same way)

Login validates a password via an application-level read-then-compare, not a single
atomic operation. If a password reset commits — changing the password and revoking every
refresh-token family — *between* login's read of the old hash and login's creation of a
new session, that new session was authorized by a credential already dead by the time
it's created, and the reset's revocation (having already run) has no way to retroactively
catch it. The identical blind spot applies to `logout-all`'s family enumeration: a
`WHERE user_id = ... AND revoked_at IS NULL` scan doesn't see a family created by a
concurrent login that starts after the scan begins — the same escape-race as the
family-wide revocation above, one level up.

**Fix**: login, password-reset, and logout-all all acquire `SELECT ... FROM users WHERE
id = :user_id FOR UPDATE` **first**, before validating a password or enumerating
families. **Plain refresh and single-session logout never touch this lock** — neither
validates a password nor enumerates across families, so they only ever need their own
family's advisory lock, unchanged from above.

**Alternative considered and rejected**: a `credential_version` counter on `users`,
bumped on reset and compared before issuing a session. Rejected in favor of directly
re-reading and re-comparing the password hash under the lock — same correctness, no new
column.

```sql
-- Login
BEGIN;
SELECT id FROM users WHERE email = :email;   -- unlocked bootstrap, to learn which row to lock
-- not found -> COMMIT; 401 invalid_credentials (no distinction from a wrong password)
SELECT id, password_hash FROM users WHERE id = :candidate_id FOR UPDATE;
-- Application code verifies :presented_password against THIS row's password_hash --
-- the value just read under the lock, never one read earlier or elsewhere.
-- Mismatch -> COMMIT (read-only); 401 invalid_credentials.
INSERT INTO refresh_tokens (id, user_id, family_id, token_hash, expires_at, created_at)
VALUES (:new_token_id, :candidate_id, :new_family_id, :new_token_hash,
        clock_timestamp() + interval '30 days', clock_timestamp());
COMMIT;
```

```sql
-- Password reset (folds logout-all's revoke-everything logic into the same transaction)
BEGIN;
UPDATE password_reset_tokens SET consumed_at = now()
WHERE token_hash = :hash AND consumed_at IS NULL AND expires_at > clock_timestamp()
RETURNING user_id;
-- 0 rows -> COMMIT; 400 invalid_or_expired_reset_token. No user lock for this outcome --
-- nothing about the user is touched if the token itself doesn't check out.

SELECT id FROM users WHERE id = :user_id FOR UPDATE;
UPDATE users SET password_hash = :new_hash WHERE id = :user_id;

family_ids := SELECT DISTINCT family_id FROM refresh_tokens
              WHERE user_id = :user_id AND revoked_at IS NULL ORDER BY family_id;
for fid in family_ids: SELECT pg_advisory_xact_lock(hashtextextended(fid::text, 0));
for fid in family_ids:
    UPDATE refresh_tokens SET revoked_at = clock_timestamp()
    WHERE family_id = fid AND revoked_at IS NULL;
COMMIT;
```

```sql
-- Logout-all
BEGIN;
SELECT id FROM users WHERE id = :user_id FOR UPDATE;   -- :user_id from the caller's access token

family_ids := SELECT DISTINCT family_id FROM refresh_tokens
              WHERE user_id = :user_id AND revoked_at IS NULL ORDER BY family_id;
for fid in family_ids: SELECT pg_advisory_xact_lock(hashtextextended(fid::text, 0));
for fid in family_ids:
    UPDATE refresh_tokens SET revoked_at = clock_timestamp()
    WHERE family_id = fid AND revoked_at IS NULL;
COMMIT;
```

**Why this closes the race in both directions**: whichever of these three operations
acquires the user lock first runs to completion — visible to the other — before the
other can even begin. If login wins first, its new family already exists (committed) by
the time reset's or logout-all's enumeration runs afterward, so it's correctly swept up.
If reset or logout-all wins first, login's `FOR UPDATE` blocks until they commit, so
login re-reads the *already-changed* password hash (reset) or simply proceeds after the
revocation already happened (logout-all) — never creating a session on top of a
credential or session set that's already dead.

**Global lock order, restated with this addition**: whenever a user-row lock and a
family advisory lock are both needed, the **user lock is always acquired first** and
held through every family lock taken afterward. Only login, password-reset, and
logout-all ever acquire a user-row lock, and each acquires at most one (for the one user
it operates on). Combined with the family-lock design above, no pair of operations —
same user or different users — can form a lock-ordering cycle: deadlock-free by
construction, not by coincidence.

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

## A.6 Required schema additions (APPLIED to `04-DATABASE-DESIGN.md`, revision round 7)

Per `CLAUDE.md`, the approved database design was not modified silently — these two
additions were presented here first, then merged into `04-DATABASE-DESIGN.md` on your
explicit approval (see that document's "Revision history," round 7, and its Alembic
sequence, migrations `0003` and `0010`). Reproduced here for reference, since this is
where the full operational reasoning for each column lives.

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

# Part B — Per-endpoint contracts

## B.1 Authentication & Account Management (APPROVED)

All nine endpoints you specified, plus one addition (`resend-verification`) called out
explicitly as new rather than silently added. All inherit Part A's conventions
(envelopes, status codes, error codes, pagination N/A here) unless noted otherwise.

### Cross-cutting decisions for this group

- **Password hashing: Argon2id — APPROVED.** OWASP's current recommended default for
  new systems. Exact parameters (memory cost, iterations) remain **PROPOSED**.
- **Password rule**: 10–128 characters, no forced composition rules — **PROPOSED**.
- **JWT claims**: `sub`, `iat`, `exp` plus `iss` and `aud` — **APPROVED as a claim set**;
  the exact `iss`/`aud` string values are **PROPOSED**. No `jti` — **APPROVED decision**,
  justified below.
- **Access-token lifetime: 15 minutes — PROPOSED** (value only; the architecture around
  it is approved).
- **No access-token denylist — APPROVED decision, justified, not merely deferred.** A
  `jti` only earns its keep if something looks it up. Closing the window between a
  revocation event and an already-issued access token's natural expiry would require
  either a denylist (a new table plus a lookup on every authenticated request — a real
  cost on the hot path) or materially shorter-lived access tokens (raising refresh
  frequency for everyone to shrink a rare edge case). For this product's risk profile, a
  bounded ≤15-minute window after an explicit security event is an accepted trade-off,
  not a gap.
- **Explicit, documented property**: refresh-token revocation (logout, logout-all,
  password-reset) does **not** retroactively invalidate an access token already issued
  before that point — it only prevents *future* issuance via refresh. An already-issued,
  unexpired access token continues to pass signature+expiry verification until its own
  `exp` passes.
- **Email provider**: sent via an `EmailProvider` interface (see
  `03-TECHNOLOGY-STACK.md`) — concrete vendor is **DEFERRED**, not part of this contract.
- **Rate limiting**: mechanism and categories below are **APPROVED**; numeric limits are
  **PROPOSED**.
- **Idempotency**: none of these endpoints use the general `Idempotency-Key` mechanism
  (§A.5) — each is safe to retry on its own terms (register: `users.email` UNIQUE;
  login: naturally repeatable; refresh: its own bespoke mechanism in §A.3; logout/
  logout-all: naturally idempotent; verify-email: idempotent-success on replay;
  forgot-password: safe to repeat, rate-limited instead; reset-password: the one
  deliberate exception where replay is a hard error, by design, not a gap).

### 1. `POST /api/v1/auth/register`
**Auth**: none. **Request**: `{"email": "...", "password": "..."}`.
**Success**: `201 Created`, no `Location` header (stated exception to the general 201
convention — there is no single resource URL this points at).
```json
{
  "user": {"id": "...", "email": "...", "email_verified_at": null, "created_at": "..."},
  "access_token": "...", "access_token_expires_at": "...", "refresh_token": "..."
}
```
`refresh_token` present in the body only for extension-origin requests (cookie set
instead for dashboard-origin, per §A.2). **Errors**: `422` schema; `409`
`email_already_registered` (confirming a taken email here is standard signup UX, unlike
`forgot-password`'s anti-enumeration rule below); `429` rate-limited.
**Transaction**: one transaction — `INSERT ... ON CONFLICT (email) DO NOTHING RETURNING
id`, the default `plan_tier_id` lookup, the `email_verification_tokens` insert, and the
initial `refresh_tokens` row (a **fresh** `family_id` — never copied, no predecessor).
Sending the verification email happens **after** commit, best-effort, never inside the
transaction. **Registration auto-logs the user in — APPROVED**; see "Registration and
verification behavior" below for what this does and doesn't gate.

### 2. `POST /api/v1/auth/login`
**Auth**: none. **Request**: `{"email": "...", "password": "..."}`.
**Success**: `200 OK` (not 201 — "authenticate me," not "create a session resource";
same body shape as register). **Errors**: `401` `invalid_credentials` — identical
whether the email doesn't exist or the password is wrong, no distinction revealed.
**Concurrency**: see A.3's "User-row lock for login, password-reset, and logout-all."
**Security**: rate-limited per-IP and per-attempted-email (**PROPOSED** values) —
deliberately no hard account lockout, which would itself be a denial-of-service vector
against a specific victim's account.

### 3. `POST /api/v1/auth/refresh`
Fully specified in §A.3 — this entry only wraps it in HTTP terms. **Auth**: none via
header; a valid refresh token via cookie (dashboard) or body (extension). **Request**:
dashboard sends `{}` (satisfies the CSRF `Content-Type` defense; cookie carries the real
token); extension sends `{"refresh_token": "..."}`. **Success**: `200 OK`,
`{"access_token", "access_token_expires_at", "refresh_token"}`.

| Outcome (§A.3) | HTTP | `error.code` |
|---|---|---|
| Token not found at all | 401 | `invalid_refresh_token` |
| `FAIL_GRACE_EXPIRED` | 401 | `refresh_token_grace_expired` |
| `FAIL_REUSE_DETECTED` | 401 | `refresh_token_reuse_detected` |

All three require the same client action (clear tokens, show login); kept distinct for
observability, not because the client branches on them.

### 4. `POST /api/v1/auth/logout`
**Auth**: refresh token only (same transport as refresh) — deliberately not requiring a
valid access token, since logout must succeed even for an already-expired session.
```sql
BEGIN;
SELECT family_id FROM refresh_tokens WHERE token_hash = :presented_hash;
-- not found at all -> treat as already logged out.
SELECT pg_advisory_xact_lock(hashtextextended(:family_id::text, 0));
UPDATE refresh_tokens SET revoked_at = clock_timestamp()
WHERE family_id = :family_id AND revoked_at IS NULL;
COMMIT;
```
Revokes whatever is *currently* live in the presented token's family — correct even if
the calling tab holds an older, already-rotated-away token. **Success**: `204 No
Content`, always — found-and-revoked, already-revoked, and not-found-at-all all produce
the identical response.

### 5. `POST /api/v1/auth/logout-all`
**Auth**: valid **access token** (not the refresh-token transport) — scoped by
`user_id`, which the access token already carries; the calling session's own family is
naturally included in the enumeration below, so "log out everywhere" correctly includes
"here." **Concurrency**: see A.3's user-row-lock subsection. **Success**: `204 No
Content`. **Boundary condition, explicit, not a bug**: a login completing after the
family-enumeration step but before this transaction finishes isn't included — a
revocation is a point-in-time action, not a standing ban on future logins.

### 6. `GET /api/v1/auth/me`
**Auth**: valid access token. **Success**: `200 OK`:
```json
{"id": "...", "email": "...", "email_verified_at": null, "plan_tier": {"name": "free"}, "created_at": "..."}
```
Identity-scoped only — quota *usage* numbers stay in a later round's endpoint. Pure
read, no transaction, no idempotency concern.

### 7. `POST /api/v1/auth/verify-email`
**Auth**: none — the token in the body is the credential; must work even if the caller
isn't logged in on this device. **Request**: `{"token": "..."}`.
```sql
BEGIN;
UPDATE email_verification_tokens SET consumed_at = now()
WHERE token_hash = :hash AND consumed_at IS NULL AND expires_at > clock_timestamp()
RETURNING user_id;
-- row returned:
UPDATE users SET email_verified_at = now() WHERE id = :user_id AND email_verified_at IS NULL;
COMMIT;
-- 0 rows -> fallback read, ALSO using clock_timestamp() -- this read can be reached
-- right after this same transaction's UPDATE already blocked on a concurrent duplicate
-- submission of the identical token, so a frozen now() would be equally stale here:
SELECT consumed_at, expires_at FROM email_verification_tokens WHERE token_hash = :hash;
-- consumed_at IS NOT NULL                          -> 200, idempotent "already verified."
-- consumed_at IS NULL AND expires_at <= clock_timestamp() -> 400 verification_token_expired.
-- not found                                         -> 400 invalid_verification_token.
COMMIT;
```
`consumed_at`'s own assignment correctly stays `now()` — it's a pure audit marker, never
later used as a comparison anchor by another transaction, unlike `expires_at`'s
comparison above. **Replay is deliberately idempotent-success** (contrast with
reset-password below): the end state ("is this email verified") is already unambiguous
and true, so treating a replay as an error would just be unfriendly. **Expiry: 24 hours
— PROPOSED.**

### 8. `POST /api/v1/auth/forgot-password`
**Request**: `{"email": "..."}`. **Success**: `200 OK`, **always the identical generic
body**, regardless of whether the email exists — the explicit anti-enumeration
requirement. If the email exists: invalidate prior unconsumed reset tokens for that user,
create a new one, send the email after commit (best-effort, same pattern as
registration). If it doesn't: do nothing, same response either way. **Residual risk,
stated not hidden**: response timing could theoretically differ between the two paths (a
low-severity side channel) — not engineering a constant-time fix for v1. **Security**:
rate-limited **per-email**, not just per-IP (**PROPOSED** values) — email-bombing a
victim's address is the realistic abuse case here. **Expiry: 1 hour — PROPOSED**
(shorter than email verification, reflecting higher sensitivity).

### 9. `POST /api/v1/auth/reset-password`
**Request**: `{"token": "...", "new_password": "..."}`.
```sql
BEGIN;
UPDATE password_reset_tokens SET consumed_at = now()
WHERE token_hash = :hash AND consumed_at IS NULL AND expires_at > clock_timestamp()
RETURNING user_id;
-- 0 rows -> COMMIT; 400 invalid_or_expired_reset_token.
-- row returned -> proceed into A.3's user-lock + password-change + revoke-all flow.
```
**Replay is deliberately a hard error**, unlike email verification: a reset token
authorizes a credential *mutation*, so a second use is either a confused client or a
replay attempt, and the safe response in either case is rejection, never success. Does
not require the old password (the token itself, delivered via a separate channel, is the
authorization). Same password rule as registration.

### 10. `POST /api/v1/auth/resend-verification` — recommended addition
Without this, a user whose verification token expires has no way to get a new one.
**Auth**: valid access token (the caller is already logged in via auto-login; no
anti-enumeration concern since we already know exactly who they are). **Success**: `200
OK` — `{"status": "already_verified"}` if `email_verified_at` is already set (no new
token created), else invalidates prior unconsumed verification tokens and creates a new
one, same pattern as `forgot-password`. Rate-limited per-user (**PROPOSED** values).

### Registration and verification behavior — confirmed decisions

- `email_verified_at` stays `NULL` until `verify-email` succeeds — true by construction.
- **Unverified users have full application access in v1 — no feature is gated on
  verification status.** Confirmed per your directive to retain auto-login as the
  approach.
- **No restrictions on unverified accounts** — no concrete restriction to propose given
  the current feature set (no collaboration/sharing, no account-email-change feature
  exists). May need revisiting if either is added later.
- Exposure to clients: via `GET /auth/me`'s `email_verified_at` field only — how the
  dashboard renders a reminder banner, or whether the extension surfaces it at all, is a
  UI/UX decision for `07-DASHBOARD-UI-UX-SPECIFICATION.md`, not this document.
- **Still open, product-level, not technical**: with zero restrictions tied to
  verification, what is verification actually *for* in v1 (recovery reliability?
  anti-fake-account hygiene?) — not a blocker for this document, but worth an explicit
  answer before it's forgotten.

### Rate-limiting categories (mechanism APPROVED, numbers PROPOSED)
In-process/in-memory (no Redis/Celery, per the approved stack) — **accepted limitation**:
counters reset on restart, and don't coordinate across multiple backend processes if
ever scaled horizontally; revisit before any such scaling, not a v1 concern.
- Per-IP: `register`, `login`, `refresh`, `verify-email`, `resend-verification`.
- Per-email (in addition to per-IP): `forgot-password`, `resend-verification`
  (email-bombing is the realistic abuse case for both), `login` (the stated alternative
  to a hard account lockout).
- `logout`/`logout-all`: low priority — abuse here only logs people out, not a
  credential/data exposure risk; a light generic per-IP ceiling is enough.

## Remaining rounds (NOT YET DESIGNED)

- **Round 3** — Meeting management
- **Round 4** — Audio chunk processing (endpoint-level detail beyond §A.4's conventions)
- **Round 5** — Transcript & meeting intelligence
- **Round 6** — Notes & action items
- **Round 7** — Usage, quota, search & history
- **Round 8** — Complete API consistency review

## Recommended next step

Begin Round 3 (Meeting Management APIs) once explicitly approved — not before.
