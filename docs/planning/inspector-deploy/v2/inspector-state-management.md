# Inspector State Management Strategy (v2)

Companion to [`inspector-deployment-plan.md`](inspector-deployment-plan.md). Implementation-grade reference for everything reciter-state: the source-of-truth file in the bucket, the catalog file on GitHub, the embedded state machine, the audit log, the identity convention, Inspector integration, per-phase acceptance criteria, and risks.

The parent doc owns deployment architecture, file IO (which lives in [`inspector-data-storage.md`](inspector-data-storage.md)), auth/claim UX, locking, and edit-history simplifications. This doc owns *what state means, where it lives, who writes it, and how it gets reflected back to consumers.*

## 1. Model in one paragraph

`<bucket>/state/reciter_state.json` is the source of truth for pipeline state, current assignee, active issue numbers, and per-reciter event history. It lives in the HF bucket mounted into the Space. **Inspector backend is the only writer** — `inspector/services/state.py` validates every transition through an embedded state machine before persisting. There is no GitHub workflow for state writes (the v1 `update-reciter-state.yml` is not built in v2). Static identity (display name, riwayah, audio source, `url_template`) lives in `data/reciter_catalog.json` on GitHub, updated by manual PRs from the Reciter Requests intake. Inspector reads catalog from GitHub raw on startup, state from the bucket on startup, and refreshes both on demand. External consumers (HF Jobs, GH Actions for `RECITERS.md`/Releases) read the state file from the bucket via `huggingface_hub`.

## 2. Source of truth: `<bucket>/state/reciter_state.json`

### Schema

```jsonc
{
  "schema_version": 1,
  "updated_at": "2026-05-09T14:23:11Z",
  "updated_by": "inspector-prod-replica-0",
  "reciters": {
    "saad_al_ghamdi": {
      "slug": "saad_al_ghamdi",
      "state": "under_review",
      "state_since": "2026-05-08T14:23:11Z",
      "issue_number": 42,
      "assignee": "alice",
      "assignee_hf_id": "12345",
      "assignee_since": "2026-05-08T14:23:11Z",
      "history": [
        { "at": "2026-04-15T...", "event": "catalog_synced",      "detail": "added"      },
        { "at": "2026-04-15T...", "event": "alignment_requested", "by": "bob"            },
        { "at": "2026-04-20T...", "event": "alignment_completed"                           },
        { "at": "2026-05-08T...", "event": "claimed",             "by": "alice"          }
      ]
    }
  }
}
```

### Field semantics

| Field | Type | Nullable | Notes |
|---|---|---|---|
| `schema_version` | int | no | Bump on rename / removal / semantic change. Additive fields don't bump. |
| `updated_at` | ISO 8601 | no | Wall-clock of last write |
| `updated_by` | string | no | Inspector replica id (for multi-replica future); single-replica today |
| `reciters[<slug>].slug` | string | no | Redundant with key — kept for tooling that streams entries |
| `reciters[<slug>].state` | enum | no | One of the seven states in §4 |
| `reciters[<slug>].state_since` | ISO 8601 | no | Latest transition into current state |
| `reciters[<slug>].issue_number` | int | yes | Null in `catalogued`; set from `awaiting_alignment` onward (Reciter Requests Space provides) |
| `reciters[<slug>].assignee` | string | yes | HF login. Null except in `under_review` and `ready_for_merge` |
| `reciters[<slug>].assignee_hf_id` | string | yes | HF user id; permanent identifier |
| `reciters[<slug>].assignee_since` | ISO 8601 | yes | Same lifetime as `assignee` |
| `reciters[<slug>].history` | array | no | Bounded ring of last 20 entries; full history in `<bucket>/state/audit.jsonl` |

Note: v1's `pr_number`, `pr_head_sha` fields are **dropped** — there are no per-reciter PRs in v2.

### History entries

```jsonc
{ "at": "<iso8601>", "event": "<event_name>", "by": "<login>", "detail": "<free-form>" }
```

`event` is from the closed vocabulary in §4. `by` is set when the event was triggered by a specific user (claim, release, marked_ready, admin override). Entries are append-only within a transition; truncation drops the oldest entry when the array exceeds 20.

### Audit log: `<bucket>/state/audit.jsonl`

Append-only, one line per state-changing event. Holds the full event payload that the bounded `history` array can't:

```jsonc
{ "ts": "2026-05-08T14:23:11Z",
  "slug": "saad_al_ghamdi",
  "event": "claimed",
  "from_state": "awaiting_review",
  "to_state": "under_review",
  "actor": { "login": "alice", "hf_user_id": "12345" },
  "client_payload": { ... },
  "request_id": "req_abc123",
  "replica": "inspector-prod-replica-0" }
```

Read pattern: ad-hoc by maintainers via the admin dashboard; potential future "your contributions" page. No size cap (~3.6 MB/year sustained). Archive to dated subdirs only if pathological growth appears.

### Write semantics

- **Single writer:** Inspector backend's `services/state.py::transition()` function.
- **Serialization:** in-process mutex per slug serializes concurrent transitions on the same reciter; multi-replica future uses bucket-side optimistic concurrency.
- **Atomicity:** state file write uses tempfile + `os.replace` (atomic on local disk; mount caches the rename and flushes the renamed file as a single unit, see [`inspector-data-storage.md`](inspector-data-storage.md) §10).
- **Audit append:** every transition appends a line to `audit.jsonl` BEFORE the state file write completes. If the state write fails, the audit entry is a "would-have-transitioned" record — useful for debugging.
- **Mount flush:** within 2–30 s. External consumers (HF Jobs, GH Actions) reading via `huggingface_hub` see writes within that bound.
- **In-memory cache:** Inspector keeps the parsed `state_store: dict[str, ReciterEntry]` and updates it synchronously on every successful transition. Per-request reads are O(1).

### Read semantics

- **Inspector:** parses on startup, caches in memory, refreshes on every successful local transition. No webhook or polling needed (Inspector is the only writer, so the cache is always authoritative).
- **HF Jobs (publish, snapshot, etc.):** download via `huggingface_hub.download_bucket_files(...)` for the slug they're operating on. Read-only.
- **GH Actions (`update-reciters.yml`, `release.yml`):** download via `huggingface_hub` at the start of the workflow run. Read-only.
- **External tools (Reciter Requests Space, etc.):** can read from the bucket if they have the bucket-read token, or read a snapshot Inspector exposes via `/api/state/snapshot.json` (proposed; see §8).

### Validation

`scripts/validate_reciter_state.py` runs on the in-memory dict after every transition (CI-like guard inside Inspector itself):

- JSON parses cleanly (atomic tempfile means partial writes never reach the bucket).
- `schema_version` matches the expected version (or one supported version up).
- Every slug in `reciters` exists in `reciter_catalog.json`.
- `state` is in the closed enum.
- For each state, the required-fields invariants in §4 hold.
- `history` arrays are length ≤ 20.
- Timestamps are monotonic per slug.

Failure rolls back the in-memory transition and returns an error to the caller; the bucket file is unchanged.

## 3. Static identity: `<bucket>/catalog/reciter_catalog.json` (on the HF bucket — moved from GitHub per H3+H4 decision)

### Why the bucket for the catalog (revised v2.1)

The catalog was originally planned to live on GitHub with PR-reviewed edits. Two problems with that:

1. v2's whole architectural shift is "no per-reciter PRs." Keeping catalog edits on PRs means we still need a PR-creation token + a PR-review queue + a catalog-auto-merge workflow, just for catalog. That's the only PR-creation surface left.
2. The same `<bucket>/state/audit.jsonl` pattern (Inspector-as-sole-writer + audit log + state-machine validation) works equally well for catalog. Moving catalog to the bucket consolidates the operational model.

**Catalog now lives at `<bucket>/catalog/reciter_catalog.json`** with `<bucket>/catalog/audit.jsonl` for change history. Same writer (Inspector backend, single-process). Same validation discipline. Maintainer+ role required for `catalog.edited` events; immutable fields (`slug`, `reciter_id`) are still rejected by the validator.

`data/inspector_owners.json` and `data/inspector_maintainers.json` **stay on GitHub** — those govern *who can edit*, not *what's edited*. CODEOWNERS-gated PR review is the right gate for role mutations (it's a security-critical change that should require GitHub-account-attested approval).

### Catalog read paths

| Consumer | Path |
|---|---|
| Inspector backend | `<INSPECTOR_BUCKET_MOUNT>/catalog/reciter_catalog.json` (mount); refreshed every 5 min in a background thread (single-process) |
| GH Actions (`update-reciters.yml`) | Reads via `huggingface_hub.HfFileSystem`: `buckets/hetchyy/quranic-inspector-bucket/catalog/reciter_catalog.json` |
| HF Jobs | Same pattern as GH Actions when needed |
| External (Reciter Requests Space) | Reads `data/reciters_index.json` (regenerated derivative) — unchanged contract |

The 5-min poll inside Inspector is removed (Inspector is the writer; it knows its own cache is fresh). Other consumers re-fetch on demand.

### Design principle: slug is opaque, catalog is structured

The slug is just a unique ID string. **No parser ever extracts semantic meaning from it.** All dimensions that matter — name, riwayah, style, source, year, variant grouping — are catalog fields. Adding a new dimension later is a schema-additive change, never a slug reshape.

### Schema (v2)

```jsonc
{
  "schema_version": 2,
  "reciters": {
    "alafasy_mujawwad": {
      "slug": "alafasy_mujawwad",
      "reciter_id": "alafasy",
      "name_en": "Mishary Rashid Alafasy",
      "name_ar": "مشاري راشد العفاسي",
      "country": "kw",
      "riwayah": "hafs_an_asim",
      "style": "mujawwad",
      "audio_source": "mp3quran",
      "audio_category": "by_surah",
      "url_template": "...",
      "recording_year": null,
      "variant_label": "Mujawwad",
      "is_canonical": false,
      "added_at": "2026-04-15T...",
      "added_by": "bob"
    }
  }
}
```

### Field semantics

| Field | Type | Required | Notes |
|---|---|---|---|
| `slug` | string | yes | Primary key. Matches `^[a-z][a-z0-9_]{1,39}$`. Immutable. |
| `reciter_id` | string | yes | Same shape as slug. Groups variants. Defaults to slug for single-variant reciters. Immutable. |
| `name_en`, `name_ar` | string | yes | Display |
| `country` | ISO-2 code | yes | `unknown` if undisclosed |
| `riwayah`, `style`, `audio_source` | string | yes | Controlled vocab in `data/{riwayat,sources,styles}.json` |
| `audio_category` | enum | yes | `by_surah` or `by_ayah` |
| `url_template` | string | yes | Per [`timestamps-tab-deployment-plan.md`](../../timestamps-tab-deployment-plan.md) §3 |
| `recording_year` | int | no | When same reciter+style+riwayah+source has multiple recordings |
| `variant_label` | string | no | Human-readable distinguisher when ≥2 entries share `reciter_id` |
| `is_canonical` | bool | no | Exactly one `true` per `reciter_id` |
| `added_at`, `added_by` | metadata | yes | Audit |

### Slug naming rules

```
^[a-z][a-z0-9_]{1,39}$
```

ASCII lowercase, single underscores between tokens, no double-underscore, no trailing underscore. 2–40 characters. Branch-name-safe and URL-safe by construction. Immutable after first publish.

### Update path

- **Adds:** Reciter Requests Space submits a PR or fires a workflow that opens one. PR-reviewed by maintainer, merged.
- **Edits:** typo fixes, source corrections — manually authored PRs.
- **New variants:** add a new row with the same `reciter_id` as the existing canonical entry.

On merge to main, the catalog is now updated. The next time Inspector reads it (startup, manual refresh, or `update-reciters.yml` runs), new slugs appear with state `catalogued` (Inspector's startup reconciler creates a state entry for any catalog slug missing from the state file).

### Validation

`.github/workflows/validate-catalog.yml` runs `scripts/validate_reciter_catalog.py` on every PR touching the file:

- JSON parses; `schema_version` is 2
- Every `slug` and `reciter_id` matches the regex
- `riwayah`, `style`, `audio_source` exist in their respective controlled-vocab files
- `audio_category ∈ {by_surah, by_ayah}`
- `url_template` matches one of the two supported patterns or is empty
- At most one `is_canonical: true` per `reciter_id`
- No duplicate slugs

### Constraints

- Slugs and `reciter_id`s are immutable for now.
- Removing a row is not supported (use `discarded` flow when implemented).

### Initial catalog (one-shot, manual)

The catalog is seeded **manually** at v2 cutover (~15 rows). Author the JSON locally from existing identity sources (`data/reciters_index.json` + per-reciter audio manifests' `_meta`); set `reciter_id = slug` and `is_canonical = true` for every row, leave new optional fields null. Validate locally with `inspector/services/catalog.py::validate()`, then `hf buckets cp` into the target bucket. After cutover, all changes go through the admin endpoint `POST /api/admin/catalog/edit/<slug>`.

### State seeding (one-shot, manual)

There are only ~15 reciters at the time of v2 cutover. State is seeded **manually** by a maintainer using `hf buckets cp` (or the Hub UI) to upload an initial `reciter_state.json` and an empty `audit.jsonl`. No migration script — the rule complexity isn't worth the script effort at this scale.

For reference when authoring the manual seed, the implicit state of each existing reciter follows file-presence:

| Signal | → Initial state |
|---|---|
| Has `data/timestamps/<slug>/...` AND `data/recitation_segments/<slug>/segments.json` (per `scripts/lib/reciter_eligibility.py`) | `completed` |
| Has `data/recitation_segments/<slug>/segments.json` only | `awaiting_review` (no claim) |
| Open GitHub issue + no on-disk segments | `awaiting_alignment` |
| Catalog entry only | `catalogued` |

Initial seed fields per row:
- `assignee`, `assignee_hf_id`, `assignee_since` → null (reviewers re-claim fresh)
- `issue_number` → from open issue if present, else null
- `state_since` → seeding wall-clock
- `history` → single entry `{ "at": now, "event": "reciter.seeded", "detail": "manual seed v2 cutover" }`

After cutover, all subsequent transitions go through `state.py::transition()`.

## 4. State machine

### States

| State | Definition | Editable | Required state-file fields | Forbidden fields |
|---|---|---|---|---|
| `catalogued` | In catalog. No alignment work has started. | No | none beyond identity | `issue_number`, `assignee` must be null |
| `awaiting_alignment` | Alignment pipeline pending or running. | No | `issue_number` | `assignee` null |
| `awaiting_review` | Alignment done. Bucket entry exists. No reviewer claimed. | No (claimable) | `issue_number` | `assignee` null |
| `under_review` | A reviewer has claimed. | Yes (assignee only) | `issue_number`, `assignee`, `assignee_hf_id`, `assignee_since` | none |
| `ready_for_merge` | Reviewer marked complete. Awaiting maintainer publish. Frozen from edits. | No | `issue_number`, `assignee`, `assignee_hf_id`, `assignee_since` | none |
| `awaiting_timestamps` | Bucket → dataset snapshot done. TS data not yet on dataset. | No | `issue_number` | `assignee` null |
| `completed` | Segments + TS both on dataset, in sync. | No | `issue_number` | `assignee` null |

`assignee_since` is preserved through `ready_for_merge` (the assignee identity stays when the reviewer marks ready, since they may unmark to continue editing).

### Events — canonical vocabulary

**Naming convention: `<noun>.<verb>` namespacing for every event.** Three nouns: `reciter` (lifecycle of a recitation), `claim` (assignee bookkeeping), `state` (manual machine override), plus `catalog` and `pipeline` and `admin` for cross-cutting actions. This is the **single source of truth** — `inspector/services/state.py` and the audit log both consume from this list. The admin-perms doc's events list ([`inspector-admin-perms.md`](inspector-admin-perms.md) §11) extends this same vocabulary; do not introduce alternate names elsewhere.

```
# Lifecycle (reciter.*)
reciter.catalog_synced            # catalog file changed; add new slugs / propagate metadata changes
reciter.alignment_requested       # from Reciter Requests Space
reciter.alignment_completed       # pipeline finished, bucket entry seeded
reciter.published                 # maintainer published — snapshot bucket → dataset
reciter.timestamps_completed      # TS data on dataset
reciter.discarded                 # admin marked rejected/abandoned (new state in v2; see admin §11)
reciter.merge_rejected            # maintainer sent ready entry back to reviewer

# Claim cycle (claim.* + reciter.* for state-changing review actions)
reciter.claimed                   # someone took the reciter
reciter.released                  # claimant gave it back
reciter.marked_ready              # reviewer marked ready for maintainer publish
reciter.unmarked_ready            # reviewer pulled back to under_review
claim.force_released              # admin override (one-arg or batch)
claim.reassigned                  # admin override
claim.force_acquired              # admin first-save on a not-owned reciter (ephemeral, no transition)
claim.force_released_auto         # 30-min lease timer (ephemeral, no transition)

# State-machine override (state.*)
state.manual_override             # direct state edit via admin (was 'admin_override' in v1; renamed)
reciter.seeded            # one-shot manual cutover seed (no migration script)

# Catalog (catalog.*)
catalog.edited                    # admin edited a catalog row (writes to <bucket>/catalog/, see H3+H4)

# Pipeline / Job re-run (pipeline.* / admin.*)
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
| `admin_override` | `state.manual_override` |
| `review_merged` (v1) | `reciter.published` |

The terminology shift from v1: there's no merge anymore; the maintainer's action is "publish" — copying the bucket entry to the canonical dataset and cleaning up the bucket.

Deferred (recognised but not implemented):

```
reciter.alignment_failed
reciter.timestamps_failed
reciter.timestamps_stale
reciter.audio_source_changed
```

### Transition matrix (canonical — single source for `state.py`)

States = `catalogued`, `awaiting_alignment`, `awaiting_review`, `under_review`, `ready_for_merge`, `awaiting_timestamps`, `completed`, `discarded` (8 total — `discarded` added per admin §11).

| Event | From state(s) | To state | Actor role | Side effects |
|---|---|---|---|---|
| `reciter.catalog_synced` (new slug) | (no row) | `catalogued` | system | Append history `added` |
| `reciter.catalog_synced` (existing) | any | (same) | system | Diff catalog; no transition |
| `reciter.alignment_requested` | `catalogued` | `awaiting_alignment` | system (forward webhook) | Set `issue_number` from event payload |
| `reciter.alignment_completed` | `awaiting_alignment` | `awaiting_review` | system (pipeline webhook) | Bucket entry seeded by pipeline; Inspector verifies presence |
| `reciter.claimed` | `awaiting_review` | `under_review` | contributor+ | Set `assignee`, `assignee_hf_id`, `assignee_since`; one-claim-per-user check |
| `reciter.released` | `under_review`, `ready_for_merge` | `awaiting_review` | claim-holder OR maintainer+ | Clear assignee fields |
| `reciter.marked_ready` | `under_review` | `ready_for_merge` | claim-holder | Retain assignee |
| `reciter.unmarked_ready` | `ready_for_merge` | `under_review` | claim-holder | Retain assignee |
| `reciter.merge_rejected` | `ready_for_merge` | `under_review` | maintainer+ | Retain assignee; record reason in history detail |
| `reciter.published` | `ready_for_merge` | `awaiting_timestamps` | maintainer+ | Clear assignee. Triggers HF Jobs + GH Actions per [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md). Bucket entry archived (or deleted) post-snapshot |
| `reciter.timestamps_completed` | `awaiting_timestamps` | `completed` | system (job callback) | TS HF Job confirmed; reciter live on dataset |
| `reciter.discarded` | any (except `discarded`) | `discarded` | maintainer+ | Requires typed `confirmation_phrase`; reason ≥10 chars |
| `claim.force_released` | `under_review`, `ready_for_merge` | `awaiting_review` | maintainer+ | Clear assignee; reason required |
| `claim.reassigned` | `awaiting_review`, `under_review`, `ready_for_merge` | `under_review` | maintainer+ | Set new assignee (resolved via HF API per H7); reason required |
| `claim.force_acquired` | `under_review` (any) | (same) | maintainer+ | **Ephemeral** — no state transition. Sets `force_assignee` field with 30-min lease. Audit-only. |
| `claim.force_released_auto` | (any with active force-claim) | (same) | system (timer) | **Ephemeral** — clears `force_assignee` field after 30-min inactivity. Audit-only. |
| `state.manual_override` | any | (specified) | maintainer+ | Reason ≥10 chars in history detail. Does NOT auto-clean assignee fields if target state implies they should be null — maintainer uses `/api/admin/claim/clear` separately (intentional friction). |
| `reciter.seeded` | (no row) | (specified — `catalogued` / `awaiting_alignment` / `awaiting_review` / `completed`) | manual (one-shot) | Reflects manual cutover seeding (no migration script in v2 — too few reciters to justify) |
| `catalog.edited` | (any) | (same) | maintainer+ | **No state-file change.** Mutates `<bucket>/catalog/reciter_catalog.json` (per H3+H4). Audited under `<bucket>/catalog/audit.jsonl`. Fires `repository_dispatch reciter.catalog_changed` for `update-reciters.yml`. |
| `pipeline.triggered` | (any compatible) | (none — pipeline emits its own follow-up event) | maintainer+ | Fires `repository_dispatch pipeline.triggered`. Reason required. |
| `admin.job_rerun` | (any) | (same) | maintainer+ | Re-enqueues a specific failed HF Job. Audit only. |

Direct `under_review → reciter.published` is **not** allowed. The reviewer must mark ready first. Maintainer emergency direct-publish uses `state.manual_override`.

`discarded → *` is only via `state.manual_override` (intentional friction — recovery is deliberate).

### Why re-edits don't get their own state

Once a reciter is `completed`, a maintainer can re-claim it. Implementation: maintainer calls `/api/admin/reopen/<slug>` — Inspector restores the bucket entry from the latest `inspector/segments/<slug>/...` shards on the dataset (HF Job downloads + extracts), transitions state back to `awaiting_review`. The re-edit then follows the same path through `under_review → ready_for_merge → published`. No new state. (Deferred — Phase 6+; v2 ships without re-edits initially.)

## 5. State machine implementation

`inspector/services/state.py` is the single point of truth for state writes. Pseudocode:

```python
@dataclass
class ReciterEntry:
    slug: str
    state: ReciterState
    state_since: datetime
    issue_number: int | None
    assignee: str | None
    assignee_hf_id: str | None
    assignee_since: datetime | None
    history: list[HistoryEntry]

class StateMachine:
    def __init__(self, bucket: Bucket, audit_log: AuditLog, mutex: PerSlugMutex):
        self.bucket = bucket
        self.audit_log = audit_log
        self.mutex = mutex
        self.store: dict[str, ReciterEntry] = self._load_from_bucket()

    def transition(self, slug: str, event: Event, actor: User) -> ReciterEntry:
        with self.mutex.acquire(slug):
            entry = self.store.get(slug)
            new_entry = self._apply_transition(entry, event, actor)  # raises on invalid
            self._validate_invariants(new_entry)
            self.audit_log.append(AuditRecord(slug, event, entry.state, new_entry.state, actor, event.payload))
            self._persist_atomic(new_entry)  # tempfile + os.replace on bucket mount
            self.store[slug] = new_entry
            return new_entry

    def _apply_transition(self, entry, event, actor):
        # Pure function. Raises InvalidTransition if event isn't allowed from entry.state.
        # Encodes the matrix in §4 plus business rules:
        #   - claimed: assignee must be None on the from-state
        #   - released: actor must equal entry.assignee (unless admin)
        #   - marked_ready: actor must equal entry.assignee
        #   - merge_rejected: actor must be maintainer+ and provide reason
        #   - published: actor must be maintainer+
        #   - admin_override: actor must be maintainer+ and provide detail
        ...
```

Concurrency:

- **Per-slug mutex** serializes transitions on the same reciter. `(slug, ...)` lock with short TTL.
- **Cross-slug transitions** are fully concurrent — different slugs touch different state-file entries within the same dict, but writes go through `_persist_atomic` which serializes on the file write itself (~1 ms per write).

Fault model:

- If `_persist_atomic` fails (network, disk full): in-memory store is NOT updated; raises to the caller. Audit log already has the "attempted" entry — useful for postmortem. Caller (the API handler) returns 503.
- If `audit_log.append` fails but `_persist_atomic` succeeds: state diverges from audit. Mitigation: audit append uses a small local write buffer that flushes ahead of state writes; if buffer flush fails repeatedly, refuse to proceed (fail-closed).
- If Inspector crashes mid-transition: bucket has either old or new state, never partial (atomic file replace semantics). Audit log may have an "attempted" entry without a corresponding state change — recoverable on restart.

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

## 7. Reciter request issue body templates

Issues for reciter requests are still created on GitHub by the Reciter Requests Space (existing flow, kept). The issue body carries identity markers Inspector can parse:

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

---
*Live state in the [Inspector](https://hetchyy-quranic-inspector.hf.space/r/saad_al_ghamdi).*
```

The issue body is **not re-rendered on every state transition** in v2. It's set once at request creation and stays static. Live state lives in the Inspector website, not on the GitHub issue. Maintainers who want to see "what state are all reciters in" use the Inspector's admin dashboard or query the bucket state file directly.

The issue is closed when state transitions to `completed` (HF Job calls GitHub API to close). All other transitions don't touch the issue.

## 8. Inspector integration

### State refresh strategy

- **On startup:** fetch `reciter_catalog.json` via GitHub raw at `main` (no auth needed, public repo); fetch `reciter_state.json` from `<bucket>/state/...`. Parse into in-memory `state_store`.
- **On every state write:** Inspector mutates `state_store` directly (it's the only writer).
- **On catalog change:** GH webhook (or scheduled poll every 5 min) re-fetches catalog from GitHub raw. Catalog refresh triggers `catalog_synced` event to add new slugs to state.
- **No webhook from anywhere else** — there is no other writer.

### API endpoints

Full contracts in [`inspector-deployment-plan.md`](inspector-deployment-plan.md) §4. Index here:

```
# Identity
GET  /api/me                       → { login, hf_user_id, role, active_claim }
GET  /api/auth/login               → initiates HF OAuth flow
GET  /api/auth/callback            → handles HF redirect, sets session
POST /api/auth/logout              → clears session

# State reads (sourced from in-memory state_store + catalog)
GET  /api/reciters                 → [{ slug, display, state, riwayah, style }]
GET  /api/reciter-task/<slug>      → full ReciterTask + can_*_for_current_user predicates
GET  /api/state/snapshot.json      → public read-only snapshot of state_store, for Reciter Requests Space + other consumers (rate-limited; cached 30 s)

# Claim flow (mutating — write directly to bucket state, return 200)
POST /api/claim/<slug>             → state.transition(slug, ClaimEvent(actor))
POST /api/release/<slug>           → state.transition(slug, ReleaseEvent(actor))
POST /api/mark-ready/<slug>        → state.transition(slug, MarkReadyEvent(actor))
POST /api/unmark-ready/<slug>      → state.transition(slug, UnmarkReadyEvent(actor))

# Admin (maintainer+ only)
POST /api/admin/publish/<slug>     → publish ready_for_merge → awaiting_timestamps; fires fan-out
POST /api/admin/send-back/<slug>   → merge_rejected
POST /api/admin/override/<slug>    → admin_override with detail
POST /api/admin/reopen/<slug>      → re-claim a completed reciter (deferred Phase 6+)
```

### Predicates

Computed server-side in the `/api/reciter-task/<slug>` response:

```python
def can_edit(entry, user):
    return user is not None and entry.state == 'under_review' and entry.assignee == user.login

def can_mark_ready(entry, user):
    return user is not None and entry.state == 'under_review' and entry.assignee == user.login

def can_unmark_ready(entry, user):
    return user is not None and entry.state == 'ready_for_merge' and entry.assignee == user.login

def can_release(entry, user):
    return user is not None and entry.state in ('under_review', 'ready_for_merge') and entry.assignee == user.login

def can_claim(entry, user):
    return user is not None and entry.state == 'awaiting_review' and not has_other_active_claim(user)

def can_publish(entry, user):
    return user is not None and user.role in ('maintainer', 'owner') and entry.state == 'ready_for_merge'
```

`can_edit` gates `@require_edit_lock` on every mutating *save* endpoint. `ready_for_merge` is explicitly **not editable** — saves return 410.

### No optimistic UI needed

In v1, claim/release fired `repository_dispatch` and returned 202 with optimistic state, with reconciliation arriving via webhook + 30 s polling backstop. In v2, claim/release write the bucket state file synchronously (within the request handler) and return 200 with authoritative state. No propagation lag, no optimistic flag, no reconciliation. The frontend gets the truth in the response.

Caveat: **other tabs / other users** of the same reciter still need to learn about the state change. Two paths:

- **Polling:** frontend polls `/api/reciter-task/<slug>` every 30 s while on the reciter page. Authoritative within 30 s.
- **Server-Sent Events (future):** Inspector can push state updates over an SSE stream. Out of scope for v2 initial.

For Phase 3, polling is sufficient.

## 9. Authorization

| Concept | v1 | v2 |
|---|---|---|
| User identity | GitHub OAuth (login + id) | HF OAuth (login + hf_user_id) |
| Maintainer membership | GitHub team `<org>/inspector-maintainers` (resolved via App's team-membership API at request time) | `data/inspector_owners.json` (canonical list, plus a future `data/inspector_maintainers.json` if owners want a separate tier) |
| Owner membership | `data/inspector_owners.json` | Same |
| Role cache | 60 s | 60 s |

In v2, **`inspector_owners.json` is the sole source of role truth.** No GitHub team membership API call. The file is fetched from GitHub raw on Inspector startup and refreshed every 60 s. Adding/removing maintainers/owners is a manual PR to that file (CODEOWNERS-gated to existing owners).

If you decide to split owners from maintainers later: add `data/inspector_maintainers.json` with the same fetch + cache pattern; resolution becomes:

```python
def resolve_role(user) -> Role:
    if user.login in OWNERS_SET:
        return Role.OWNER
    if user.login in MAINTAINERS_SET:
        return Role.MAINTAINER
    return Role.CONTRIBUTOR
```

Until that's added, all elevated roles are owners.

The HF OAuth `hf_oauth_authorized_org` setting can additionally restrict who can sign in at all — useful if the Inspector is for org-internal contributors only. By default we leave it unset (public).

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

- `push` to `main` touching `data/reciter_catalog.json`
- `repository_dispatch` event `reciter.completed` (fired by Inspector via `INSPECTOR_GITHUB_DISPATCH_TOKEN`)
- `schedule` cron every 30 minutes (catches anything missed)
- `workflow_dispatch` for manual runs

It reads the bucket state file via `huggingface_hub.download_bucket_files(...)` at the start of each run.

### Staleness scenarios

| Scenario | Symptom | Mitigation |
|---|---|---|
| `update-reciters.yml` not updated (still reads from old labels) | `reciters_index.json` stale | Rewrite is in scope of Phase 0 |
| `--build-manifest` not updated | HF dataset manifest stale | Rewrite is in scope of Phase 0 |
| `package_release.py` left on file-presence check | Two truth sources for "is reciter completed" | Optional cleanup in Phase 6 |
| Reciter Requests Space points at old `reciters_index.json` shape | Space's reciter dropdown stale on new fields | Keep regenerating until the Space is updated |

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

### State file corruption from Inspector bug

A bug in `state.py::_apply_transition` could write structurally-valid but semantically-wrong state. The `_validate_invariants` step catches schema violations. **Mitigation:** the audit log captures every transition with full payload; a `scripts/replay_audit.py` tool can rebuild the state file from scratch given the audit log. Acceptable as long as the validator covers the field-presence invariants in §4.

### Audit log corruption / loss

If `audit.jsonl` is corrupted (partial write, mount glitch), state is unrecoverable except from `git log`-equivalent of previous state writes. **Mitigation:** Inspector verifies audit log is appendable on startup; refuses to start if it can't. Periodic backup of `<bucket>/state/` to a versioned location (e.g., quarterly snapshot to a dataset).

### Catalog ↔ state drift

A catalog PR adds slug `X`. Inspector hasn't re-fetched the catalog yet. Slug `X` exists in catalog but not in state. **Symptom:** Inspector lists slug `X` with `state: catalogued` (graceful default). **Mitigation:** the 5-min catalog-refresh poll catches new slugs; the manual admin "refresh catalog" action does the same on demand.

### Bucket write fails mid-transition

`_persist_atomic` raises (network, HF outage, token revoked). In-memory `state_store` is NOT updated. The audit log already has an "attempted" entry. Caller (API handler) returns 503. **Mitigation:** retry with exponential backoff inside `state.py`. Five retries over 30 s; if all fail, propagate the error.

### Stalled `awaiting_alignment`

Pipeline crashes before firing `alignment_completed`. State stays `awaiting_alignment`. **Mitigation:** the daily reconciler workflow (read state → check for state-since older than threshold) flags for maintainer review. No automatic recovery.

### Stalled `awaiting_timestamps`

TS HF Job fails. State stays `awaiting_timestamps`. **Mitigation:** reconciler flags after N hours; maintainer triggers the TS HF Job manually.

### Stuck `ready_for_merge`

Reviewer marked ready; maintainer never publishes. The bucket entry is frozen from edits. **Mitigation:** reconciler flags >7 days; admin dashboard surfaces in stalled-reciters tab.

### Reciter Requests Space integration

The Reciter Requests Space currently fires a `repository_dispatch` event into GH Actions. In v2, the equivalent flow is: Space POSTs to Inspector's `/api/inspector-events/alignment-requested?slug=<slug>` (with a shared secret). Inspector validates and writes the state transition `catalogued → awaiting_alignment`. **Decision:** keep the `repository_dispatch` flow and have Inspector subscribe to GH dispatch events via a webhook. Cleaner separation. Detail in [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md).

### History array cap

History is bounded to 20 entries per reciter. The 21st event drops the oldest. Full history is in `audit.jsonl`. Adequate.

### Slug rename

Currently impossible — slugs are immutable. If we ever need it: a coordinated audit-log entry, catalog edit, bucket-path rename, dataset republish under new slug. **Decision: defer until a real rename request appears.**

### Concurrent transitions on the same slug

Per-slug mutex serializes. Only one Inspector replica today; multi-replica future needs bucket-side optimistic concurrency or Redis lock. Deferred.
