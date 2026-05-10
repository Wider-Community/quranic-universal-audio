# Inspector v2 Deferred Items

Items consciously punted out of v2 scope. Each entry: *what*, *why deferred*, *what triggers revisit*, *who's affected if we never do it*. Anything not here is either in scope (see other v2 docs) or already implemented.

This is the single canonical home for "we know about it, not now." If a v2 doc says "deferred," it should link here.

---

## D1 — Per-job publish sub-status

**What.** Replace the single `awaiting_timestamps` state with a per-job sub-struct on the published row:

```jsonc
"state": "published",
"jobs": {
  "snapshot":   { "status": "done|pending|failed", "job_id": "...", "completed_at": "..." },
  "timestamps": { "status": "...", ... },
  "audio":      { "status": "...", ... }
}
```

Display state computed from the tuple; `completed` requires all three done. Each job retried independently.

**Why deferred.** The current single-state model has a real correctness issue (snapshot or audio failure → state still becomes `completed` driven by timestamps job alone). But we're likely to refactor the publish workflow itself in a later iteration anyway — the per-job sub-status work belongs in that refactor, not as a standalone change now.

**Trigger to revisit.** Whenever the publish workflow gets reworked (HF Jobs API changes, server-side Xet copy lands, new artifact added to the publish set, or a real partial-failure incident).

**Affected if never done.** Maintainers see "completed" reciters that aren't actually fully published. Recovery is manual via admin dashboard. Acceptable risk at the publish cadence (~10/month) and current observability.

**Cross-refs.** [`inspector-state-management.md`](inspector-state-management.md) §4 (current state model), [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md) §3 (publish flow).

---

## D2 — Reciter Requests Space deprecation

**What.** The current Reciter Requests Space (Gradio + FastAPI public intake at `reciter_requests/`) is on its way out. New requests will eventually flow through the Inspector itself — likely a "Request a reciter" button in the Inspector UI that writes the catalog row + initial state directly through the same admin endpoints maintainers use today.

**Why deferred.** Whole separate work item. Would entail:
- Designing the public-facing request form inside Inspector
- Permission model (anonymous can submit, maintainer approves)
- Migration of existing intake (open issues, Notion pages)
- Sunsetting the existing Space (it has its own URL, users may have bookmarked)
- Removing `reciter_requests/` from this repo
- Removing `forward-to-inspector.yml` workflow

None of v2's other phases require this. The forward-webhook is a small piece of operational tape that bridges existing intake into v2 cleanly.

**Trigger to revisit.** After v2 is stable in production AND we have a concrete UX design for the in-Inspector request flow.

**Affected if never done.** Two intake surfaces (Inspector for editing, separate Space for requesting). Mild UX inconsistency. Operational overhead of maintaining a second Space. No correctness issue.

**Cross-refs.** [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md) §4a (forward webhook), `reciter_requests/` source dir.

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

**Trigger to revisit.** When a maintainer reports the missing notification is causing real workflow pain (reciters stuck in `ready_for_merge` because nobody knows). Or alongside D2 work.

**Affected if never done.** Reciters can sit in `ready_for_merge` indefinitely until a maintainer happens to check the dashboard. Reviewers don't know their work was rejected until they next visit. Original requesters never hear back. All workable via the admin dashboard "stalled" filter; not a correctness issue.

**Cross-refs.** [`inspector-state-management.md`](inspector-state-management.md) §4 (events vocabulary — these are the trigger sources), [`inspector-admin-perms.md`](inspector-admin-perms.md) §6.3 (stalled-reciter dashboard, the workaround).

---

## D4 — Frontend failure-mode UX

**What.** Concrete UI behavior when each backend data source is unavailable:

- HF dataset CDN down → completed reciters fail to load — banner + retry?
- Bucket mount inaccessible → in-flight reciters fail — banner + which tab works?
- HF OAuth callback fails → sign-in broken — what's the fallback?
- Audio origin returns 404 → which reciters are unplayable; how does the Audio tab signal it?
- Catalog read fails → Inspector boots with stale catalog — banner?

**Why deferred.** Each data source already has a happy-path flow defined; the failure-mode design is a UX pass that's worth doing once Phase 1 is live and we can see real error rates. Premature design risks over-engineering for failures that won't happen at our scale.

**Trigger to revisit.** First post-Phase-1 incident OR after 30 days of production where we can quantify real failure rates per source. Whichever comes first.

**Affected if never done.** Inconsistent partial-degradation UX during outages. Users see generic 500 pages instead of "X tab is temporarily unavailable; Y still works." No data loss, just a poor incident experience.

**Cross-refs.** [`inspector-data-storage.md`](inspector-data-storage.md) §10 (current outage notes — too brief).

---

## D5 — Re-edits of completed reciters

**What.** A maintainer re-claims a `completed` reciter (typo fix, audio replacement, schema migration). Inspector restores the bucket entry from the latest `inspector/segments/<slug>/...` shards on the dataset (HF Job downloads + extracts). State transitions back to `awaiting_review`.

**Why deferred.** No published reciter currently needs a re-edit. Building it pre-emptively would commit us to a CDN URL versioning scheme + restore HF Job + state-machine `completed → awaiting_review` transition that may need rework once we have a real use case.

**Pre-work to make later cheap.** [Done in v2] CDN URL scheme should already include a publish-version segment (`inspector/segments/<slug>/v<n>/<file>.gz`) so re-edits don't break browser caches with `Cache-Control: immutable`. **Action:** verify [`inspector-data-storage.md`](inspector-data-storage.md) §2 includes the `v<n>/` segment; if not, add it before Phase 1 ships.

**Trigger to revisit.** First real re-edit request from a maintainer.

**Affected if never done.** Typo fixes on completed reciters require admin `state.manual_override` + manual bucket restore via CLI. Painful but not blocking.

**Cross-refs.** [`inspector-state-management.md`](inspector-state-management.md) §4 (deferred-events list), [`inspector-data-storage.md`](inspector-data-storage.md) §4 (lifecycle).

---

## D6 — Multi-replica scale-out

**What.** Run more than one Space replica (or move to a multi-process setup like `gunicorn -w 2+`). Requires moving every in-memory structure (state_store, per-slug mutex, session cache, force-claim leases, parsed seg cache, role cache, pending_jobs map) to a shared coordinator: Redis OR bucket-side optimistic concurrency (read-version → write-if-version).

**Why deferred.** v2's whole concurrency model assumes one Python process. `gunicorn -w 1` is a load-bearing assertion enforced at startup ([`inspector-data-storage.md`](inspector-data-storage.md) §7 CMD). Single replica handles the projected ≤25 concurrent active reviewers comfortably.

**Trigger to revisit.** Any of:
- p95 latency > 1.5 s under steady load (suggests CPU saturation that more vCPU per replica won't fix)
- More than ~25 active reviewers concurrently per replica (mutex contention)
- Memory > 800 MB sustained (parsed cache eviction churn)

**Affected if never done.** Single point of failure at the Space level; Space restart drops force-claim leases and in-progress sessions (re-auth on rebuild is the user-facing pain).

**Cross-refs.** [`inspector-data-storage.md`](inspector-data-storage.md) §11 scaling triggers.

---

## D7 — HF server-side Xet copy bucket → dataset

**What.** Replace the publish snapshot Job's "download from bucket → gzip → upload to dataset" round trip with a single `api.copy_files(...)` call. Per HF docs, "transferring data from a Bucket to a repository (model, dataset, Space) without reuploading is **not yet available, but is on the roadmap**."

**Why deferred.** Waiting on HF.

**Trigger to revisit.** HF announces server-side bucket-to-repo copy availability.

**Affected if never done.** ~30 s extra wall time per publish (download + reupload of ~25 MB). Acceptable.

**Cross-refs.** [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md) §9.

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

**Why deferred.** Slugs are immutable in v2. A rename would require: coordinated audit-log entry, catalog edit, bucket-path rename, dataset republish under new slug, browser cache invalidation, redirect handling for old URLs. Lots of moving pieces for an undemonstrated need.

**Trigger to revisit.** First real rename request from a maintainer (typo discovered post-publish; reciter-name change post-marriage; etc.).

**Affected if never done.** A typo in a slug at creation lives forever. Workaround: discard + re-create with correct slug.

**Cross-refs.** [`inspector-state-management.md`](inspector-state-management.md) §12 (already flagged as deferred).

---

## D10 — Public "your contributions" page

**What.** A public page per HF user surfacing their contribution history (claims made, reciters published, etc.), reading from `<bucket>/state/audit.jsonl`. Recovers some of the public attribution that v1's per-edit GitHub commit Co-authored-by gave contributors.

**Why deferred.** Audit log lives in the **private** metadata bucket per [`inspector-data-storage.md`](inspector-data-storage.md) §3 (it carries PII — login + hf_user_id per event). Surfacing per-user contribution data publicly requires either (a) a curated derived feed published to a separate public location, or (b) per-user opt-in. Both need product design.

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

**Why deferred.** Phase 1 measurement decides. CDN headers are already in place for peaks routes; without measured cold-cache pain, adding a CDN is premature.

**Trigger to revisit.** Phase 1 metrics show p95 cold > 1 s sustained after a deploy.

**Affected if never done.** First user after each deploy pays a cold-cache hit (~200–400 ms extra). Subsequent users hit the parsed seg cache.

**Cross-refs.** [`inspector-deployment-plan.md`](inspector-deployment-plan.md) Open Questions, [`inspector-data-storage.md`](inspector-data-storage.md) §11.

---

## D13 — Bucket archive cutover automation

**What.** The `INSPECTOR_BUCKET_ARCHIVE_POLICY=archive-30d` default keeps `<bucket>/_archive/<slug>/<published_at>/` for 30 days post-publish, then deletes. The 30-day cutover is currently unspecified — manual cleanup or a scheduled HF Job?

**Why deferred.** The 30-day window is more than enough lead time to design and deploy the cleanup mechanism after first-publish lands. Not blocking any phase.

**Trigger to revisit.** First archive directory crosses 30 days post-publish.

**Affected if never done.** Bucket `_archive/` grows without bound. ~15 MB per published reciter; at 10 publishes/month, ~1.8 GB/year. Eventually needs cleanup; not urgent.

**Cross-refs.** [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md) §11.

---

## How to add an item to this list

1. Add a new `## D<N> — <title>` section using the template (what / why deferred / trigger to revisit / affected if never done / cross-refs).
2. Update the source doc that mentions it to link here instead of inlining the deferral reasoning.
3. If a deferred item gets picked up: move it out of this doc and update the cross-ref source.
