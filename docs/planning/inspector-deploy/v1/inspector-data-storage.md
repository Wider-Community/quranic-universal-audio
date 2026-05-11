# Inspector Data Storage Strategy

Companion to [`inspector-deployment-plan.md`](inspector-deployment-plan.md). Implementation-grade reference for how the deployed Inspector reads, writes, and caches data files when there is no local repo on disk. Specifies file-by-file classification, the github-fetch service contract, the scratch dir lifecycle, the Git Data API write path, configuration, image build changes, per-phase acceptance criteria, and open risks.

The parent doc covers identity convention, auth/claim flow, locking, state computation, and phased rollout. This doc owns everything file-IO.

## 1. Model in one paragraph

The deployed backend is **stateless for reads** and **near-stateless for writes**. Read traffic flows through three tiers based on reciter state. Completed-reciter Inspector data (`segments`, `detailed`, `edit_history`, `edit_history_peaks`, `low_confidence_v2`) is published to the HF dataset under `inspector/segments/<slug>/` alongside the existing TS shards and slim Aligner shards, and fetched browser → HF CDN direct, no backend involvement. Under-review reciter data lives on PR branches and is served via a `github-fetch` service that pulls from GitHub raw at `reciter/<slug>` and caches in a server-side LRU. Static reference data (Quran word text, controlled vocabularies, the consolidated audio URL catalog) ships **baked into the Space image** and is served same-origin. Write traffic is gated to one active reviewer per reciter; their session materialises the editable files into a small per-session **scratch dir**, and edits flow scratch → debounced → Git Data API multi-file commit → PR branch. The backend keeps no persistent state for read traffic, and only ephemeral per-session disk for the active reviewer's writes. Audio plays browser → origin direct; timestamps come browser → HF CDN direct.

## 2. Classification map

Four tiers: **server-image** (baked into the Docker image), **HF static** (published to `hetchyy/quranic-universal-ayahs`, browser-direct), **github-fetch** (raw.githubusercontent.com via the Inspector backend, only for in-flight branches), **scratch** (per-active-reviewer ephemeral disk).

| File / pattern | Scope | Read path | Write path | Notes |
|---|---|---|---|---|
| `data/surah_info.json` | static | server-image | n/a | Loaded once at app boot |
| `data/qpc_hafs.json` | static | server-image | n/a | ~11 MB; also published to HF `_resources/` for TS-tab browser fetches in local mode (deployed mode reads same-origin) |
| `data/digital_khatt_v2_script.json` | static | server-image | n/a | ~9.5 MB; same dual-publishing as `qpc_hafs.json` |
| `data/phoneme_sub_costs.json` | static | server-image | n/a | Boundary check input |
| `data/reciters_index.json` | static | server-image | n/a | UI dropdown source |
| `data/riwayat.json`, `sources.json`, `styles.json` | static | server-image | n/a | Controlled vocab |
| `data/.audio_meta.json`, `.audio_durations.json` | static | server-image | n/a | VBR + duration cache |
| `data/audio/<cat>/<src>/<slug>.json` (391 files, ~67 MB pretty) | per-reciter manifests | **server-image as `audio_catalog.json.gz`** (consolidated, compact, gzipped — ~6 MB total) | n/a (build-time) | One catalog covers all reciters. Build step strips `_timing` (irrelevant ~70 KB), compacts JSON (51% saved), gzips (92% saved overall vs current pretty layout). Browser fetches once on Audio-tab mount. |
| `inspector/segments/<slug>/segments.json.gz` | per-reciter, completed | **HF CDN direct** (browser) | n/a (publish on merge) | Published by `--build-inspector-segments`. Stays per-reciter, not chapter-sharded — read pattern is whole-reciter |
| `inspector/segments/<slug>/detailed.json.gz` | per-reciter, completed | **HF CDN direct** (browser) | n/a (publish on merge) | Largest editable file. Per-reciter cap ~5.2 MB raw / ~1 MB gz; cohort avg ~4.4 MB raw |
| `inspector/segments/<slug>/edit_history.jsonl.gz` | per-reciter, completed | **HF CDN direct** (browser, lazy on History panel expand) | n/a (publish on merge) | Per-reciter avg ~1-2 MB gz from ~8 MB raw |
| `inspector/segments/<slug>/edit_history_peaks.jsonl.gz` | per-reciter, completed | **HF CDN direct** (browser, lazy on History panel expand) | n/a (publish on merge) | Per-reciter avg ~300 KB gz from ~1.1 MB raw; max ~600 KB gz |
| `inspector/segments/<slug>/low_confidence_v2.json.gz` | per-reciter, completed | **HF CDN direct** (browser) | n/a (publish on merge) | Tiny (KB) |
| `data/recitation_segments/<slug>/segments.json` | per-reciter, **under-review only** | **github-fetch** + LRU at `reciter/<slug>` (read-only viewers); **scratch** (active reviewer) | Git Data API on debounce (active reviewer) | Same file as completed but on PR branch; flips to HF static after merge |
| `data/recitation_segments/<slug>/detailed.json` | per-reciter, **under-review only** | same | same | |
| `data/recitation_segments/<slug>/edit_history.jsonl` | per-reciter, **under-review only** | same | same | Append-only |
| `data/recitation_segments/<slug>/edit_history_peaks.jsonl` | per-reciter, **under-review only** | same | same | History panel waveform cache; **kept** (read path exists at `/api/seg/history-peaks/<reciter>`) |
| `data/recitation_segments/<slug>/low_confidence_v2.json` | per-reciter, **under-review only** | same | n/a (pipeline-written) | Sidecar; read-only in Inspector |
| `timestamps/<slug>/<chapter>.json.gz` | per-reciter, completed | **HF CDN direct** (browser) | offline pipeline | Already implemented per [`timestamps-tab-deployment-plan.md`](timestamps-tab-deployment-plan.md) |
| `segments/<slug>/<chapter>.json.gz` | per-reciter, completed | **HF CDN direct** (browser, Aligner Space only) | offline pipeline (`--build-segments`) | Slim shards (segments + audio URL only) for the Aligner preload mode; Inspector does not consume these |
| Audio mp3/wav | per-reciter | **origin direct** (browser) | n/a | Backend never touches |
| `data/recitation_segments/<slug>/*.bak` | per-reciter | n/a | discard | `backup_file()` calls removed in deployed save path |
| `validation.log` (per-reciter or root) | dev artifact | n/a | discard | Not shipped |
| `data/qul_downloads/` | dev artifact | n/a | discard | Pipeline input only; excluded from image |
| `data/RECITERS.md`, `data/README.md`, `beam_diff_report.txt` | docs | n/a | discard | Kept in repo, excluded from image |
| `data/.cache/<slug>/canonical_phonemes.pkl` | per-reciter | recompute lazy + JSON re-encode | regenerable | Pickle dropped (Python-version-fragile) |
| `data/.cache/<slug>/audio/` | per-reciter | n/a | discard | Audio proxy gone in deployed |
| `inspector/.cache/<slug>/peaks/` | per-reciter | recompute on demand + browser/CDN cache headers | n/a | No persistent volume; immutable response |

## 3. The github-fetch service

A new module `inspector/services/github_fetch.py`. ~80–120 lines. Replaces the worktree concept entirely. Scope is **only** PR-branch reads for under-review reciters — completed-reciter data is on HF CDN and bypasses this service entirely (browser fetches direct).

### Interface

```python
def fetch_text(slug: str, file: str, ref: str) -> str: ...
def fetch_json(slug: str, file: str, ref: str) -> Any: ...
def fetch_jsonl(slug: str, file: str, ref: str) -> Iterator[dict]: ...
def invalidate(slug: str, file: str | None = None, ref: str | None = None) -> None: ...
```

`file` is repo-relative (e.g. `data/recitation_segments/<slug>/segments.json`). `ref` is a branch name or sha. The service resolves to `https://raw.githubusercontent.com/<owner>/<repo>/<ref>/<file>` and pipes through:

1. **LRU cache (raw bytes)** keyed on `(file, ref)`. Default cap: **128 MB**, **10 MB** per-entry guard. Configurable via `INSPECTOR_FETCH_LRU_BYTES` and `INSPECTOR_FETCH_MAX_ENTRY_BYTES`. Sized for the under-review working set: ~20 in-flight reciters × ~5 files × ~5 MB max ≈ ~100 MB. The original 512 MB / 50 MB-per-entry sizing assumed completed reciters were also served via github-fetch — they're not anymore.
2. **TTL** — `main` ref is ignored by this service (completed reciters are HF static); only `reciter/<slug>` refs cached, **30 seconds** with **±10% jitter** to prevent stampede on cache cold-start. Configurable via `INSPECTOR_FETCH_TTL_BRANCH_SEC`.
3. **Conditional revalidation** with `ETag`/`If-None-Match` — GitHub raw supports it. 304 responses don't burn the GitHub rate-limit budget.
4. **Auth** via the GitHub App installation token. Adds the rate limit headroom of an authenticated client (5,000 req/h) and works for private branches if the repo ever needs that.
5. **Single-flight** (mandatory, not optional) — concurrent requests for the same `(file, ref)` collapse to one upstream call, all callers await the same future. Required to prevent thundering-herd on cold-cache reciters where 10 concurrent viewers would otherwise trigger 10 redundant GitHub fetches and 10 redundant `detailed.json` parses (each up to 5 MB / ~120 ms on the GIL).

### Parsed-cache layer (separate from raw LRU)

A second layer **above** the raw-bytes LRU caches the parsed Python dict / list of each fetched JSON/JSONL file. Keyed on `(slug, file, ref)`. No TTL — invalidate-on-merge via the cache-invalidate webhook (and on-write for the active reviewer's own scratch path). Sized to ~100 MB.

Why two layers: parsing 5 MB JSON via orjson + adapter walk costs ~80-150 ms each; without a parsed cache, every cache-warm read still pays the parse cost on every request because `services/cache.py::_seg` invalidates aggressively today. Parsed-cache TTL is bounded by content hash (the raw-LRU's ETag) — when the upstream bytes change, parsed entries derived from the old bytes are dropped.

### Cache invalidation triggers

- **Squash-merge of `reciter/<slug>`** — `segments-pr-merged.yml` POSTs `/api/internal/cache-invalidate?slug=<slug>` (with a shared secret). Backend drops every cache key matching that slug from both layers.
- **Active reviewer's own commit** — `services/github_commit.py` invalidates the slug's parsed and raw entries after a successful Git Data API commit, so other anonymous viewers see the new state immediately rather than waiting for the 30 s TTL.
- **Manual force-refresh** — admin endpoint `/api/internal/cache-invalidate-all` for emergencies.
- **TTL expiry** — natural backstop.

### Freshness contract

Anonymous viewers see data with bounded staleness depending on reciter state:

| Reciter state | Worst-case staleness | Source |
|---|---|---|
| `completed` (HF static) | Bounded by browser HTTP cache (`max-age` from HF CDN) + cache-invalidate webhook on next merge | HF CDN |
| `under_review`, no active reviewer | 30 s (PR-branch TTL) | github-fetch |
| `under_review`, active reviewer mid-session | **≤ 5 min** (debounce hard cap) + 30 s (TTL) ≈ 5.5 min worst case, typically ≤ 60 s after reviewer pauses | github-fetch reads last-debounce-flushed state on PR branch |
| Just merged | Sub-second if cache-invalidate webhook fires; else 30 s TTL | github-fetch invalidates → HF static next fetch |

The 5-minute under-review staleness bound is a deliberate design point — viewers see committed work, not in-flight typing. Reviewers' typing within the debounce window is private to their scratch dir.

### What this service does NOT do

- It does **not** serve completed-reciter data. Completed reciters are on HF CDN; the browser fetches them directly without backend involvement.
- It does **not** write. Writes go through the dedicated commit pathway in §5.
- It does **not** mediate active-reviewer reads of *their own* slug. The reviewer's session reads from scratch dir, which is materialised once on session start (using github-fetch under the hood for the initial fetch) then mutated locally.
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
| Reviewer claims reciter | Backend creates `<scratch>/<slug>/...`, materialises 5 files via github-fetch at branch ref `reciter/<slug>`, marks dir clean |
| Save POST | Existing `save_seg_data()` runs in-place: atomic write `detailed.json`, rebuild `segments.json`, append `edit_history.jsonl`. Marks dir dirty. Resets debounce timer |
| Debounce fires | Multi-file commit via Git Data API (§5). Marks dir clean |
| Reviewer marks ready | Force-flush, then delete scratch dir (state freezes; future saves return 410) |
| Reviewer unmarks ready | Re-materialise scratch from PR branch (same as fresh claim) |
| Reviewer releases claim / lock expires | Force-flush any pending commits, then delete scratch dir |
| Backend restart with dirty scratch | On boot, check for dirty scratch dirs; flush each as one commit, then delete |

### What lives in scratch but is NOT pushed

- `validation.log` — regenerated on demand
- `.bak` siblings — `backup_file()` calls are removed from the deployed save flow (§5)
- `inspector/.cache/<slug>/peaks/` — peaks are recomputed/cached separately, not pushed

### Scratch is private working state, not a shared cache

Scratch dir holds the active reviewer's in-flight state for the slug they have claimed. **Anyone else reading data for that slug** — other authenticated users, anonymous viewers, the same reviewer browsing a different slug — reads via the standard tier path (HF CDN for completed, github-fetch+LRU for under-review). They see the last-debounce-flushed version on the PR branch, not the live scratch state.

Concrete cases:
- Active reviewer for slug X opens History panel for X → reads `edit_history_peaks.jsonl` from scratch (sees the op they just performed but haven't debounce-flushed yet)
- Same reviewer opens a different slug Y → reads via github-fetch + LRU at `reciter/Y` (Y has its own potential reviewer; this user is just an anonymous viewer of Y's data)
- Anonymous viewer opens History panel for slug X (which has an active reviewer) → reads via github-fetch + LRU at `reciter/X`, which returns the last-debounce-flushed state (≤ 5 min old per the freshness contract in §3)

This avoids any need for a "shared read-only scratch" or for synchronising scratch reads across sessions. The PR branch is the rendezvous point — once debounce flushes, every non-owner reads the same bytes through the LRU.

### Footprint

Per active reviewer: 9–19 MB on disk. With one-reviewer-per-reciter and realistic concurrency (1–10), total scratch occupancy fits comfortably in <250 MB. Ephemeral disk is sufficient — restart loss is bounded by the debounce window (≤5 min) and recoverable by re-fetching from the PR branch on next session.

## 5. Write path

### Git Data API multi-file commit

On debounce-fire, for the dirty scratch dir of slug `<slug>` on branch `reciter/<slug>`:

1. **Read** the 4–5 dirty files from scratch.
2. **Create blobs** — `POST /repos/.../git/blobs` for each file. Returns SHAs.
3. **Get current tree** at the branch tip — `GET /repos/.../git/ref/heads/reciter%2F<slug>` → commit SHA → tree SHA.
4. **Create new tree** — `POST /repos/.../git/trees` with the parent tree SHA + blob entries for each updated path.
5. **Create commit** — `POST /repos/.../git/commits` with:
   - `tree` = new tree SHA
   - `parents` = `[current_commit_sha]`
   - `message` = `[<slug>] [wip] <op summary>` for debounced auto-commits, `[<slug>] <message>` for explicit pushes (e.g. future "Push to PR now" button)
   - `author` = `{ "name": "<gh-login>", "email": "<id>+<gh-login>@users.noreply.github.com" }` (the active reviewer)
   - `committer` = `{ "name": "github-actions[bot]", "email": "..." }` (the App)
6. **Update ref** — `PATCH /repos/.../git/refs/heads/<branch>` with the new commit SHA. `force = false` (fail if the branch moved out from under us).
7. On 422 ref-update conflict: re-fetch base, re-fold the scratch state, retry once. If still conflicting, surface to the reviewer ("branch changed externally; reload to merge").

### Debounce triggers

A commit fires when **any** of:

1. 30 seconds since last save with no further saves
2. 5 minutes since last commit with continuous saves (hard cap)
3. Explicit "Push to PR now" button (UI affordance, future)
4. **Mark-ready transition** (`POST /api/mark-ready/<slug>` flushes before firing `reciter.marked_ready`) — the marked-ready commit must reflect everything the reviewer intends
5. **Release** (`POST /api/release/<slug>` flushes before firing `reciter.released`) — the abandoning reviewer's last edits must land for the next reviewer to continue from
6. Lock release / claim transfer (admin force-release per [`inspector-admin-perms.md`](inspector-admin-perms.md) §5.1 also flushes)
7. `beforeunload` `sendBeacon` from the browser tab
8. Backend graceful shutdown (drains dirty scratch dirs)

Once state transitions to `ready_for_merge`, save endpoints return 410 with "unmark ready first." The scratch dir is destroyed after the mark-ready flush completes — re-acquired on `unmark-ready` via the standard session-start materialisation path.

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
| `INSPECTOR_DATA_DIR` | `/app/data` | repo `data/` (via bind mount to `/data`) | Static reference data location |
| `INSPECTOR_QUA_DATA_PATH` | `/app/data` | `/data` | Linguistic data location read by `services/data_loader.py` (parallel to `INSPECTOR_DATA_DIR`) |
| `INSPECTOR_SCRATCH_DIR` | `/tmp/inspector-scratch` | `/tmp/inspector-scratch` | Per-session writable workspace |
| `INSPECTOR_CACHE_DIR` | `/tmp/inspector-cache` | repo `inspector/.cache/` | Inspector's own peak/canonical-phoneme cache |
| `INSPECTOR_HF_DATASET_REPO` | `hetchyy/quranic-universal-ayahs` | unused | HF dataset hosting completed-reciter Inspector shards |
| `INSPECTOR_HF_DATASET_REVISION` | `main` | unused | HF dataset ref pinned by frontend manifest fetch |
| `INSPECTOR_GITHUB_OWNER`, `INSPECTOR_GITHUB_REPO` | repo coords | unused (local fs) | github-fetch target |
| `INSPECTOR_GITHUB_APP_ID`, `INSPECTOR_GITHUB_APP_PRIVATE_KEY` | secret | unset | Installation token issuance |
| `INSPECTOR_FETCH_LRU_BYTES` | `134217728` (128 MB) | unused | github-fetch raw-bytes cache cap |
| `INSPECTOR_FETCH_MAX_ENTRY_BYTES` | `10485760` (10 MB) | unused | Per-entry size guard — refuse to cache anything bigger |
| `INSPECTOR_PARSED_CACHE_BYTES` | `134217728` (128 MB) | unused | Parsed-cache layer cap (separate from raw LRU) |
| `INSPECTOR_FETCH_TTL_BRANCH_SEC` | `30` | unused | Cache TTL for `reciter/<slug>` refs (jittered ±10%) |
| `INSPECTOR_DEBOUNCE_INACTIVITY_SEC` | `30` | unused | Debounce inactivity window |
| `INSPECTOR_DEBOUNCE_HARDCAP_SEC` | `300` | unused | Hard-cap commit interval |
| `INSPECTOR_INTERNAL_SECRET` | secret | unset | Cache-invalidate webhook auth |
| `INSPECTOR_AUDIO_PROXY_ENABLED` | `0` | `1` | Local mode keeps audio proxy |
| `INSPECTOR_ALLOWED_SLUGS_REGEX` | unset (prod) / `^_test_` (dev Space) | unset | If set, write endpoints reject slugs not matching — used for dev/staging Space isolation |

A single `inspector/config.py` resolution function returns a typed `Config` object so route handlers don't read env vars directly.

`INSPECTOR_FETCH_TTL_MAIN_SEC` is removed — the github-fetch service no longer serves `main`-ref data (completed reciters are on HF static). Any leftover code reading from `main` should be rewritten to read from HF CDN client-side.

## 7. Image build changes

### Build context note

The repo's `inspector/Dockerfile` is built with **repo root as context** (`docker build -f inspector/Dockerfile .`). This means the **root `.dockerignore`** governs exclusion, not `inspector/.dockerignore` — the latter is only honoured when the Dockerfile context is `inspector/` itself. When the Space-repo upload pipeline (see [`inspector-deploy-runbook.md`](inspector-deploy-runbook.md)) restructures the upload tree so the Dockerfile sits at the Space repo root, `.dockerignore` lives at that root in the Space repo (not in the main monorepo).

### ENV defaults flipped to deployed profile

The Dockerfile's runtime stage today defaults `INSPECTOR_DATA_DIR=/data` and `INSPECTOR_QUA_DATA_PATH=/data`, but only `COPY`s the static linguistic files to `/app/data/`. This works in local mode because `docker-compose.yml` mounts `$PWD/data:/data`, but a deployed image without a mount finds nothing.

**Fix:** flip the deployed defaults to `/app/data` for both env vars; local `docker-compose.yml` overrides back to `/data` and bind-mounts the host `data/`. One image, two profiles.

```dockerfile
ENV INSPECTOR_DATA_DIR=/app/data \
    INSPECTOR_QUA_DATA_PATH=/app/data \
    INSPECTOR_TS_SOURCE=huggingface \
    INSPECTOR_AUDIO_PROXY_ENABLED=0 \
    INSPECTOR_CACHE_DIR=/tmp/inspector-cache \
    INSPECTOR_SCRATCH_DIR=/tmp/inspector-scratch
```

`docker-compose.yml`:
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

Add to root `.dockerignore` (or use selective `COPY`):

```
data/audio/                   # superseded by audio_catalog.json.gz (built in)
data/recitation_segments/     # served via HF CDN (completed) / github-fetch (under-review) / scratch (active reviewer)
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
inspector/frontend/src/       # only dist/ ships
inspector/frontend/node_modules/
inspector/tests/
**/__pycache__/
**/.pytest_cache/
```

### Included in Docker image (after the build steps)

```
inspector/                    # code (frontend dist/ only — src/ excluded)
validators/                   # code
scripts/__init__.py
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
data/audio_catalog.json.gz    # NEW — consolidated 391 manifests, compact + gzipped
```

The current Dockerfile only `COPY`s three static files (`qpc_hafs`, `digital_khatt_v2_script`, `phoneme_sub_costs`). Phase 1 extends the COPY list to the full set above.

### Audio catalog build step

A pre-build step (`scripts/build_audio_catalog.py`) consolidates all 391 per-reciter audio manifests under `data/audio/<cat>/<src>/<slug>.json` into one `data/audio_catalog.json.gz`:

1. Walk `data/audio/**/*.json` (skip `SOURCE` text files).
2. For each manifest: parse, drop `_timing` field if present (irrelevant runtime, ~70 KB total), serialize compact (no whitespace).
3. Aggregate into `{ <slug>: <manifest_dict>, ... }`.
4. Gzip the aggregate.

Sizes (measured against current repo state):

| Format | Total |
|---|---|
| Current pretty (sum of 391 files) | 67.3 MB |
| Compact JSON (one file) | 33.0 MB |
| Compact + gzipped | **5.7 MB** |

The script runs once during image build (or on-demand via `make catalog`), output committed to image only — never to the repo. Local Docker mode falls back to reading individual manifests under `INSPECTOR_QUA_DATA_PATH/audio/` if `audio_catalog.json.gz` is absent, so maintainers don't need to rebuild the catalog after editing a single source manifest.

### Resulting image

~89 MB of static data (~80 MB linguistic + ~6 MB audio catalog + ~3 MB controlled vocab/index) + Python deps + Alpine static ffmpeg + frontend dist. Total ~300–400 MB. Image rebuilds only on **code or static-data** changes (audio manifest changes do trigger a rebuild via the catalog regeneration; gate `docker-publish.yml` on a content hash so identical catalog content doesn't republish).

### `.dockerignore` discipline

Add a CI check that diff-fails if any `data/audio/<cat>/`, `data/recitation_segments/`, `data/timestamps/`, `data/qul_downloads/`, `data/.cache/`, `**/*.bak` path appears in the built image. Concretely:

```bash
docker run --rm <image> sh -c '
  find /app/data \( \
    -path "*/recitation_segments/*" -o \
    -path "*/timestamps/*" -o \
    -path "*/qul_downloads/*" -o \
    -path "*/.cache/*" -o \
    -name "*.bak" \
  \) -print | head -1
' | grep -q . && exit 1 || exit 0
```

Should return success (no matches) or fail the build.

## 8. Per-file specifications

For each meaningful per-reciter file, the deployed-mode spec, broken down by reciter state where it matters.

Realistic sizes from disk (14 committed reciters as of writing):

| File | Avg | Largest committed | Notes |
|---|---|---|---|
| `segments.json` | ~340 KB | 386 KB | |
| `detailed.json` | ~4.4 MB | **5.2 MB** (`nasser_alqatami`) | Earlier "max ~33 MB" was wrong — that's the per-reciter dir total |
| `edit_history.jsonl` | ~8 MB | 11.1 MB (`nasser_alqatami`) | |
| `edit_history_peaks.jsonl` | ~1.1 MB | 2.4 MB (`maher_al_meaqli`) | 7 reciters carry it today; will be all reciters going forward |
| `low_confidence_v2.json` | <4 KB | 3.6 KB | |
| Per-reciter dir total | ~12-20 MB | 33 MB (`maher_al_meaqli`) | This is the 33 MB figure that was previously misattributed to `detailed.json` alone |

### `segments.json`

- **Read (completed):** HF CDN → `inspector/segments/<slug>/segments.json.gz`, browser fetches direct.
- **Read (under-review, anonymous viewer):** github-fetch at `reciter/<slug>` ref.
- **Read (active reviewer):** scratch dir.
- **Written by:** `save.py::rebuild_segments_json` on every save; never edited directly.
- **Pushed:** every debounced commit, alongside `detailed.json`. Republished to HF on squash-merge via `--build-inspector-segments`.
- **Acceptance:** completed reciter renders within p99 ≤ 600 ms cold (HF CDN warm-up); under-review reciter within p99 ≤ 800 ms cold via github-fetch, ≤ 50 ms warm.

### `detailed.json`

- Same source matrix as `segments.json`.
- **Size:** typical ~4 MB raw / ~800 KB gzipped on HF; cohort max ~5.2 MB raw / ~1 MB gz.
- **Why per-reciter, not per-chapter:** every Segments-tab read endpoint depends on `load_detailed(slug)` — the existing code loads the whole file (see `inspector/services/data_loader.py:121-144`, `inspector/services/segments_query.py:28`). Refactoring to per-chapter load is non-trivial and out of scope for the deploy. Per-reciter file at ~1 MB gz from HF cold-fetches in <1 s; acceptable.
- **Cache key (under-review only):** `(slug, "detailed.json", ref)` in raw LRU; `(slug, "detailed_parsed", ref)` in parsed-cache.
- **Acceptance:** parsed payload stays under the 10 MB per-entry guard; if a reciter ever exceeds it (none currently approach), the build pipeline must alert.

### `edit_history.jsonl`

- Same source matrix.
- **Append cadence:** one line per save batch (under-review). Pushed in the same commit as the segment files. Republished to HF on merge.
- **Read pattern:** lazy on History panel expand — most anonymous viewers never load it.
- **Schema cleanup (parent §7):** drop `file_hash_after` field, drop genesis record, keep `batch_id` / `schema_version` / `validation_summary_*` / `operations` / `reverts_*`.
- **Acceptance:** validators that read this file (CI-only `validate_edit_history.py`) pass with the new schema.

### `edit_history_peaks.jsonl`

- Same source matrix. **Kept** (the original plan §7 misjudged this — the read path exists at `routes/peaks.py:82` `seg_history_peaks_get` and is wired to the History panel via `tabs/segments/utils/data/reciter-actions.ts:72` and `playback/preview.ts:209`).
- **Append cadence:** one line per op that has peaks payload at save time (FE-driven). Lazy POST during playback for ops with no precomputed peaks.
- **Pushed:** in the same commit as the other history files. Republished to HF on merge.
- **Read pattern:** lazy on History panel expand.
- **Acceptance:** anonymous viewer expanding a History row sees the waveform render without recomputing peaks (p99 ≤ 50 ms warm; ≤ 600 ms cold via HF CDN).

### `low_confidence_v2.json`

- Read-only sidecar. HF static for completed; github-fetch for under-review; scratch for active reviewer.
- **Written by:** offline extraction pipeline only (out of scope for Inspector save flow). Republished to HF on merge.
- **Acceptance:** absence is graceful — Inspector treats missing file as empty set.

### `data/audio_catalog.json.gz` (consolidated audio catalog)

- **Read:** browser fetches once on Audio-tab mount via `/api/static/audio_catalog.json.gz` (Flask static route + `Cache-Control: public, max-age=31536000, immutable; ETag: <build-sha>`).
- **Source:** baked into the Space image at build time from all 391 per-reciter manifests (see §7 audio catalog build step). Does not live on HF — single-tenant Inspector data, doesn't belong in the public dataset.
- **Schema:** `{ "<slug>": { "_meta": {...}, "1:1": "<url>", ... }, ... }` — same per-reciter structure as today, just consolidated and stripped of irrelevant `_timing` field.
- **Pushed:** never. Build-time only.
- **Acceptance:** Audio-tab navigation across reciters does not round-trip the backend per-reciter (one initial fetch, then in-memory).

### `inspector/.cache/<slug>/peaks/<hash>.json`

- **Computed on demand** via `services/peaks.py::compute_segment_peaks` (HTTP Range decode against the audio origin → ffmpeg → peaks).
- **Stored:** disk-backed under `INSPECTOR_CACHE_DIR/<slug>/peaks/` for warm-rescue across requests within one container life. Lost on rebuild; recomputed lazily.
- **Returned with HTTP headers:** `Cache-Control: public, max-age=31536000, immutable; ETag: <hash>`. Browser caches forever; CDN in front of Inspector caches across users.
- **Performance reality:** the doc previously claimed "~50 ms compute" — that's the disk-cache-hit path. **Cold compute is 400–700 ms** (HTTP Range fetch ~150 ms + ffmpeg subprocess fork+decode ~250–500 ms). 10 concurrent scrubbing users hitting cold peaks **saturate the 2 vCPU on free CPU-basic** — see §11.
- **Acceptance:** disk-cache hit <5 ms; cold compute ≤ 700 ms p95; cross-user latency ≤ 50 ms p99 once a CDN sits in front.

## 9. Phased rollout

Maps onto the parent doc's [§10 phased migration](inspector-deployment-plan.md). This doc's scope lands across phases 1, 2, 5a, and 5b:

### Phase 1 — Read-only deploy (anonymous, completed reciters via HF)

**In scope of this doc:**
- **Free-tier perf prerequisites (deploy-blockers):**
  - Replace `app.run()` in `inspector/app.py:180` with `gunicorn -k gthread -w 2 --threads 8` in the Dockerfile CMD. Werkzeug dev server is not production-grade and cannot handle the targeted concurrency.
  - Implement `services/github_fetch.py` with **single-flight** + **parsed-cache layer** + ETag revalidation + 30 s TTL with ±10% jitter (raw-bytes LRU at 128 MB / 10 MB per-entry, parsed cache at 128 MB).
  - Add `Cache-Control: public, max-age=31536000, immutable` headers to `/api/seg/segment-peaks` and `/api/seg/peaks` responses (CDN-front decision deferred until Phase 1 traffic measurement, but headers must be set so the CDN — when added — actually caches).
- Image build:
  - Root `.dockerignore` excludes `data/audio/`, `data/recitation_segments/`, `data/timestamps/`, `data/qul_downloads/`, `data/.cache/`, `inspector/frontend/src/`, `inspector/frontend/node_modules/`.
  - ENV defaults flipped: `INSPECTOR_DATA_DIR=/app/data`, `INSPECTOR_QUA_DATA_PATH=/app/data`, `INSPECTOR_TS_SOURCE=huggingface`, `INSPECTOR_AUDIO_PROXY_ENABLED=0`.
  - COPY list extended to all 10 static `data/*.json` files.
  - `scripts/build_audio_catalog.py` runs at build time to produce `data/audio_catalog.json.gz` (consolidated, compact, gzipped).
- HF dataset extension:
  - `build_reciter.py --build-inspector-segments <slug>` — gzip + upload the 5 per-reciter completed-reciter files under `inspector/segments/<slug>/`. Hash-diff against `manifest.reciters.<slug>._build.inspector_shard_hashes` to skip unchanged uploads (mirrors the existing `--build-timestamps` and `--build-segments` patterns).
  - `sync-dataset.yml` extended with the new build target.
  - One-shot bootstrap: invoke `--build-inspector-segments` for every currently-eligible reciter to seed the dataset.
- Frontend:
  - New `services/segments_hf_client.ts` fetches completed-reciter data direct from HF CDN.
  - `/api/ts/config` extended to return `inspector_shard_url_template` and `globals_url_template` (globals are same-origin, not HF, in deployed mode — collapses one cold-load network hop).
- Backend exclusions:
  - `routes/timestamps.py::ts_validate` deleted from deployed image (no validation panel surface).
  - `routes/audio_proxy.py` and `app.py::serve_audio` excluded (gated by `INSPECTOR_AUDIO_PROXY_ENABLED=0`).

**Out of scope:** PR-branch reads, writes, scratch dir, auth.

**Acceptance:**
- Anonymous user lands on deployed website, segments tab for any completed reciter renders within p99 ≤ 800 ms cold, ≤ 50 ms warm.
- Image ≤ ~400 MB.
- No `data/audio/<cat>/`, `data/recitation_segments/`, `data/timestamps/` paths present in `/app/data` of running container (the `.dockerignore` discipline check passes).
- GitHub rate-limit budget consumed at ≤ 5% per hour under expected anonymous traffic (most reads are HF static; only the future under-review reads will burn budget).
- gunicorn workers handle 6 concurrent cache-warm reads with p95 ≤ 1 s.

### Phase 2 — PR-branch reads (under-review reciters)

**In scope:**
- github-fetch already covers the read path (Phase 1 implemented it for under-review only). Phase 2 wires the routes that need it.
- Reciter state pills wired to `/api/reciter-task/<slug>` (parent doc §6).
- Available + Under-review tabs render their data files via github-fetch at the `reciter/<slug>` ref.
- `editingDisabled` store consumed by every edit-affordance component (writes still 403'd until Phase 5a).

**Acceptance:**
- Under-review reciter renders within p99 ≤ 1.5 s cold via github-fetch, ≤ 50 ms warm (parsed cache hit).
- A push to the PR branch (made externally via CLI) is reflected in the website within 30 s (TTL bound).
- Concurrent burst of 10 anonymous viewers on the same cold under-review reciter triggers exactly **one** GitHub fetch per file (single-flight working).

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
- Save POST during `ready_for_merge` returns 410 cleanly; frontend hides save buttons (per [`inspector-state-management.md`](inspector-state-management.md) §8 `can_edit` predicate).
- Mark-ready triggers a final debounce flush before the dispatch event; the resulting PR-branch tip reflects every save the reviewer made.
- Unmark-ready re-materialises scratch from PR branch tip — no stale local state from a prior session.
- Squash-merge of the PR onto `main` carries `Co-authored-by:` trailer with the reviewer's `<id>+<login>@users.noreply.github.com` email (per [`inspector-auth-claim.md`](inspector-auth-claim.md) §5).

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

### `detailed.json` over 10 MB

Per-entry cache guard caps at 10 MB. Current cohort max is **5.2 MB** raw (the 33 MB figure in earlier drafts was the per-reciter dir total). If a future reciter's `detailed.json` exceeds 10 MB, the cache refuses to store it and every read hits github-fetch — slow and burns rate budget. Worth a CI check that fails if any committed `detailed.json` exceeds 10 MB. Cap can be raised to 25 MB if backend memory budget allows; 256 MB raw LRU + 256 MB parsed cache + ~50 MB heap + ~50 MB static = ~600 MB runtime, still inside HF Spaces 16 GB.

### Backend memory

128 MB raw LRU + 128 MB parsed cache + ~50–100 MB Python heap + ~80 MB resident static data (qpc_hafs + digital_khatt + audio catalog parsed in memory) → ~400 MB runtime. Sized comfortably inside HF Spaces CPU-basic 16 GB and any small Fly.io shape. Two separate caches because:
- Raw LRU is byte-cached for fast re-fetch on parsed-cache eviction
- Parsed cache holds Python dicts/lists ready for service handlers — without it, every request re-parses 5 MB JSON via orjson (~80–150 ms on the GIL)

The raw LRU and parsed cache are deliberately the same size — one parsed entry corresponds to one raw entry, so the bound holds.

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

## 11. Performance budget on free CPU-basic

Sized for HF Spaces CPU-basic (2 vCPU shared, 16 GB RAM, ephemeral disk) targeting ~10 mixed-tab concurrent users.

### Op cost table

Measured / estimated on the target environment:

| Op | Cost | Source / dependency |
|---|---|---|
| Parse `detailed.json` (5 MB) via orjson + adapter walk | **80–150 ms** | `services/data_loader.py:121-144`. orjson parses ~1 GB/s, adapter walks every entry/segment ~30 ms/MB |
| 11-category validator cold (`validate_reciter_segments`) | **300–600 ms** | `services/validation/__init__.py:143`. Pure Python loops: `chapter_validation_counts` × 114 + `_check_structural_errors` + `_build_missing_words` + phoneme canonical lookups |
| Peaks compute, ~30 s segment region, cold | **400–700 ms** wall | `services/peaks.py:245`. HTTP Range fetch ~150 ms + ffmpeg subprocess fork+decode ~250–500 ms (`FFMPEG_TIMEOUT=15`) |
| Peaks compute, disk-cache hit | <5 ms | `services/peaks.py` cache lookup |
| Save flow (active reviewer) | ~500 ms compute + ~600–1500 ms network | atomic write 5 MB ~80 ms + rebuild segments ~50 ms + validation snapshot ~400 ms + history append ~5 ms + Git Data API blob+tree+commit+ref. Debounced — off the user's hot path |
| github-fetch cold (5 MB JSON) | ~200–400 ms | Network + ETag round-trip from raw.githubusercontent.com |
| github-fetch warm (LRU hit, parsed cache hit) | <10 ms | In-memory dict lookup |

### Concurrency ceiling

- **4–6 truly concurrent active users** stay under p95 1 s.
- **10 concurrent works only if cache-warm** — already-parsed `detailed.json`, already-cached peaks. Cold-reciter switch by one user during a scrubbing burst can spike p95 to 2–4 s.
- **First bottleneck is ffmpeg subprocess fork on `/api/seg/segment-peaks`** — the per-segment route runs ffmpeg inline in the request thread (not through the per-reciter ThreadPoolExecutor at `peaks.py:346`, which is the prefetch path). 2 vCPU saturate at ~4–6 concurrent decodes.
- **Second bottleneck is the validator** — 300–600 ms cold per reciter. `/api/seg/trigger-validation` must stay gated to authenticated, lock-holding reviewers; letting an anonymous bot warm 300 reciters' caches is a denial-of-service vector.
- **Memory headroom is comfortable** — ~400 MB runtime vs 16 GB available.

### Top 3 mitigations (ordered by leverage)

1. **gunicorn-gthread w=2 t=8** in the Dockerfile CMD, replacing `app.run()`. Werkzeug dev server is not production-grade. Two worker processes (one per vCPU) × 8 threads each gives proper request scheduling for I/O-bound work and graceful CPU-bound serialization. **Mandatory before public deploy.**
2. **Single-flight + parsed-cache TTL** in `services/github_fetch.py`. Without it, 10 concurrent cold viewers of the same reciter trigger 10 redundant 5 MB GitHub fetches and 10 redundant parses on the GIL. Single-flight collapses to one upstream fetch + one parse; parsed cache keeps subsequent requests at <10 ms.
3. **`Cache-Control: public, max-age=31536000, immutable` on peaks routes**, plus front Inspector with Cloudflare or HF edge cache. Peaks are deterministic per `(audio_url, start_ms, end_ms)`. CDN absorbs scrubbing bursts entirely; backend ffmpeg stays idle except on first global hit per region. This is the single biggest win for the per-segment peaks bottleneck.

### Scaling triggers

When to leave free CPU-basic:

- **p95 latency > 1.5 s for 10+ minutes** under steady load → upgrade to CPU-upgrade (4 vCPU, $0.03/h on HF Spaces) or migrate to Fly.io shared-cpu-2x@2GB.
- **Backend memory > 800 MB sustained** → indicates parsed-cache pressure. Either raise `INSPECTOR_PARSED_CACHE_BYTES` and upgrade RAM, or audit for memory leaks.
- **GitHub rate-limit consumption > 50% per hour** → indicates either bug (TTL not respected, single-flight not working) or genuinely high under-review traffic. Investigate before scaling.
- **More than ~50 active reviewers concurrently** → scratch occupancy + debounce timer count starts pressuring single-VM resources. Move locks to Redis, scale horizontally.

### Out of scope (won't implement until measurement demands)

- Distributed cache (Redis) for parsed entries across multiple backend nodes
- Persistent volume for scratch dirs (current loss bound of ≤5 min is acceptable)
- Async migration (FastAPI/uvicorn) — gunicorn-gthread is sufficient for the targeted scale
- Custom CDN beyond Cloudflare free / HF edge

## TODO

Live measurements once Phase 1 is deployed: actual ms costs against the table above, real GitHub rate budget consumption, real cache hit ratios.
