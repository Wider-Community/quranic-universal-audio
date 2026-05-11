# Inspector v2 Deferred Items

Items consciously punted out of v2 scope. Each entry: *what*, *why deferred*, *what triggers revisit*, *who's affected if we never do it*. Anything not here is either in scope (see other v2 docs) or already implemented.

This is the single canonical home for "we know about it, not now." If a v2 doc says "deferred," it should link here.

---

## D1 — Per-job publish sub-status

**What.** Replace the single `awaiting_timestamps` state with a per-job sub-struct on the published row:

```jsonc
"state": "published",
"jobs": {
  "timestamps": { "status": "done|pending|failed", "job_id": "...", "completed_at": "..." }
}
```

Display state computed from the tuple; `completed` requires the timestamps job done. Each job retried independently, and the structure naturally extends if more publish-time jobs land later.

**Why deferred.** The current single-state model has a real correctness issue (a silent timestamps-refresh failure leaves the slug stuck in `awaiting_timestamps` until a maintainer notices on the dashboard). v2's publish path was simplified to a single async job (D16) which limits the blast radius, but the "stuck" failure mode still exists and is the structural slot a sub-status would fill. We're likely to refactor the publish workflow itself in a later iteration anyway — the per-job sub-status work belongs in that refactor, not as a standalone change now.

**Trigger to revisit.** Whenever the publish workflow gets reworked (HF Jobs API changes, new artifact added to the publish set, or a real silent-failure incident).

**Affected if never done.** Maintainers see "completed" reciters that aren't actually fully published, or `awaiting_timestamps` rows that need manual triage from the dashboard. Recovery is manual via "re-enqueue timestamps". Acceptable risk at the publish cadence (~10/month) and current observability.

**Cross-refs.** [`inspector-state-management.md`](inspector-state-management.md) §4 (current state model), [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md) §3 (publish flow).

---

## D2 — Reciter Requests Space deprecation

**What.** The current Reciter Requests Space (Gradio + FastAPI public intake at `reciter_requests/`) is being decommissioned in v2 cleanup. The Space goes away alongside `forward-to-inspector.yml` and `INSPECTOR_FORWARD_SECRET`. New requests for the v2 transitional period are **GitHub issues** carrying the body marker `<!-- reciter-task: slug=... schema=1 -->`; a maintainer reads the issue and adds the catalog row via `POST /api/admin/catalog/add`.

What's actually deferred here: a **native in-Inspector request flow** — likely a "Request a reciter" button on the Inspector UI that writes the catalog row + initial state directly through the same admin endpoints maintainers use today, with a permission model where anonymous can submit and maintainers approve. See D14 for the Inspector-native intake entry.

**Why deferred.** The native flow is a whole separate work item. Would entail:
- Designing the public-facing request form inside Inspector
- Permission model (anonymous can submit, maintainer approves)
- Migration of existing intake (open issues, Notion pages)

None of v2's other phases require this. The GH issue body marker is the lightweight bridge that lets us decommission the Space immediately while deferring the native UX.

**Trigger to revisit.** After v2 is stable in production AND we have a concrete UX design for the in-Inspector request flow.

**Affected if never done.** Two intake surfaces (Inspector for editing, GH issues + maintainer manual add for new requests). Mild UX inconsistency. No correctness issue.

**Cross-refs.** [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md) §2 (decommissioned workflows), `reciter_requests/` source dir (slated for removal).

---

## D3 — Notifications fan-out

**What.** Outbound user-facing notifications on key events:

| Event | Notify | Channel |
|---|---|---|
| `reciter.claimed` | The claimer | "You started reviewing X" confirmation |
| `reciter.marked_ready` | Maintainers | "Publish queue: X is ready" |
| `reciter.merge_rejected` | The reviewer | "Maintainer asked for changes on X: <reason>" |
| `reciter.published` | Original requester | "Your reciter X is live" |
| `reciter.discarded` | Original requester | "Your reciter X was rejected: <reason>" |

**Why deferred.** Planned feature — depends on knowing the contributor's preferred contact channel (HF inbox? email scraped from HF profile? in-app banner only?), and on the request-tracking system (D2) that links a reciter back to its original requester. Tying both threads together.

**Trigger to revisit.** When a maintainer reports the missing notification is causing real workflow pain (reciters stuck in `marked_ready=1` because nobody knows). Or alongside D2 work.

**Affected if never done.** Reciters can sit in `marked_ready=1` indefinitely until a maintainer happens to check the dashboard. Reviewers don't know their work was rejected until they next visit. Original requesters never hear back. All workable via the admin dashboard "stalled" filter; not a correctness issue.

**Cross-refs.** [`inspector-state-management.md`](inspector-state-management.md) §4 (events vocabulary — these are the trigger sources), [`inspector-admin-perms.md`](inspector-admin-perms.md) §6.3 (stalled-reciter dashboard, the workaround).

---

## D4 — Frontend failure-mode UX

**What.** Concrete UI behavior when each backend data source is unavailable:

- Bucket inaccessible (mount or API) → reciters fail to load — banner + retry?
- HF OAuth callback fails → sign-in broken — what's the fallback?
- Audio origin returns 404 → which reciters are unplayable; how does the Audio tab signal it?
- Catalog read fails → Inspector boots with stale catalog — banner?

**Why deferred.** Each data source already has a happy-path flow defined; the failure-mode design is a UX pass that's worth doing once Phase 1 is live and we can see real error rates. Premature design risks over-engineering for failures that won't happen at our scale.

**Trigger to revisit.** First post-Phase-1 incident OR after 30 days of production where we can quantify real failure rates per source. Whichever comes first.

**Affected if never done.** Inconsistent partial-degradation UX during outages. Users see generic 500 pages instead of "X tab is temporarily unavailable; Y still works." No data loss, just a poor incident experience.

**Cross-refs.** [`inspector-data-storage.md`](inspector-data-storage.md) §10 (current outage notes — too brief).

---

## D5 — Re-edits of completed reciters

**What.** A maintainer re-claims a `completed` reciter (typo fix, audio replacement, schema migration). Inspector restores the bucket WIP entry from the latest `<bucket>/published/<slug>/...` snapshot (server-side copy). State transitions back to `awaiting_review`.

**Why deferred.** No published reciter currently needs a re-edit. Building it pre-emptively would commit us to a `completed → awaiting_review` transition, a re-claim semantics question, and a cache-bust mechanism that may need rework once we have a real use case.

**Pre-work to make later cheap.** When implemented, the response-cache strategy will need a cache-bust mechanism then; in v2, `Cache-Control: public, max-age=86400` (1 day) on inspector segment shards keeps caches fresh enough for re-edits to propagate within a day. Versioned dataset URLs (`v<n>/` segments) and `CURRENT` pointer files are NOT used in v2 (per canonical decision D3) — `published/<slug>/` is overwritten in place when a re-edit lands.

**Trigger to revisit.** First real re-edit request from a maintainer.

**Affected if never done.** Typo fixes on completed reciters require manual maintainer steps: `admin.force_set_state` to set `completed → under_review` (not in the v2 allowed-pairs list, so this would itself need a small extension), copy `published/<slug>/` back to `wip/<slug>/`, edit, republish. Painful but not blocking.

**Cross-refs.** [`inspector-state-management.md`](inspector-state-management.md) §4 (deferred-events list), [`inspector-data-storage.md`](inspector-data-storage.md) §4 (lifecycle).

---

## D6 — Multi-replica scale-out

**What.** Run more than one Space replica (or move to a multi-process setup like `gunicorn -w 2+`). Requires moving every in-memory structure (state_store, per-slug `threading.Lock`, parsed seg cache, role cache) to a shared coordinator: Redis OR bucket-side optimistic concurrency (read-version → write-if-version).

**Why deferred.** v2's whole concurrency model assumes one Python process. `gunicorn -w 1` is a load-bearing assertion enforced at startup ([`inspector-data-storage.md`](inspector-data-storage.md) §7 CMD). Single replica handles the projected ≤25 concurrent active reviewers comfortably. Note that v2 does NOT ship a `revision` column on state rows — OCC is a multi-replica concern that arrives only when we cross this trigger.

**Trigger to revisit.** Any of:
- p95 latency > 1.5 s under steady load (suggests CPU saturation that more vCPU per replica won't fix)
- More than ~25 active reviewers concurrently per replica (lock contention)
- Memory > 800 MB sustained (parsed cache eviction churn)

**Affected if never done.** Single point of failure at the Space level; Space restart drops in-progress sessions (re-auth on rebuild is the user-facing pain).

**Cross-refs.** [`inspector-data-storage.md`](inspector-data-storage.md) §11 scaling triggers.

---

## D7 — In-bucket server-side copy/move

**What.** Inspector's publish path moves files from `<bucket>/wip/<slug>/` to `<bucket>/published/<slug>/`. The preferred shape is a single `copy_files`/`rename` API call inside the bucket; if HF doesn't yet expose that for the bucket-internal pattern we want, the fallback is a download + reupload from inside the running Inspector container (~30 s for ~25 MB).

Either way, both source and destination live in the **same private bucket** — no cross-repo transfer is required. The earlier "bucket → dataset Xet copy" question is obsolete given canonical decision D4 (Inspector reads completed reciter data from the bucket, not from the HF dataset; there is no bucket-to-dataset publish step).

**Why deferred.** Waiting on HF for a clean in-bucket move/rename API. The download + reupload fallback is acceptable at the publish cadence (~10/month).

**Trigger to revisit.** HF announces in-bucket server-side copy/move for the pattern Inspector uses.

**Affected if never done.** ~30 s extra wall time per publish on the synchronous publish path. Acceptable.

**Cross-refs.** [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md) §3 (publish flow), §10 (risks).

---

## D8 — Server-Sent Events for cross-tab state sync

**What.** Inspector pushes state updates over an SSE stream. Other tabs / other users of the same reciter learn about claim / release / publish in real-time, instead of via 30 s polling.

**Why deferred.** Polling at 30 s is sufficient for v2's user count. SSE adds connection-management complexity (keepalive, reconnect, per-replica fan-out) that's not justified at current scale.

**Trigger to revisit.** Reports of "my colleague claimed and I didn't notice for a minute" friction that polling doesn't solve.

**Affected if never done.** Up to 30 s lag for non-active-reviewer tabs to see state changes. Acceptable per the freshness contract.

**Cross-refs.** [`inspector-state-management.md`](inspector-state-management.md) §8 ("No optimistic UI needed" — polling is sufficient).

---

## D9 — Slug rename support

**What.** Allow a reciter's `slug` (and thus URL, dataset path, bucket path) to be renamed.

**Why deferred.** Slugs are immutable in v2. A rename would require: coordinated audit-log entry, catalog edit (with an `aliases[]` row), bucket-path rename inside `wip/` and `published/`, browser cache invalidation, redirect handling for old URLs. The catalog already has the `aliases[]` slot for forward-compat, but the actual rename machinery isn't built.

**Trigger to revisit.** First real rename request from a maintainer (typo discovered post-publish; reciter-name change post-marriage; etc.).

**Affected if never done.** A typo in a slug at creation lives forever. Workaround: discard + re-create with correct slug.

**Cross-refs.** [`inspector-state-management.md`](inspector-state-management.md) §12 (already flagged as deferred).

---

## D10 — Public "your contributions" page

**What.** A public page per HF user surfacing their contribution history (claims made, reciters published, etc.), reading from `<bucket>/audit/<YYYY>-<MM>.jsonl`. Recovers some of the public attribution that v1's per-edit GitHub commit Co-authored-by gave contributors.

**Why deferred.** The audit log lives in the single private bucket per [`inspector-data-storage.md`](inspector-data-storage.md) §3 (it carries PII — `hf_user_id` + `login_at_time` per event). Surfacing per-user contribution data publicly requires either (a) a curated derived feed published to a separate public location, or (b) per-user opt-in. Both need product design.

**Trigger to revisit.** When contributor recognition becomes a friction point (volunteers asking "where do I see my work?").

**Affected if never done.** Contributors get no public-facing footprint for their work. Audit log is the source of truth but maintainer-only.

**Cross-refs.** [`inspector-deployment-plan.md`](inspector-deployment-plan.md) §3 attribution.

---

## D11 — `_failed` lifecycle events

**What.** First-class events for terminal failures: `reciter.alignment_failed`, `reciter.timestamps_failed`, `reciter.timestamps_stale`, `reciter.audio_source_changed`. Today these stalls show up only as "stuck in `awaiting_alignment`" or "stuck in `awaiting_timestamps`" with the dashboard's "stalled" filter as the only signal.

**Why deferred.** Reconciler workflow + admin dashboard "stalled" filter cover the operational need. Adding `_failed` states / events without auto-recovery just means more enum values. Real value comes when paired with auto-recovery (retry pipeline, etc.) which is out of v2 scope.

**Trigger to revisit.** When stuck-state volume exceeds maintainer attention — i.e., when manual triage from the dashboard becomes a bottleneck. Or, naturally, alongside D1 (per-job sub-status), which provides the structural slot for `failed` per-job.

**Affected if never done.** Stuck reciters require manual maintainer triage via the dashboard. Workable at projected volume.

**Cross-refs.** [`inspector-state-management.md`](inspector-state-management.md) §4 (deferred-events list).

---

## D12 — CDN front for Inspector

**What.** Front the Inspector backend with Cloudflare free tier (or HF edge cache). Cold-start cache miss after a deploy currently hits backend reads for every active user's first request; CDN absorbs that.

**Why deferred.** Phase 1 measurement decides. CDN headers are already in place for peaks routes; without measured cold-cache pain, adding a CDN is premature. Note this is even more relevant in v2 than in earlier drafts: per canonical decision D4, all reciter reads (in-flight AND completed) flow through Flask, so a CDN in front of Inspector now caches the completed-reciter path that previously hit HF dataset CDN directly.

**Trigger to revisit.** Phase 1 metrics show p95 cold > 1 s sustained after a deploy.

**Affected if never done.** First user after each deploy pays a cold-cache hit (~200–400 ms extra). Subsequent users hit the parsed seg cache.

**Cross-refs.** [`inspector-deployment-plan.md`](inspector-deployment-plan.md) Open Questions, [`inspector-data-storage.md`](inspector-data-storage.md) §11.

---

## D13 — Bucket archive cutover automation

**What.** The `INSPECTOR_BUCKET_ARCHIVE_POLICY=archive-30d` default keeps `<bucket>/_archive/<slug>/<published_at>/` for 30 days post-publish, then deletes. The 30-day cutover is currently unspecified — manual cleanup or a scheduled HF Job?

**Why deferred.** The 30-day window is more than enough lead time to design and deploy the cleanup mechanism after first-publish lands. Not blocking any phase.

**Trigger to revisit.** First archive directory crosses 30 days post-publish.

**Affected if never done.** Bucket `_archive/` grows without bound. ~15 MB per published reciter; at 10 publishes/month, ~1.8 GB/year. Eventually needs cleanup; not urgent.

**Cross-refs.** [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md) §10.

---

## D14 — Inspector-native reciter-request flow

**What.** A "Request a reciter" surface inside the Inspector UI itself. Anonymous (or signed-in) users submit a request through Inspector; maintainers approve from the admin dashboard; approval writes the catalog row + initial state in the same path the existing admin endpoints use.

This is the longer-term sibling to D2: D2 is about decommissioning the existing Reciter Requests Space (which is happening in v2 cleanup); D14 is about replacing the bridge with a first-class native flow.

**Why deferred.** v2 ships with GH issues + maintainer manual `POST /api/admin/catalog/add` as the lightweight transitional intake. Building the Inspector-native form requires:
- Public-facing form UX (anonymous submission flow, captcha or HF-OAuth-gate decision)
- Maintainer review queue UI
- Permission model for "approve catalog add"
- Migration of any in-flight GH issues to the new flow once it lands

None of these block v2.

**Trigger to revisit.** After v2 stabilizes AND request volume justifies investing in a dedicated flow, OR a maintainer reports the GH-issue intake as a real bottleneck.

**Affected if never done.** New reciter requests live as GH issues forever; maintainer manually triages. Workable; mild operational friction.

**Cross-refs.** [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md) §2 (workflow inventory; the forward webhook is removed in v2 cleanup).

---

## D19 — 14 legacy-pattern test failures from Phase 1 fixture migration

**What.** Phase 1's call-site migration moved per-reciter IO behind `services/data_dir` + the storage backend, and the conftest fixture was rewritten to install a `FilesystemBackend` rooted at `tmp_path`. That brought 138/152 inspector tests green, but 14 tests still fail because they bypass the conftest fixture and bake in legacy patterns:

- `tests/classifier/test_resolved_by_edit.py` (6) — directly `monkeypatch.setattr("services.history_query.RECITATION_SEGMENTS_PATH", tmp_path)` on a module-level constant that no longer exists in `history_query.py`
- `tests/classifier/test_classify_parity.py` (3) — spawn subprocesses that hand-build classifier inputs; need `INSPECTOR_BACKEND=filesystem` + `INSPECTOR_FILESYSTEM_ROOT` env wired into the subprocess and a fixture written under the bucket-shape layout
- `tests/test_audio_meta.py` (4) — write directly to `AUDIO_META_PATH` on the local filesystem (now moved to `<bucket>/catalog/audio_meta.json`)
- `tests/persistence/test_uid_backfill.py::test_uid_deterministic_across_processes` (1) — subprocess hand-builds `<INSPECTOR_DATA_DIR>/recitation_segments/<slug>/detailed.json` and calls `load_detailed`; needs the bucket-shape layout + backend env

**Why deferred.** Each is a small individual rewrite (5–15 min) but compounding to a focused test-cleanup pass. The 138 passing tests cover all critical Phase 1 paths (state machine, storage backend, route smokes, save flow gates). Phase 2 deploy is not blocked — these are unit tests that happen to encode the v1 storage layout in their setup code, not regression tests of the deployed behavior.

**Trigger to revisit.** Either:
- Before Phase 2 deploy if CI gating on a 100% green inspector suite is required for the upload pipeline (pre-push hook from `inspector-deploy.yml`)
- Or opportunistically when the surrounding code area is next touched (e.g. `test_resolved_by_edit.py` gets rewritten when the resolved-by-edit classifier is next modified)

**Affected if never done.** 14 tests stay red. Each remaining failure has a clear "expected behavior under v1 layout" annotation in the test name; ignoring them is low-risk for as long as no one regresses the underlying behavior elsewhere.

**Cross-refs.** [`phases/01-foundation.md`](phases/01-foundation.md) Outcomes log (Tests — partial migration); the commit that left them red is `7dca3422` on `dev`.

---

## D20 — Legacy CDN shards on the dev bucket (timestamps tab + universal aligner Preload)

**What.** The dev bucket `hetchyy/quranic-inspector-bucket-dev` carries a pre-v2 layout at the root:

- `manifest.json.gz` — top-level manifest (~60 KB): `dataset_base_url`, `shard_url_template`, `segments_shard_url_template`, `resources`, `reciters[<slug>] = {audio_category, url_template, riwayah, name_en, name_ar, …}`, `_build`
- `segments/<slug>/<chapter>.json.gz` — per-chapter gzipped segments shards
- `timestamps/<slug>/<chapter>.json.gz` — per-chapter gzipped timestamps shards

Built by `scripts/lib/segments_shards.py` + `scripts/lib/timestamps_shards.py` as a *CDN-format projection* of `data/recitation_segments/<slug>/{segments,detailed}.json` + `data/timestamps/<slug>/timestamps.json`.

**Active consumers (verified):**

- ~~Inspector's deployed timestamps tab when `INSPECTOR_TS_SOURCE=huggingface`.~~ **Removed in Phase 2.** Inspector reads timestamps from `<bucket>/published/<slug>/timestamps/<chapter>.json` via its own backend now (`INSPECTOR_TS_SOURCE=bucket`). Legal `INSPECTOR_TS_SOURCE` values are `local | bucket`; `huggingface` raises at config load.
- **Universal aligner Space (`.local/spaces/quranic_universal_aligner/`) Preload mode** — reads directly from this bucket via `PRELOAD_BUCKET_ID` (defaults to `hetchyy/quranic-inspector-bucket-dev`). `src/preload/manifest_client.py` opens `manifest.json.gz` + shards via `huggingface_hub.hffs`; `repo_loader.py::build_segment_infos` slices the per-chapter segments shard into UI cards. The Preload reciter dropdown, the per-chapter segment cards, and the chapter-audio prewarm all flow from this bucket.

### Schema diff: aligner shards vs v2 `published/<slug>/segments.json`

The aligner shards are **not a slice of `segments.json`** — they're a different shape that the v2 layout doesn't expose:

| Field | Aligner segments shard (`segments/<slug>/<chapter>.json.gz`) | v2 `published/<slug>/segments.json` |
|---|---|---|
| Granularity | One shard **per chapter** | Whole file per reciter |
| Body | `segments[] = [{matched_ref, time_start, time_end, confidence}, …]` (per-segment list) | `{<verse_ref>: [[start_word, end_word, t_from, t_to], …]}` (verse-aggregated tuples) |
| `_meta.audio_url` | Chapter-level URL (by_surah) | Reciter-level only |
| `_meta.audio_urls` | Per-ayah URL map (by_ayah) | Absent — sidecar carries it |
| `_meta.{schema_version, reciter, chapter, audio_category}` | Present | Absent |

The per-segment list with `matched_ref` matches `published/<slug>/detailed.json` entries filtered by chapter, not `segments.json`. Phase 6's `published/<slug>/timestamps/<chapter>.json` *does* land per-chapter and would replace the timestamps shard, but **no v2 path replaces the segments shard** without a per-chapter slice of `detailed.json` (5 MB whole file today). Same conclusion for the per-ayah audio URL map: today it lives in the legacy shard `_meta`, in v2 it lives in `<bucket>/catalog/audio_manifest/<slug>.json` (per-delivery sidecar, populated when bulk probe completes).

### Migration options

- *Option A — keep the shards; rewire the builder.* Read from v2 paths but keep producing the same shard layout. Aligner + TS tab stay as-is. Lowest churn but **two source-of-truth shapes on the same bucket forever**.
- *Option B — clients read v2 paths directly.* Drop the shards. Aligner Preload + Inspector TS tab refactor to read from v2 catalog + sidecars + `published/<slug>/segments.json` + per-chapter `published/<slug>/timestamps/<chapter>.json`. Drop `scripts/lib/{segments,timestamps}_shards.py` + `manifest_client.py`.
- *Option C — Inspector backend serves on-demand shards.* Half-measure; aligner is a standalone HF Space that can't depend on Inspector backend uptime. Rejected.

**Recommendation: Option B.** The shard layout is a v1 artifact that exists because the source data (`data/recitation_segments/<slug>/segments.json` + `data/timestamps/<slug>/timestamps.json`) was repo-tracked + whole-file. v2 already publishes the same content under `<bucket>/published/<slug>/` with the catalog + sidecars carrying the metadata side. Keeping the shards is duplicate state by a different name.

#### Why Option B works

- **Reciter dropdown info** — comes from `<bucket>/catalog/reciter_catalog.json` (`reciters[]` + `deliveries[]` joined on `reciter_id` gives every field the legacy `manifest.reciters[<slug>]` block carried: `name_en`, `name_ar`, `riwayah`, `style`, `audio_category`).
- **Per-chapter audio URL** — comes from the per-delivery sidecar `<bucket>/catalog/audio_manifest/<slug>.json::chapters[<n>].url`. Replaces `manifest.reciters[<slug>].url_template` + the legacy seg shard's `_meta.audio_url` / `_meta.audio_urls`. Covers both `by_surah` and `by_ayah` cleanly (`by_ayah` keys are `"<surah>:<ayah>"`).
- **Segments shape** — the aligner today reads `segments[] = [{matched_ref, time_start, time_end, confidence}, …]`. From v2 `segments.json`:
  - `matched_ref` derives from the verse-ref key + tuple's `[start_word, end_word]` (~5 lines: key `"1:2"` + tuple `[1, 4, 6730, 12280]` → `"1:2:1-1:2:4"`; cross-verse keys are already in the canonical ref shape).
  - `time_start` / `time_end` = `t_from` / `t_to` from the tuple.
  - `confidence` — drop. Aligner Preload UI shows it as a per-card score badge; without it every card renders in high-conf colour. Acceptable UX trade.
- **Whole-file `segments.json` size** — 340 KB avg / 386 KB max (data-storage §8). Cold fetch of the whole file vs cold fetch of a single per-chapter shard (~5–200 KB) is roughly comparable; **warm-cache wins are bigger for whole-file** (one fetch covers the whole reciter). LRU shrinks to per-reciter keys instead of per-(reciter, chapter).
- **Timestamps still per-chapter** — `timestamps.json` whole-file is 5–25 MB per reciter; per-chapter sharding stays. Phase 6 publish pipeline already lands `<bucket>/published/<slug>/timestamps/<chapter>.json` per-chapter via the HF Job. Drop-in for the legacy `timestamps/<slug>/<chapter>.json.gz` after un-gzipping (or keep gzip via `Content-Encoding`).

#### Dependent work (two parallel tracks)

**Track A — universal aligner Preload migration** (owned by the aligner Space):

- `.local/spaces/quranic_universal_aligner/src/preload/manifest_client.py` — replace `_bucket_read("manifest.json.gz")` with a catalog fetch (read `<bucket>/catalog/reciter_catalog.json` + the per-slug sidecar `<bucket>/catalog/audio_manifest/<slug>.json`). Drop the gzipped-shard fetch + LRU; replace with whole-file `<bucket>/published/<slug>/segments.json` (whole-reciter LRU) + per-chapter `<bucket>/published/<slug>/timestamps/<chapter>.json` (per-chapter LRU, same shape as today).
- `.local/spaces/quranic_universal_aligner/src/preload/repo_loader.py::build_segment_infos` — slice the whole-reciter `segments.json` by chapter (filter verse keys), derive `matched_ref` from key + word indices, drop `match_score` from `SegmentInfo`.
- Aligner UI — drop the confidence badge from the card.
- `PRELOAD_BUCKET_ID` env stays; the bucket is the same, only the layout it reads changes.
- **Three cascading dropdowns:** Reciter → Mushaf → Source. Reciter dropdown is always shown (`catalog.reciters[]`, 422 entries, typeahead on `name_en + name_ar`). Mushaf dropdown appears only when group-by `(riwayah, style, recording_year, variant_label)` over the reciter's deliveries gives >1 row; label built from the dimensions that vary inside that reciter ("Hafs Murattal", "Hafs Mujawwad", "Warsh Murattal"). Source dropdown appears only when the selected Mushaf has >1 delivery; user picks the source/channel/bitrate. **No top-level riwayah filter** — the riwayah surfaces inside Mushaf labels. **No auto-pick** — when there's only 1 source, the Source dropdown hides; when there's >1, the user always chooses.

**Track B — Inspector deployed timestamps-tab data layer** (minimal scope — keep current UX):

- Replace the manifest.json.gz fetch with a catalog read served by Inspector backend at `/api/static/catalog.json` (in-memory catalog snapshot via `services/catalog.snapshot()`).
- Frontend `inspector/frontend/src/tabs/timestamps/services/ts_client.ts` — replace `loadManifest()` with `loadCatalog()`. Keep `loadChapterShard()` for now (shards still fetch from the public dataset; their migration to v2 paths is Phase 6 work).
- `routes/timestamps.py::ts_config` — add `catalog_url: "/api/static/catalog.json"` alongside existing `manifest_url` for a soft transition.
- **No cascading dropdowns in the TS tab.** Same flat reciter list the tab has today, just sourced from the catalog instead of the manifest. The Mushaf/Source UX from Track A is aligner-only.
- Track B unblocks the legacy `<bucket>/manifest.json.gz` deletion (since the TS tab no longer reads from there).

**Decommission (Phase 11 cleanup):**

- `scripts/lib/segments_shards.py`, `scripts/lib/timestamps_shards.py` deleted.
- `<bucket>/manifest.json.gz`, `<bucket>/segments/<slug>/`, `<bucket>/timestamps/<slug>/` deleted.
- `INSPECTOR_TS_HF_DATASET_BASE_URL` env var dropped from `inspector/config.py` (no external dataset URL needed).

**Trigger to revisit.** Catalog promotion lands (real `reciters[]` + `deliveries[]` + sidecars in `<bucket>/catalog/`). At that point Track A can start immediately; Track B starts after Phase 6 lands per-chapter timestamps.

**Affected if never done.** Two parallel layouts on the bucket; aligner + Inspector TS tab keep depending on the shard builders being maintained. Not catastrophic, just ongoing tax.

**Cross-refs.** [`phases/01-foundation.md`](phases/01-foundation.md) Outcomes; [`phases/05-publish-pipeline.md`](phases/05-publish-pipeline.md) (Phase 6 lands per-chapter timestamps that unblock Track B); [`phases/11-cleanup-and-docs.md`](phases/11-cleanup-and-docs.md) (decommission step); `inspector/routes/timestamps.py`; `inspector/services/ts_local.py`; `inspector/frontend/src/tabs/timestamps/services/ts_client.ts`; `scripts/lib/{segments,timestamps}_shards.py`; aligner consumer at `.local/spaces/quranic_universal_aligner/src/preload/{manifest_client,repo_loader}.py` (Track A target).

---

## How to add an item to this list

1. Add a new `## D<N> — <title>` section using the template (what / why deferred / trigger to revisit / affected if never done / cross-refs).
2. Update the source doc that mentions it to link here instead of inlining the deferral reasoning.
3. If a deferred item gets picked up: move it out of this doc and update the cross-ref source.
