# Timestamps Tab — Deployment Plan

Companion to `inspector-deployment-plan.md`. Captures the migration strategy for the Timestamps tab specifically, since it is the most data-heavy surface in the Inspector and needs a different read path than the Segments tab.

This revision supersedes the earlier "HF Datasets Server proxy" sketch. The deployed read path is a pure static-CDN model: Inspector fetches gzipped per-chapter JSON shards directly from the existing HF dataset, with no backend code on the hot path.

## Goals

- Stop the eager backend preload of every reciter's timestamps at startup. The current model is unviable at deployed scale (~22 MB per reciter × 300+ reciters → ~7 GB resident before any user shows up).
- Serve word + letter + phoneme timestamps for completed reciters from a stateless, cacheable source.
- Keep audio fetching off the backend's hot path entirely.
- First verse on screen in **<1 s cold**, every subsequent action **instant** for the common cases.
- Local-Docker development continues to work against on-disk JSON files.

## Non-goals

- Backwards-compatible serving of in-progress reciters from the deployed dataset (only completed reciters are on Hugging Face — in-review reciters fall back to the PR-branch worktree, same flow as today's Segments tab).
- Server-side row filtering / random selection. The deployed Inspector picks targets client-side and fetches static files.

## 1. Read-path architecture

| Reciter state | Source | Backend role |
|---|---|---|
| **Completed** | `hetchyy/quranic-universal-ayahs` HF dataset, files served via `https://huggingface.co/datasets/.../resolve/main/timestamps/<reciter>/<chapter>.json.gz` | None on the read path. |
| **Under review** | PR-branch worktree (`reciter/<slug>/segments`) — same as Segments tab | Lazy load + cache, same flow as today |
| **Catalogued / Pending alignment** | n/a | Hidden from the Timestamps tab |

Audio is **not** served by the backend in either case. Browser fetches directly from a URL derived client-side from the reciter's `url_template` (see §3) and the `(surah, ayah)` of the verse being played.

The `/api/ts/*` Flask blueprint stays in the codebase for local-Docker use (`INSPECTOR_TS_SOURCE=local`). When `INSPECTOR_TS_SOURCE=huggingface` (deployed default) **the frontend bypasses it entirely** and talks straight to HF. No backend proxy, no LRU, no cache invalidation.

## 2. Dataset layout — what we publish

Bench results (see `.local/bench/`) drove every choice below.

### 2a. Per-chapter `.json.gz` shards

Each completed reciter publishes 114 files at `timestamps/<reciter>/<chapter>.json.gz` (one per surah they cover; reciters with partial coverage publish fewer). File contents are the same schema as `timestamps_full.json` today, scoped to one chapter:

```jsonc
{
  "_meta": {
    "schema_version": 1,
    "reciter": "<slug>",
    "chapter": <int>,
    "audio_category": "by_surah" | "by_ayah",
    "url_template": "everyayah.com/data/Ghamadi_40kbps/{surah:03d}{ayah:03d}.mp3",
    "padding": "forward",
    "aligner_model": "...",
    "beam": 10
  },
  "1:1": { "verse_start_ms": ..., "verse_end_ms": ..., "words": [[idx, s, e, [[char,s,e],...], [[phone,s,e],...]], ...] },
  "1:2": { ... }
}
```

Why this shape:

- **gzip, not brotli.** Brotli saves ~9% on the wire but `DecompressionStream('gzip')` is native in browsers; brotli requires a JS decoder library. The 9% doesn't pay for ~30 KB of decoder weight.
- **Chapter-sharded, not single-file.** Bench (Sydney → us-east HF CDN, cold cache):

  | Shape | First-paint cold | Same-chapter random | Cross-chapter | Cross-reciter |
  |---|---|---|---|---|
  | Single 5 MB gz | **2.3 s** | 0 ms | 0 ms | 2.3 s |
  | Chapter ~15 KB gz | **0.6 s** | 0 ms (in mem) | 0.6 s (or 0 ms prefetched) | 0.6 s |

  TTFB (~500 ms) dominates everything else for chapter shards — so compression barely matters, but the small files make first-paint and reciter-switch feel instant.

- **`_meta.url_template` per shard** (not per dataset). Self-contained — knowing the chapter file is enough to play audio. Removes the `data/audio/<source>/<reciter>.json` dependency entirely; all 381 reciter manifests in the repo today have a derivable template (verified, see `.local/bench/check_templates.py`).

### 2b. Global resources (one-time fetch per Inspector session)

The Quran word text and the optional Digital Khatt rendering script are global and reciter-independent. They live at the dataset root (no folder prefix — HF has no folder semantics on the CDN, and a `_resources/` prefix only pollutes dataset-viewer search):

```
qpc_hafs.json.gz                       ~3 MB gz, fetched once
digital_khatt_v2_script.json.gz        ~3 MB gz, fetched once
DigitalKhattV2.otf                     ~520 KB, fetched once
```

Browser HTTP caching covers repeat visits (HF's strong ETag → cheap conditional revalidation). One-time cost on first ever Inspector visit per device.

### 2c. Deployment manifest (the catalog file)

A single small JSON published at the root of the dataset:

```
manifest.json.gz                                 ~10–20 KB gz
```

Shape:

```jsonc
{
  "schema_version": 1,
  "generated_at": "2026-05-08T...",
  "commit": "<repo sha at build time>",
  "resources": {
    "qpc_hafs":          "qpc_hafs.json.gz",
    "digital_khatt":     "digital_khatt_v2_script.json.gz",
    "digital_khatt_otf": "DigitalKhattV2.otf"
  },
  "reciters": {
    "saad_al_ghamdi": {
      "name_en": "Saad Al-Ghamdi",
      "name_ar": "سعد الغامدي",
      "riwayah": "hafs_an_asim",
      "style": "murattal",
      "audio_category": "by_ayah",
      "url_template": "everyayah.com/data/Ghamadi_40kbps/{surah:03d}{ayah:03d}.mp3",
      "ts_chapters": [1, 2, 3, ..., 114],
      "ts_built_at": "2026-04-12",
      "validation": {
        "boundary_mismatches": [
          { "verse_key": "37:151", "side": "end", "diff_ms": 612 }
        ]
      },
      "_build": {
        // build-internal — clients ignore. SHA-256 of each gzipped shard,
        // used by --build-timestamps next run to skip unchanged uploads.
        "shard_hashes": { "1": "abc123...", "2": "def456..." }
      }
    },
    ...
  }
}
```

### Why a single manifest, not per-reciter discovery

The user-facing Inspector start cycle is:
1. Open page → need full reciter list for the dropdown → **one manifest fetch covers everything**, ~10 KB gz.
2. Pick a reciter → need chapter list → **already in the manifest's `ts_chapters` field**, no extra fetch.
3. Pick a chapter / random verse → fetch one chapter shard (~15–500 KB gz, ~600 ms cold).

Inlining the chapter list into each ts shard's `_meta` is cute for self-containment but blocks the chapter dropdown until you've already fetched a chapter — bad chicken-and-egg UX.

### Scaling the manifest

The manifest is the seed for any future global metadata the deployed Inspector needs. Per the parent deployment plan, this includes things like:

| Future addition | What it carries | Where it'd land |
|---|---|---|
| Inspector-deployed reciter state (catalogued / pending / available / under-review / completed) | `state`, `pr_number`, `assignee`, `last_state_changed_at` | `reciters.<slug>.state` block. Static for completed reciters; live PR-state still needs the GitHub API for in-review ones, but the static path covers the common case. |
| Segments artifact pointers | `segments_url`, `detailed_url` if those also move to static-CDN later | `reciters.<slug>.segments` block |
| Validation summaries | Pre-computed `mfa_failures` / `missing_words` / `boundary_mismatches` for completed reciters (dropping the runtime validator on the deployed path) | `reciters.<slug>.validation` block |
| Editorial metadata | Editor notes, deprecation flags, etc. | top-level or per-reciter |

The shape choice that protects this: **clients ignore unknown fields**, schema_version bumps signal real breakage. Costs nothing now, scales to anything we want later.

### Why this beats the HF Datasets Server (§previous version)

| | Datasets Server `/rows` (old plan) | Static `.json.gz` shards (new plan) |
|---|---|---|
| Cold per-call latency | 1.5–2 s typical, 7 s outliers | ~0.6 s |
| SLA | None published | Implicit — backed by HF's CloudFront/Xet |
| Backend code on hot path | Proxy + LRU + cache invalidation + token mgmt | Zero |
| Phoneme data | Schema doesn't carry it | Native — same `timestamps_full.json` schema |
| `_meta.mfa_failures` | Lost (dataset is polished output) | Preserved per shard |
| Inspector code path | New `services/timestamps_hf.py` + adapter shim | Frontend `fetch()` |

## 3. Audio URL resolution

Per-reciter `url_template` lives in both the manifest and each shard's `_meta`. Client expansion at playback time:

```ts
function audioUrlFor(template: string, surah: number, ayah: number): string {
  const expanded = template
    .replace('{surah:03d}', String(surah).padStart(3, '0'))
    .replace('{ayah:03d}',  String(ayah).padStart(3, '0'))
    .replace('{surah}',     String(surah));
  return `https://${expanded}`;
}
```

Two patterns cover all 381 manifests in the repo today (verified via `.local/bench/check_templates.py`):
- `by_surah`: `<host>/<reciter_dir>/{surah:03d}.mp3`
- `by_ayah`: `<host>/<reciter_dir>/{surah:03d}{ayah:03d}.mp3`

If a future reciter's URLs don't fit either pattern, `_derive_url_template` returns `""`. In that case `--build-timestamps` inlines the per-verse URL map into each shard's `_meta.audio_urls` (scoped to that chapter's verses only — ~5–15 KB extra per shard for `by_ayah`, trivial for `by_surah`). The map is copied from the existing `data/audio/<source>/<reciter>.json`. Client logic:

```ts
function audioUrlFor(meta, surah, ayah) {
  return meta.url_template
    ? expandTemplate(meta.url_template, surah, ayah)
    : (meta.audio_urls?.[`${surah}:${ayah}`] ?? "");
}
```

The fallback rides the existing chapter-shard fetch — no extra round-trip, doesn't bloat the global manifest, doesn't break the prefetch model (which only knows about chapter shards). Reciters not fitting either path stay viewable on the deployed site.

## 4. Inspector behavior

### 4a. Startup

```
on TimestampsTab mount (deployed mode):
  1. fetch manifest.json.gz (cached forever after first visit) ──┐
  2. fetch qpc_hafs.json.gz (cached forever)                    ├─ in parallel
  3. fetch digital_khatt_v2_script.json.gz (cached forever)     ──┘
  4. populate reciter dropdown from manifest.reciters
  5. if Timestamps tab is active on this load (hash, route, or
     last-tab localStorage):
       ► enter "random any" mode
       ► load random verse + attempt autoplay
       ► if browser blocks autoplay: stay primed-paused, no error
     else:
       ► load random verse + paused
       ► (matches current behavior for non-active tabs)
```

The autoplay-on-active-tab change replaces today's "always paused on first paint." Detection lives at mount time — read the active tab from the URL hash or `LS_KEYS.ACTIVE_TAB` (whichever the existing tab framework uses), and only autoplay when this tab is the one the user is actually looking at on entry.

**Browser autoplay policy.** Page-refresh autoplay can be denied when the browser's Media Engagement Index for the origin is low (e.g. first-time visitor, fresh incognito). The `audio.play()` promise rejects in that case. We swallow the rejection (`.catch(() => {})`) and leave the UI in primed-paused state with the play button highlighted — same effect as today's default for users whose browser denies autoplay.

### 4b. Lookahead prefetch — always

Maintain two pre-rolled candidates regardless of whether the user is in auto-random mode:

```ts
type PreRoll = { reciter: string; chapter: number; verseRef: string; chapterShard: Promise<ChapterDoc> };

let nextRandomSame: PreRoll;  // re-roll within the currently selected reciter
let nextRandomAny:  PreRoll;  // re-roll across all reciters

function reroll() {
  nextRandomSame = pickRandom({ reciter: currentReciter });
  nextRandomAny  = pickRandomAcrossReciters();
  // Fire both fetches in parallel — no waterfall.
  nextRandomSame.chapterShard = fetchChapterShard(nextRandomSame.reciter, nextRandomSame.chapter);
  nextRandomAny.chapterShard  = fetchChapterShard(nextRandomAny.reciter,  nextRandomAny.chapter);
}
```

`reroll()` runs:
- Right after the *current* verse finishes loading (start prefetching for the next click).
- Whenever the user clicks "random same" or "random any" — consume the matching pre-roll, re-roll for the next click.
- Whenever the user changes reciter — `nextRandomSame` is now stale, reroll within the new reciter.

Worst-case in-memory state: **3 chapter shards** (current, prefetched-same, prefetched-any) — 0.5–5 MB depending on chapters touched. The browser HTTP cache holds anything beyond that.

UX outcome:
- "Random same" click → already cached → 0 ms render.
- "Random any" click → already cached → 0 ms render.
- Switch to auto-random mid-playback → first auto-pick is instant.
- The only non-instant path left is "user manually picks a chapter we haven't prefetched" → ~600 ms one-shot.

A small extension worth doing as part of this work: when the user lands on chapter N for sequential listening, also prefetch chapter N+1 in the background. Auto-next across the chapter boundary then feels instant. Cheap — one extra fetch tied to the current `selectedChapter` change.

### 4c. Code to delete

In the deployed `INSPECTOR_TS_SOURCE=huggingface` mode, the following are dead and should be removed (or guarded behind the local-only flag):

- `inspector/services/data_loader.py::load_timestamps` — the eager-or-lazy in-memory loader (kept for local mode).
- `inspector/services/data_loader.py::discover_ts_reciters` 512-byte `_meta.audio_source` peek — the manifest carries this directly.
- `inspector/services/ts_query.py::get_verse_data`'s server-side payload assembly — the browser does this from the shard.
- `routes/timestamps.py` blueprint **on the deployed path**: endpoints `/data/<reciter>/<verse>`, `/random*`, `/verses/<reciter>/<chapter>`, `/chapters/<reciter>` are all dead. `/config` and `/validate/<reciter>` stay (the validate panel is a worktree-mode-only feature per §5).

Frontend: drop `fetchJson('/api/ts/data/...')` etc. in [TimestampsTab.svelte:199](inspector/frontend/src/tabs/timestamps/TimestampsTab.svelte:199) and route through a thin `services/ts_hf.ts` module that fetches manifest + shards and assembles the same `TsDataResponse` shape from the shard slice (the `get_verse_data` logic in [ts_query.py:15](inspector/services/ts_query.py:15) ports cleanly to TS).

## 5. Validation panel on the deployed path

Three categories today, two derivable without `segments.json`:

| Category | Source today | Deployed path |
|---|---|---|
| `mfa_failures` | `_meta.mfa_failures` in `timestamps_full.json` | Preserved in shards' `_meta`. Works. |
| `missing_words` | Coverage check vs `surah_info.json` | Computed client-side (surah_info bundled with the frontend), or pre-computed into manifest. Works. |
| `boundary_mismatches` | Cross-file check against `segments.json` | **Pre-compute at build time**, store in `manifest.reciters.<slug>.validation.boundary_mismatches`. Drops the runtime dependency on `segments.json` for completed reciters. |

Pre-computing the boundary check happens once per release in `build_reciter.py` (the existing validator already produces the data) and ships in the manifest. For in-review reciters, the live worktree path keeps doing it dynamically — no change.

## 6. Sync workflow

Extend `sync-dataset.yml` rather than adding a new workflow. Today it: detects changed reciters from a push diff or workflow_dispatch, builds and uploads each via `build_reciter.py <slug>`, deletes removed ones, rebuilds the `reciters` config catalog.

Add three things:

### 6a. New build target: `build_reciter.py --build-timestamps <slug>`

For one reciter:
1. Load `data/timestamps/by_*_audio/<slug>/timestamps_full.json`.
2. Split by chapter, attach `_meta` (with `url_template` derived via `_derive_url_template`) per shard.
3. Gzip each shard.
4. Compute SHA-256 of each gzipped payload.
5. List existing `timestamps/<slug>/*.json.gz` on HF and their hashes (via `HfApi.list_repo_files` + `hf_hub_download` HEAD-equivalent, or store the hashes in the manifest's per-reciter section to avoid the HEAD round-trips).
6. Upload only the shards whose hash changed; delete shards no longer in the local data (chapters dropped between builds).

This is the "what changed locally + what's on HF → diff" check you asked for. The hash map for "what's on HF" lives in `manifest.json.gz` itself (see §6c) so the workflow doesn't need to crawl the dataset every run.

### 6b. New build target: `build_reciter.py --build-resources`

One-shot uploader for `_resources/qpc_hafs.json.gz`, `_resources/digital_khatt_v2_script.json.gz`, `_resources/DigitalKhattV2.otf`. Idempotent — only uploads if local hash differs from manifest's recorded hash. Runs at the end of every sync cycle.

### 6c. Manifest rebuild — last step, always

After per-reciter timestamps work:

```
build_reciter.py --build-manifest
```

Walks the dataset's `timestamps/` tree to enumerate per-reciter `ts_chapters`, merges in metadata from `data/reciters_index.json` and the local audio manifests' `url_template`, attaches per-reciter shard hash maps (used by §6a's diff check next run), and uploads the result. This step is cheap (~30 KB pushed) and atomicizes the post-state — clients always see a consistent (manifest, shards) pair.

### 6d. Workflow shape

Two trigger modes:

```yaml
on:
  workflow_dispatch:
    inputs:
      reciter:           # blank = full sync (existing field)
      readme_only:       # existing
      timestamps_only:   # NEW — skip segments rebuild, only refresh ts/ + manifest
  push:
    branches: [main]
    paths:
      - 'data/timestamps/**'
      - 'data/audio/**'                # because audio manifests determine url_template
```

Steps:
1. **Detect changed reciters** — same logic as today (`git diff` filter), now also expanding to include reciters whose `data/timestamps/...` changed since the last successful run.
2. **Build + upload reciter (existing)** — `build_reciter.py <slug>` for the verse-row dataset, unchanged.
3. **Build + upload timestamps shards (new)** — `build_reciter.py --build-timestamps <slug>` for each changed slug. Diff against manifest hashes; upload only what changed.
4. **Build + upload resources (new)** — `build_reciter.py --build-resources`. Cheap idempotent step.
5. **Rebuild reciters catalog (existing)** — unchanged.
6. **Rebuild manifest (new)** — `build_reciter.py --build-manifest`. Always last.

The manual-dispatch full-sync path (`reciter: ""`) iterates all eligible reciters through steps 2–4 in sequence. Ad-hoc `timestamps_only=true` skips step 2 for fast resync of just the ts payloads.

### 6e. Local-Docker dev (unchanged)

`INSPECTOR_TS_SOURCE=local` (default in `docker-compose.yml`) keeps the on-disk path: `services/data_loader.py::load_timestamps` reads `data/timestamps/by_*_audio/<reciter>/timestamps_full.json` lazily as today. The startup eager preload + the audio-source byte-peek go away regardless of mode (see also `inspector-deployment-plan.md` §7).

## 7. Phased rollout

This plan delivers the static-shard read path end-to-end (build pipeline + local-mode shard endpoints + frontend) but does **not** flip the deployed default to `huggingface`. The cutover ties to the wider Inspector Fly.io deployment in `inspector-deployment-plan.md` and is owned there.

1. **A — config plumbing.** Add `INSPECTOR_TS_SOURCE` env, extend `/api/ts/config` to return `mode` + `manifest_url` + `shard_url_template`. No behaviour change.

2. **B — local cleanups.** Remove the startup `ThreadPoolExecutor` preload in `inspector/app.py`; drop the `audio_source` 512-byte peek in `discover_ts_reciters`.

3. **C — boundary-mismatch extraction.** Pull the cross-file consistency check out of `validate_reciter()` into a pure `compute_boundary_mismatches()`. Build pipeline reuses it.

4. **D — build pipeline.** `_derive_url_template` already exists. Factor sharding into `scripts/lib/timestamps_shards.py`. Add `--build-timestamps`, `--build-resources`, `--build-manifest` to `build_reciter.py`. One-shot seed + diff-based incremental updates.

5. **E — local-mode shard endpoints + dead-code deletion.** `GET /api/ts/manifest` and `GET /api/ts/shard/<reciter>/<chapter>` reuse the same sharding logic from D. Old verse-by-verse routes (`/reciters`, `/chapters`, `/verses`, `/data`, `/random*`) and their backing loaders (`load_timestamps`, `load_audio_urls`, `discover_ts_reciters`, `services/ts_query.py::get_verse_data`, `_ts`/`_ts_reciters`/`_audio_url` cache slots) all delete in the same commit.

6. **F — frontend.** New `services/ts_client.ts` parameterised by `manifest_url`/`shard_url_template` from `/api/ts/config`. One code path, both modes. `DecompressionStream('gzip')` natively. Lookahead prefetch (current + same + any), autoplay-on-active-tab.

7. **G — CI workflow wiring.** Three new steps in `sync-dataset.yml` (build-timestamps, build-resources, build-manifest) plus a `timestamps_only` workflow_dispatch input.

The deployed default (`INSPECTOR_TS_SOURCE=huggingface` on Fly.io) is deferred to the broader Inspector deployment work.

## Open questions

- **Range-partial shard fetches.** For pathological chapters (Al-Baqarah at ~500 KB gz), HTTP Range with sub-shard slicing could in theory drop first-paint to <300 KB on average. Almost certainly not worth the complexity; flagged in case bench numbers change.
