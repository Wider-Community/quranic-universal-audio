# Inspector State Management Strategy (v2)

Companion to [`inspector-deployment-plan.md`](inspector-deployment-plan.md). Implementation-grade reference for everything reciter-state: the source-of-truth JSON file in the bucket, the catalog JSON file in the bucket, the embedded state machine, the audit log, the identity convention, Inspector integration, per-phase acceptance criteria, and risks.

The parent doc owns deployment architecture, file IO (which lives in [`inspector-data-storage.md`](inspector-data-storage.md)), auth/claim UX, locking, and edit-history simplifications. This doc owns *what state means, where it lives, who writes it, and how it gets reflected back to consumers.*

## 1. Model in one paragraph

`<bucket>/state/reciter_state.json` is the source of truth for pipeline state and current assignee. It lives in the single private HF bucket mounted into the Space. **Inspector backend is the only writer** — `inspector/services/state.py` validates every transition through an embedded state machine + pydantic models before persisting. There is no GitHub workflow for state writes (the v1 `update-reciter-state.yml` is not built in v2). Catalog (vocab, reciters, aliases, audio source templates) lives at `<bucket>/catalog/reciter_catalog.json` on the same bucket, also Inspector-managed. External consumers (HF Jobs, GH Actions for `RECITERS.md`/Releases) read both via `huggingface_hub` (download JSON file → parse).

**Plain JSON, not SQLite.** Earlier drafts proposed SQLite on the mount. The operational surface (WAL semantics on NFS, `-wal`/`-shm` sidecars, mount-flush interaction with the WAL file, the Phase 0 acceptance spike) outweighed any indexing benefit at sub-1/sec write rate and ~300 rows. Pydantic models at the service boundary handle validation + schema migration; in-memory dicts keyed on slug serve point lookups in <1 µs cold; writes are atomic-write-then-rename + per-write `huggingface_hub.upload_file()` for durability. Two files, two pydantic schemas, one bucket.

## 2. Source of truth: `<bucket>/state/reciter_state.json`

### Schema sketch

The on-bucket file is a JSON object with `schema_version`, `writer_version`, and a `reciters` list. The Inspector backend parses it via the pydantic model `inspector.schemas.state.ReciterStateFile` on startup and on every refresh; writes serialize the model back out.

```jsonc
{
  "schema_version": 1,
  "writer_version": "inspector-v2",
  "reciters": [
    {
      "slug": "saad_al_ghamdi",
      "state": "under_review",                 // enum, see §4
      "state_since": "2026-05-08T14:23:11Z",
      "assignee_hf_id": "12345",                // canonical user ref (immutable)
      "assignee_login": "alice",                // display cache (mutable; refreshed on session)
      "assignee_since": "2026-05-08T14:23:11Z",
      "marked_ready": false,                    // bool; supersedes ready_for_merge state (see §4)
      "visibility": "public",                   // enum: 'public' | 'discarded'  (archived deferred)
      "visibility_reason": null,
      "last_save_at": "2026-05-08T14:25:01Z",
      "timestamps_job_ids": ["job_a1b2"],        // append-on-refresh; tracks every MFA TS job dispatched
      "revision_in_progress": null               // sub-struct only when unlocked for re-revision; see §4
    }
  ]
}
```

The pydantic model:

```python
# scripts/lib/schemas/state.py  (cross-consumer location; see cleanup-registry §10)
class Visibility(str, Enum):
    PUBLIC = "public"
    DISCARDED = "discarded"

class ReciterState(str, Enum):
    CATALOGUED          = "catalogued"
    AWAITING_ALIGNMENT  = "awaiting_alignment"
    AWAITING_REVIEW     = "awaiting_review"
    UNDER_REVIEW        = "under_review"
    AWAITING_TIMESTAMPS = "awaiting_timestamps"
    RELEASED            = "released"
    COMPLETED           = "completed"

class RevisionContext(BaseModel):
    """Set on admin.unlocked_for_revision; cleared on re-publish.
    Lets the publish endpoint auto-restore the row to its prior state."""
    unlocked_from_state: Literal["released", "completed"]
    unlocked_at: datetime
    unlocked_by_hf_id: str
    original_assignee_hf_id: str | None  # to re-credit on re-publish

class ReciterRow(BaseModel):
    slug: str
    state: ReciterState
    state_since: datetime
    assignee_hf_id: str | None = None
    assignee_login: str | None = None
    assignee_since: datetime | None = None
    marked_ready: bool = False
    visibility: Visibility = Visibility.PUBLIC
    visibility_reason: str | None = None
    last_save_at: datetime | None = None
    timestamps_job_ids: list[str] = []                       # append-on-refresh
    revision_in_progress: RevisionContext | None = None      # see §4 unlock flow

class ReciterStateFile(BaseModel):
    schema_version: int
    writer_version: str
    reciters: list[ReciterRow]
```

**Notable design decisions** (see §2.2 for rationale):
- **No `history` array per reciter.** Audit log (`<bucket>/audit/<YYYY>-<MM>.jsonl`) is the sole source for history. Dashboard "history of slug X" is a tail-grep over the audit partitions.
- **No `issue_number`.** GitHub-shaped fields don't belong in canonical state.
- **No `assignee_login` as primary key.** Logins are mutable on HF; using login as the canonical identifier breaks on rename. **`assignee_hf_id` is canonical** (immutable, equals OIDC `sub`); `assignee_login` is a refreshable display cache. Every claim ownership check uses `assignee_hf_id`.
- **`marked_ready` as a boolean field**, not as a separate state. The under_review↔ready_for_merge round-trip via mark/unmark was a state-as-flag artifact. One field, three transitions removed. See §4.
- **`visibility` orthogonal to lifecycle.** A reciter can be discarded from any state without losing the lifecycle position. `discarded` is no longer a state value — it's `visibility = 'discarded'`. Reversal is just clearing the visibility field.
- **No `force_assignee_*` fields.** Force-claim is deferred entirely (see [`inspector-admin-perms.md`](inspector-admin-perms.md) §11). When implemented later, the fields live alongside in this same row.
- **No `revision` field.** OCC for multi-writer future is itself deferred — adding the field with no current consumer is dead-bytes. When multi-writer scale-out lands, schema migration will add it.

### 2.1 Mount semantics

The JSON file lives on the bucket mount (NFS Advanced). Writes are atomic-write-then-rename + a direct `huggingface_hub.upload_file()` call per write (durability beyond the mount's 2–30 s flush window).

- **Reads** within Inspector: parsed once at startup into the in-memory `state_store: dict[str, ReciterRow]`; replaced atomically on each write (Inspector is sole writer, so in-memory model is always correct).
- **Writes** within Inspector: per-slug `threading.Lock` serializes around `(read row, validate, write file, upload_file, append audit)`.
- **External readers** (HF Jobs, GH Actions): download the JSON file via `huggingface_hub`, parse with the same pydantic model.
- **Crash safety**: atomic-write-then-rename guarantees the file on disk is either old or new — never torn. The direct `upload_file` provides durability even if the container dies before the mount flush.
- **Tooling**: `huggingface_hub.hf_hub_download` for forensic export; replay tool reconstructs state from audit log for disaster recovery.

### 2.2 Why these schema choices

| Decision | Rationale | What was rejected |
|---|---|---|
| Plain JSON over SQLite | Pydantic validation at the service boundary, atomic-write-then-rename + per-write `upload_file()` covers durability, no `-wal`/`-shm` semantics on NFS, no Phase 0 spike needed | SQLite-on-bucket-mount; required a Phase 0 spike to verify NFS-with-WAL semantics, plus sidecar files in the bucket |
| `assignee_hf_id` canonical | HF logins are mutable; rename silently breaks login-keyed joins | `assignee` (login) as canonical — silent correctness bug on rename |
| Drop `history` array | Two SoTs for history (state file + audit log) drift on any forgotten dual-write | Bounded 20-entry ring — vestigial denormalization |
| Drop `issue_number` | GitHub-shaped field bleeding into canonical state; no longer rely on issues/PRs/GH assignees | Embedding `issue_number` per row — couples state to GitHub |
| `marked_ready` as bool | `under_review` ↔ `ready_for_merge` round-trip is a flag, not two distinct states | Two states, three transitions, identical assignee/edit semantics |
| `visibility` orthogonal | Discardable from any lifecycle phase; round-trip preserves position | `discarded` as a state value — loses previous lifecycle on un-discard |
| No `force_assignee_*` | Force-claim deferred; adding columns without consumers is dead-bytes | Carrying columns + 30-min lease + auto-clear timer for an undelivered feature |
| No `revision` field | Multi-writer scale-out deferred; YAGNI | Forward-compat scaffolding for unspecified future requirements |

### Audit log: `<bucket>/audit/<YYYY>-<MM>.jsonl`

Append-only, one line per state-changing event. Single `audit/` folder for ALL events (state, catalog, claim, admin) — no separate state/audit and catalog/audit split. Partitioned per-month from day one (`audit/<YYYY>-<MM>.jsonl`).

```jsonc
{ "ts": "2026-05-08T14:23:11Z",
  "slug": "saad_al_ghamdi",
  "event": "reciter.claimed",
  "from_state": "awaiting_review",
  "to_state": "under_review",
  "actor": { "hf_user_id": "12345", "login_at_time": "alice", "role": "contributor" },
  "payload": { },
  "request_id": "req_abc123",
  "reason": null,
  "result": "ok"
}
```

**Schema notes:**
- `schema_version` lives in `audit/_meta.json` once per partition, NOT per record. Per-record version-stamping inflates every line for no read-time benefit.
- `actor.hf_user_id` is canonical (immutable). `login_at_time` snapshots the display login at write time.
- `actor.role` snapshots the role at write time so audit forensics survive role changes.
- **No `prev_hash` chain.** Tamper detection comes from offsite versioned snapshots of the bucket (cross-Region snapshot or scheduled `huggingface_hub` download to an air-gapped store), not from in-record cryptographic linkage. Removing the chain also removes the recovery-after-orphan-record pathway, which was a recurring complexity source in early v2 drafts.
- `from_state` / `to_state` null for non-state-changing events (`catalog.edited`, etc.). Document in §4 events table per event.
- `reason` populated for events that require it (admin overrides, send-back).
- Per-event `payload` shape lives alongside its event constant in `services/state.py` as a `TypedDict` — colocation, no separate schema-doc-by-grep.

Read pattern: ad-hoc by maintainers via the admin dashboard; future "your contributions" page (deferred). ~3.6 MB/year sustained.

### Write semantics

- **Single writer:** Inspector backend's `services/state.py::transition()` function.
- **Serialization:** per-slug `threading.Lock` around `(read row, validate, write file, upload_file, append audit)`. Single lock per slug — no `(slug, login)` sub-mutex.
- **Atomicity:** atomic-write-then-rename on the mount + direct `huggingface_hub.upload_file()` per write. Readers (in-process and external) never see torn writes.
- **Audit append:** every transition appends a line to the current `audit/<YYYY>-<MM>.jsonl` partition via direct `huggingface_hub.upload_file()` (or append API equivalent), bypassing the mount's flush window — durability is more important than latency for state events (~1/min in steady state).
- **External consumers** (HF Jobs, GH Actions): download the JSON file via `huggingface_hub`, parse. Read-after-write is bounded by upload + HF CDN propagation (~5 s typical).

### Read semantics

- **Inspector:** in-memory `state_store: dict[str, ReciterRow]` hydrated from the bucket file at startup; replaced atomically on every write. Listing all reciters for the dashboard is `state_store.values()` filtered/sorted in Python.
- **HF Jobs / GH Actions:** download the JSON file via `huggingface_hub`; parse with the same pydantic model.
- **External tools:** read via the bucket-read token, or read a snapshot Inspector exposes via `/api/state/snapshot.json` (rate-limited, cached 30 s).

### Validation

`inspector/services/state.py::_validate_invariants()` runs inside the per-slug lock, before persistence:

- Pydantic enforces field types + enum membership at parse time.
- Per-state required-field invariants from §4 hold — e.g., `state == 'under_review'` requires `assignee_hf_id is not None`.
- Timestamps monotonic — `state_since >= prev_state_since`.
- `marked_ready == True` requires `state == 'under_review'` and `assignee_hf_id is not None`.

Failure raises `InvalidTransition`; the in-memory model is not mutated; the on-disk file is unchanged; caller receives 400 with the violation message. No audit entry is written for invalid attempts (the request log captures them).

## 3. Catalog: `<bucket>/catalog/reciter_catalog.json`

### Why the bucket + plain JSON for the catalog

Same reasoning as state (§2): pydantic models at the service boundary handle validation + schema migration; per-write `huggingface_hub.upload_file()` covers durability; in-memory dicts serve point lookups. Catalog also lives on the bucket because:

1. v2's architectural shift is "no per-reciter PRs." Keeping catalog on GitHub PRs means a PR-creation token + auto-merge workflow + PR review queue, just for catalog edits.
2. The same Inspector-as-sole-writer pattern works for catalog. Maintainer+ role required for `catalog.added` / `catalog.edited` events; immutable fields (`slug`, `reciter_id`) rejected by the validator.

`<bucket>/access/inspector_roles.json` (the role file, see §9) lives **on the same private bucket** as state + catalog + audit — Inspector is sole writer; bootstrap via hand-seed.

### Catalog read paths

| Consumer | Path |
|---|---|
| Inspector backend | Parse `<INSPECTOR_BUCKET_MOUNT>/catalog/reciter_catalog.json` via pydantic at startup; in-memory model replaced atomically on each write |
| GH Actions (`update-reciters.yml`) | Download via `huggingface_hub`; parse with the same pydantic model |
| HF Jobs | Same |
| Browser (Audio tab) | Backend serves a cached copy via `/api/static/catalog.json`; browser fetches once on app load |

### Design principle: slug is opaque, catalog is structured

The slug is just a unique ID string. **No parser ever extracts semantic meaning from it.** All dimensions that matter — name, riwayah, style, source, channel, year, variant — are catalog fields. Adding a new dimension later is a pydantic schema bump + version migration, never a slug reshape.

### Schema reference

**The canonical schema reference is [`../../reference/reciter-catalog.md`](../../reference/reciter-catalog.md)** — the live source for vocab shapes, `reciters[]`, `deliveries[]`, sidecars, slug convention, naming style guide, and workflows. The sketch below in this section is historical (pre-dedup-pass) and **does not match what ships**. When implementing Phase 0 schemas at `scripts/lib/schemas/`, mirror the reference doc, not this section.

Key v2-specific concerns that the reference doc does not cover (these still apply):

- **Inspector is sole writer.** Maintainer+ role required for `catalog.added` / `catalog.edited` events. Immutable fields (`slug`, `reciter_id`) rejected by `services/catalog.py::_validate`. Direct mutation outside Inspector forbidden by convention post-cutover.
- **Same write semantics as state file**: per-slug `threading.Lock`, atomic-write-then-rename to bucket mount, direct `huggingface_hub.upload_file()` per write for durability beyond the mount flush window.
- **Browser catalog access** — Inspector backend serves a cached copy via `/api/static/catalog.json`; browser fetches once on app load.

### Historical schema sketch (do not implement — see reference doc)

ONE file consolidates: vocab (riwayat, styles, audio sources) + reciters list + aliases. Replaces `data/riwayat.json`, `data/sources.json`, `data/styles.json`, the 381 per-reciter audio manifests under `data/audio/<cat>/<src>/<slug>.json`, and the previously-planned catalog SQLite.

```jsonc
{
  "schema_version": 1,
  "vocab": {
    "riwayat":  ["Hafs an Asim", "Warsh an Nafi", "Qaloon an Nafi", "..."],
    "styles":   ["Murattal", "Mujawwad"],
    "audio_sources": [
      {
        "source_id": "mp3quran",
        "audio_category": "by_surah",
        "url_template_kind": "by_surah",
        "url_template_default": "https://server8.mp3quran.net/{slug}/{surah:03d}.mp3",
        "timing_supported": false
      },
      {
        "source_id": "everyayah",
        "audio_category": "by_ayah",
        "url_template_kind": "by_ayah_padded",
        "url_template_default": "https://everyayah.com/data/{slug}/{surah:03d}{ayah:03d}.mp3",
        "timing_supported": false
      }
    ]
  },
  "reciters": [
    {
      "slug": "saad_al_ghamdi",
      "reciter_id": "saad_al_ghamdi",
      "name_en": "Saad Al-Ghamdi",
      "name_ar": "سعد الغامدي",
      "country": "SA",
      "riwayah": "Hafs an Asim",
      "style": "Murattal",
      "audio_source": "mp3quran",
      "url_template_override": null,
      "url_overrides": null,             // optional per-chapter map: { "1": "...", "2": "..." }
      "recording_year": 2018,
      "variant_label": null,
      "added_at": "2025-09-01T12:00:00Z",
      "added_by_hf_id": "67890",
      "notes": null
    }
  ],
  "aliases": [
    { "old_slug": "saad_alghamdi", "new_slug": "saad_al_ghamdi", "aliased_at": "2025-12-01T..." }
  ]
}
```

The pydantic model lives at `scripts/lib/schemas/catalog.py` (cross-consumer):

```python
class AudioCategory(str, Enum):
    BY_SURAH = "by_surah"
    BY_AYAH  = "by_ayah"

class UrlTemplateKind(str, Enum):
    BY_SURAH         = "by_surah"
    BY_AYAH_PADDED   = "by_ayah_padded"
    BY_AYAH_UNPADDED = "by_ayah_unpadded"
    CUSTOM           = "custom"

class AudioSource(BaseModel):
    source_id: str
    audio_category: AudioCategory
    url_template_kind: UrlTemplateKind
    url_template_default: str | None = None
    timing_supported: bool = False

class Vocab(BaseModel):
    riwayat: list[str]
    styles: list[str]
    audio_sources: list[AudioSource]

class CatalogReciter(BaseModel):
    slug: str
    reciter_id: str
    name_en: str
    name_ar: str
    country: str = "unknown"
    riwayah: str
    style: str
    audio_source: str
    url_template_override: str | None = None
    url_overrides: dict[str, str] | None = None
    recording_year: int | None = None
    variant_label: str | None = None
    added_at: datetime
    added_by_hf_id: str
    notes: str | None = None

class Alias(BaseModel):
    old_slug: str
    new_slug: str
    aliased_at: datetime

class ReciterCatalog(BaseModel):
    schema_version: int
    vocab: Vocab
    reciters: list[CatalogReciter]
    aliases: list[Alias]
```

### Field semantics

| Field | Required | Notes |
|---|---|---|
| `slug` | yes | Primary key inside the list; uniqueness enforced by `services/catalog.py`. Immutable. |
| `reciter_id` | yes | Groups variants. Convention: **canonical variant has `slug == reciter_id`** (no `is_canonical` bool needed — the convention carries the invariant). Variants have `reciter_id` matching the canonical's slug. |
| `audio_source` | yes | References `vocab.audio_sources[].source_id`. Most reciters per source share the source's default URL template. |
| `url_template_override` | no | Only set for reciters that don't fit their source's default — rare. Eliminates the 50-fold denormalization v1 had. |
| `url_overrides` | no | Per-chapter override map for the rare reciter where individual chapters have anomalous URLs. |
| `country` | yes | ISO-2 or `unknown`. Validated app-side against an ISO-2 list baked into the validator. |
| `notes` | no | Free-form. Maintainers always want it; better to have than not. |

Audio URLs are computed on-the-fly by `services/audio_url.py::resolve(slug, surah, ayah)` using the source's template (or the reciter's `url_template_override`, or the per-chapter `url_overrides[str(surah)]`).

**Dropped**: `is_canonical: bool` invariant (replaced by `slug == reciter_id` convention); per-row `audio_category` and `url_template` denormalization (factored to `vocab.audio_sources`); the 381 per-reciter manifests (one source-template per source covers them all).

### Slug naming rules

```
^[a-z][a-z0-9_]{1,39}$
```

ASCII lowercase, single underscores between tokens, no double-underscore, no trailing underscore. 2–40 characters. URL-safe by construction. Immutable after first publish.

### Update path

- **Adds:** maintainer uses `POST /api/admin/catalog/add` (admin §5.6); Inspector validates + writes + audits. New requests in v2 = GitHub issue with `<!-- reciter-task: slug=... schema=1 -->` body marker; maintainer reads the issue, manually adds the catalog row.
- **Edits:** maintainer uses `POST /api/admin/catalog/edit/<slug>`. Validator rejects mutations to `slug` and `reciter_id`.
- **New variants:** add a new entry with `reciter_id` matching the canonical entry's `slug`.

On any catalog write, Inspector fires `repository_dispatch reciter.catalog_changed` to trigger `update-reciters.yml`. Inspector's own cache is fresh by construction (it's the writer).

### Validation

`inspector/services/catalog.py::_validate()` runs inside the per-slug lock, before persistence:

- Pydantic enforces field types + enum membership at parse time.
- `slug` matches the regex; `reciter_id` matches the regex.
- `riwayah` is in `vocab.riwayat`; `style` is in `vocab.styles`.
- `audio_source` references an existing entry in `vocab.audio_sources`.
- `country` is in the ISO-2 list or `'unknown'`.
- Variant entries reference an existing canonical entry via `reciter_id`.
- `aliases[].new_slug` references an existing `reciters[].slug`.

Failure raises `InvalidCatalogChange`; the in-memory model is not mutated; admin endpoint returns 400 with the violation message.

### Constraints

- `slug` and `reciter_id` immutable post-add (validator rejects updates to either).
- Removing a reciter is not exposed in v2 admin endpoints (the data is small; soft-delete via `visibility = 'archived'` is deferred).

### Initial seed (one-shot, manual at cutover)

There are ~15 reciters at v2 cutover. Maintainer authors the seed locally:

1. Hand-author `<bucket>/catalog/reciter_catalog.json` from existing `data/reciters_index.json` + per-reciter manifest `_meta` blocks. Audio source entries authored once for the ~6 known sources (`mp3quran`, `everyayah`, etc.).
2. Hand-author `<bucket>/state/reciter_state.json` from on-disk file presence per these mapping rules:

| Signal | → Initial state |
|---|---|
| Has `data/timestamps/<slug>/...` AND `data/recitation_segments/<slug>/segments.json` (per `scripts/lib/reciter_eligibility.py`) | `completed` |
| Has `data/recitation_segments/<slug>/segments.json` only | `awaiting_review` (no claim) |
| Open GitHub issue + no on-disk segments | `awaiting_alignment` |
| Catalog entry only | `catalogued` |

3. `huggingface_hub.upload_file()` both into the target bucket.
4. Audit log gets one `reciter.seeded` entry per row at cutover.

Initial seed fields per row: `assignee_*` null (reviewers re-claim fresh); `state_since = now`; `marked_ready = false`; `visibility = 'public'`.

After cutover, all subsequent transitions go through `state.py::transition()` — direct mutation outside Inspector is forbidden by convention (Inspector is sole writer).

### Audio metadata sidecars on the bucket

Per-delivery sidecars at `<bucket>/catalog/audio_manifest/<slug>.json` — one per delivery — carry the per-chapter URL map + (size_bytes, duration_sec, bitrate_kbps) when probed. The `_meta.checksum` field inside each sidecar invalidates re-probes. Schema details in [`../../reference/reciter-catalog.md`](../../reference/reciter-catalog.md) §4.

The legacy v1 `data/.audio_meta.json` and `data/.audio_durations.json` caches are **deprecated** — equivalent data now lives in the delivery row (totals, mode) and per-chapter sidecars (per-file metrics). Deletion is in Phase 1 cleanup.

## 4. State machine

### Lifecycle states

Seven lifecycle phases. **`ready_for_merge` is NOT a state** — it's a `marked_ready: bool` field on `under_review` rows. **`discarded` is NOT a state** — it's `visibility: 'discarded'` orthogonal to lifecycle. The `released → completed` split is a deliberate maintainer-gated step: `released` = files+TS visible publicly via Inspector; `completed` = also in HF dataset.

| State | Definition | Editable | Required fields | Forbidden fields |
|---|---|---|---|---|
| `catalogued` | In catalog. No alignment work has started. | No | none beyond identity | `assignee_hf_id` null |
| `awaiting_alignment` | Alignment pipeline pending or running. | No | none | `assignee_hf_id` null |
| `awaiting_review` | Alignment done. Bucket entry exists. No reviewer claimed. | No (claimable) | none | `assignee_hf_id` null |
| `under_review` | A reviewer has claimed. `marked_ready` may be false or true. | Yes (assignee only, **and** `marked_ready == false`) | `assignee_hf_id`, `assignee_login`, `assignee_since` | none |
| `awaiting_timestamps` | Publish triggered. Bucket move done. TS data not yet written. | No | none | `assignee_hf_id` null |
| `released` | Files + TS in `published/<slug>/`, in sync. Visible publicly via Inspector. **Not yet in HF dataset.** | No (admin direct-edit only via `published.edited`) | none | `assignee_hf_id` null |
| `completed` | Also published to HF dataset. | No (admin direct-edit only) | none | `assignee_hf_id` null |

**`marked_ready` semantics (boolean field on `under_review` rows):**
- `marked_ready == false`: reviewer is editing. Saves accepted.
- `marked_ready == true`: reviewer has marked ready for publish. Saves return 410 (frozen). Maintainer can now publish.
- Unmark = set `marked_ready = false`. Mark again = set to true. No state transitions; one field flip per action.

**`visibility` semantics (orthogonal field):**
- `'public'` (default): visible to everyone with appropriate permissions.
- `'discarded'`: hidden from anonymous + non-maintainer lists. Surfaced under the admin "Internal" filter. Reversal is just clearing the field back to `'public'`.
- `'archived'`: deferred. Not implemented in v2.
- A `visibility != 'public'` reciter still has a lifecycle state — `discarded` is not "no state."

`assignee_*` fields are preserved through `marked_ready = true` (the assignee may unmark to continue editing).

### Events — canonical vocabulary

**Naming convention: `<noun>.<past-tense-verb>` for every event.** Five nouns: `reciter` (lifecycle), `claim` (assignee bookkeeping), `catalog` (catalog mutations), `pipeline` (admin-triggered pipeline runs), `admin` (admin operational events). This is the **single source of truth** — `inspector/services/state.py` and the audit log both consume from this list. The admin-perms doc ([`inspector-admin-perms.md`](inspector-admin-perms.md) §11) extends the same vocabulary; do not introduce alternate names elsewhere.

**Shipping in v2:**

```
# Lifecycle (reciter.*)
reciter.alignment_completed       # pipeline finished, bucket entry seeded
reciter.published                 # maintainer published — synchronous in-process bucket move
reciter.timestamps_completed      # TS data written into published/<slug>/  -> released
reciter.dataset_published         # released → completed; dispatches sync-dataset rebuild
reciter.removed_from_dataset      # completed → released; dispatches dataset rebuild dropping slug
reciter.unpublished               # released | completed → awaiting_review; moves published/ → wip/
reciter.merge_rejected            # maintainer flipped marked_ready=false on a ready entry; assignee retained
reciter.seeded                    # one-shot cutover seed
published.edited                  # maintainer direct-edit save on a released/completed reciter (per save batch)

# Visibility (orthogonal — not lifecycle transitions)
reciter.discarded                 # admin set visibility='discarded' (any lifecycle state)
reciter.undiscarded               # admin cleared visibility back to 'public'

# Claim cycle (claim.* / reciter.* depending on noun)
reciter.claimed                   # someone took the reciter
reciter.released                  # claimant gave it back
reciter.marked_ready              # reviewer set marked_ready=true (no state transition)
reciter.unmarked_ready            # reviewer set marked_ready=false
claim.force_released              # admin override
claim.reassigned                  # admin override

# Discrete admin overrides
admin.force_set_state             # direct state field write — narrow allowed pairs only
admin.unlocked_for_revision       # released | completed → awaiting_review; copies published/ → wip/; sets revision_in_progress
admin.batch_timestamps_refresh    # re-enqueues MFA timestamps job(s); appends to timestamps_job_ids

# Access (access.*)  — roles file on the bucket, see §9
access.role_granted               # admin elevated a user
access.role_revoked               # admin demoted/removed a user
access.role_updated               # any other mutation (login refresh, etc.)

# Catalog (catalog.*)
catalog.added                     # new entry in catalog
catalog.edited                    # mutated mutable fields on existing entry
catalog.audio_source_added        # new entry in vocab.audio_sources
```

**Deferred events (not implemented in v2 — no code, no events, no fields, no endpoints):**

```
reciter.alignment_requested        # pipeline-triggered awaiting_alignment is now a maintainer admin
                                   # action (until Inspector-native intake lands)
reciter.archived                   # visibility='archived' deferred
reciter.unarchived
reciter.alignment_failed
reciter.timestamps_failed
reciter.timestamps_stale
reciter.audio_source_changed
claim.force_acquired               # force-claim entirely deferred — no force_assignee_* fields,
claim.force_released_auto          # no 30-min lease, no auto-clear timer
admin.force_clear_assignee         # deferred
admin.force_unmark_ready           # deferred
admin.force_revision_bump          # deferred (no revision field exists)
pipeline.triggered                 # deferred — no in-Inspector pipeline trigger
admin.job_rerun                    # deferred — maintainer manual re-trigger via "check status" button
```

The admin-perms doc lists these explicitly under "Deferred admin actions" so endpoints + UI surface stay aligned.

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

### Transition matrix (canonical — single source for `state.py`)

Lifecycle states = `catalogued`, `awaiting_alignment`, `awaiting_review`, `under_review`, `awaiting_timestamps`, `released`, `completed` (seven total). `marked_ready` and `visibility` are orthogonal fields. `timestamps_job_ids` and `revision_in_progress` are append/set columns documented in §2.

| Event | From state(s) | To state | Other field changes | Actor role | Side effects |
|---|---|---|---|---|---|
| `catalog.added` (creates state row implicitly) | (no row) | `catalogued` | — | system / maintainer+ | New row inserted with defaults |
| `catalog.edited` | any | (same) | — | maintainer+ | No state transition; catalog file mutated; audit in `<bucket>/audit/<YYYY>-<MM>.jsonl` |
| `reciter.alignment_completed` | `awaiting_alignment` | `awaiting_review` | — | system (pipeline webhook) | Bucket entry seeded by pipeline |
| `reciter.claimed` | `awaiting_review` | `under_review` | set `assignee_hf_id`, `assignee_login`, `assignee_since`; `marked_ready = false` | contributor+ | One-claim-per-user check |
| `reciter.released` | `under_review` | `awaiting_review` | clear assignee_*; `marked_ready = false` | claim-holder OR maintainer+ | — |
| `reciter.marked_ready` | `under_review` | (same) | `marked_ready = true` | claim-holder | — |
| `reciter.unmarked_ready` | `under_review` | (same) | `marked_ready = false` | claim-holder | — |
| `reciter.merge_rejected` | `under_review` (with `marked_ready = true`) | (same) | `marked_ready = false` (assignee retained) | maintainer+ | Reason required ≥10 chars |
| `reciter.published` | `under_review` (with `marked_ready = true`) | `awaiting_timestamps` | clear assignee_*; `marked_ready = false` | maintainer+ | Synchronous in-process: bucket move `wip/<slug>/` → `published/<slug>/`; fire `repository_dispatch reciter.completed`; enqueue ONE timestamps HF Job |
| `reciter.timestamps_completed` | `awaiting_timestamps` | `released` | append job_id to `timestamps_job_ids` | system (job callback via `POST /api/internal/job-completed`) | TS HF Job confirmed; reciter now visible publicly via Inspector but not yet in HF dataset |
| `reciter.dataset_published` | `released` | `completed` | — | maintainer+ (single via `POST /api/admin/publish-to-dataset/<slug>`, batch via `POST /api/admin/publish-to-dataset` with `{slugs:[...]}`) | Fires `repository_dispatch sync-dataset.yml` to add slug to HF dataset |
| `reciter.removed_from_dataset` | `completed` | `released` | — | maintainer+ (reason ≥10 chars) | Dispatches dataset rebuild dropping slug; bucket files retained |
| `reciter.unpublished` | `released`, `completed` | `awaiting_review` | clear assignee_*; if was `completed`, also dispatch dataset rebuild | maintainer+ (reason ≥10 chars + typed `unpublish <slug>` confirmation) | Moves `<bucket>/published/<slug>/` → `<bucket>/wip/<slug>/` |
| `admin.unlocked_for_revision` | `released`, `completed` | `awaiting_review` | set `revision_in_progress = {unlocked_from_state, unlocked_at, unlocked_by_hf_id, original_assignee_hf_id}`; clear assignee_*; `marked_ready = false` | maintainer+ (reason ≥10 chars) | Copies `published/<slug>/` → `wip/<slug>/` (published files retained so public continues seeing the current version) |
| `published.edited` | `released`, `completed` | (same) | — | maintainer+ | Direct edit on a published reciter; saves write to `published/<slug>/`; emitted per save batch; disallowed during `awaiting_timestamps` |
| `admin.batch_timestamps_refresh` | `released`, `completed` | (same) | append new job_id(s) to `timestamps_job_ids` | maintainer+ (reason in payload) | Re-enqueues MFA timestamps job(s); single-slug or batch via `POST /api/admin/refresh-timestamps[/<slug>]` |
| `reciter.discarded` | (any) | (same) | `visibility = 'discarded'`, `visibility_reason = ...` | maintainer+ | Typed confirmation phrase + reason ≥10 chars |
| `reciter.undiscarded` | (any with `visibility = 'discarded'`) | (same) | `visibility = 'public'` | maintainer+ | — |
| `claim.force_released` | `under_review` | `awaiting_review` | clear assignee_*; `marked_ready = false` | maintainer+ | Reason required |
| `claim.reassigned` | `awaiting_review`, `under_review` | `under_review` | set new assignee_* (HF API resolved per admin §5.2); `marked_ready = false` | maintainer+ | Reason required |
| `admin.force_set_state` | (narrow allowed pairs) | (specified) | — | maintainer+ | Allowed pairs: `catalogued ↔ awaiting_alignment`, `awaiting_alignment ↔ awaiting_review`, `awaiting_timestamps ↔ released`, `released ↔ completed` (alternative to `reciter.dataset_published` / `reciter.removed_from_dataset` for force-correction without dispatching dataset rebuild), `under_review → awaiting_review` (alternative to `claim.force_released`). Other pairs return 400. |
| `reciter.seeded` | (no row) | (specified) | initial values per cutover spec | manual (one-shot) | One-time only |

**Notes:**

- Direct `under_review → reciter.published` requires `marked_ready = true` — the validator enforces this per the §4 invariants table.
- `visibility = 'discarded'` does NOT change the lifecycle state — the row keeps its `state`, just becomes hidden. `reciter.undiscarded` un-hides without the lifecycle losing position.
- **No `* → *` escape hatch exists.** `admin.force_set_state` accepts only the narrow allowed pairs above. If a recovery scenario isn't covered, add a new named event (audit pattern: write the use case, name the event, add to this matrix, ship).
- The "Deferred events" callout above lists every event that v2 explicitly does NOT implement. Re-introducing any of them is a separate decision.

### Why re-edits don't get their own state

Re-edits of `completed` reciters are deferred — see [`inspector-deferred.md`](inspector-deferred.md). When implemented, the path will be: maintainer calls a re-claim endpoint → Inspector copies `<bucket>/published/<slug>/...` back into `<bucket>/wip/<slug>/...` (in-process, server-side) → state transitions `completed → awaiting_review`. The re-edit then follows the normal `awaiting_review → under_review → published` path. Browser caches behave correctly because inspector segment shards use `Cache-Control: max-age=86400` (1 day, NOT immutable) — re-publishes propagate within a day without versioned URLs.

## 5. State machine implementation

`inspector/services/state.py` is the single point of truth for state writes. Pseudocode:

```python
class StateStore:
    def __init__(self, bucket: HfBucket, audit_log: AuditLog, locks: PerSlugLocks):
        self.bucket = bucket
        self.audit_log = audit_log
        self.locks = locks                                  # one threading.Lock per slug
        self._model: ReciterStateFile = self._load()        # parse on startup
        self._index: dict[str, ReciterRow] = {r.slug: r for r in self._model.reciters}

    def transition(self, slug: str, event: Event, actor: User) -> ReciterRow:
        with self.locks.acquire(slug):                      # one lock per slug, no sub-mutex
            row = self._index.get(slug)
            new_row = self._apply(row, event, actor)        # pure function; raises InvalidTransition
            self._validate_invariants(new_row)
            self.audit_log.append(AuditRecord(
                ts=now_utc(), slug=slug, event=event.name,
                from_state=row.state if row else None, to_state=new_row.state,
                actor=actor.audit_view(), payload=event.payload,
                request_id=current_request_id(), reason=event.reason, result='ok',
            ))
            self._index[slug] = new_row
            self._model = ReciterStateFile(
                schema_version=self._model.schema_version,
                writer_version=self._model.writer_version,
                reciters=list(self._index.values()),
            )
            self.bucket.write_state(self._model)            # atomic-write-then-rename + upload_file
            return new_row

    def _apply(self, row, event, actor):
        # Pure function. Raises InvalidTransition if event isn't allowed from (row.state, row.marked_ready, row.visibility).
        # Encodes the §4 matrix plus business rules:
        #   - reciter.claimed: row.assignee_hf_id must be None; actor must not have another active claim.
        #   - reciter.released / reciter.unmarked_ready / reciter.marked_ready:
        #       actor.hf_user_id must equal row.assignee_hf_id (NOT login).
        #   - reciter.merge_rejected / reciter.published: actor.role >= maintainer.
        #   - admin.force_set_state: actor.role >= maintainer; reason required;
        #       (from_state, to_state) must be in the narrow allowed-pairs whitelist.
        ...
```

**Concurrency:**

- **Per-slug `threading.Lock`** serializes transitions within Inspector. ONE lock per slug — no `(slug, login)` sub-mutex, no force-claim sub-mutex coordination (force-claim is deferred entirely).
- **Cross-slug transitions** run concurrently (different locks).
- **`hf_user_id` everywhere** — the lookup is `row.assignee_hf_id == user.hf_user_id`, not `row.assignee_login == user.login`. Login renames don't break locks.

**Fault model:**

- Audit append fails before file write → caller gets 503; in-memory model untouched; no inconsistency.
- File write / `upload_file` fails after audit append → in-memory model rolled back to prior; audit log retains the entry (with `result: 'ok'` — durability of the audit means the change *was* recorded; on recovery, replay tool reconciles).
- Inspector crashes mid-transition → atomic-write-then-rename guarantees the file is either old or new, never torn. Per-write `upload_file` makes durability independent of mount flush.
- Mount flush window: bypassed for state file writes (direct `upload_file` on every transition) and audit appends (same).

## 5.1 The single-writer assertion (`-w 1`)

`inspector/app.py::create_app()` MUST assert at boot:

```python
workers = int(os.environ.get("GUNICORN_WORKERS", "1"))
if workers != 1:
    raise RuntimeError(
        "Inspector v2 assumes single-process: state lock, in-memory state_store, "
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
| Bucket path, in-flight | `<bucket>/wip/<slug>/` | `<bucket>/wip/saad_al_ghamdi/` |
| Bucket path, published | `<bucket>/published/<slug>/` | `<bucket>/published/saad_al_ghamdi/` |
| Inspector URL | `/r/<slug>` | `/r/saad_al_ghamdi` |

Dropped vs v1: branch convention `reciter/<slug>`, PR title convention, commit subject conventions, squash-merge subject convention, HTML-comment markers in PR bodies.

## 7. Reciter request flow

The Reciter Requests Space is being decommissioned (separate cleanup work; see [`inspector-deferred.md`](inspector-deferred.md)). Inspector-native intake is explicitly deferred.

In the meantime, new requests in v2 = a GitHub issue with a body marker:

```markdown
<!-- reciter-task: slug=saad_al_ghamdi schema=1 -->

| | |
|---|---|
| Slug | `saad_al_ghamdi` |
| Display | Saad Al-Ghamdi |
| Riwayah | Hafs an Asim |
| Style | Murattal |
| Audio source | everyayah |
```

A maintainer reads the issue, manually adds the catalog entry via `POST /api/admin/catalog/add`, and the row's lifecycle starts at `catalogued`. Pipeline-triggered `awaiting_alignment` transitions are now a maintainer admin action (until the in-Inspector intake lands later).

**Dropped vs earlier v2 drafts:**

- `forward-to-inspector.yml` workflow.
- `/api/internal/inspector-event` endpoint.
- `INSPECTOR_FORWARD_SECRET` (and `_PREV`).
- `reciter.alignment_requested` event from the canonical event vocabulary (§4).

## 8. Inspector integration

### State refresh strategy

- **On startup:** parse `<INSPECTOR_BUCKET_MOUNT>/state/reciter_state.json` and `.../catalog/reciter_catalog.json` via pydantic. Hydrate `state_store: dict[str, ReciterRow]` and the catalog model.
- **On every state write:** Inspector replaces the in-memory model atomically; on-disk file written via atomic-write-then-rename + `huggingface_hub.upload_file()`.
- **No webhook from anywhere else** — there is no other writer.

### API endpoints

Full contracts in [`inspector-deployment-plan.md`](inspector-deployment-plan.md) §4. Index here (slug always in path):

```
# Identity
GET  /api/me                            → { hf_user_id, login, role, active_claim }
GET  /api/auth/login                    → initiates HF OAuth flow
GET  /api/auth/callback                 → handles HF redirect, sets signed-cookie session
POST /api/auth/logout                   → clears session cookie

# State reads
GET  /api/reciters                      → [{ slug, display, state, marked_ready, visibility, riwayah, style }]
GET  /api/reciter-task/<slug>           → full row + can_*_for_current_user predicates
GET  /api/state/snapshot.json           → read-only snapshot, rate-limited; cached 30 s

# Claim flow (mutating — write directly to bucket state file, return 200 with authoritative row)
POST /api/claim/<slug>                  → state.transition(slug, ReciterClaimedEvent(actor))
POST /api/release/<slug>                → state.transition(slug, ReciterReleasedEvent(actor))
POST /api/mark-ready/<slug>             → state.transition(slug, ReciterMarkedReadyEvent(actor))
POST /api/unmark-ready/<slug>           → state.transition(slug, ReciterUnmarkedReadyEvent(actor))

# Admin (maintainer+ only) — the v2-shipped subset
POST /api/admin/publish/<slug>          → reciter.published; under_review (with marked_ready=true) → awaiting_timestamps
POST /api/admin/send-back/<slug>        → reciter.merge_rejected (flips marked_ready=false; assignee retained)
POST /api/admin/discard/<slug>          → reciter.discarded; set visibility='discarded'
POST /api/admin/undiscard/<slug>        → reciter.undiscarded; clear visibility back to 'public'
POST /api/admin/claim/force-release/<slug>   → claim.force_released
POST /api/admin/claim/reassign/<slug>        → claim.reassigned (resolves to_login → hf_user_id server-side)
POST /api/admin/state/force-set/<slug>       → admin.force_set_state (narrow allowed pairs only)
POST /api/admin/catalog/add                  → catalog.added
POST /api/admin/catalog/edit/<slug>          → catalog.edited

# Internal callbacks (not user-facing)
POST /api/internal/job-completed             → reciter.timestamps_completed; Bearer-auth via INSPECTOR_JOB_CALLBACK_SECRET
```

**Deferred admin endpoints (NOT in v2):**

- `POST /api/admin/archive/<slug>` / `unarchive/<slug>` — `visibility='archived'` deferred
- `POST /api/admin/claim/clear/<slug>` — `admin.force_clear_assignee` deferred
- `POST /api/admin/state/force-unmark-ready/<slug>` — `admin.force_unmark_ready` deferred
- `POST /api/admin/pipeline/trigger/<slug>` — `pipeline.triggered` deferred
- `POST /api/admin/job/rerun/<slug>` — `admin.job_rerun` deferred (maintainer manually re-triggers from a "check status" button)
- `POST /api/internal/inspector-event` — forward-from-Reciter-Requests endpoint deferred (D17)

**Endpoint conventions:** slug always in the URL path (no slug-in-body). Internal endpoints use Bearer token (constant-time compare) via `INSPECTOR_JOB_CALLBACK_SECRET` — single secret, no `_PREV` rotation slot. (Earlier-v2-draft "HMAC" wording is gone.)

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

`can_edit` gates `@require_edit_lock` on every mutating *save* endpoint. `under_review + marked_ready=true` is explicitly **not editable** — saves return 410.

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
| Maintainer / owner membership | GitHub team via App API | **One bucket file: `<bucket>/access/inspector_roles.json`** — Inspector is the sole writer (same pattern as state + catalog). |
| Role cache | 60 s | In-memory, replaced atomically on every write (Inspector is sole writer; no external authority to refresh from). |

### Single roles file on the bucket

`<bucket>/access/inspector_roles.json` consolidates owners + maintainers. Lives on the private HF bucket alongside state + catalog + audit — same sole-writer pattern via `services/access.py`. **Not on GitHub** — the previous draft put it there for CODEOWNERS-gated review, but the costs (public list of maintainer HF IDs, weak coupling with the rest of v2 which is HF-resident, external availability dependency) outweighed the benefits. Mutations are audited and reversible from the bucket audit log.

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

**Why soft-delete:** historical role membership stays queryable. "Who was an owner when X bad action happened?" is a JSON scan over the current file + a tail-grep over `<bucket>/audit/<YYYY>-<MM>.jsonl` for `access.*` events.

### Backend resolution

```python
def resolve_role(user: AuthenticatedUser) -> Role:
    member = next(
        (m for m in ACCESS_STORE.values()
         if m.hf_user_id == user.hf_user_id and m.removed_at is None),
        None,
    )
    return member.role if member else Role.CONTRIBUTOR
```

`ACCESS_STORE` is an in-memory dict hydrated from the bucket file at startup, replaced atomically on every write (Inspector is sole writer, so the cache is correct by construction). No GitHub-raw refresh, no per-request fetch, no force-refresh endpoint needed.

### Admin endpoints

- `POST /api/admin/access/grant` — body `{hf_user_id, login, role, reason}`. Reason ≥10 chars. Owner-only when granting `owner`; maintainer+ for `maintainer`. Audit event: `access.role_granted`.
- `POST /api/admin/access/revoke` — body `{hf_user_id, reason}`. Soft-delete via `removed_at` + `removed_by_hf_id`. Audit event: `access.role_revoked`.
- `POST /api/admin/access/update` — body `{hf_user_id, login?, role?}`. Used for login-cache refresh or role tier change. Audit event: `access.role_updated`.

### Bootstrap

First owner is hand-uploaded at Phase 0 setup time:

```bash
# One-shot bootstrap — only needed once per env.
python -c "
from huggingface_hub import upload_file
import json
seed = {'schema_version': 1, 'members': [
  {'hf_user_id': '<your_hf_user_id>', 'login': '<your_login>',
   'role': 'owner', 'added_at': '<iso>', 'added_by_hf_id': 'bootstrap',
   'removed_at': None, 'removed_by_hf_id': None}
]}
upload_file(
  path_or_fileobj=json.dumps(seed, indent=2).encode(),
  path_in_repo='access/inspector_roles.json',
  repo_id='hetchyy/quranic-inspector-bucket-dev',
  repo_type='dataset',
  commit_message='Bootstrap: seed first owner',
)
"
```

After bootstrap, all role mutations go through Inspector admin endpoints. Documented step in [`inspector-deploy-runbook.md`](inspector-deploy-runbook.md).

### Org-level OAuth gate (optional)

The HF OAuth `hf_oauth_authorized_org` setting can additionally restrict who can sign in at all — useful if Inspector is for org-internal contributors only. Default unset (public sign-in).

## 10. Downstream consumers and producers

### Files derived from catalog + state

| Output | Producer | Reads from |
|---|---|---|
| `data/RECITERS.md` | `.github/scripts/list_reciters.py` (GH Action) | bucket catalog (identity) + bucket state (status) + dataset (ts/segments coverage). Calls `huggingface_hub` to read both |
| README badge counts | same | same |
| HF dataset `manifest.json.gz` | `.github/scripts/build_reciter.py --build-manifest` (GH Action / HF Job) | bucket catalog + bucket state + dataset shard hashes |
| GitHub release `manifest.json` | `.github/scripts/package_release.py` (GH Action) | bucket state (`completed` filter) + bucket published shards |

**`data/reciters_index.json` is dropped.** Bucket catalog (`reciter_catalog.json`) is the source of truth for releases + downstream consumers from day one (no transitional period). External consumers re-fetch the catalog via `huggingface_hub`. The Reciter Requests Space is being decommissioned (separate cleanup work).

### Trigger sources for the regeneration

`update-reciters.yml` triggers on:

- `repository_dispatch` events `reciter.completed` and `reciter.catalog_changed` (both fired by Inspector via `INSPECTOR_GITHUB_DISPATCH_TOKEN`)
- `schedule` cron hourly (catches anything missed; reduced from 30 min — primary triggers are dispatch events)
- `workflow_dispatch` for manual runs

It reads BOTH JSON files (state + catalog) from the bucket via `huggingface_hub` at the start of each run. Workflow has `concurrency: { group: update-reciters, cancel-in-progress: false }` to avoid races between dispatch + cron.

### Bucket data hygiene

A new scheduled `bucket-data-hygiene.yml` GH Action runs validators (`validate_segments`, `validate_audio`, `validate_edit_history`, `validate_timestamps` — now libraries, see [`inspector-deployment-plan.md`](inspector-deployment-plan.md) §10 Phase 5) across every reciter in the bucket weekly (or on-demand via `workflow_dispatch`). Findings surface to the admin dashboard; CRITICAL findings open a GH issue automatically. This replaces the deleted `validate-segments-pr.yml` PR-gate.

### Staleness scenarios

| Scenario | Symptom | Mitigation |
|---|---|---|
| `update-reciters.yml` not yet rewritten for bucket reads | `RECITERS.md` stale | Rewrite in scope of Phase 0 |
| `--build-manifest` outdated | HF dataset manifest stale | Rewrite in scope of Phase 0 |
| `package_release.py` left on file-presence check | Two truth sources for "is reciter completed" | Cleanup in Phase 6 |

## 11. Phased rollout

### Phase 0 — Foundation

**In scope:**
- Land `scripts/lib/reciter_task.py` (slug resolver against catalog + state).
- Land `scripts/lib/reciter_state.py` — bucket-aware state file parser, used by `list_reciters.py` and other GH Action scripts.
- Land `scripts/lib/schemas/` (pydantic models for state, catalog, audit, edit_history v2).
- Land `inspector/services/state.py` (state machine + JSON persistence + audit log; per-slug `threading.Lock`; per-write `huggingface_hub.upload_file()`).
- Land `inspector/services/catalog.py` (mirrors `state.py` write pattern; vocab + reciters + aliases in one file).
- Land `inspector/services/hf_bucket.py` (mount path resolver + write helpers + atomic-write-then-rename).
- Create the dev + prod single private HF buckets.
- **Manually seed** `<bucket>/state/reciter_state.json` and `<bucket>/catalog/reciter_catalog.json` per §3 mapping rules. No script — too few rows.
- Land `scripts/validate_reciter_state.py` + `scripts/validate_reciter_catalog.py` (libraries; CLI wrappers retained for ad-hoc maintainer use against the bucket via `huggingface_hub`).
- **Rewrite `list_reciters.py`** to read identity from bucket catalog and state from bucket state via `huggingface_hub`.
- **Rewrite `build_reciter.py --build-manifest`** to read identity from bucket catalog.
- **Extend `update-reciters.yml` triggers** to include `reciter.completed` and `reciter.catalog_changed` dispatch events.

**Acceptance:**
- Bucket state file matches observable GitHub state for every existing reciter.
- Catalog parses, validates, every existing reciter has an entry.
- Regenerated `RECITERS.md` matches pre-migration (or differ only in newly added fields with documented null values).
- A test event (manual call to `state.transition()`) successfully transitions a test reciter and appends an audit line.

### Phase 1 — Read-only deploy

Inspector backend parses `reciter_state.json` and `reciter_catalog.json` from bucket on startup. In-memory `state_store` and catalog model populated. `/api/reciter-task/<slug>`, `/api/reciters` endpoints serve from the parsed store. Anonymous viewers see correct state pills.

### Phase 3 — HF OAuth + claim flow

`/api/claim`, `/api/release`, `/api/mark-ready`, `/api/unmark-ready` endpoints fire transitions through `state.py`. Self-contained signed-cookie session (Flask `itsdangerous`) — no server-side session store. No dispatch events. Synchronous. 200 returned with authoritative state.

### Phase 5 — Writes + 4 admin events

Save flow + the 4 v2 admin events: `claim.force_released`, `claim.reassigned`, `admin.force_set_state` (narrow allowed pairs only), `reciter.merge_rejected`. Reuses `assignee_hf_id` lookup for `@require_edit_lock`.

### Phase 6 — Publish pipeline

`POST /api/admin/publish/<slug>` is the new completion gate. Synchronous in-process: state transition + bucket move `wip/<slug>/` → `published/<slug>/` + `repository_dispatch reciter.completed` + ONE timestamps HF Job enqueue. The job-completion webhook (`POST /api/internal/job-completed`, Bearer-auth via single `INSPECTOR_JOB_CALLBACK_SECRET`) flips `awaiting_timestamps → completed`. See [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md).

## 12. Risks and open questions

### State file corruption from Inspector bug

A bug in `state.py::_apply` could write structurally-valid but semantically-wrong rows. Pydantic validation + invariant checks catch most. **Mitigation:** audit log captures every transition with full payload; offsite versioned snapshot of the bucket (cross-Region or scheduled `huggingface_hub` download) is the recovery copy. A replay tool can rebuild `reciter_state.json` from scratch given the audit log if needed.

### Audit log corruption / loss

Audit lives in the (single, private) bucket and is partitioned per-month. Tampering by an owner is mitigated by offsite versioned snapshots — there is **no `prev_hash` chain** in v2. Periodic backup snapshot to a cross-Region versioned location is the audit guarantee.

### Catalog ↔ state drift

Catalog and state are both Inspector-written; in-process they're consistent. External readers re-download both files; they may see one updated and not the other within a ~5s upload window. Acceptable. **Mitigation:** consumers tolerate missing catalog entries for a state slug (and vice versa) gracefully.

### Bucket write fails mid-transition

`upload_file` for state JSON or audit append raises (network, HF outage, token revoked). The in-memory model is rolled back to prior; caller gets 503. Audit log entry was written first (durability-first), so the audit may show an entry without a corresponding state change — recoverable on next boot via reconciliation.

### Stalled lifecycle states

Stalled `awaiting_alignment` (pipeline crash), `awaiting_timestamps` (TS Job fail), `under_review + marked_ready=true` (maintainer never publishes) — all surface in the admin dashboard's "stalled" filter. No automatic recovery in v2; first-class `_failed` events deferred (see [`inspector-deferred.md`](inspector-deferred.md)). The maintainer can manually re-trigger the timestamps job from a "check status" button if needed.

### HF Jobs reliability for the timestamps job

The publish path enqueues exactly one HF Job. If it fails, the row sits in `awaiting_timestamps`. Maintainer surfaces include: status indicator on the admin dashboard, a manual "re-trigger" button. No automated retry/backoff in v2.

### Slug rename

Immutable in v2. Deferred — see [`inspector-deferred.md`](inspector-deferred.md). The `aliases[]` array in the catalog schema (§3) is forward-compat groundwork.

### Multi-replica scaling

Single-process today (`-w 1` asserted at boot). Multi-replica deferred — see [`inspector-deferred.md`](inspector-deferred.md). When it lands, `revision` field gets added via pydantic schema migration; per-slug `threading.Lock` moves to a shared coordinator (Redis or bucket-CAS).
