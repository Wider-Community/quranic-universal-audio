# Inspector Data Storage Strategy

Companion to [`inspector-deployment-plan.md`](inspector-deployment-plan.md). Implementation-grade reference for how the deployed Inspector reads, writes, and caches data files when there is no local repo on disk. Specifies file-by-file classification, the github-fetch service contract, the scratch dir lifecycle, the Git Data API write path, configuration, image build changes, per-phase acceptance criteria, and open risks.

The parent doc covers identity convention, auth/claim flow, locking, state computation, and phased rollout. This doc owns everything file-IO.

## 1. Model in one paragraph

The deployed backend is **stateless for reads** and **near-stateless for writes**. Read traffic for any reciter — anonymous or authenticated — flows through a single `github-fetch` service that pulls files from GitHub raw at the appropriate ref (`main` for completed, `reciter/<slug>/segments` for under-review) and caches them in a server-side LRU. Write traffic is gated to one active reviewer per reciter; their session materialises the same files into a small per-session **scratch dir**, and edits flow scratch → debounced → Git Data API multi-file commit → PR branch. The backend keeps no persistent state for read traffic, and only ephemeral per-session disk for the active reviewer's writes. Audio plays browser → origin direct; timestamps come browser → HF CDN direct.

## 2. Classification map

| File / pattern | Scope | Read path | Write path | Notes |
|---|---|---|---|---|
| `data/surah_info.json` | static | server-image | n/a | Loaded once at app boot |
| `data/qpc_hafs.json` | static | server-image | n/a | ~11 MB |
| `data/digital_khatt_v2_script.json` | static | server-image | n/a | ~9.5 MB |
| `data/phoneme_sub_costs.json` | static | server-image | n/a | Boundary check input |
| `data/reciters_index.json` | static | server-image | n/a | UI dropdown source |
| `data/riwayat.json`, `sources.json`, `styles.json` | static | server-image | n/a | Controlled vocab |
| `data/.audio_meta.json`, `.audio_durations.json` | static | server-image | n/a | VBR + duration cache |
| `data/audio/<cat>/<src>/<slug>.json` | per-reciter | **github-fetch** + LRU | n/a (build-time) | Audio URL templates |
| `data/recitation_segments/<slug>/segments.json` | per-reciter | **github-fetch** + LRU (read-only viewers); **scratch** (active reviewer) | Git Data API on debounce (active reviewer) | |
| `data/recitation_segments/<slug>/detailed.json` | per-reciter | same | same | Largest editable file (avg ~12 MB, max ~33 MB) |
| `data/recitation_segments/<slug>/edit_history.jsonl` | per-reciter | same | same | Append-only |
| `data/recitation_segments/<slug>/edit_history_peaks.jsonl` | per-reciter | same | same | History panel waveform cache; **kept** (read path exists at `/api/seg/history-peaks/<reciter>`) |
| `data/recitation_segments/<slug>/low_confidence_v2.json` | per-reciter | same | n/a (pipeline-written) | Sidecar; read-only in Inspector |
| `data/timestamps/...` | per-reciter | **HF CDN** direct (browser) | offline pipeline | Already implemented |
| Audio mp3/wav | per-reciter | **origin direct** (browser) | n/a | Backend never touches |
| `data/recitation_segments/<slug>/*.bak` | per-reciter | n/a | discard | `backup_file()` calls removed in deployed save path |
| `validation.log` (per-reciter or root) | dev artifact | n/a | discard | Not shipped |
| `data/qul_downloads/` | dev artifact | n/a | discard | Pipeline input only; excluded from image |
| `data/RECITERS.md`, `data/README.md`, `beam_diff_report.txt` | docs | n/a | discard | Kept in repo, excluded from image |
| `data/.cache/<slug>/canonical_phonemes.pkl` | per-reciter | recompute lazy + JSON re-encode | regenerable | Pickle dropped (Python-version-fragile) |
| `data/.cache/<slug>/audio/` | per-reciter | n/a | discard | Audio proxy gone in deployed |
| `inspector/.cache/<slug>/peaks/` | per-reciter | recompute on demand + browser/CDN cache headers | n/a | No persistent volume; immutable response |

## 3. The github-fetch service

A new module `inspector/services/github_fetch.py`. ~80–120 lines. Replaces the worktree concept entirely.

### Interface

```python
def fetch_text(slug: str, file: str, ref: str) -> str: ...
def fetch_json(slug: str, file: str, ref: str) -> Any: ...
def fetch_jsonl(slug: str, file: str, ref: str) -> Iterator[dict]: ...
def invalidate(slug: str, file: str | None = None, ref: str | None = None) -> None: ...
```

`file` is repo-relative (e.g. `data/recitation_segments/<slug>/segments.json`). `ref` is a branch name or sha. The service resolves to `https://raw.githubusercontent.com/<owner>/<repo>/<ref>/<file>` and pipes through:

1. **LRU cache** keyed on `(file, ref)`. Default cap: 256 entries, ~512 MB max. Configurable via `INSPECTOR_FETCH_LRU_BYTES`.
2. **TTL** of 5 minutes for `main` ref entries (anonymous viewers tolerate small staleness; merge invalidations refresh sooner). PR-branch refs cached only 30 seconds (under-review files mutate; the active reviewer's scratch is the canonical store anyway).
3. **Conditional revalidation** with `ETag`/`If-None-Match` — GitHub raw supports it. 304 responses don't burn the GitHub rate-limit budget.
4. **Auth** via the GitHub App installation token. Adds the rate limit headroom of an authenticated client (5,000 req/h) and works for private branches if the repo ever needs that.

### Cache invalidation triggers

- **Squash-merge of `reciter/<slug>/segments`** — `segments-pr-merged.yml` POSTs `/api/internal/cache-invalidate?slug=<slug>` (with a shared secret). Backend drops every cache key matching that slug.
- **Manual force-refresh** — admin endpoint `/api/internal/cache-invalidate-all` for emergencies.
- **TTL expiry** — natural backstop.

### What this service does NOT do

- It does **not** write. Writes go through the dedicated commit pathway in §5.
- It does **not** mediate active-reviewer reads. The reviewer's session reads from scratch dir, which is materialised once on session start (using github-fetch under the hood) then mutated locally.
- It does **not** stream audio or large binaries. JSON/JSONL only. Audio is browser→origin.

## 4. Scratch dir

A small ephemeral working area on the deployed backend, used **only for the one active reviewer per reciter** to run the existing file-based save flow without modification.

### Layout

```
INSPECTOR_SCRATCH_DIR/<slug>/
└── data/recitation_segments/<slug>/
    ├── segments.json
    ├── detailed.json
    ├── edit_history.jsonl
    ├── edit_history_peaks.jsonl
    └── low_confidence_v2.json
```

Reproduces the path layout `save_seg_data()` and validators expect, scoped to one slug.

### Lifecycle

| Event | Action |
|---|---|
| Reviewer claims reciter | Backend creates `<scratch>/<slug>/...`, materialises 5 files via github-fetch at branch ref `reciter/<slug>/segments`, marks dir clean |
| Save POST | Existing `save_seg_data()` runs in-place: atomic write `detailed.json`, rebuild `segments.json`, append `edit_history.jsonl`. Marks dir dirty. Resets debounce timer |
| Debounce fires | Multi-file commit via Git Data API (§5). Marks dir clean |
| Reviewer releases claim / lock expires | Force-flush any pending commits, then delete scratch dir |
| Backend restart with dirty scratch | On boot, check for dirty scratch dirs; flush each as one commit, then delete |

### What lives in scratch but is NOT pushed

- `validation.log` — regenerated on demand
- `.bak` siblings — `backup_file()` calls are removed from the deployed save flow (§5)
- `inspector/.cache/<slug>/peaks/` — peaks are recomputed/cached separately, not pushed

### Footprint

Per active reviewer: 9–19 MB on disk. With one-reviewer-per-reciter and realistic concurrency (1–10), total scratch occupancy fits comfortably in <250 MB. Ephemeral disk is sufficient — restart loss is bounded by the debounce window (≤5 min) and recoverable by re-fetching from the PR branch on next session.

## 5. Write path

### Git Data API multi-file commit

On debounce-fire, for the dirty scratch dir of slug `<slug>` on branch `reciter/<slug>/segments`:

1. **Read** the 4–5 dirty files from scratch.
2. **Create blobs** — `POST /repos/.../git/blobs` for each file. Returns SHAs.
3. **Get current tree** at the branch tip — `GET /repos/.../git/ref/heads/reciter%2F<slug>%2Fsegments` → commit SHA → tree SHA.
4. **Create new tree** — `POST /repos/.../git/trees` with the parent tree SHA + blob entries for each updated path.
5. **Create commit** — `POST /repos/.../git/commits` with:
   - `tree` = new tree SHA
   - `parents` = `[current_commit_sha]`
   - `message` = `[<slug>] segments: <human summary>` (`[wip]` prefix for debounced auto-commits; absent for explicit "Push to PR now" button)
   - `author` = `{ "name": "<gh-login>", "email": "<id>+<gh-login>@users.noreply.github.com" }` (the active reviewer)
   - `committer` = `{ "name": "github-actions[bot]", "email": "..." }` (the App)
6. **Update ref** — `PATCH /repos/.../git/refs/heads/<branch>` with the new commit SHA. `force = false` (fail if the branch moved out from under us).
7. On 422 ref-update conflict: re-fetch base, re-fold the scratch state, retry once. If still conflicting, surface to the reviewer ("branch changed externally; reload to merge").

### Debounce triggers

A commit fires when **any** of:

1. 30 seconds since last save with no further saves
2. 5 minutes since last commit with continuous saves (hard cap)
3. Explicit "Push to PR now" button (UI affordance, future)
4. Lock release / claim transfer
5. `beforeunload` `sendBeacon` from the browser tab
6. Backend graceful shutdown (drains dirty scratch dirs)

### Attribution

`author = reviewer`, `committer = App bot`. This makes commits show on the contributor's GitHub graph and feeds `segments-pr-merged.yml`'s author roundup. Documented as the **one exception** to the "all bot artifacts as `github-actions[bot]`" rule that the `process-requests` skill enforces (see parent doc §3 "Commit attribution").

### Removed in deployed save path

- `backup_file()` calls in `save.py` and `undo.py` — git history is the recovery path.
- `file_hash_after` field write in `_persist_and_record` and `_append_revert_record` — chain is dropped.
- `seg_save_chart` route + `analysis/*.png` writes — debug-only, no UI surface.

## 6. Configuration

| Env var | Default (deployed) | Default (local) | Purpose |
|---|---|---|---|
| `INSPECTOR_TS_SOURCE` | `huggingface` | `local` | Picks `services/ts_local.py` (off in deployed) vs HF CDN |
| `INSPECTOR_DATA_DIR` | `/app/data` (image) | repo root | Static reference data location |
| `INSPECTOR_SCRATCH_DIR` | `/tmp/inspector-scratch` | `/tmp/inspector-scratch` | Per-session writable workspace |
| `INSPECTOR_GITHUB_OWNER`, `INSPECTOR_GITHUB_REPO` | repo coords | unused (local fs) | github-fetch target |
| `INSPECTOR_GITHUB_APP_ID`, `INSPECTOR_GITHUB_APP_PRIVATE_KEY` | secret | unset | Installation token issuance |
| `INSPECTOR_FETCH_LRU_BYTES` | `536870912` (512 MB) | unused | github-fetch cache cap |
| `INSPECTOR_FETCH_TTL_MAIN_SEC` | `300` | unused | Cache TTL for `main` ref |
| `INSPECTOR_FETCH_TTL_BRANCH_SEC` | `30` | unused | Cache TTL for PR branch refs |
| `INSPECTOR_DEBOUNCE_INACTIVITY_SEC` | `30` | unused | Debounce inactivity window |
| `INSPECTOR_DEBOUNCE_HARDCAP_SEC` | `300` | unused | Hard-cap commit interval |
| `INSPECTOR_INTERNAL_SECRET` | secret | unset | Cache-invalidate webhook auth |
| `INSPECTOR_AUDIO_PROXY_ENABLED` | `0` | `1` | Local mode keeps audio proxy |

A single `inspector/config.py` resolution function returns a typed `Config` object so route handlers don't read env vars directly.

## 7. Image build changes

### Excluded from Docker image

Add to `inspector/.dockerignore` (or use selective `COPY`):

```
data/audio/                   # served via github-fetch
data/recitation_segments/     # served via github-fetch / scratch
data/timestamps/              # served via HF CDN
data/qul_downloads/           # pipeline input only
data/.cache/                  # local-only artifacts
data/RECITERS.md
data/README.md
data/**/validation.log
data/**/beam_diff_report.txt
data/**/*.bak
.local/
.github/
docs/
```

### Included in Docker image

```
inspector/                    # code (after frontend build)
validators/                   # code
scripts/lib/                  # code
data/surah_info.json
data/qpc_hafs.json
data/digital_khatt_v2_script.json
data/phoneme_sub_costs.json
data/reciters_index.json
data/riwayat.json
data/sources.json
data/styles.json
data/.audio_meta.json
data/.audio_durations.json
```

### Resulting image

~22 MB of static data + Python deps + ffmpeg + frontend dist. Total ~250–400 MB depending on base. Image rebuilds only on **code** changes. Audio manifest changes, reciter additions, edit history updates — none trigger redeploys.

### `.dockerignore` discipline

Add a CI check that diff-fails if any `data/audio/*`, `data/recitation_segments/*`, `data/timestamps/*`, `data/qul_downloads/*`, `data/.cache/*`, `**/*.bak` path appears in the built image (e.g. `docker run --rm <image> find /app/data -type f | grep -E '...'` returns empty).

## 8. Per-file specifications

For each meaningful per-reciter file, the deployed-mode spec:

### `segments.json`

- **Read (anonymous viewer):** github-fetch at `main` (completed) or PR branch (under-review).
- **Read (active reviewer):** scratch dir.
- **Written by:** `save.py::rebuild_segments_json` on every save; never edited directly.
- **Pushed:** every debounced commit, alongside `detailed.json`.
- **Cache key:** `(slug, "segments.json", ref)`.
- **Acceptance:** anonymous user opens reciter → segments tab renders within p99 ≤ 800 ms cold, ≤ 50 ms warm.

### `detailed.json`

- Same paths as `segments.json`.
- **Size concern:** can hit 33 MB. Cache cap (§3) sized accordingly — 256 entries × 1 MB avg = 256 MB; max-size guard limits any one entry to 50 MB to avoid one heavy reciter blowing the cache.
- **Acceptance:** memory footprint of cached `detailed.json` files stays under `INSPECTOR_FETCH_LRU_BYTES`; hot eviction is logged.

### `edit_history.jsonl`

- Same paths.
- **Append cadence:** one line per save batch. Pushed in the same commit as the segment files.
- **Schema cleanup (parent §7):** drop `file_hash_after` field, drop genesis record, keep `batch_id` / `schema_version` / `validation_summary_*` / `operations` / `reverts_*`.
- **Acceptance:** validators that read this file (CI-only `validate_edit_history.py`) pass with the new schema.

### `edit_history_peaks.jsonl`

- Same paths. **Kept** (the original plan §7 misjudged this — the read path exists at `routes/peaks.py:82` `seg_history_peaks_get` and is wired to the History panel via `tabs/segments/utils/data/reciter-actions.ts:72` and `playback/preview.ts:209`).
- **Append cadence:** one line per op that has peaks payload at save time (FE-driven). Lazy POST during playback for ops with no precomputed peaks.
- **Pushed:** in the same commit as the other history files.
- **Acceptance:** anonymous viewer expanding a History row sees the waveform render without recomputing peaks (p99 ≤ 50 ms).

### `low_confidence_v2.json`

- Read-only sidecar. github-fetch in deployed; scratch in active reviewer mode.
- **Written by:** offline extraction pipeline only (out of scope for Inspector save flow).
- **Acceptance:** absence is graceful — Inspector treats missing file as empty set.

### `data/audio/<cat>/<src>/<slug>.json` (audio manifest)

- **Read:** github-fetch at `main` (audio manifests don't live on PR branches).
- **Pushed:** never by Inspector (build-time only).
- **Cache:** longer TTL (~30 min) — manifests change rarely.
- **Acceptance:** browser receives `url_template` and constructs playback URLs without round-tripping the backend per-verse.

### `inspector/.cache/<slug>/peaks/<hash>.json`

- **Computed on demand** via `services/peaks.py::compute_segment_peaks` (HTTP Range decode against the audio origin → ffmpeg → peaks).
- **Stored:** request-scoped only — not persisted to disk in deployed mode.
- **Returned with HTTP headers:** `Cache-Control: public, max-age=31536000, immutable; ETag: <hash>`. Browser caches forever; CDN in front of Inspector caches across users.
- **Acceptance:** first hit ~50 ms compute; subsequent hits <5 ms (cached); p99 cross-user latency ≤ 50 ms once warm.

## 9. Phased rollout

Maps onto the parent doc's [§10 phased migration](inspector-deployment-plan.md). This doc's scope lands across phases 1, 2, 5a, and 5b:

### Phase 1 — Read-only deploy (anonymous, `main` data only)

**In scope of this doc:**
- Implement `services/github_fetch.py` with LRU + TTL + ETag revalidation
- App token plumbing for github-fetch
- Image build with `.dockerignore` for `data/audio/`, `data/recitation_segments/`, `data/timestamps/`, `data/qul_downloads/`, `data/.cache/`
- Static reference data baked in (~22 MB)
- `INSPECTOR_TS_SOURCE=huggingface` flipped on for the image
- `routes/segments_data.py` and `routes/audio_metadata.py` route through github-fetch for read paths at `main` ref
- `routes/timestamps.py::ts_validate` deleted from deployed image (no validation panel)
- `routes/audio_proxy.py` and `app.py::serve_audio` excluded from deployed image (gated by `INSPECTOR_AUDIO_PROXY_ENABLED=0`)

**Out of scope:** PR-branch reads, writes, scratch dir, auth.

**Acceptance:**
- Anonymous user lands on deployed website, segments tab for any completed reciter renders within p99 ≤ 800 ms cold, ≤ 50 ms warm.
- Image ≤ ~400 MB.
- No `data/audio/*`, `data/recitation_segments/*`, `data/timestamps/*` files present in `/app/data` of running container.
- GitHub rate-limit budget consumed at ≤ 10% per hour under expected anonymous traffic.

### Phase 2 — PR-branch reads

**In scope:**
- github-fetch extended to take `ref` parameter
- TTL differentiated per ref (5 min for main, 30 s for branch)
- Reciter state pills wired to `/api/reciter-task/<slug>` (parent doc §6)
- Available + Under-review tabs render their data files via github-fetch at the PR branch ref

**Acceptance:**
- Under-review reciter renders the same way as completed, just sourced from the PR branch.
- A push to the PR branch (made externally via CLI) is reflected in the website within 30 s.

### Phase 5a — Writes against existing edit_history schema

**In scope of this doc:**
- `services/scratch.py` for scratch dir lifecycle (create, materialise, mark dirty, flush, destroy)
- `services/github_commit.py` for the Git Data API multi-file commit path
- Save flow rewired: route handlers detect "active reviewer for this slug" → save runs against scratch dir → debounce timer set
- Debounce loop wakes and triggers `github_commit.flush(slug)`
- Backend graceful shutdown drains dirty scratch
- Backend boot check: any dirty scratch from prior crash → flush

**Out of scope:** edit_history schema change (Phase 5b).

**Acceptance:**
- One volunteer reviewer end-to-end edits a reciter, edits show on PR branch within 30 s of pause, all 4–5 files updated atomically per commit, author = reviewer, committer = App.
- Backend restart mid-session does not corrupt edit_history.jsonl (scratch is replayed from PR branch on next session).

### Phase 5b — Edit history schema simplification

**In scope:**
- Drop `file_hash_after` writes in `save.py::_persist_and_record` and `undo.py::_append_revert_record`
- Drop genesis record write path (already orphaned reader; CI check removed)
- Update `validators/validate_edit_history.py` — delete `check_file_hash`, `check_genesis_record`
- Drop `utils/io.py::file_sha256`
- Drop `config.py::METADATA_PEEK_BYTES`
- Drop `backup_file()` calls in deployed save path

**Out of scope:** anything that changes commit semantics (handled in 5a).

**Acceptance:**
- New commits land without `file_hash_after` field.
- CI `validate_edit_history.py` passes against new-schema histories.
- `.bak` files do not appear in any PR branch (git status clean except for the actual edits).

### Phase 6 — Cleanup landing in this doc's scope

- Final removal of `services/ts_local.py` references that aren't gated (the file stays for local mode)
- Final removal of audio-proxy code paths from the deployed image
- Cache invalidation webhook from `segments-pr-merged.yml` to `/api/internal/cache-invalidate`

## 10. Risks and open questions

Beyond what the parent doc already covers:

### GitHub rate limits

5,000 req/h authenticated. Each anonymous viewer opening a reciter triggers ~5 github-fetch calls (4 data files + 1 audio manifest), all cache-cold the first time. Steady-state with healthy LRU + TTL: most reads cache-hit. Thundering-herd risk if many viewers request a freshly-merged reciter simultaneously after cache invalidation. Mitigation: single-flight pattern in github-fetch (in-flight requests for same key share the response), plus cache stampede protection (TTL jitter ±10%).

### `detailed.json` over 50 MB

Hard cap in the cache caps at 50 MB per entry. If a reciter ever produces a `detailed.json` larger than that, the cache will refuse to store it and every read will hit github-fetch. Risk is small (current max is 33 MB), but worth a CI check that fails if any committed `detailed.json` exceeds the cap. Or raise the cap to 75 MB — depends on backend memory budget.

### Backend memory

512 MB LRU + ~50–100 MB Python heap + ~50 MB resident static data (qpc_hafs etc. parsed in memory) → ~700 MB runtime. Sized for a Fly.io shared-cpu-1x@1GB or shared-cpu-2x@2GB. If the LRU cap is raised or many reciters are accessed concurrently, may need to scale up. Open question: do we want to cap in-memory `detailed.json` parsed cache (`services/cache.py::_seg`) separately from raw fetch cache, to avoid double-counting?

### Cache invalidation race on merge

`segments-pr-merged.yml` fires the invalidate webhook AFTER merge. If a viewer hits the just-merged reciter between merge-commit and webhook-fire (sub-second), they may get the pre-merge cached response. Tolerable — TTL backstops within 5 min. Worth documenting that the website is "eventually consistent within 5 min of merge" rather than promising instant.

### Anonymous PR-branch reads

Per parent doc Open Questions, defaulting to "anonymous can view in-review PR data" — this means github-fetch will serve PR-branch refs to unauthenticated browsers. Implications:
- Sub-WIP edits become publicly visible
- A reviewer's mid-typing state (within debounce) is hidden (still in scratch), but everything past debounce is public
- Rate-limit accounting: PR-branch hits count against the App's rate limit, not the user's

### Concurrent active reviewers per backend node

Locking enforces one reviewer per reciter. Across reciters, multiple reviewers can be active. Each holds a scratch dir + a debounce timer. With ephemeral disk and modest concurrency this is fine. If concurrency grows past ~50 active reviewers per node, scratch occupancy + debounce timer count may pressure a single small VM. Decision: scale vertically (larger Fly.io shape) or move to Redis-backed lock + horizontal scale. Defer until measurement.

### Scratch dir on backend crash mid-debounce

If the debounce timer is set but the backend crashes before fire, the scratch dir state is lost (ephemeral disk) up to 5 min of edits. Recovery: next session re-fetches from PR branch. Tolerable per parent doc agreement. **Mitigation if pain:** tiny persistent volume mounted only at `<scratch>/` (cheap, ~$0.15/GB/mo), changes nothing in code (env var points scratch at the volume mount).

### Single-flight on github-fetch

When N concurrent requests hit a cold cache key, naive code triggers N github-fetch calls. Single-flight (one request goes through, others wait on the same future) is required to avoid amplification on popular reciters or on cache-cold start. Implemented in `services/github_fetch.py` via `asyncio.Lock` per key (or `threading.Lock` if Flask sync).

### App token expiry

GitHub App installation tokens expire after 1 hour. Renewal must happen seamlessly inside github-fetch and the commit pathway. Use a token cache that refreshes 5 min before expiry. Acceptance: backend uptime > 1 hour does not produce 401s on any github API call.

### Cache cold-start after deploy

Every deploy clears the LRU. First page-load post-deploy is all cold. With a CDN in front of Inspector, only the first user on each (slug, file) tuple pays the cost. Without a CDN, every active user does. Decision: front Inspector with a thin CDN (Fly's edge cache, Cloudflare free) for `/api/seg/data/*` GETs. Open until Phase 1 measures real cold-start traffic.

### Selective `.dockerignore` correctness

If `.dockerignore` is wrong (e.g. fails to exclude `data/recitation_segments/`), the image silently bloats and ships sensitive in-progress data. Mitigated by the Phase 1 acceptance check that fails if these paths exist in the built image.
