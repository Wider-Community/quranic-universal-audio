# Inspector State Management Strategy (v2)

Companion to [`inspector-deployment-plan.md`](inspector-deployment-plan.md). Implementation-grade reference for everything reciter-state: the source-of-truth file in the bucket, the catalog file on GitHub, the embedded state machine, the audit log, the identity convention, Inspector integration, per-phase acceptance criteria, and risks.

The parent doc owns deployment architecture, file IO (which lives in [`inspector-data-storage.md`](inspector-data-storage.md)), auth/claim UX, locking, and edit-history simplifications. This doc owns *what state means, where it lives, who writes it, and how it gets reflected back to consumers.*

## 1. Model in one paragraph

`<bucket>/state/reciter_state.sqlite` is the source of truth for pipeline state, current assignee, and per-reciter event history. It lives in the HF bucket mounted into the Space. **Inspector backend is the only writer** — `inspector/services/state.py` validates every transition through an embedded state machine before persisting. There is no GitHub workflow for state writes (the v1 `update-reciter-state.yml` is not built in v2). Catalog (display name, riwayah, audio source, `url_template`) lives at `<bucket>/catalog/reciter_catalog.sqlite` on the same bucket, also Inspector-managed. External consumers (HF Jobs, GH Actions for `RECITERS.md`/Releases) read both via `huggingface_hub` (download SQLite file → open read-only).

**SQLite, not JSON.** Earlier drafts proposed a single JSON file. SQLite gives WAL atomicity, schema migrations as `ALTER TABLE`, indexes on `state` / `assignee_hf_id`, ad-hoc query language for maintainer investigation, and a clean multi-replica path via Litestream-style replication. The operational surface is identical to a JSON file — `import sqlite3` (stdlib), one file. See §2.1 for the SQLite-on-NFS-mount semantics.

## 2. Source of truth: `<bucket>/state/reciter_state.sqlite`

### Schema (DDL)

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE schema_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
INSERT INTO schema_meta (key, value) VALUES
  ('schema_version', '1'),
  ('writer_version', 'inspector-v2');

CREATE TABLE reciters (
  slug              TEXT PRIMARY KEY,
  state             TEXT NOT NULL,                -- enum, see §4
  state_since       TEXT NOT NULL,                -- ISO 8601 UTC
  assignee_hf_id    TEXT,                         -- canonical user ref (immutable)
  assignee_login    TEXT,                         -- display cache (mutable; refreshed on session)
  assignee_since    TEXT,                         -- ISO 8601; same lifetime as assignee_hf_id
  marked_ready      INTEGER NOT NULL DEFAULT 0,   -- boolean 0/1; supersedes ready_for_merge state (see §4)
  force_assignee_hf_id TEXT,                      -- ephemeral admin force-claim; null when no force-claim
  force_assignee_since TEXT,                      -- ISO 8601; lease expires force_assignee_since + 30min
  visibility        TEXT NOT NULL DEFAULT 'public', -- enum: 'public' | 'discarded' | 'archived'
  visibility_reason TEXT,                         -- required when visibility != 'public'
  revision          INTEGER NOT NULL DEFAULT 1,   -- monotonic; OCC for future multi-writer
  last_save_at      TEXT,                         -- updated on every save (drives "stalled" dashboard)
  CHECK (state IN (
    'catalogued','awaiting_alignment','awaiting_review',
    'under_review','awaiting_timestamps','completed'
  )),
  CHECK (visibility IN ('public','discarded','archived'))
);

CREATE INDEX reciters_state_idx       ON reciters(state);
CREATE INDEX reciters_assignee_idx    ON reciters(assignee_hf_id) WHERE assignee_hf_id IS NOT NULL;
CREATE INDEX reciters_visibility_idx  ON reciters(visibility) WHERE visibility != 'public';
```

**Notable design decisions** (see §2.2 for rationale):
- **No `history` array per reciter.** Audit log (`<bucket>/state/audit.jsonl`) is the sole source for history; bounded-ring duplicates were a split-brain trap. Dashboard "history of slug X" is `tail-grep audit.jsonl WHERE slug=X | tail 20`.
- **No `issue_number`** in the state table. GitHub-shaped fields don't belong in canonical state. If/when an external reference is needed, add a separate `external_refs` table (`slug`, `kind`, `value`) — out of scope for v2.
- **No `assignee` column** keyed by login. Logins are mutable on HF; using login as the canonical identifier breaks on rename. **`assignee_hf_id` is canonical** (immutable, equals OIDC `sub`); `assignee_login` is a refreshable display cache. Every join + every claim ownership check uses `assignee_hf_id`.
- **`marked_ready` as a boolean column**, not as a separate state. The under_review→ready_for_merge round-trip via `marked/unmarked_ready` was a state-as-flag artifact. One column, three transitions removed. See §4.
- **`visibility` orthogonal to lifecycle.** A reciter can be discarded from any state without losing the lifecycle position. `discarded` is no longer a state value — it's `visibility = 'discarded'`. Reversal is just clearing the visibility column.
- **`force_assignee_hf_id` persisted**, not in-memory. Earlier drafts treated the 30-min force-claim lease as ephemeral; that meant Space restart silently dropped it. Now it survives container rebuilds; expiry is computed from `force_assignee_since + 30min`.
- **`revision` for OCC.** Today single-writer; the column exists so multi-writer (future) doesn't require a schema migration.

### 2.1 SQLite-on-mount semantics

The SQLite file lives on the bucket mount (NFS Advanced). Writes are WAL-mode; readers see committed transactions atomically; Phase 0 spike must verify NFS-with-WAL semantics under our mount (lock files, `-wal` and `-shm` sidecars flush correctly).

- **Reads** within Inspector: `sqlite3.connect(..., uri=True)` with `mode=ro` is fine for everywhere except `services/state.py` itself.
- **Writes** within Inspector: a single connection in `services/state.py`, opened at boot, kept open. Write transactions wrap each transition.
- **External readers** (HF Jobs, GH Actions): download the `.sqlite` file via `huggingface_hub`, open read-only locally. Do NOT mount the bucket from outside Inspector — single-mount-point keeps the WAL semantics simple.
- **Crash safety**: SQLite WAL handles crash-mid-write atomically. Combined with the mount's flush window (2–30 s), a Space crash inside the flush window means the bucket retains the previous WAL state — which is consistent. No torn writes.
- **Tooling**: `sqlite3 <bucket>/state/reciter_state.sqlite '.dump'` for forensic export; `replay_audit.py` rebuilds the DB from `audit.jsonl` for disaster recovery.

### 2.2 Why these schema choices

| Decision | Rationale | What was rejected |
|---|---|---|
| SQLite over JSON | WAL atomicity, indexes, query language, future migrations via `ALTER TABLE`, free Litestream replication path | Single 150 KB JSON file with no concurrency primitive, no transactions, no indexes |
| `assignee_hf_id` canonical | HF logins are mutable; rename silently breaks login-keyed joins | `assignee` (login) as canonical — silent correctness bug on rename |
| Drop `history` array | Two SoTs for history (state file + audit log) drift on any forgotten dual-write | Bounded 20-entry ring — vestigial denormalization |
| Drop `issue_number` | GitHub-shaped field bleeding into canonical state; no longer rely on issues/PRs/GH assignees | Embedding `issue_number` per row — couples state to GitHub |
| `marked_ready` as bool | `under_review` ↔ `ready_for_merge` round-trip is a flag, not two distinct states | Two states, three transitions, identical assignee/edit semantics |
| `visibility` orthogonal | Discardable from any lifecycle phase; round-trip preserves position | `discarded` as 8th state value — loses previous lifecycle on un-discard |
| Persisted force-claim | Container rebuild silently dropping force-claims is a correctness regression | In-memory-only 30-min lease |
| `revision` column | Multi-writer future shouldn't need a schema bump | Adding OCC later as a migration |

### Audit log: `<bucket>/state/audit.jsonl`

Append-only, one line per state-changing event. Lives in the **private metadata bucket** (carries PII — `actor.hf_user_id` per event). Partitioned per-month from day one (`audit/<YYYY>-<MM>.jsonl`); one symlink/pointer file `audit/CURRENT` that points at the active partition. Quarterly rollover is automatic; nothing to revisit at scale.

```jsonc
{ "ts": "2026-05-08T14:23:11Z",
  "slug": "saad_al_ghamdi",
  "event": "reciter.claimed",
  "from_state": "awaiting_review",
  "to_state": "under_review",
  "actor": { "hf_user_id": "12345", "login_at_time": "alice", "role": "contributor" },
  "payload": { },
  "request_id": "req_abc123",
  "prev_hash": "sha256:abc123...",         // sha256 of canonical(prev record); chain integrity
  "result": "ok"
}
```

**Schema notes:**
- `schema_version` lives in `audit/_meta.json` once per partition file, NOT per record. Per-record version-stamping inflates every line for no read-time benefit.
- `actor.hf_user_id` is canonical (immutable). `login_at_time` snapshots the display login at write time.
- `actor.role` snapshots the role at write time so audit forensics survive role changes.
- `prev_hash` chains records for tamper detection. `replay_audit.py` validates the chain and rebuilds `reciter_state.sqlite` on demand.
- `from_state` / `to_state` null for non-state-changing events (`catalog.edited`, `pipeline.triggered`, `admin.job_rerun`, etc.). Document in §4 events table per event.
- Per-event `payload` shape lives alongside its event constant in `services/state.py` as a `TypedDict` — colocation, no separate schema-doc-by-grep.

Read pattern: ad-hoc by maintainers via the admin dashboard; future "your contributions" page (deferred — see [`inspector-deferred.md`](inspector-deferred.md) D10). ~3.6 MB/year sustained.

### Write semantics

- **Single writer:** Inspector backend's `services/state.py::transition()` function.
- **Serialization:** SQLite WAL handles concurrent reads against a serialized writer natively. Inspector still holds a per-slug mutex around `(read row, validate, write)` to keep the transition atomic at the application level.
- **Atomicity:** WAL transaction wraps every transition. Inspector's transition is one SQL `UPDATE` (or `INSERT` for new slugs) inside `BEGIN EXCLUSIVE`. SQLite's WAL guarantees readers see committed transactions atomically; partial writes are never visible.
- **Audit append:** every transition appends a line to the current `audit/<YYYY>-<MM>.jsonl` partition BEFORE the SQL `COMMIT`. If the SQL commit fails, the audit entry is a "would-have-transitioned" record (debug forensics). Audit append uses `huggingface_hub.upload_file()` directly, bypassing the mount's flush window — durability is more important than latency for state events (~1/min in steady state).
- **State file durability:** the SQLite file goes through the mount (NFS Advanced flush window 2–30 s). For state writes specifically, also call `huggingface_hub.upload_file()` direct on the SQLite file at write time — same rationale as audit. The mount's lazy flush is fine for save-data; not fine for state, where the failure mode is silent rollback after a 200 response.
- **External consumers** (HF Jobs, GH Actions): download the SQLite file via `huggingface_hub`; open read-only. Read after write is bounded by the upload + HF CDN propagation (~5 s typical).

### Read semantics

- **Inspector:** opens the SQLite file read-only at request time (or holds the writer connection open and reads from it). No in-memory parse cache needed — SQLite + indexes serve point lookups in <100 µs. Listing all reciters for the dashboard is a single `SELECT` against the indexed columns.
- **HF Jobs (publish, snapshot, etc.):** download the `.sqlite` file via `huggingface_hub`; open read-only locally.
- **GH Actions (`update-reciters.yml`, `release.yml`):** same.
- **External tools (Reciter Requests Space, etc.):** read via the bucket-read token, or read a snapshot Inspector exposes via `/api/state/snapshot.json` (rate-limited, cached 30 s).

### Validation

`inspector/services/state.py::_validate_invariants()` runs inside the transaction, before `COMMIT`:

- `state` is in the closed enum (enforced at SQL level via `CHECK` constraint, but checked again for friendly error messages).
- Per-state required-field invariants from §4 hold — e.g., `state == 'under_review'` requires `assignee_hf_id IS NOT NULL`.
- `assignee_login`, when present, has been verified against `https://huggingface.co/api/users/<login>/overview` within the last 24 h (cached at session boundary; refresh on miss).
- Timestamps monotonic — `state_since >= prev_state_since`.
- `force_assignee_since`, when present, is no older than 30 min (auto-clear via `claim.force_released_auto` event before transition if expired).
- `marked_ready == 1` requires `state == 'under_review'` and `assignee_hf_id IS NOT NULL`.

Failure raises `InvalidTransition`; transaction rolls back; caller receives 400 with the violation. The SQL is untouched; the audit log carries an `attempted` record only if the violation is detected post-audit-append (rare).

## 3. Catalog: `<bucket>/catalog/reciter_catalog.sqlite`

### Why the bucket + SQLite for the catalog

Same reasoning as state (§2): SQLite gives indexed lookups, atomicity, schema migrations. Catalog also lives on the bucket because:

1. v2's architectural shift is "no per-reciter PRs." Keeping catalog on GitHub PRs means a PR-creation token + auto-merge workflow + PR review queue, just for catalog edits.
2. The same Inspector-as-sole-writer pattern works for catalog. Maintainer+ role required for `catalog.edited` events; immutable fields (`slug`, `reciter_id`) rejected by the validator.

`data/inspector_roles.json` (the role file, see §9) **stays on GitHub** — it governs *who can edit*, not *what's edited*. CODEOWNERS-gated PR review is the right gate for role mutations.

### Catalog read paths

| Consumer | Path |
|---|---|
| Inspector backend | Open `<INSPECTOR_BUCKET_MOUNT>/catalog/reciter_catalog.sqlite` read-only via SQLite |
| GH Actions (`update-reciters.yml`) | Download via `huggingface_hub`; open SQLite read-only |
| HF Jobs | Same |
| External (Reciter Requests Space, until D2) | Reads `data/reciters_index.json` (regenerated derivative) — unchanged contract |

### Design principle: slug is opaque, catalog is structured

The slug is just a unique ID string. **No parser ever extracts semantic meaning from it.** All dimensions that matter — name, riwayah, style, source, year, variant grouping — are catalog fields. Adding a new dimension later is `ALTER TABLE`, never a slug reshape.

### Schema (DDL)

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE schema_meta (
  key TEXT PRIMARY KEY, value TEXT NOT NULL
);
INSERT INTO schema_meta (key, value) VALUES ('schema_version', '2');

CREATE TABLE audio_sources (              -- factored out from per-reciter denormalization
  source_id            TEXT PRIMARY KEY,  -- e.g. 'mp3quran', 'everyayah'
  audio_category       TEXT NOT NULL,     -- 'by_surah' | 'by_ayah'
  url_template_kind    TEXT NOT NULL,     -- 'by_surah' | 'by_ayah_padded' | 'by_ayah_unpadded' | 'custom'
  url_template_default TEXT,              -- used when row's url_template_override is null
  timing_supported     INTEGER NOT NULL DEFAULT 0,
  CHECK (audio_category IN ('by_surah','by_ayah')),
  CHECK (url_template_kind IN ('by_surah','by_ayah_padded','by_ayah_unpadded','custom'))
);

CREATE TABLE reciters (
  slug                  TEXT PRIMARY KEY,
  reciter_id            TEXT NOT NULL,            -- groups variants; defaults to slug
  name_en               TEXT NOT NULL,
  name_ar               TEXT NOT NULL,
  country               TEXT NOT NULL DEFAULT 'unknown',  -- ISO-2 or 'unknown'
  riwayah               TEXT NOT NULL,             -- references controlled vocab (validated app-side)
  style                 TEXT NOT NULL,             -- references controlled vocab
  audio_source          TEXT NOT NULL REFERENCES audio_sources(source_id),
  url_template_override TEXT,                      -- only when reciter doesn't fit the source's default
  recording_year        INTEGER,
  variant_label         TEXT,                      -- distinguisher when ≥2 share reciter_id
  added_at              TEXT NOT NULL,
  added_by_hf_id        TEXT NOT NULL,
  notes                 TEXT,                      -- free-form maintainer notes
  CHECK (slug GLOB '[a-z][a-z0-9_]*' AND length(slug) BETWEEN 2 AND 40),
  CHECK (reciter_id GLOB '[a-z][a-z0-9_]*' AND length(reciter_id) BETWEEN 2 AND 40)
);

CREATE INDEX reciters_reciter_id_idx ON reciters(reciter_id);
CREATE INDEX reciters_audio_source_idx ON reciters(audio_source);

CREATE TABLE reciter_aliases (             -- old slugs that redirect to canonical (forward-compat for D9)
  old_slug   TEXT PRIMARY KEY,
  new_slug   TEXT NOT NULL REFERENCES reciters(slug),
  aliased_at TEXT NOT NULL
);
```

### Field semantics

| Field | Required | Notes |
|---|---|---|
| `slug` | yes | Primary key. Immutable. |
| `reciter_id` | yes | Groups variants. Convention: **canonical variant has `slug == reciter_id`** (no `is_canonical` bool needed — the convention carries the invariant). Variants have `reciter_id` matching the canonical's slug. |
| `audio_source` | yes | FK to `audio_sources.source_id`. Most reciters per source share the source's default URL template. |
| `url_template_override` | no | Only set for reciters that don't fit their source's default — rare. Eliminates the 50-fold denormalization v1 had. |
| `country` | yes | ISO-2 or `unknown`. Validated app-side against an ISO-2 list baked into the validator. |
| `notes` | no | Free-form. Maintainers always want it; better to have than not. |

**Dropped**: `is_canonical: bool` invariant (replaced by `slug == reciter_id` convention); per-row `audio_category` and `url_template` denormalization (factored to `audio_sources`).

### Slug naming rules

```
^[a-z][a-z0-9_]{1,39}$
```

ASCII lowercase, single underscores between tokens, no double-underscore, no trailing underscore. 2–40 characters. URL-safe by construction. Immutable after first publish.

### Update path

- **Adds:** maintainer uses `POST /api/admin/catalog/add` (admin §5.6); Inspector validates + writes + audits. Future request intake (D2) will route through the same endpoint.
- **Edits:** maintainer uses `POST /api/admin/catalog/edit/<slug>`. Validator rejects mutations to `slug` and `reciter_id`.
- **New variants:** add a new row with `reciter_id` matching the canonical row's `slug`.

On any catalog write, Inspector fires `repository_dispatch reciter.catalog_changed` to trigger `update-reciters.yml`. Inspector's own cache is fresh by construction (it's the writer).

### Validation

`inspector/services/catalog.py::_validate()` runs inside the SQLite write transaction:

- Schema CHECK constraints handle slug regex + audio_category enum + url_template_kind enum (SQL-level).
- App-side: `riwayah`, `style` exist in their respective controlled-vocab files (`data/{riwayat,styles}.json` baked into the image).
- App-side: `audio_source` row exists in the `audio_sources` table.
- App-side: `country` is in the ISO-2 list or `'unknown'`.
- App-side: variant rows reference an existing canonical row via `reciter_id`.

Failure rolls back the transaction; admin endpoint returns 400 with the violation message.

### Constraints

- `slug` and `reciter_id` immutable post-add (validator rejects updates to either).
- Removing a row is via `visibility = 'archived'` (state machine §4); the row stays for forensics.

### Initial seed (one-shot, manual at cutover)

There are ~15 reciters at v2 cutover. Maintainer authors the seed locally:

1. Run `scripts/seed_catalog.py` — reads existing `data/reciters_index.json` + per-reciter manifest `_meta` blocks, generates a `seed.sql` script that populates the catalog SQLite from current identity sources. (`audio_sources` rows authored once by hand for the ~6 known sources — `mp3quran`, `everyayah`, etc.)
2. Run `scripts/seed_state.py` — reads the catalog seed + on-disk file presence, generates a `seed.sql` for state per these mapping rules:

| Signal | → Initial state |
|---|---|
| Has `data/timestamps/<slug>/...` AND `data/recitation_segments/<slug>/segments.json` (per `scripts/lib/reciter_eligibility.py`) | `completed` |
| Has `data/recitation_segments/<slug>/segments.json` only | `awaiting_review` (no claim) |
| Open GitHub issue + no on-disk segments | `awaiting_alignment` |
| Catalog entry only | `catalogued` |

3. Apply seed: `sqlite3 reciter_state.sqlite < seed.sql`; same for catalog.
4. `hf buckets cp` the two `.sqlite` files into the target bucket.

Initial seed fields per row: `assignee_*` columns null (reviewers re-claim fresh); `state_since = now`; `marked_ready = 0`; `visibility = 'public'`. Audit log gets one `reciter.seeded` entry per row at cutover.

After cutover, all subsequent transitions go through `state.py::transition()` — direct SQLite mutation outside Inspector is forbidden by convention (Inspector is sole writer).

## 4. State machine

### Lifecycle states

Six lifecycle phases. **`ready_for_merge` is NOT a state** — it's a `marked_ready: bool` column on `under_review`. **`discarded` is NOT a state** — it's `visibility: 'discarded'` orthogonal to lifecycle.

| State | Definition | Editable | Required fields | Forbidden fields |
|---|---|---|---|---|
| `catalogued` | In catalog. No alignment work has started. | No | none beyond identity | `assignee_hf_id` null |
| `awaiting_alignment` | Alignment pipeline pending or running. | No | none | `assignee_hf_id` null |
| `awaiting_review` | Alignment done. Bucket entry exists. No reviewer claimed. | No (claimable) | none | `assignee_hf_id` null |
| `under_review` | A reviewer has claimed. `marked_ready` may be 0 or 1. | Yes (assignee only, **and** `marked_ready == 0`) | `assignee_hf_id`, `assignee_login`, `assignee_since` | none |
| `awaiting_timestamps` | Publish triggered. Snapshot done. TS data not yet on dataset. | No | none | `assignee_hf_id` null |
| `completed` | Segments + TS both on dataset, in sync. | No | none | `assignee_hf_id` null |

**`marked_ready` semantics (boolean column on `under_review`):**
- `marked_ready == 0`: reviewer is editing. Saves accepted.
- `marked_ready == 1`: reviewer has marked ready for publish. Saves return 410 (frozen). Maintainer can now publish.
- Unmark = set `marked_ready = 0`. Mark again = set to 1. No state transitions; one column flip per action.

**`visibility` semantics (orthogonal column):**
- `'public'` (default): visible to everyone with appropriate permissions.
- `'discarded'`: hidden from anonymous + non-maintainer lists. Surfaced under the admin "Internal" filter. Reversal is just clearing the column back to `'public'`.
- `'archived'`: post-publish soft-delete (rare; only used if a reciter is permanently retired). Same visibility as `'discarded'` but conceptually different (the reciter was once live).
- A `visibility != 'public'` reciter still has a lifecycle state — `discarded` is not "no state."

`assignee_*` columns are preserved through `marked_ready = 1` (the assignee may unmark to continue editing).

### Events — canonical vocabulary

**Naming convention: `<noun>.<past-tense-verb>` for every event.** Five nouns: `reciter` (lifecycle), `claim` (assignee bookkeeping), `catalog` (catalog mutations), `pipeline` (admin-triggered pipeline runs), `admin` (admin operational events). This is the **single source of truth** — `inspector/services/state.py` and the audit log both consume from this list. The admin-perms doc ([`inspector-admin-perms.md`](inspector-admin-perms.md) §11) extends the same vocabulary; do not introduce alternate names elsewhere.

```
# Lifecycle (reciter.*)
reciter.alignment_requested       # from Reciter Requests Space (until D2)
reciter.alignment_completed       # pipeline finished, bucket entry seeded
reciter.published                 # maintainer published — snapshot bucket → dataset
reciter.timestamps_completed      # TS data on dataset
reciter.merge_rejected            # maintainer sent ready entry back to reviewer (sets marked_ready=0)
reciter.seeded                    # one-shot cutover seed
reciter.archived                  # post-publish soft-delete (rare; sets visibility='archived')
reciter.unarchived                # reverse of above

# Visibility (orthogonal — not lifecycle transitions)
reciter.discarded                 # admin set visibility='discarded' (any lifecycle state)
reciter.undiscarded               # admin cleared visibility back to 'public'

# Claim cycle (claim.*)
reciter.claimed                   # someone took the reciter
reciter.released                  # claimant gave it back
reciter.marked_ready              # reviewer set marked_ready=1 (no state transition)
reciter.unmarked_ready            # reviewer set marked_ready=0
claim.force_released              # admin override
claim.reassigned                  # admin override
claim.force_acquired              # admin first-save on a not-owned reciter (writes force_assignee_*)
claim.force_released_auto         # 30-min lease expired (system timer)

# Discrete admin overrides (replace v1 wildcard `state.manual_override`)
admin.force_set_state             # direct state column write — narrow, audited
admin.force_clear_assignee        # clear assignee_* columns explicitly
admin.force_unmark_ready          # set marked_ready=0 (admin path, distinct from reviewer's)
admin.force_revision_bump         # bump revision column without other change (debug recovery)
# NOTE: there is no generic "any → any" admin escape hatch. Add a new named admin.* event
# if a need arises that none of the above + lifecycle events cover.

# Catalog (catalog.*)
catalog.added                     # new row in catalog SQLite
catalog.edited                    # mutated mutable fields on existing row
catalog.audio_source_added        # new row in audio_sources table

# Pipeline / Job (pipeline.* / admin.*)
pipeline.triggered                # admin fired a re-extraction or re-timestamps via web
admin.job_rerun                   # admin re-ran a failed publish HF Job
```

**Renames from v1 / earlier v2 drafts** (all places that used the old name should be updated):

| Old name | New canonical name |
|---|---|
| `claimed` | `reciter.claimed` |
| `released` | `reciter.released` |
| `marked_ready` | `reciter.marked_ready` |
| `unmarked_ready` | `reciter.unmarked_ready` |
| `merge_rejected` | `reciter.merge_rejected` |
| `published` | `reciter.published` |
| `admin_override` / `state.manual_override` | discrete `admin.force_*` events (no wildcard) |
| `review_merged` (v1) | `reciter.published` |
| `reciter.catalog_synced` | `catalog.added` (new slug) / `catalog.edited` (existing) |

Deferred (recognized but not implemented in v2 — see [`inspector-deferred.md`](inspector-deferred.md) D11):

```
reciter.alignment_failed
reciter.timestamps_failed
reciter.timestamps_stale
reciter.audio_source_changed
```

### Transition matrix (canonical — single source for `state.py`)

Lifecycle states = `catalogued`, `awaiting_alignment`, `awaiting_review`, `under_review`, `awaiting_timestamps`, `completed` (six total). `marked_ready` and `visibility` are orthogonal columns.

| Event | From state(s) | To state | Other column changes | Actor role | Side effects |
|---|---|---|---|---|---|
| `catalog.added` (creates state row implicitly) | (no row) | `catalogued` | — | system | New row inserted with defaults |
| `catalog.edited` | any | (same) | — | maintainer+ | No state transition; catalog SQLite mutated; audit in `<bucket>/catalog/audit.jsonl` |
| `reciter.alignment_requested` | `catalogued` | `awaiting_alignment` | — | system (forward webhook, until D2) | — |
| `reciter.alignment_completed` | `awaiting_alignment` | `awaiting_review` | — | system (pipeline webhook) | Bucket entry seeded by pipeline |
| `reciter.claimed` | `awaiting_review` | `under_review` | set `assignee_hf_id`, `assignee_login`, `assignee_since`; `marked_ready = 0` | contributor+ | One-claim-per-user check |
| `reciter.released` | `under_review` | `awaiting_review` | clear assignee_*; `marked_ready = 0` | claim-holder OR maintainer+ | — |
| `reciter.marked_ready` | `under_review` | (same) | `marked_ready = 1` | claim-holder | — |
| `reciter.unmarked_ready` | `under_review` | (same) | `marked_ready = 0` | claim-holder | — |
| `reciter.merge_rejected` | `under_review` (with `marked_ready = 1`) | (same) | `marked_ready = 0` | maintainer+ | Reason required ≥10 chars |
| `reciter.published` | `under_review` (with `marked_ready = 1`) | `awaiting_timestamps` | clear assignee_*; `marked_ready = 0` | maintainer+ | Triggers HF Jobs + GH Actions per [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md). Bucket entry archived/deleted post-snapshot |
| `reciter.timestamps_completed` | `awaiting_timestamps` | `completed` | — | system (job callback) | TS HF Job confirmed |
| `reciter.archived` | `completed` (only) | (same) | `visibility = 'archived'`, `visibility_reason = ...` | maintainer+ | — |
| `reciter.unarchived` | (any with `visibility = 'archived'`) | (same) | `visibility = 'public'` | maintainer+ | — |
| `reciter.discarded` | (any) | (same) | `visibility = 'discarded'`, `visibility_reason = ...` | maintainer+ | Typed confirmation phrase + reason ≥10 chars |
| `reciter.undiscarded` | (any with `visibility = 'discarded'`) | (same) | `visibility = 'public'` | maintainer+ | — |
| `claim.force_released` | `under_review` | `awaiting_review` | clear assignee_*; `marked_ready = 0` | maintainer+ | Reason required |
| `claim.reassigned` | `awaiting_review`, `under_review` | `under_review` | set new assignee_* (HF API resolved per admin §5.2); `marked_ready = 0` | maintainer+ | Reason required |
| `claim.force_acquired` | `under_review` | (same) | set `force_assignee_hf_id`, `force_assignee_since` | maintainer+ | 30-min lease. Persisted (NOT ephemeral) so survives Space restart |
| `claim.force_released_auto` | (any with `force_assignee_hf_id IS NOT NULL`) | (same) | clear `force_assignee_*` | system (timer or boot-time check) | Lease expired |
| `admin.force_set_state` | any | (specified, narrow set) | — | maintainer+ | Allowed transitions: `awaiting_alignment ↔ awaiting_review`, `awaiting_timestamps ↔ completed`. Other targets return 400 — must use a discrete operation. |
| `admin.force_clear_assignee` | (any with `assignee_hf_id IS NOT NULL`) | (same) | clear assignee_*; `marked_ready = 0` | maintainer+ | — |
| `admin.force_unmark_ready` | `under_review` | (same) | `marked_ready = 0` | maintainer+ | Distinct from `reciter.unmarked_ready` (admin path; reviewer not required to be assignee) |
| `admin.force_revision_bump` | any | (same) | `revision += 1` | maintainer+ | Debug-only; for OCC-related recovery |
| `reciter.seeded` | (no row) | (specified) | initial values per cutover spec | manual (one-shot) | One-time only |
| `pipeline.triggered` | (any compatible) | (none — pipeline emits follow-up) | — | maintainer+ | Fires `repository_dispatch pipeline.triggered`; reason required |
| `admin.job_rerun` | (any) | (same) | — | maintainer+ | Re-enqueues a specific failed HF Job |

**Notes:**

- Direct `under_review → reciter.published` requires `marked_ready = 1` — the validator enforces this per the §4 invariants table.
- `visibility = 'discarded'` does NOT change the lifecycle state — the row keeps its `state`, just becomes hidden. `reciter.undiscarded` un-hides without the lifecycle losing position.
- The discrete admin `admin.force_*` events replace the v1/early-v2 wildcard `state.manual_override`. **No `* → *` escape hatch exists.** If a recovery scenario isn't covered by the listed admin events, add a new named one (audit pattern: write the use case, name the event, add to this matrix, ship).

### Why re-edits don't get their own state

Re-edits of `completed` reciters are deferred — see [`inspector-deferred.md`](inspector-deferred.md) D5. When implemented, the path will be: maintainer calls a re-claim endpoint → Inspector triggers an HF Job that downloads `inspector/segments/<slug>/v<n>/...` shards from the dataset and writes them back into `<bucket>/wip/<slug>/...` → state transitions `completed → awaiting_review`. The re-edit then follows the normal `awaiting_review → under_review → published` path. **CDN URLs already include a publish-version segment** (`v<n>/`) so browser caches don't break across re-publishes, even with `Cache-Control: immutable`.

## 5. State machine implementation

`inspector/services/state.py` is the single point of truth for state writes. Pseudocode:

```python
@dataclass(frozen=True)
class ReciterRow:
    slug: str
    state: ReciterState
    state_since: datetime
    assignee_hf_id: str | None
    assignee_login: str | None
    assignee_since: datetime | None
    marked_ready: bool
    force_assignee_hf_id: str | None
    force_assignee_since: datetime | None
    visibility: Visibility               # 'public' | 'discarded' | 'archived'
    visibility_reason: str | None
    revision: int
    last_save_at: datetime | None

class StateMachine:
    def __init__(self, db: SqliteConnection, audit_log: AuditLog, mutex: PerSlugMutex):
        self.db = db
        self.audit_log = audit_log
        self.mutex = mutex
        # No in-memory state cache — SQLite + indexes serve point lookups in <100µs.

    def transition(self, slug: str, event: Event, actor: User) -> ReciterRow:
        with self.mutex.acquire(slug):
            with self.db:                              # BEGIN EXCLUSIVE
                row = self._read(slug)                 # SELECT ... FROM reciters WHERE slug=?
                new_row = self._apply(row, event, actor)  # pure function; raises InvalidTransition
                self._validate_invariants(new_row)
                # Audit FIRST (durable via direct upload_file), then SQL commit.
                self.audit_log.append(AuditRecord(
                    ts=now_utc(), slug=slug, event=event.name,
                    from_state=row.state if row else None, to_state=new_row.state,
                    actor=actor.audit_view(), payload=event.payload,
                    request_id=current_request_id(), result='ok',
                    prev_hash=self.audit_log.tip_hash(),
                ))
                self._write(new_row)                   # UPDATE/INSERT; revision auto-bumps
                # Direct upload_file on the .sqlite file too — bypasses mount flush window.
                self.bucket.upload_state_file()
            return new_row

    def _apply(self, row, event, actor):
        # Pure function. Raises InvalidTransition if event isn't allowed from (row.state, row.marked_ready, row.visibility).
        # Encodes the §4 matrix plus business rules:
        #   - reciter.claimed: row.assignee_hf_id must be None; actor must not have another active claim.
        #   - reciter.released / reciter.unmarked_ready / reciter.marked_ready:
        #       actor.hf_user_id must equal row.assignee_hf_id (NOT login).
        #   - reciter.merge_rejected / reciter.published: actor.role >= maintainer.
        #   - admin.force_*: actor.role >= maintainer; reason required.
        ...
```

**Concurrency:**

- **Per-slug mutex** serializes transitions within Inspector — pairs with SQLite's `BEGIN EXCLUSIVE` for transaction-level serialization. The mutex is the **application-level** boundary; the SQL transaction is the **storage-level** boundary.
- **Cross-slug transitions** run concurrently (different mutexes; SQLite WAL allows concurrent transactions on different rows).
- **`hf_user_id` everywhere** — the lookup is `WHERE assignee_hf_id = ?`, not `WHERE assignee_login = ?`. Login renames don't break locks.

**Fault model:**

- Audit append fails before SQL commit → caller gets 503; SQL untouched; no inconsistency.
- SQL commit fails after audit append → audit log carries an `attempted` entry (`result: 'failed'` would be added in a follow-up audit entry on recovery). `replay_audit.py` detects orphaned attempted records and either retries or marks them failed.
- Inspector crashes mid-transition → SQLite WAL guarantees the row is either old or new, never torn. Audit log may have a leading `attempted` entry without a follow-up; recovery on next boot.
- Mount flush window: bypassed for state SQLite writes (direct `upload_file` on every transition) and audit appends (same). The mount is read-only-with-fallback for these two files.

## 5.1 The single-writer assertion (`-w 1`)

`inspector/app.py::create_app()` MUST assert at boot:

```python
workers = int(os.environ.get("GUNICORN_WORKERS", "1"))
if workers != 1:
    raise RuntimeError(
        "Inspector v2 assumes single-process: state mutex, force-claim leases, "
        "and parsed seg cache are per-process. -w 2+ requires a shared coordinator "
        "(see inspector-deferred.md D6)."
    )
```

The Dockerfile passes `-w 1` to gunicorn and sets `GUNICORN_WORKERS=1` for the assertion. Concurrency comes from `--threads 16` (gunicorn-gthread releases the GIL during NFS reads and ffmpeg subprocesses, where the actual load is).

## 6. Identity convention

The slug-rules-only convention. No PR/branch/commit conventions in v2.

| Artifact | Convention | Example |
|---|---|---|
| Reciter request issue title | `[request] <slug>: <Display Name>` | `[request] saad_al_ghamdi: Saad Al-Ghamdi` |
| Issue body marker | `<!-- reciter-task: slug=<slug> schema=1 -->` | `<!-- reciter-task: slug=saad_al_ghamdi schema=1 -->` |
| Bucket path for in-flight | `<bucket>/wip/<slug>/` | |
| HF dataset path for completed | `inspector/segments/<slug>/` | |
| Inspector URL | `/r/<slug>` | `/r/saad_al_ghamdi` |

Dropped vs v1: branch convention `reciter/<slug>`, PR title convention, commit subject conventions, squash-merge subject convention, HTML-comment markers in PR bodies.

## 7. Reciter request issue body templates (transitional)

While the Reciter Requests Space is still in use (deprecation tracked in [`inspector-deferred.md`](inspector-deferred.md) D2), it creates GitHub issues with this body:

```markdown
<!-- reciter-task: slug=saad_al_ghamdi schema=1 -->
**[Open in Inspector](https://hetchyy-quranic-inspector.hf.space/r/saad_al_ghamdi)**

| | |
|---|---|
| Slug | `saad_al_ghamdi` |
| Display | Saad Al-Ghamdi |
| Riwayah | Hafs an Asim |
| Style | Murattal |
| Audio source | everyayah |
```

The issue body is **not re-rendered on every state transition** — it's set once at request creation and stays static. Live state lives in the Inspector website. The issue is closed when state transitions to `completed` (HF Job calls GitHub API to close). All other transitions don't touch the issue.

When D2 lands, the entire issue-tracking surface goes away — requests become Inspector-internal records.

## 8. Inspector integration

### State refresh strategy

- **On startup:** open `<INSPECTOR_BUCKET_MOUNT>/state/reciter_state.sqlite` and `.../catalog/reciter_catalog.sqlite` via SQLite. No parse-into-memory step — read at request time via indexed queries.
- **On every state write:** Inspector commits the SQLite transaction (`BEGIN EXCLUSIVE` → `UPDATE` → `COMMIT`); other readers see the new row on next query.
- **No webhook from anywhere else** — there is no other writer.

### API endpoints

Full contracts in [`inspector-deployment-plan.md`](inspector-deployment-plan.md) §4. Index here (slug always in path):

```
# Identity
GET  /api/me                            → { hf_user_id, login, role, active_claim }
GET  /api/auth/login                    → initiates HF OAuth flow
GET  /api/auth/callback                 → handles HF redirect, sets session cookie
POST /api/auth/logout                   → clears session

# State reads
GET  /api/reciters                      → [{ slug, display, state, marked_ready, visibility, riwayah, style }]
GET  /api/reciter-task/<slug>           → full row + can_*_for_current_user predicates
GET  /api/state/snapshot.json           → public read-only snapshot, rate-limited; cached 30 s

# Claim flow (mutating — write directly to bucket SQLite, return 200 with authoritative row)
POST /api/claim/<slug>                  → state.transition(slug, ReciterClaimedEvent(actor))
POST /api/release/<slug>                → state.transition(slug, ReciterReleasedEvent(actor))
POST /api/mark-ready/<slug>             → state.transition(slug, ReciterMarkedReadyEvent(actor))
POST /api/unmark-ready/<slug>           → state.transition(slug, ReciterUnmarkedReadyEvent(actor))

# Admin (maintainer+ only) — discrete operations, no wildcard
POST /api/admin/publish/<slug>          → publish under_review (with marked_ready=1) → awaiting_timestamps
POST /api/admin/send-back/<slug>        → reciter.merge_rejected (resets marked_ready)
POST /api/admin/discard/<slug>          → set visibility=discarded
POST /api/admin/undiscard/<slug>        → clear visibility back to public
POST /api/admin/archive/<slug>          → set visibility=archived (for completed only)
POST /api/admin/unarchive/<slug>        → clear archived
POST /api/admin/claim/force-release/<slug>   → claim.force_released
POST /api/admin/claim/reassign/<slug>        → claim.reassigned (resolves to_login → hf_user_id server-side)
POST /api/admin/claim/clear/<slug>            → admin.force_clear_assignee
POST /api/admin/state/force-set/<slug>        → admin.force_set_state (narrow allowed targets only)
POST /api/admin/state/force-unmark-ready/<slug> → admin.force_unmark_ready
POST /api/admin/catalog/add                  → catalog.added
POST /api/admin/catalog/edit/<slug>          → catalog.edited
POST /api/admin/pipeline/trigger/<slug>      → pipeline.triggered
POST /api/admin/job/rerun/<slug>             → admin.job_rerun
```

**Endpoint conventions:** slug always in the URL path (no slug-in-body). HMAC + Bearer choices documented per endpoint family in publish-pipeline doc.

### Predicates

Computed server-side in the `/api/reciter-task/<slug>` response. Note `assignee_hf_id` (canonical) used for claim ownership, NOT `login`:

```python
def can_edit(row, user):
    return (user is not None
            and row.state == 'under_review'
            and not row.marked_ready
            and row.visibility == 'public'
            and row.assignee_hf_id == user.hf_user_id)

def can_mark_ready(row, user):   # same gate as can_edit + not already marked
    return can_edit(row, user) and not row.marked_ready

def can_unmark_ready(row, user):
    return (user is not None
            and row.state == 'under_review'
            and row.marked_ready
            and row.assignee_hf_id == user.hf_user_id)

def can_release(row, user):
    return (user is not None
            and row.state == 'under_review'
            and row.assignee_hf_id == user.hf_user_id)

def can_claim(row, user):
    return (user is not None
            and row.state == 'awaiting_review'
            and row.visibility == 'public'
            and not has_other_active_claim(user))

def can_publish(row, user):
    return (user is not None
            and user.role in ('maintainer', 'owner')
            and row.state == 'under_review'
            and row.marked_ready)
```

`can_edit` gates `@require_edit_lock` on every mutating *save* endpoint. `under_review + marked_ready=1` is explicitly **not editable** — saves return 410.

### No optimistic UI needed

In v1, claim/release fired `repository_dispatch` and returned 202 with optimistic state, with reconciliation arriving via webhook + 30 s polling backstop. In v2, claim/release write the bucket state file synchronously (within the request handler) and return 200 with authoritative state. No propagation lag, no optimistic flag, no reconciliation. The frontend gets the truth in the response.

Caveat: **other tabs / other users** of the same reciter still need to learn about the state change. Two paths:

- **Polling:** frontend polls `/api/reciter-task/<slug>` every 30 s while on the reciter page. Authoritative within 30 s.
- **Server-Sent Events (future):** Inspector can push state updates over an SSE stream. Out of scope for v2 initial.

For Phase 3, polling is sufficient.

## 9. Authorization

| Concept | v1 | v2 |
|---|---|---|
| User identity | GitHub OAuth (login + id) | HF OAuth (`hf_user_id` canonical, login is display-only) |
| Maintainer / owner membership | GitHub team via App API | **One file: `data/inspector_roles.json`** on GitHub (CODEOWNERS-gated) |
| Role cache | 60 s | 60 s |

### Single roles file

`data/inspector_roles.json` consolidates owners + maintainers into one file. Earlier drafts had two parallel files (`inspector_owners.json` + `inspector_maintainers.json`); collapsing eliminates two failure modes (one file present, the other not) and makes "promote to owner" a single-row edit.

Schema:

```jsonc
{
  "schema_version": 1,
  "members": [
    {
      "hf_user_id": "12345",       // canonical (immutable)
      "login": "ahmed",            // display cache (refreshed periodically)
      "role": "owner",             // 'owner' | 'maintainer'
      "added_at": "2026-04-01T...",
      "added_by_hf_id": "67890",
      "removed_at": null,          // soft-delete; preserves audit
      "removed_by_hf_id": null
    }
  ]
}
```

**Why `hf_user_id` canonical:** if an owner renames themselves on HF, `login`-based lookup silently revokes their role. The lookup is `member.hf_user_id == user.hf_user_id`, never `login`.

**Why soft-delete:** historical role membership stays queryable. "Who was an owner when X bad action happened?" doesn't require `git blame` of the file — it's a JSON scan.

### Backend resolution

```python
def resolve_role(user: AuthenticatedUser) -> Role:
    member = next(
        (m for m in MEMBERS_CACHE
         if m.hf_user_id == user.hf_user_id and m.removed_at is None),
        None,
    )
    return member.role if member else Role.CONTRIBUTOR
```

Cache: 60 s. Source: GitHub raw (`https://raw.githubusercontent.com/<owner>/<repo>/main/data/inspector_roles.json`). Refreshed in the request path (cache miss → fetch). Fallback: snapshot baked into the Space image at build time; live wins on next refresh.

Owners can additionally call `POST /api/admin/refresh-roles` to force-refresh.

### Why GitHub for the roles file (not the bucket)

Roles govern *who can edit*, not *what's edited*. CODEOWNERS-gated PR review is the right gate for security-critical role changes (existing owners must approve). The bucket is the right place for *content*; GitHub is the right place for *permissions*.

The HF OAuth `hf_oauth_authorized_org` setting can additionally restrict who can sign in at all — useful if Inspector is for org-internal contributors only. Default unset (public).

## 10. Downstream consumers and producers

### Files derived from catalog + state

| Output | Producer | Reads from |
|---|---|---|
| `data/reciters_index.json` | `.github/scripts/list_reciters.py` (GH Action) | catalog (identity) + bucket state (status) + dataset (ts/segments coverage). Calls `huggingface_hub` to read state |
| `data/RECITERS.md` | same | same |
| README badge counts | same | same |
| HF dataset `manifest.json.gz` | `.github/scripts/build_reciter.py --build-manifest` (HF Job) | catalog + bucket state + dataset shard hashes |
| GitHub release `manifest.json` | `.github/scripts/package_release.py` (GH Action) | bucket state (`completed` filter) + dataset shards |
| Reciter Requests Space's reciter catalog | The Space itself | reads `data/reciters_index.json` from GitHub (unchanged interface; Space sees no breakage) |

### Keeping `reciters_index.json` alive (transitional)

External consumers — chiefly the Reciter Requests Space — read `reciters_index.json`. Two paths:

A. **Keep regenerating** as a derived snapshot from catalog + state. `update-reciters.yml` rebuilds it on every relevant change. External consumers see no change.

B. **Drop entirely** and update external consumers to read catalog and state directly.

**Decision:** start with (A) (low-risk migration), schedule (B) as later cleanup once the Reciter Requests Space and any other external readers are migrated to read state via `huggingface_hub`.

### Trigger sources for the regeneration

`update-reciters.yml` triggers on:

- `repository_dispatch` event `reciter.completed` and `reciter.catalog_changed` (both fired by Inspector via `INSPECTOR_GITHUB_DISPATCH_TOKEN`)
- `schedule` cron hourly (catches anything missed; reduced from 30 min — primary triggers are dispatch events)
- `workflow_dispatch` for manual runs

It reads BOTH SQLite files (state + catalog) from the buckets via `huggingface_hub` at the start of each run. Workflow has `concurrency: { group: update-reciters, cancel-in-progress: false }` to avoid races between dispatch + cron.

### Staleness scenarios

| Scenario | Symptom | Mitigation |
|---|---|---|
| `update-reciters.yml` workflow file outdated | `reciters_index.json` stale | Rewrite in scope of Phase 0 |
| `--build-manifest` outdated | HF dataset manifest stale | Rewrite in scope of Phase 0 |
| `package_release.py` left on file-presence check | Two truth sources for "is reciter completed" | Optional cleanup in Phase 6 |
| Reciter Requests Space points at old `reciters_index.json` shape | Space's reciter dropdown stale on new fields | Keep regenerating until D2 (Space deprecation) lands |

## 11. Phased rollout

### Phase 0 — Foundation

**In scope:**
- Land `scripts/lib/reciter_task.py` (slug resolver against catalog + state).
- Land `scripts/lib/reciter_state.py` — bucket-aware state file parser, used by `list_reciters.py` and other GH Action scripts.
- Land `inspector/services/state.py` (state machine + bucket persistence + audit log).
- Land `inspector/services/hf_bucket.py` (mount path resolver + write helpers).
- Create `data/reciter_catalog.json` (v2 schema).
- Create the dev + prod HF buckets.
- **Manually seed** `<bucket>/state/reciter_state.json` and `<bucket>/catalog/reciter_catalog.json` per §3 mapping rules. No script — too few rows.
- Land `scripts/validate_reciter_state.py` + `scripts/validate_reciter_catalog.py` + CI gates.
- **Rewrite `list_reciters.py`** to read identity from catalog and state from bucket via `huggingface_hub`.
- **Rewrite `build_reciter.py --build-manifest`** to read identity from catalog.
- **Extend `update-reciters.yml` triggers** to include catalog file paths and `reciter.completed` dispatch events.

**Acceptance:**
- Bucket state file matches observable GitHub state for every existing reciter.
- Catalog v2 parses, validates, every existing reciter has a row.
- Regenerated `reciters_index.json` is byte-identical (or differ only in newly added fields with documented null values) compared to pre-migration.
- A test event (manual call to `state.transition()`) successfully transitions a test reciter.

### Phase 1 — Read-only deploy

Inspector backend reads `reciter_state.json` from bucket on startup; reads `reciter_catalog.json` from GitHub raw. In-memory `state_store` populated. `/api/reciter-task/<slug>`, `/api/reciters` endpoints serve from the parsed store. Anonymous viewers see correct state pills.

### Phase 3 — HF OAuth + claim flow

`/api/claim`, `/api/release`, `/api/mark-ready`, `/api/unmark-ready` endpoints fire transitions through `state.py`. No dispatch events. Synchronous. 200 returned with authoritative state.

### Phase 5 — Writes

Reuses the `assignee` lookup for `@require_edit_lock`. Out of scope of this doc beyond the lock semantics.

### Phase 6 — Publish pipeline

`POST /api/admin/publish/<slug>` is the new completion gate. Fires HF Jobs + GH Actions per [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md). State transitions `ready_for_merge → awaiting_timestamps`.

## 12. Risks and open questions

### State SQLite corruption from Inspector bug

A bug in `state.py::_apply` could write structurally-valid but semantically-wrong rows. Validators (§2 invariants + SQL CHECK constraints) catch most. **Mitigation:** audit log captures every transition with full payload + `prev_hash` chain; `scripts/replay_audit.py` rebuilds the SQLite file from scratch given the audit log. SQLite's `.dump` provides forensic export.

### Audit log corruption / loss

Audit lives in the **private** metadata bucket and is partitioned per-month. Tampering by an owner is mitigated by: (a) `prev_hash` chain detects breaks; (b) periodic backup snapshot to a versioned location (quarterly).

### Catalog ↔ state drift

Catalog and state are both Inspector-written; in-process they're consistent. External readers re-download both files; they may see one updated and not the other within a ~5s upload window. Acceptable. **Mitigation:** consumers tolerate missing catalog rows for a state slug (and vice versa) gracefully.

### Bucket write fails mid-transition

`upload_file` for state SQLite or audit append raises (network, HF outage, token revoked). The SQL transaction rolls back; caller gets 503. Audit log entry was written before SQL commit (durability-first), so the audit may show an `attempted` record without a corresponding state change — recoverable on next boot via the reconciler.

### Stalled lifecycle states

Stalled `awaiting_alignment` (pipeline crash), `awaiting_timestamps` (TS Job fail), `under_review + marked_ready=1` (maintainer never publishes) — all surface in the admin dashboard's "stalled" filter. No automatic recovery in v2; first-class `_failed` events deferred ([`inspector-deferred.md`](inspector-deferred.md) D11).

### Reciter Requests Space integration

The current Reciter Requests Space (planned for deprecation — [`inspector-deferred.md`](inspector-deferred.md) D2) fires `repository_dispatch reciter.alignment_requested` into GH Actions, which is forwarded to Inspector via `forward-to-inspector.yml` (HMAC-POSTs to `/api/internal/inspector-event`). When the Space is replaced by an in-Inspector request flow, the forward webhook + the `reciter.alignment_requested` event source become Inspector-internal.

### Slug rename

Immutable in v2. Deferred — see [`inspector-deferred.md`](inspector-deferred.md) D9. The `reciter_aliases` table in the catalog schema (§3) is forward-compat groundwork.

### Multi-replica scaling

Single-process today (`-w 1` asserted at boot). Multi-replica deferred — see [`inspector-deferred.md`](inspector-deferred.md) D6. The `revision` column on `reciters` is forward-compat groundwork for OCC.
