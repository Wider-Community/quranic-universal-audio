# Inspector Data Storage Strategy (v2)

Companion to [`inspector-deployment-plan.md`](inspector-deployment-plan.md). Implementation-grade reference for how the deployed Inspector reads, writes, and caches data files when there is no local repo on disk. Specifies file-by-file classification, the bucket mount semantics, image build changes, configuration, per-phase acceptance criteria, and open risks.

The parent doc covers identity convention, auth/claim flow, locking, state computation, and phased rollout. This doc owns everything file-IO.

## 1. Model in one paragraph

The deployed backend is **always in the read path** (the HF bucket is private — browser → backend → bucket for both in-flight and published reciter data) and **uses the mounted HF bucket as the working store** for everything (in-flight and published reciter data, the reciter state file, the catalog file, and the audit log). Write traffic is gated to one active reviewer per reciter; their saves are plain file writes against `<INSPECTOR_BUCKET_MOUNT>/wip/<slug>/...`, the mount handles flush within 2–30 s, and an additional `huggingface_hub.upload_file()` call per save provides durability. Static reference data (Quran word text, baked-in linguistic data, controlled vocabularies snapshot for offline boot) ships **baked into the Space image** and is served same-origin. Audio plays browser → origin direct; timestamps come browser → HF CDN direct (timestamps live on the public HF dataset, not in the bucket).

**No github-fetch service. No Git Data API write path. No scratch dir. No debounce loop. No SQLite. No HF dataset extension for Inspector segments.** The bucket mount is the persistence layer; pydantic models at the service boundary handle validation + schema migration; existing local-disk save semantics work unchanged because the mount IS local-disk semantics from the code's perspective.

## 2. Classification map

Two tiers: **server-image** (baked into the Docker image, slim static set) and **HF bucket** (mounted into the Space, all reciter data + state + catalog + audit).

| File / pattern | Scope | Read path | Write path | Notes |
|---|---|---|---|---|
| `data/surah_info.json` | static | server-image | n/a | Loaded once at app boot |
| `data/qpc_hafs.json` | static | server-image | n/a | ~11 MB; also published to HF `_resources/` for TS-tab browser fetches in local mode |
| `data/digital_khatt_v2_script.json` | static | server-image | n/a | ~9.5 MB; same dual-publishing |
| `data/phoneme_sub_costs.json` | static | server-image | n/a | Boundary check input |
| `<bucket>/access/inspector_roles.json` | role mgmt | bucket mount; in-memory cache hydrated at startup + replaced on every write | Inspector backend (sole writer; via `services/access.py`) | Single consolidated file. `hf_user_id` canonical. Bootstrap via hand-seed at Phase 0. Schema in [`inspector-state-management.md`](inspector-state-management.md) §9. |
| `<bucket>/catalog/reciter_catalog.json` | curated metadata (single file: vocab + reciters + aliases + audio source templates) | bucket mount (parsed via pydantic) | Inspector backend (sole writer; via `services/catalog.py`) | Plain JSON. Replaces `data/{riwayat,sources,styles}.json` + `data/audio/<cat>/<src>/<slug>.json` (381 manifests) + `data/reciter_catalog.json`. Schema in [`inspector-state-management.md`](inspector-state-management.md) §3. |
| `<bucket>/catalog/audio_meta.json` | VBR + ffprobe cache | bucket mount | Inspector backend / maintainer scripts | Was `data/.audio_meta.json` |
| `<bucket>/catalog/audio_durations.json` | duration cache | bucket mount | Inspector backend / maintainer scripts | Was `data/.audio_durations.json` |
| `<bucket>/published/<slug>/segments.json` | per-reciter, completed | bucket mount via Inspector backend | n/a (in-process bucket move on publish) | `Cache-Control: public, max-age=86400` (1 day; not `immutable` since shards mutate on re-edit). Same flat shape as `wip/<slug>/`. |
| `<bucket>/published/<slug>/detailed.json` | per-reciter, completed | bucket mount via backend | n/a | Per-reciter cap ~5.2 MB raw; cohort avg ~4.4 MB |
| `<bucket>/published/<slug>/edit_history.jsonl` | per-reciter, completed | bucket mount via backend (lazy on History panel expand) | n/a | Per-reciter avg ~8 MB raw |
| `<bucket>/published/<slug>/edit_history_peaks.jsonl` | per-reciter, completed | bucket mount via backend (lazy on History panel expand) | n/a | Per-reciter avg ~1.1 MB raw |
| `<bucket>/published/<slug>/low_confidence_v2.json` | per-reciter, completed | bucket mount via backend | n/a | Tiny (KB) |
| `<bucket>/published/<slug>/timestamps/<chapter>.json` | per-reciter, completed | bucket mount via backend | n/a (timestamps HF Job writes after publish) | Same slug subtree as segments — no separate top-level `timestamps/` folder |
| `<bucket>/wip/<slug>/segments.json` | per-reciter, **in-flight** | bucket mount via backend | bucket mount (atomic write; mount flushes within 2–30 s; `upload_file()` per save) | **Flat layout** — no `data/recitation_segments/<slug>/` nesting. Save flow uses `data_dir.resolve(slug)` to map this back from legacy code. |
| `<bucket>/wip/<slug>/detailed.json` | per-reciter, **in-flight** | bucket mount | bucket mount | |
| `<bucket>/wip/<slug>/edit_history.jsonl` | per-reciter, **in-flight** | bucket mount | bucket mount | Append-only; new schema (no genesis, no `file_hash_after`, with `actor` per batch) |
| `<bucket>/wip/<slug>/edit_history_peaks.jsonl` | per-reciter, **in-flight** | bucket mount | bucket mount | History panel waveform cache |
| `<bucket>/wip/<slug>/low_confidence_v2.json` | per-reciter, **in-flight** | bucket mount | n/a (pipeline-written, copied in on alignment-completed) | Read-only sidecar |
| `<bucket>/state/reciter_state.json` | global state | bucket mount; parsed via pydantic in `services/state.py` | Inspector backend (sole writer; per-slug `threading.Lock`); also direct `huggingface_hub.upload_file()` per write to bypass mount flush window | See [`inspector-state-management.md`](inspector-state-management.md) §2 for schema |
| `<bucket>/audit/<YYYY>-<MM>.jsonl` | global audit (state + catalog + claim + admin events; ONE folder) | append-only | Inspector backend (direct upload, not via mount) | Partitioned per-month from day one. **No `prev_hash` chain** — tamper detection via offsite versioned snapshots. |
| `<bucket>/audit/_meta.json` | per-month meta | append-only | Inspector backend | Carries `schema_version` once per partition (not per record) |
| Audio mp3/wav | per-reciter | **origin direct** (browser) | n/a | Backend never touches |
| `data/recitation_segments/<slug>/*.bak` | dev artifact | n/a | discard | `backup_file()` calls removed in deployed save path |
| `validation.log` | dev artifact | n/a | discard | Not shipped |
| `data/qul_downloads/`, `data/.cache/`, `data/RECITERS.md`, etc. | dev / docs | n/a | discard | Not shipped |
| `inspector/.cache/<slug>/peaks/` | per-reciter | recompute on demand + browser/CDN cache headers | n/a | No persistent volume; `Cache-Control: public, max-age=31536000, immutable` (peaks ARE hash-keyed) |

**Dropped from earlier v2 drafts:**

- `data/reciters_index.json` — gone entirely; bucket catalog is source of truth from day one for releases + downstream consumers.
- `data/audio/<cat>/<src>/<slug>.json` (381 manifests) and `data/audio_catalog.json.gz` — replaced by audio source templates inside `<bucket>/catalog/reciter_catalog.json`.
- `inspector/segments/<slug>/v<n>/...` namespace on the public HF dataset — Inspector reads everything from the private bucket. The HF dataset stays for downstream consumers (training parquet, GitHub release zips), Inspector never reads from it.
- `inspector/segments/<slug>/CURRENT` pointer file — no `v<n>/` versioning, no pointer.
- All SQLite files (`reciter_state.sqlite`, `reciter_catalog.sqlite`) and their `-wal`/`-shm` sidecars — replaced by plain JSON files validated by pydantic.

## 3. Bucket mount

ONE private HF bucket per environment, mounted into the Space at `INSPECTOR_BUCKET_MOUNT` (default `/data/inspector-bucket`). Replaces github-fetch + Git Data API + scratch dir entirely.

### Backend choice: NFS Advanced mode

[hf-mount](https://github.com/huggingface/hf-mount) (which Space volume mounts use under the hood) offers two modes:

| Mode | Semantics | Fit |
|---|---|---|
| **Streaming** (FUSE default) | Append-only, sequential. Buffers in memory, uploads on `close()`. Append-only. | Good for `edit_history.jsonl` and `edit_history_peaks.jsonl` (append-only) but BAD for `detailed.json`/`segments.json` (full rewrites) |
| **Advanced** (NFS default, FUSE opt-in) | Downloads full file to local cache on open, edits in place, **async debounced flush 2 s default / 30 s max**. Supports random writes, seeks, overwrites. | Right answer — supports all our file shapes |

**Choice: NFS Advanced mode.** Single mount per Space; one configuration; works for every file the save flow touches. The 2–30 s flush window is functionally equivalent to v1's debounce (30 s inactivity, 5 min hardcap) — same staleness bound, but the mount handles it instead of Inspector code.

### Mount layout (one bucket per env)

`<INSPECTOR_BUCKET_MOUNT>` (default `/data/inspector-bucket`):

```
<INSPECTOR_BUCKET_MOUNT>/
├── state/
│   └── reciter_state.json            # global state, Inspector sole writer
├── catalog/
│   ├── reciter_catalog.json          # vocab + reciters + aliases + audio source templates (single file)
│   ├── audio_meta.json               # VBR + ffprobe cache (was data/.audio_meta.json)
│   └── audio_durations.json          # duration cache (was data/.audio_durations.json)
├── audit/
│   ├── _meta.json                    # carries schema_version once
│   └── <YYYY>-<MM>.jsonl             # one folder for ALL events (state, catalog, claim, admin)
├── wip/                              # one subtree per in-flight reciter (FLAT layout)
│   └── <slug>/
│       ├── segments.json
│       ├── detailed.json
│       ├── edit_history.jsonl
│       ├── edit_history_peaks.jsonl
│       └── low_confidence_v2.json
├── published/                        # one subtree per completed reciter (same flat shape)
│   └── <slug>/
│       ├── segments.json
│       ├── detailed.json
│       ├── edit_history.jsonl
│       ├── edit_history_peaks.jsonl
│       ├── low_confidence_v2.json
│       └── timestamps/
            └── <chapter>.json        # written by timestamps HF Job after publish
```

(No `_archive/` folder — publish is an in-bucket `wip/<slug>/` → `published/<slug>/` move; nothing to archive on every publish. The "explicit retire" path is deferred — see [`inspector-deferred.md`](inspector-deferred.md).)

**Why ONE bucket (not two):** earlier drafts split state/audit (private) from data (public) on the rationale that browsers should read completed reciter data direct from HF CDN. With Inspector backend always in the read path (single read path through the backend, regardless of state), there's no anonymous public-bucket read use case. The whole bucket is private; access via `INSPECTOR_HF_TOKEN`. The PII concern in audit is handled by privacy on the same bucket.

**Why flat `wip/<slug>/` and `published/<slug>/` layouts** (no `data/recitation_segments/<slug>/` nesting, no `v<n>/` versioning, no `CURRENT` pointer): the v1 nesting only existed to share a path shape with local-mode. With `services/data_dir.py::resolve(slug)` indirecting all save-flow paths anyway, the flat layout is cleaner across publish + restore + admin tooling. Versioning was rejected because Inspector segment-shard responses are served with `Cache-Control: public, max-age=86400` (1 day) — short enough that re-publishes propagate within a day without immutable URLs.

**Per state-write-durability concern:** state, catalog, and audit writes go via **direct `huggingface_hub.upload_file()` calls** in addition to the mount-side write. The mount is read-side and best-effort write-side; direct upload is the durability guarantee. The two state-related files are tiny (~150 KB state JSON, ~50 KB catalog JSON) and infrequent (~1/min steady state); the latency cost of direct upload is acceptable. Save-flow writes (`detailed.json`, `edit_history.jsonl`) also call `upload_file()` per save when `INSPECTOR_FORCE_FLUSH_ON_SAVE=1` (the default in deployed mode).

### Auth model

| Authority | Source | Used by |
|---|---|---|
| **Bucket-write authority** | Space-level secret `INSPECTOR_HF_TOKEN` (HF user token with write scope on the bucket's namespace) | All Inspector backend writes — saves, state file updates, catalog updates, audit appends |
| **Bucket-read** | Same `INSPECTOR_HF_TOKEN`; mount uses it transparently | Backend reads of state, catalog, audit, in-flight + published reciter data |

The Space's bucket-write authority is decoupled from the contributor's HF identity. The user authenticates with HF OAuth (`hf_oauth: true`) for identity only; their token is never used to write to the bucket. The Space writes "on behalf of" the user using its own token.

### Why this is fine for attribution

Per-edit attribution lives in `<bucket>/audit/<YYYY>-<MM>.jsonl`, written by Inspector with the authenticated user's `hf_user_id` and `login_at_time`. The bucket mutation itself is the Space's act, but the audit entry establishes who triggered it. The same user's edits also carry an `actor` block per `edit_history.jsonl` batch (D13). No GitHub-style author/committer split needed.

### Cache layers

| Layer | Purpose | Eviction |
|---|---|---|
| **Parsed seg cache** (`_seg`) | Parsed Python representation of `detailed.json` per active reciter | LRU 128 MB; invalidated on save for the active slug |
| **State + catalog parsed cache** | In-memory pydantic models hydrated on startup, replaced on each write (Inspector is sole writer) | Replaced on write; never expires otherwise |

State + catalog are now in-memory pydantic models — small (~150 KB and ~50 KB JSON), parsed once, replaced atomically on each write. Inspector being the sole writer means the cache is correct by construction; no "is the cache fresh?" race because no other writer exists.

The github-fetch + raw-bytes LRU + parsed-cache + single-flight machinery from v1 is **gone** — there's no upstream API the cache fronts. Bucket mount NFS reads have their own kernel-level cache; the parsed seg cache sits above that to avoid re-parsing 5 MB JSON on every request.

### Mount behaviour vs v1's github-fetch

| Concern | v1 (github-fetch) | v2 (bucket mount) |
|---|---|---|
| Cold read of 5 MB JSON | ~200–400 ms (network + ETag + parse) | ~100–300 ms (NFS lazy fetch) — verify in Phase 2 |
| Warm read | <10 ms (parsed-cache hit) | <10 ms (parsed-cache hit; NFS local cache absorbs raw bytes) |
| Concurrent reads of same cold file | Risk of thundering herd (mitigated by single-flight) | NFS handles it natively — kernel coalesces |
| Write semantics | Atomic local write → debounce timer → Git Data API blob+tree+commit+ref | Atomic write to mount → mount async flush within 2–30 s + per-write `huggingface_hub.upload_file()` for durability |
| Loss on container rebuild | Up to 5 min unflushed scratch | Up to mount flush window (≤30 s) for save-data — but `INSPECTOR_FORCE_FLUSH_ON_SAVE=1` default eliminates this; bucket persists across container restarts |
| Rate limit anxiety | 5,000 req/h GitHub budget shared across all under-review traffic | None — no per-request API budget |
| Code complexity | ~150 LoC `github_fetch.py` + ~200 LoC `github_commit.py` + ~100 LoC `scratch.py` | ~30 LoC `hf_bucket.py` (path resolver + write helpers) |

### What the bucket mount does NOT do

- It does **not** stream audio. Audio is browser→origin.
- It does **not** replace the parsed seg cache. The mount is the bytes; the parsed cache is the Python object.
- It does **not** serve `timestamps/` for the timestamps tab. Those live on the public HF dataset; the browser hits HF CDN direct.

### Freshness contract

| Reciter state | Worst-case staleness for non-owner viewers | Source |
|---|---|---|
| `completed` (`published/<slug>/`) | Bounded by `Cache-Control: max-age=86400` on the inspector-segment response (1 day); maintainer publish on a re-edit propagates within a day | Bucket mount via backend |
| `under_review`, no active reviewer | Effectively zero — mount serves last-flushed state | Bucket mount |
| `under_review`, active reviewer mid-session | **≤ 30 s** (mount flush window) typical; with `INSPECTOR_FORCE_FLUSH_ON_SAVE=1` (default) effectively zero | Bucket mount + per-save upload |
| Just published | Sub-second after `POST /api/admin/publish/<slug>` returns; bucket move is in-process synchronous; backend cache invalidated on transition | Bucket mount |

Reviewers' typing between saves is private to their Space replica's local mount cache; visible to themselves immediately, visible to others on next save (since saves force-flush by default).

## 4. Bucket lifecycle per reciter

The slug exists in `wip/<slug>/` during `awaiting_review` and `under_review` (regardless of `marked_ready`). On publish, the entry is moved (server-side, in-process) to `published/<slug>/`. There is no archive step in v2 except for explicit retire scenarios.

### Lifecycle events

| Event | Action |
|---|---|
| Alignment pipeline finishes | Pipeline writes outputs into `<bucket>/wip/<slug>/...` (flat layout). Inspector backend (notified via job-completion webhook OR via state transition `awaiting_alignment → awaiting_review`) marks state. |
| Reviewer claims | State writes only — no bucket file changes. The reviewer's first save will mutate the existing bucket entry. |
| Save POST | Existing `save_seg_data()` runs against the mount path. Mount flushes within 2–30 s; per-save `upload_file()` provides durability. |
| Mark ready | `marked_ready = 1` flip on the row; bucket files frozen (saves return 410 per the API gate). No state transition. |
| Unmark ready | `marked_ready = 0` flip; bucket files unfrozen. No state transition. |
| Release | State write only (state → `awaiting_review`, clear `assignee_*`); bucket files preserved for the next reviewer. |
| Publish (maintainer action) | Synchronous in-process: state transitions `under_review` (with `marked_ready=1`) → `awaiting_timestamps`; bucket move/copy `wip/<slug>/` → `published/<slug>/` (in-bucket, server-side); fire `repository_dispatch reciter.completed`; enqueue ONE `timestamps-refresh` HF Job. The `wip/<slug>/` entry is cleared. |
| Timestamps job completes | Job-completion webhook (`POST /api/internal/job-completed`, Bearer-auth) receives the callback; transitions `awaiting_timestamps → completed`. |
| Re-edit of completed reciter (deferred) | Re-claim → in-process bucket copy `published/<slug>/` → `wip/<slug>/` and state `completed → awaiting_review`. Deferred per [`inspector-deferred.md`](inspector-deferred.md). |

### Footprint

Per active in-flight reciter: 9–19 MB on the bucket. Bucket storage budget: 20 in-flight × ~15 MB ≈ 300 MB sustained, plus the long tail of `published/<slug>/` entries (one per completed reciter). Free private bucket allowance is ample.

Backend memory footprint: the parsed seg cache holds active and recently-viewed reciters per Space replica. With 10 concurrent reviewers across 10 different reciters: theoretically 10× ~15 MB parsed = ~150 MB. LRU cap at 128 MB enforces. State + catalog parsed models add ~200 KB; negligible.

## 5. Save flow

The deployed save flow is **identical to local mode** at the code level — the indirection is `inspector/services/data_dir.py::resolve(slug)`:

- Local mode: returns `{INSPECTOR_DATA_DIR}/data/recitation_segments/{slug}/`
- Deployed mode: returns `{INSPECTOR_BUCKET_MOUNT}/wip/{slug}/` (flat layout)

The save flow asks the resolver for the per-reciter data dir; it gets back something it can `open()` against in both modes. Save code itself is unchanged.

After the local-disk write, the save also calls `huggingface_hub.upload_file()` per affected file (`detailed.json`, `segments.json`, `edit_history.jsonl`, `edit_history_peaks.jsonl`) when `INSPECTOR_FORCE_FLUSH_ON_SAVE=1` (the default in deployed mode) — this bypasses the mount's lazy flush window and provides durability across container rebuilds.

### Removed in deployed save path

- `backup_file()` calls in `save.py` and `undo.py` — bucket file mutability is the concern, not local backups; we rely on `audit/<YYYY>-<MM>.jsonl` for forensic recovery.
- `file_hash_after` field write in `_persist_and_record` and `_append_revert_record` — chain is dropped (parent §7).
- Genesis record in `_init_history` — gone with the chain.
- `seg_save_chart` route + `analysis/*.png` writes — debug-only, no UI surface.

### Added in deployed save path

- `actor: {hf_user_id, login_at_time, role}` per `edit_history.jsonl` batch — first-class attribution on the per-edit ledger.
- Validators called from `services/save.py` directly (`validate_segments` runs on every save). `validate_audio` and `validate_edit_history` are called from their respective service entry points.

### Concurrency

Per-reciter writes are serialized by the per-slug `threading.Lock` (`@require_edit_lock`). One lock per slug — no `(slug, login)` sub-mutex — two-tab same-user is also serialized by this single per-slug lock. Across slugs, writes are independent — different reciters touch different bucket subtrees, no contention.

Multi-replica Space scaling (when needed): the in-process lock moves to bucket-side optimistic concurrency (read-version → write-if-version) or a small Redis. Deferred until measured.

## 6. Configuration

| Env var | Default (deployed) | Default (local) | Purpose |
|---|---|---|---|
| `INSPECTOR_TS_SOURCE` | `bucket` | `local` | Bucket reads `<bucket>/published/<slug>/timestamps/...` via backend; local serves shards from `data/timestamps/` on disk. The legacy `huggingface` value (frontend → HF dataset CDN direct) was removed in Phase 2 — Inspector reads timestamps through its own backend in v2. |
| `INSPECTOR_DATA_DIR` | `/app/data` | `/data` (via bind mount) | Static reference data location |
| `INSPECTOR_QUA_DATA_PATH` | `/app/data` | `/data` | Linguistic data location read by `services/data_loader.py` |
| `INSPECTOR_BUCKET_MOUNT` | `/data/inspector-bucket` | unused | Single private bucket mount for state, catalog, audit, wip, published |
| `INSPECTOR_BUCKET_REPO` | `hetchyy/quranic-inspector-bucket` (prod) / `hetchyy/quranic-inspector-bucket-dev` (dev) | unused | Single bucket name for `huggingface_hub`-based access |
| `INSPECTOR_HF_TOKEN` | secret (bot account) | unset | HF token with write scope on the bucket namespace; minted from dedicated `hetchyy-bot` account, not a personal account |
| `INSPECTOR_HF_DATASET_REPO` | `hetchyy/quranic-universal-ayahs` | unused | HF dataset for downstream consumers (training parquet, release zips). Inspector never reads from it. |
| `INSPECTOR_CACHE_DIR` | `/tmp/inspector-cache` | repo `inspector/.cache/` | Inspector's own peak/canonical-phoneme cache |
| `INSPECTOR_PARSED_CACHE_BYTES` | `134217728` (128 MB) | unused | Parsed seg cache cap |
| `INSPECTOR_SESSION_SECRET` | secret | unset | Signing key for the self-contained signed-cookie session (Flask `itsdangerous`) |
| `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET` | auto-injected by `hf_oauth: true` | unset | HF OAuth client credentials |
| ~~`INSPECTOR_AUDIO_PROXY_ENABLED`~~ | retired | retired | The audio proxy blueprint stays registered in every mode because `source.ts` routes by_surah audio through `/api/seg/audio-proxy/<reciter>?url=...`. The route degrades to a 302 redirect when no cache file exists; background download workers run only on explicit `POST /prepare-audio`. |
| `INSPECTOR_GITHUB_OWNER`, `INSPECTOR_GITHUB_REPO` | repo coords | unused | For GitHub raw fetches of `inspector_roles.json` |
| `INSPECTOR_GITHUB_DISPATCH_TOKEN` | secret (bot account) | unset | Tiny GitHub PAT used to fire `repository_dispatch reciter.completed`. Minted from `hetchyy-bot` GitHub account, fine-grained PAT scoped to the project repo with `actions: write` only |
| `INSPECTOR_JOB_CALLBACK_SECRET` | secret | unset | Bearer token (constant-time compare) for `/api/internal/job-completed` (HF Job callback). Single secret — no `_PREV` rotation slot |
| `INSPECTOR_CALLBACK_URL` | `https://hetchyy-quranic-inspector{,-dev}.hf.space` (passed to HF Jobs) | unused | Per-env Inspector base URL passed into Job invocations so dev Jobs callback to dev Inspector |
| `INSPECTOR_FORCE_FLUSH_ON_SAVE` | `1` (default) | `0` | Synchronous `huggingface_hub.upload_file()` after each save; on by default in deployed mode for durability across container rebuilds |
| `GUNICORN_WORKERS` | `1` (asserted) | unused | Startup assertion — `inspector.app:create_app()` refuses to boot if != 1 |
| `INSPECTOR_WRITES_DISABLED` | unset / `1` (kill switch) | unused | Emergency kill switch — when `1`, all mutating endpoints return 503 |

Env vars dropped vs v1 / earlier v2 drafts:

- `INSPECTOR_GITHUB_APP_ID`, `INSPECTOR_GITHUB_APP_PRIVATE_KEY`, `INSPECTOR_GITHUB_INSTALLATION_ID` — no GitHub App
- `INSPECTOR_FETCH_LRU_BYTES`, `INSPECTOR_FETCH_MAX_ENTRY_BYTES`, `INSPECTOR_FETCH_TTL_BRANCH_SEC` — no github-fetch
- `INSPECTOR_DEBOUNCE_INACTIVITY_SEC`, `INSPECTOR_DEBOUNCE_HARDCAP_SEC` — mount handles flush
- `INSPECTOR_INTERNAL_SECRET` — no cache-invalidate webhook
- `INSPECTOR_GITHUB_WEBHOOK_SECRET` — no GitHub webhook receiver
- `INSPECTOR_SCRATCH_DIR` — bucket mount is the working surface
- `INSPECTOR_META_MOUNT`, `INSPECTOR_META_REPO` — single bucket; no separate metadata bucket
- `INSPECTOR_FORWARD_SECRET`, `INSPECTOR_FORWARD_SECRET_PREV` — `forward-to-inspector.yml` and `/api/internal/inspector-event` are gone (D17)
- `INSPECTOR_JOB_CALLBACK_SECRET_PREV` — single secret, no rotation slot
- `INSPECTOR_BUCKET_ARCHIVE_POLICY` — publish move is in-process; no archive policy in v2
- All `AUDIO_CATALOG`-related vars — catalog lives in `<bucket>/catalog/reciter_catalog.json`, not a baked file

## 7. Image build changes

### Build context note

The repo's `inspector/Dockerfile` is built with **repo root as context**. The Space-repo upload pipeline (see [`inspector-deploy-runbook.md`](inspector-deploy-runbook.md)) restructures the upload tree so the Dockerfile sits at the Space repo root — `.dockerignore` lives at that root.

### ENV defaults flipped to deployed profile

```dockerfile
ENV INSPECTOR_DATA_DIR=/app/data \
    INSPECTOR_QUA_DATA_PATH=/app/data \
    INSPECTOR_TS_SOURCE=bucket \
    INSPECTOR_AUDIO_PROXY_ENABLED=0 \
    INSPECTOR_CACHE_DIR=/tmp/inspector-cache \
    INSPECTOR_BUCKET_MOUNT=/data/inspector-bucket \
    INSPECTOR_PARSED_CACHE_BYTES=134217728
```

`docker-compose.yml` (local mode):

```yaml
environment:
  INSPECTOR_DATA_DIR: /data
  INSPECTOR_QUA_DATA_PATH: /data
  INSPECTOR_AUDIO_PROXY_ENABLED: "1"
  INSPECTOR_TS_SOURCE: local
volumes:
  - ./data:/data
```

### Excluded from Docker image

```
data/audio/                   # gone — replaced by audio source templates in bucket catalog
data/recitation_segments/     # served via bucket mount
data/timestamps/              # served via HF CDN (public dataset)
data/qul_downloads/           # pipeline input only
data/.cache/                  # local-only artifacts
data/reciters_index.json      # dropped entirely; bucket catalog is source of truth
data/riwayat.json             # merged into bucket catalog (vocab.riwayat[])
data/sources.json             # merged into bucket catalog (vocab.audio_sources[])
data/styles.json              # merged into bucket catalog (vocab.styles[])
data/.audio_meta.json         # moved to bucket
data/.audio_durations.json    # moved to bucket
data/RECITERS.md
data/README.md
data/**/validation.log
data/**/beam_diff_report.txt
data/**/*.bak
.local/
.github/
docs/
inspector/frontend/src/       # only dist/ ships
inspector/frontend/node_modules/
inspector/tests/
**/__pycache__/
**/.pytest_cache/
```

### Included in Docker image

```
inspector/                    # code (frontend dist/ only — src/ excluded)
validators/                   # code (libraries; CLI wrappers retained)
scripts/__init__.py
scripts/lib/                  # code
data/surah_info.json
data/qpc_hafs.json
data/digital_khatt_v2_script.json
data/phoneme_sub_costs.json
                              # (no inspector_roles.json in image — bucket-resident, see state-management §9)
```

### No audio catalog build step

The 381 per-reciter audio manifests (`data/audio/<cat>/<src>/<slug>.json`, ~67 MB pretty) are gone. Audio URL info now lives in `<bucket>/catalog/reciter_catalog.json` under `vocab.audio_sources[]` (template per source) plus per-row `audio_source` + optional `url_template_override` + optional `url_overrides` per-chapter map. `scripts/build_audio_catalog.py` is dropped from the build flow.

### Resulting image

A small slice of static reference data + Python deps + Alpine static ffmpeg + frontend dist. Total ~300–400 MB. Image rebuilds only on **code or static-data** changes.

### CMD

```dockerfile
CMD ["gunicorn", "-k", "gthread", "-w", "1", "--threads", "16", \
     "--max-requests", "5000", "--max-requests-jitter", "500", \
     "--timeout", "60", "--graceful-timeout", "30", \
     "--bind", "0.0.0.0:5000", "inspector.app:create_app()"]
```

Werkzeug dev server (`app.run()`) is gone.

**`-w 1` is load-bearing.** The whole v2 design (per-slug `threading.Lock`, in-memory `state_store`, parsed seg cache, role cache) assumes one Python process. `inspector.app:create_app()` asserts `os.environ.get("GUNICORN_WORKERS", "1") == "1"` at startup; refuses to boot otherwise. Bumping to `-w 2+` requires a shared coordinator (Redis or bucket-CAS) and is out of v2 scope. Concurrency comes from `--threads 16` (gunicorn-gthread releases the GIL during NFS reads and ffmpeg subprocesses, where the load actually is).

### `.dockerignore` discipline

CI check that diff-fails if any of the now-excluded paths leaks into the built image:

```bash
docker run --rm <image> sh -c '
  find /app/data \( \
    -path "*/audio/*" -o \
    -path "*/recitation_segments/*" -o \
    -path "*/timestamps/*" -o \
    -path "*/qul_downloads/*" -o \
    -path "*/.cache/*" -o \
    -name "reciters_index.json" -o \
    -name "riwayat.json" -o \
    -name "sources.json" -o \
    -name "styles.json" -o \
    -name ".audio_meta.json" -o \
    -name ".audio_durations.json" -o \
    -name "*.bak" \
  \) -print | head -1
' | grep -q . && exit 1 || exit 0
```

## 8. Per-file specifications

For each meaningful per-reciter file, the deployed-mode spec, broken down by reciter state.

Realistic sizes from disk (15 reciters with committed `segments.json` as of writing; `timestamps.json` lives under `data/timestamps/<slug>/...` not `recitation_segments/`):

| File | Avg | Largest committed | Notes |
|---|---|---|---|
| `segments.json` | ~340 KB | 386 KB | |
| `detailed.json` | ~4.4 MB | **5.2 MB** (`nasser_alqatami`) | Earlier "max ~33 MB" was wrong — that was per-reciter dir total |
| `edit_history.jsonl` | ~8 MB | 11.1 MB (`nasser_alqatami`) | |
| `edit_history_peaks.jsonl` | ~1.1 MB | 2.4 MB (`maher_al_meaqli`) | |
| `low_confidence_v2.json` | <4 KB | 3.6 KB | |
| Per-reciter dir total | ~12-20 MB | 33 MB (`maher_al_meaqli`) | |

### `segments.json`

- **Read (any state):** bucket mount via Inspector backend; `published/<slug>/` for completed, `wip/<slug>/` for in-flight.
- **Written by:** `save.py::rebuild_segments_json` on every save; never edited directly. On publish, copied as part of the `wip/<slug>/` → `published/<slug>/` move.
- **Mount flushes within:** 2–30 s of write; per-save `upload_file()` provides durability.
- **Cache headers:** `Cache-Control: public, max-age=86400` (1 day; not `immutable` since shards mutate on re-edit).
- **Acceptance:** completed reciter renders within p99 ≤ 800 ms cold via bucket mount, ≤ 50 ms warm; in-flight reciter same p99.

### `detailed.json`

- Same source matrix as `segments.json`.
- **Size:** typical ~4 MB raw; cohort max ~5.2 MB raw.
- **Why per-reciter, not per-chapter:** every Segments-tab read endpoint depends on `load_detailed(slug)` — refactoring to per-chapter load is non-trivial and out of scope for the deploy.
- **Parsed cache key:** `(slug, "detailed_parsed")` in 128 MB LRU.

### `edit_history.jsonl`

- Same source matrix.
- **Append cadence:** one line per save batch (in-flight). Mount flushes within 2–30 s; per-save `upload_file()`.
- **Read pattern:** lazy on History panel expand.
- **Schema cleanup (parent §7):** drop `file_hash_after`, drop genesis record, drop the file-hash chain. Add `actor: {hf_user_id, login_at_time, role}` per batch.
- **Acceptance:** validators that read this file pass with the new schema; backend's `parse_history_file` tolerates missing genesis and reads mixed v1/v2 schemas without a migration script.

### `edit_history_peaks.jsonl`

- Same source matrix. **Kept** — read path exists at `routes/peaks.py:90`, wired to History panel via `tabs/segments/utils/data/reciter-actions.ts:73` and `playback/preview.ts:209`.
- **Append cadence:** one line per op that has peaks payload at save time. Lazy POST during playback for ops with no precomputed peaks.
- **Acceptance:** anonymous viewer expanding a History row sees the waveform render without recomputing peaks (p99 ≤ 50 ms warm; ≤ 600 ms cold).

### `low_confidence_v2.json`

- Read-only sidecar. Bucket mount for both completed and in-flight.
- **Written by:** offline extraction pipeline only — copied into bucket on `alignment_completed`. Carried through on publish move.
- **Acceptance:** absence is graceful — Inspector treats missing file as empty set.

### `<bucket>/catalog/reciter_catalog.json` (single catalog file)

- **Read:** Inspector backend parses on startup via pydantic; in-memory model replaced atomically on each write. Browser fetches once on app load via a backend endpoint that serves a cached copy.
- **Source:** bucket. Inspector backend sole writer via `services/catalog.py`.
- **Schema:** see [`inspector-state-management.md`](inspector-state-management.md) §3 — combines `vocab.{riwayat, styles, audio_sources}`, `reciters[]`, `aliases[]`.
- **Acceptance:** Audio-tab navigation across reciters does not round-trip the backend per-reciter (browser uses the cached catalog response).

### `inspector/.cache/<slug>/peaks/<hash>.json`

- **Computed on demand** via `services/peaks.py::compute_segment_peaks` (HTTP Range decode against the audio origin → ffmpeg → peaks).
- **Stored:** disk-backed under `INSPECTOR_CACHE_DIR/<slug>/peaks/` for warm-rescue across requests within one container life. Lost on rebuild; recomputed lazily.
- **Returned with HTTP headers:** `Cache-Control: public, max-age=31536000, immutable; ETag: <hash>`. Hash-keyed content can stay `immutable`. Browser caches forever; CDN in front of Inspector caches across users.
- **Performance reality:** disk-cache hit <5 ms; cold compute ~400–700 ms (HTTP Range fetch + ffmpeg). 10 concurrent scrubbing users hitting cold peaks saturate the 2 vCPU on free CPU-basic — see §11.

### `<bucket>/state/reciter_state.json`

- **Read:** Inspector backend parses on startup via pydantic; in-memory model replaced atomically on each write. Other consumers download via `huggingface_hub` and parse with the same pydantic model.
- **Written by:** Inspector backend, sole writer; per-slug `threading.Lock` serializes; mount-write + direct `huggingface_hub.upload_file()` per write for durability.
- **Schema:** see [`inspector-state-management.md`](inspector-state-management.md) §2.
- **Acceptance:** state writes appear in the bucket within seconds of the API response; container restart mid-write retains either old or new row (atomic-write-then-rename pattern), never torn.

### `<bucket>/audit/<YYYY>-<MM>.jsonl`

- **Append-only.** ONE folder for all events (state, catalog, claim, admin). Partitioned per-month (`audit/2026-05.jsonl`).
- **Read pattern:** ad-hoc by maintainers via the admin dashboard; tail-reads for "recent activity" surfaces.
- **Integrity:** **no `prev_hash` chain.** Tamper detection via offsite versioned snapshots of the bucket (HF CDN versioning is not a trust boundary on its own; cross-Region snapshot is the audit guarantee).
- **Per-month meta:** `<bucket>/audit/_meta.json` carries `schema_version` once per partition; not per record.
- **Storage:** ~3.6 MB/year sustained; partitioning is automatic.

## 9. Phased rollout

Maps onto the parent doc's [§10 phased migration](inspector-deployment-plan.md). This doc's scope lands across all phases.

### Phase 0 — Foundation (no deploy)

**In scope:**
- Create the dev + prod single private HF buckets (one per env).
- Implement `scripts/lib/schemas/` (pydantic models for state, catalog, audit, edit_history v2; cross-consumer location).
- Implement `inspector/services/hf_bucket.py` (mount path resolver, write helpers, direct-upload wrapper).
- Implement `inspector/services/state.py` (state machine + JSON persistence + audit append; per-slug `threading.Lock`).
- Implement `inspector/services/catalog.py` (mirrors `state.py` — same write pattern, validation, audit; merges riwayat/styles/audio_sources/reciters/aliases).
- Implement `inspector/services/data_dir.py::resolve(slug)` per-mode data dir resolver.
- **Manually seed** at v2 cutover (~15 reciters): hand-author `<bucket>/state/reciter_state.json` and `<bucket>/catalog/reciter_catalog.json` per [`inspector-state-management.md`](inspector-state-management.md) §3 mapping rules. No script — too few rows.
- Hand-seed `<bucket>/access/inspector_roles.json` (consolidated owners + maintainers; one-shot bootstrap at Phase 0 — see [`inspector-state-management.md`](inspector-state-management.md) §9 bootstrap section).

**Acceptance:**
- Dev bucket mounts successfully into a one-off test Space.
- `state.py::transition()` validates and rejects every invalid transition from the §4 matrix; pydantic catches malformed payloads at write time.
- `catalog.py::transition()` rejects mutations to immutable fields (`slug`, `reciter_id`).
- Seeded JSON files parse, every existing reciter has an entry in both, lifecycle states match observable file presence.

### Phase 1 — Read-only deploy (anonymous, all reciters via bucket)

**In scope:**
- **Free-tier perf prerequisites (deploy-blockers):**
  - Replace `app.run()` in `inspector/app.py` with `gunicorn -k gthread -w 1 --threads 16` in the Dockerfile CMD. **`-w 1` is load-bearing — see §7 CMD section + `app.py` startup assertion.**
  - Add `Cache-Control: public, max-age=31536000, immutable` headers to `/api/seg/segment-peaks` and `/api/seg/peaks` (peaks ARE hash-keyed, so immutable is correct).
  - Add `Cache-Control: public, max-age=86400` (1 day) to inspector segment shard routes (`/api/seg/data/...`); NOT immutable since shards mutate on re-edit.
- Image build:
  - Root `.dockerignore` excludes per-reciter data dirs, `data/audio/`, `data/reciters_index.json`, `data/{riwayat,sources,styles}.json`, `data/.audio_meta.json`, `data/.audio_durations.json`.
  - ENV defaults flipped to deployed profile.
  - COPY list trimmed to the static reference set in §7.
  - No audio catalog build step.
- Backend serves both `wip/<slug>/...` and `published/<slug>/...` reads through `/api/seg/data/...` from the mounted bucket.
- Frontend reads everything from the backend (no separate HF CDN client for inspector segments).
- Bucket mount attached to Space (read-only fine for Phase 1; no writes yet).
- Backend exclusions:
  - `routes/timestamps.py::ts_validate` deleted from deployed image.
  - `routes/audio_proxy.py` and `app.py::serve_audio` excluded.

**Out of scope:** writes, auth.

**Acceptance:**
- Anonymous user lands on deployed website, segments tab for any reciter (in-flight or completed) renders within p99 ≤ 800 ms cold via bucket mount, ≤ 50 ms warm.
- Image ≤ ~400 MB.
- No `data/audio/`, `data/recitation_segments/`, `data/timestamps/`, `data/reciters_index.json`, or per-reciter manifests in `/app/data`.
- gunicorn (single worker, 16 threads) handles 6 concurrent cache-warm reads with p95 ≤ 1 s.

### Phase 2 — Bucket reads for in-flight reciters

**In scope:**
- Inspector backend reads in-flight data from `<bucket>/wip/<slug>/...` (flat layout).
- One-shot migration: copy current `data/recitation_segments/<slug>/` files into the dev bucket's flat `wip/<slug>/` layout (drop the nesting).
- Available + Under-review tabs render data from the bucket.
- `editingDisabled` store consumed by every edit-affordance component (writes still 403'd).

**Acceptance:**
- In-flight reciter renders within p99 ≤ 1.5 s cold via bucket mount, ≤ 50 ms warm.
- A bucket-side write made externally via CLI is reflected in the website within 30 s (mount flush bound).
- 10 concurrent anonymous viewers on the same in-flight reciter served by NFS local cache at <50 ms each (after the first cold fetch).

### Phase 3 — HF OAuth + claim flow (no writes yet)

**In scope:**
- HF OAuth via `hf_oauth: true` Space frontmatter.
- `/api/auth/login`, `/api/auth/callback`, `/api/auth/logout`.
- Self-contained signed-cookie session (Flask `itsdangerous`) carrying `{login, hf_user_id, iat}`. No `role` (resolved fresh per request via `access.resolve_role`), no `csrf` (Origin/Referer check + SameSite=Lax). No server-side session store.
- `/api/me` endpoint.
- `/api/claim`, `/api/release`, `/api/mark-ready`, `/api/unmark-ready` write directly to bucket state file (synchronous, no dispatch).
- Per-slug `threading.Lock` (single lock per slug; no `(slug, login)` sub-mutex).
- One-claim-per-user enforcement with maintainer/owner bypass + audit.

**Acceptance:**
- A first-time visitor can claim a reciter in 3 clicks; no GitHub OAuth involved.
- Returning user with active session claims in 1 click.
- Two simultaneous claims on the same reciter: one succeeds, one rejected immediately (no propagation lag).
- Mark-ready (flips `marked_ready=1`) → unmark-ready (flips back) preserves assignee.
- Release after mark-ready clears assignee, sets `marked_ready=0`, transitions to `awaiting_review`.
- All state writes appear in `<bucket>/audit/<YYYY>-<MM>.jsonl` with correct `actor.hf_user_id`.

### Phase 5 — Writes

**In scope:**
- Save flow points at `<INSPECTOR_BUCKET_MOUNT>/wip/<slug>/...` (via `data_dir.resolve(slug)` helper). **Flat layout** — no `data/recitation_segments/<slug>/` nesting in the bucket.
- Existing `save_seg_data()` runs unchanged at the call-site; `data_dir.resolve` is the single point of difference between modes.
- `INSPECTOR_FORCE_FLUSH_ON_SAVE=1` is the **default** in deployed mode (per-save `huggingface_hub.upload_file()` for durability across container rebuilds).
- Drop `file_hash_after`, genesis record, `backup_file()` calls in deployed save path.
- `validate_edit_history.py` (now a library) drops `check_file_hash` and `check_genesis_record`.
- Edit history schema additions: `actor: {hf_user_id, login_at_time, role}` per batch. **No `record_hash`** — tamper detection via offsite versioned snapshots.
- Validators (`validate_segments`, `validate_audio`, `validate_edit_history`, `validate_timestamps`) become libraries called by Inspector services on every relevant write; CLI wrappers retained.
- Ship the 4 v2 admin events: `claim.force_released`, `claim.reassigned`, `admin.force_set_state` (narrow allowed pairs only), `reciter.merge_rejected`.

**Acceptance:**
- Volunteer reviewer end-to-end edits a `_test_*` reciter, edits visible to other viewers within seconds of save (force-flush eliminates the 30 s window for save-data).
- Backend restart mid-session: the bucket has the last-durable state intact (force-flush guarantees); only the unflushed-since-last-save typing is lost.
- Save POST during `under_review + marked_ready=1` returns 410 cleanly.
- New `edit_history.jsonl` lines have no `file_hash_after`, no genesis record, and carry an `actor` block per batch.

### Phase 6 — Publish pipeline + cleanup

**In scope:**
- `POST /api/admin/publish/<slug>` runs synchronously: state transition + in-process bucket move/copy `wip/<slug>/` → `published/<slug>/` + fire `repository_dispatch reciter.completed` (drives `update-reciters.yml` + `release.yml`) + enqueue ONE `timestamps-refresh` HF Job. The job-completion webhook flips `awaiting_timestamps → completed`.
- Decommission v1 + earlier-v2-draft workflows: `bot-create-pr.yml`, `bot-comment.yml`, `issue-commands.yml`, `pr-assignee-sync.yml`, `validate-segments-pr.yml`, `segments-pr-merged.yml`, `forward-to-inspector.yml`.
- Delete `find_segments_pr.py`.
- Drop `data/reciters_index.json`, `data/riwayat.json`, `data/sources.json`, `data/styles.json`, `data/audio/` from the repo.
- Inspector deploy via push to Space; `inspector-deploy.yml` automates the upload from `main`.
- Add `bucket-data-hygiene.yml` (scheduled validators across all bucket reciters; surfaces to admin dashboard; opens GH issues for CRITICALs).
- Update contributor docs.

**Acceptance:**
- Publishing a `_test_*` reciter end-to-end: in-bucket move complete; `repository_dispatch` triggers `update-reciters.yml` + `release.yml`; timestamps job runs and the callback flips state to `completed`.
- All deprecated workflows have produced no runs in a 7-day observation window.

## 10. Risks and open questions

### Bucket mount cold-fetch latency

Estimated 100–300 ms for a 5 MB JSON via NFS lazy fetch — better than github-fetch's 200–400 ms but worse than CDN. **Mitigation:** the parsed seg cache (128 MB LRU) absorbs warm reads; cold reads are unavoidable on first access per Space replica per reciter. **Acceptance gate (Phase 2):** measure actual p95 cold fetch on dev Space with a representative `detailed.json`. If >500 ms, pre-warm bucket regions or upgrade to a CPU-upgrade Space tier (more local cache).

### HF outage blast radius

Bucket mount down means all reciter reads + writes break. **Mitigation:** for the rare HF outage, Inspector's session pages still serve static reference data (qpc_hafs etc., baked in), with a banner "HF is temporarily unavailable; reciter data unavailable". Reviewers see edit attempts queue locally with a "retry on reconnect" banner. **Acceptance:** during HF maintenance windows, Inspector degrades gracefully (no 500s; clear messaging; no data loss). Monitor [HF status](https://status.huggingface.co/).

### HF Jobs reliability for the timestamps job

The publish path enqueues exactly one HF Job (`timestamps-refresh`). If Jobs are flaky, the maintainer can re-trigger from a "check status" button on the admin dashboard. No automated retry/backoff in v2.

### `detailed.json` over 10 MB

Current cohort max is **5.2 MB** raw. If a future reciter exceeds 10 MB, the parsed cache LRU may evict it under pressure. **Mitigation:** cache cap can be raised. CI check that fails if any committed `detailed.json` exceeds 10 MB.

### Backend memory on shared CPU-basic

128 MB parsed seg cache + ~50–100 MB Python heap + ~80 MB resident static data → ~300 MB runtime. Comfortably inside HF Spaces 16 GB.

### Mount loss on Space rebuild

Bucket mount survives container rebuild — that's the entire point. Local NFS cache (under `/var/cache` or wherever hf-mount stores it) is wiped on rebuild; first-request-after-rebuild pays a cold fetch. Acceptable.

### Mount flush window staleness

Reviewer's typing within 30 s of the last save isn't visible to other viewers if they relied on the mount alone. With `INSPECTOR_FORCE_FLUSH_ON_SAVE=1` (the default), every save calls `huggingface_hub.upload_file()` directly, bypassing the flush window. State, catalog, and audit writes always direct-upload regardless.

### Bucket write rate ceiling

HF buckets don't publish a write QPS limit. Realistic write rate: 1 reviewer × 1 save / 10 s = 0.1 writes/s sustained per reciter; 10 concurrent reviewers = 1 write/s aggregate. Trivially under any plausible limit.

### Concurrent active reviewers

Locking enforces one reviewer per reciter. Across reciters, multiple reviewers can be active. Each holds an in-process per-slug `threading.Lock` + parsed cache slot. With 128 MB parsed cache and ~5 MB per slot, capacity is ~25 simultaneous active reciters per replica. Beyond that, eviction churn rises. **Mitigation:** scale vertically (larger Space tier) or address per [`inspector-deferred.md`](inspector-deferred.md) D6.

### Mount unavailable on container start

If a bucket mount fails to attach during Space build, the container won't see the mount point. Inspector's startup checks for paths' existence and refuses to start with a clear log message. **Mitigation:** Space-side healthcheck retries; runbook documents recovery (re-attach via Space settings → Volumes).

### Audit log growth

Per-month partitioning (`audit/<YYYY>-<MM>.jsonl`) handles growth automatically. ~3.6 MB/year sustained means a partition file is ~300 KB. No manual cleanup needed.

### Audit log tamper detection

Without a `prev_hash` chain, audit-log tampering is detected by offsite versioned snapshots of the bucket (cross-Region snapshot or scheduled `huggingface_hub` download to an air-gapped store). Audit forensics rely on these external versioned copies, not in-record cryptographic linkage.

### Single-replica assumption

Whole v2 design assumes one Inspector replica (`-w 1` asserted at boot). Multi-replica scale-out deferred — see [`inspector-deferred.md`](inspector-deferred.md) D6.

## 11. Performance budget on free CPU-basic

Sized for HF Spaces CPU-basic (2 vCPU shared, 16 GB RAM, ephemeral disk + bucket mount) targeting ~10 mixed-tab concurrent users.

### Op cost table

Measured / estimated on the target environment:

| Op | Cost | Source / dependency |
|---|---|---|
| Parse `detailed.json` (5 MB) via orjson + adapter walk | **80–150 ms** | `services/data_loader.py:121-144`. orjson parses ~1 GB/s, adapter walks every entry/segment ~30 ms/MB |
| 12-category validator cold (`validate_reciter_segments`) | **300–600 ms** | `services/validation/__init__.py:143`. Pure Python loops |
| Peaks compute, ~30 s segment region, cold | **400–700 ms** wall | `services/peaks.py:245`. HTTP Range fetch ~150 ms + ffmpeg subprocess fork+decode ~250–500 ms |
| Peaks compute, disk-cache hit | <5 ms | Cache lookup |
| Save flow (active reviewer) | ~500 ms compute + 0–30 s mount flush (off the user's hot path) | atomic write + rebuild segments + validation snapshot + history append. No network round-trip — mount handles flush |
| Bucket mount cold read (5 MB JSON) | **~100–300 ms** | NFS lazy fetch (verify in Phase 2) |
| Bucket mount warm read | <10 ms | NFS local cache hit |
| State file read (in-memory cache) | <1 ms | Dict lookup |

### Concurrency ceiling

- **6–8 truly concurrent active users** stay under p95 1 s (vs v1's 4–6, slightly better because no GIL contention from github-fetch parsing). With `-w 1 --threads 16` the GIL serializes pure-Python work but releases on I/O (NFS, ffmpeg) — that's where the bottleneck actually is.
- **10 concurrent works comfortably with cache-warm reads** — already-parsed `detailed.json`, already-cached peaks.
- **First bottleneck is ffmpeg subprocess fork on `/api/seg/segment-peaks`** — same as v1.
- **Second bottleneck is the validator** — 300–600 ms cold per reciter. `/api/seg/trigger-validation` must stay gated to authenticated, lock-holding reviewers.
- **Memory headroom is comfortable** — ~300 MB runtime vs 16 GB available.

### Top 3 mitigations

1. **`gunicorn -k gthread -w 1 --threads 16`** in the Dockerfile CMD, replacing `app.run()`. **Mandatory before public deploy.** `-w 1` is load-bearing; see §7 + state-management §5.1.
2. **`Cache-Control: public, max-age=31536000, immutable` on peaks routes** (peaks ARE hash-keyed) and `max-age=86400` on inspector segment shards (NOT immutable, since shards mutate on re-edit). Plus front Inspector with Cloudflare or HF edge cache. CDN absorbs scrubbing bursts entirely; backend ffmpeg stays idle except on first global hit.
3. **128 MB parsed seg cache** (separate from any kernel-level NFS cache) keeps `detailed.json` parses warm for active reciters.

### Scaling triggers

- **p95 latency > 1.5 s for 10+ minutes** under steady load → upgrade to CPU-upgrade (4 vCPU, $0.03/h).
- **Backend memory > 800 MB sustained** → audit for memory leaks or raise `INSPECTOR_PARSED_CACHE_BYTES` and upgrade RAM.
- **Bucket mount cold-fetch p95 > 500 ms** → enable CDN pre-warming for the bucket region; see HF docs on bucket pre-warming.
- **More than ~25 active reviewers concurrently per replica** → lock contention; move to multi-replica + bucket-side optimistic concurrency or Redis lock.
- **Multi-worker (`-w 2+`) needed** → cannot enable until a shared coordinator (Redis or bucket-CAS read-version-write-version) is in place; today's in-process structures would deadlock or corrupt cross-worker. Ship `-w 1` first; revisit if `--threads 16` hits CPU saturation under measured load.

### Out of scope (won't implement until measurement demands)

- Distributed cache (Redis) for parsed entries across multiple Space replicas
- Persistent volume for caches (current loss bound is acceptable; bucket itself is persistent)
- Async migration (FastAPI/uvicorn) — gunicorn-gthread is sufficient
- Custom CDN beyond Cloudflare free / HF edge

## TODO

Live measurements once Phase 2 is deployed: actual ms costs against the table above, real bucket mount cold-fetch latency, real cache hit ratios.
