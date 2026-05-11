# Phase 7 — Admin dashboard + cleanup

> The `/admin` route lights up with all dashboard panels (system health, reciters, stalled, recent events, contributor activity, active timestamps refresh) — extending Phase 6's table, activity-feed, detail-page, and `ReciterPicker` widgets with admin-only columns / events / actions. Bucket data hygiene runs weekly. Reciter Requests Space is decommissioned. Contributor docs migrate to "the website is the primary path." Final v2 cleanup ships.

**Status:** not started
**Depends on:** Phase 6 (Public dashboard) complete
**Blocks:** —

## Goal

Maintainers get a single coherent admin surface at `/admin` that **extends** the Phase 6 dashboard widgets — the all-reciters table gains assignee + `marked_ready` + days-in-state columns + quick-action buttons, the activity feed unredacts internal/admin events, the reciter detail page gains assignee history + inline admin action panels — plus admin-only panels (system health, active sessions, active timestamps refresh, contributor activity). The four admin override actions (force-release, reassign, force-set-state, send-back) from Phase 4 are wired into UI affordances. Discard/undiscard ships. The `bucket-data-hygiene.yml` workflow runs weekly, surfacing CRITICAL findings as GitHub issues. Repo `data/` slims to just static reference + roles file. Reciter Requests Space and `forward-to-inspector.yml` go away. Contributor onboarding now points at the website.

## Deliverables

### Phase 6 widget reuse

- [ ] All-reciters table extends Phase 6's table widget — adds `assignee` (login + HF id), `marked_ready`, `days-in-state`, dataset-membership pill, and quick-action buttons columns; same filter / sort / pagination behavior
- [ ] Activity feed extends Phase 6's feed widget — `event_filter='all'` (no public redaction); surfaces every audit event including admin overrides + lifecycle (`claim.force_released`, `claim.reassigned`, `admin.force_set_state`, `reciter.merge_rejected`, `admin.unlocked_for_revision`, `published.edited`, `admin.batch_timestamps_refresh`, `reciter.removed_from_dataset`, `reciter.unpublished`, `reciter.discarded`)
- [ ] Reciter detail page extends Phase 6's `/reciter/<slug>` — adds assignee history strip, **full** internal state timeline (all transitions incl. `awaiting_timestamps` and `released`, not just public-collapsed), dataset-membership badge, inline admin action buttons
- [ ] `ReciterPicker` reused for bulk-action target picker (multi-select mode) — powers batch dataset-publish, batch refresh-timestamps, bulk discard
- [ ] Public state buckets used as filter chip groupings on admin views; admin-only sub-pills distinguish `(under_review, marked_ready=1)` vs `awaiting_timestamps`, and `released` (files+ts ready) vs `completed` (in dataset)

### Admin lifecycle actions (post-publish)

- [ ] `POST /api/admin/publish-to-dataset/<slug>` — `released → completed`; fires `repository_dispatch reciter.dataset_published`; emits `reciter.dataset_published` audit event. Single-reciter and batch (`POST /api/admin/publish-to-dataset` with `{slugs: [...]}`).
- [ ] "Released, pending dataset" panel — lists all `released` reciters; checkbox multi-select + bulk "Add to dataset" toolbar; row-level "Add to dataset" button. Both paths reuse the same endpoint above.
- [ ] `POST /api/admin/unlock/<slug>` — `released | completed → awaiting_review`; **copies** `<bucket>/published/<slug>/` → `<bucket>/wip/<slug>/` (published files retained so public continues seeing the current version); persists `revision_in_progress = {unlocked_from_state, unlocked_at, unlocked_by_hf_id, original_assignee_hf_id}` on the state row; emits `admin.unlocked_for_revision` audit event with reason ≥ 10 chars
- [ ] Public state pill stays `published` while an unlocked reciter is being re-reviewed (the new review work is invisible publicly until next publish); admin views show a "Revision in progress" sub-pill
- [ ] On the next publish of an unlocked reciter, the publish flow reads `revision_in_progress.unlocked_from_state`: if `"completed"`, after `released` the row auto-transitions to `completed` + fires `reciter.dataset_published` (no re-gating); if `"released"`, stays at `released`. `revision_in_progress` is cleared on re-publish.
- [ ] **Direct admin edit on published reciters** — segments-tab save endpoint accepts maintainer+ writes when state ∈ {`released`, `completed`}; writes target `<bucket>/published/<slug>/`; edit-history batch records `actor.role = "maintainer"`; emits `published.edited` audit event per save batch; banner: "You're editing a published reciter — changes apply immediately. Click 'Refresh timestamps' when done."
- [ ] Direct admin edit is **disallowed** during `awaiting_timestamps` (MFA job running); save returns 409 with a clear message
- [ ] `POST /api/admin/refresh-timestamps/<slug>` — re-enqueues the MFA timestamps job for a single reciter; appends the new job id to the state row's `timestamps_job_ids` list; no state change; emits `admin.batch_timestamps_refresh` audit event (single-slug batch)
- [ ] `POST /api/admin/refresh-timestamps` (batch) — accepts `{slugs: [...]}` or filter criteria (e.g. `{riwayah: "hafs"}`); enqueues N HF Jobs; single audit line summarizing the batch (slug list + reason — e.g. "new MFA model v2.1")
- [ ] `POST /api/admin/remove-from-dataset/<slug>` — `completed → released`; dispatches `sync-dataset.yml` rebuild dropping the slug; bucket files retained; emits `reciter.removed_from_dataset` audit event with reason ≥ 10 chars
- [ ] `POST /api/admin/unpublish/<slug>` — full unpublish: `released | completed → awaiting_review`; moves `<bucket>/published/<slug>/` → `<bucket>/wip/<slug>/`; if the slug was in dataset, also dispatches dataset rebuild; emits `reciter.unpublished` audit event; reason-required ≥ 10 chars + typed `unpublish <slug>` confirmation
- [ ] All lifecycle actions surface as inline buttons on the admin reciter detail page + as quick-actions on the all-reciters table; reason modals reuse `ConfirmWithReason.svelte`

### Admin chrome — view-as switcher (owner-only)

> Owners need to inspect how the website looks from non-admin perspectives — a reviewer with an active claim, an anonymous visitor, a regular maintainer without owner privileges — without logging out and in or maintaining a second HF account. This is also the most efficient way to QA Phase 6 / 7 UI changes before a deploy.

- [ ] **Owner-only "View as" dropdown** in the admin chrome (top-right, persistent across all routes). Options:
  - `Owner (default)` — normal owner identity
  - `Anonymous` — request handled as if no session cookie were present
  - `Contributor (synthetic)` — effective `Role.CONTRIBUTOR`, synthetic `hf_user_id` with no assignee history
  - `Maintainer (synthetic)` — effective `Role.MAINTAINER`, synthetic `hf_user_id`
  - `Reviewer: @<login> (<hf_user_id>)` — one entry per **real** `hf_user_id` that has appeared as an assignee in any current or historical `under_review` row (resolved by tail-scan of `<bucket>/audit/<YYYY>-<MM>.jsonl` for `reciter.claimed` events, login cached). This is the production-grade case: owner sees segments-tab edit affordances exactly as that specific reviewer would, including claim banner, mark-ready button, and the "this is your claim" indicator.
- [ ] `POST /api/admin/view-as` — body `{kind: "anonymous"|"contributor"|"maintainer"|"reviewer", hf_user_id?: str}`. Owner-only. Sets a short-lived (≤30 min) session override stored in the signed cookie alongside the real identity. Audit event `admin.view_as_started` with `{kind, target_hf_user_id?}`.
- [ ] `DELETE /api/admin/view-as` — clears the override and restores the owner identity. Audit event `admin.view_as_ended`. Also auto-expires server-side at 30 min.
- [ ] **Reads only — writes hard-blocked while masquerading.** Every mutating endpoint checks `current_session.view_as is not None` and returns 423 Locked with `{error: "Writes disabled while in view-as mode. Exit view-as to mutate."}`. The reason: writes done under masquerade have ambiguous audit attribution — `actor.hf_user_id` could be the real owner or the masquerade target, and conflating the two breaks the per-edit ledger.
- [ ] **Persistent UI banner** while view-as is active: `Viewing as <kind> [<login>]. Writes disabled. [Exit view-as]`. Yellow background, sticky at the top of every page. Banner is rendered server-side (set in the template/SSR context) so it never flashes off during route transitions.
- [ ] **Auth resolution helper** — `services/auth.py::effective_actor(request) -> Actor` consults the session's `view_as` field first; if absent or expired, returns the real actor. Every route's authorization check goes through this helper, so adding view-as is one indirection, not 30 site-wide edits.
- [ ] **Admin tab remains accessible** while masquerading as anonymous/contributor/maintainer/reviewer — the dropdown itself lives there. The masqueraded *view* of the dashboard tab + segments tab + audio tab respects the masquerade; the `/admin` route + chrome stay owner-visible so the owner can exit.
- [ ] **`scripts/inspector_v2_seed/seed_demo_personas.py`** — one-shot helper (dev-bucket only, refuses to run on prod) that:
  - Inserts 2 synthetic maintainer rows (`demo_maintainer_a`, `demo_maintainer_b`) into `<bucket>/access/inspector_roles.json` so `View as maintainer` has a stable target across container restarts
  - For 2 of the 8 `awaiting_review` wip reciters, transitions them to `under_review` via `reciter.claimed` with synthetic contributor `hf_user_id`s (`demo_reviewer_a`, `demo_reviewer_b`) — gives the `View as reviewer` dropdown realistic targets and the assignee strip in the all-reciters table real data to render
  - Idempotent: skips if synthetic personas already present; documents how to wipe them with a single bucket-delete command
  - **Prod safety:** asserts `INSPECTOR_BUCKET_REPO` ends with `-dev` before doing anything; refuses with a clear error otherwise

### Admin route + panels

- [ ] `/admin` route — gated by maintainer+ role; 404 for everyone else (does not flash)
- [ ] Admin dashboard panels per admin-perms §6:
  - 6.1 System health (live-refreshing card; sources from `/api/admin/health`)
  - 6.2 All reciters (sortable, filterable table; columns: slug, state pill, `marked_ready`, days-in-state, assignee, last activity, quick-action buttons)
  - 6.3 Stalled reciters (auto-populated from threshold rules)
  - 6.4 Active sessions (real-time view of in-memory state)
  - 6.5 Active timestamps refresh (per-row tracked `timestamps_job_id` + on-demand status check + manual re-enqueue)
  - 6.6 Recent events log (last 100 from `<bucket>/audit/<YYYY>-<MM>.jsonl`; filterable)
  - 6.7 Contributor activity (last-30-days per-user; derived from audit log)
- [ ] `POST /api/admin/discard/<slug>` + `POST /api/admin/undiscard/<slug>` (only `'public'` and `'discarded'` ship in v2; `'archived'` deferred)
- [ ] `POST /api/admin/catalog/add` + `POST /api/admin/catalog/edit/<slug>` + `POST /api/admin/catalog/vocab/add` (catalog-edit UI surfaces — endpoints already plumbed in Phase 1; UI lands here)
- [ ] `GET /api/admin/health` endpoint returning the schema in admin-perms §6.1
- [ ] `GET /api/admin/audit?limit=100&event=...&slug=...` endpoint (paginated, filterable)
- [ ] Inline admin quick-actions on reciter cards: force-release, reassign, send-back, discard (with reason-required modals)
- [ ] Discard typed-confirmation UX (`lib/components/TypedConfirmation.svelte` requiring "discard <slug>")
- [ ] `lib/components/ConfirmWithReason.svelte` reused across all override actions (≥10-char reason)
- [ ] 6.8 Bulk actions tab (owner-only): bulk discard with 24h soft-lock + typed confirmation + preview list + cancel-by-other-owner
- [ ] `.github/workflows/bucket-data-hygiene.yml` — weekly cron (Sunday 06:00 UTC) + `workflow_dispatch`; runs validators across every reciter in the bucket; opens GH issue for CRITICAL findings; surfaces report in admin dashboard
- [ ] `scripts/jobs/bucket_hygiene.py` — library-call sweep (`validate_segments`, `validate_audio`, `validate_edit_history`, `validate_timestamps`); emits `report.json` + `report.md`
- [ ] `scripts/lib/admin_audit.py::query()` — backs the dashboard's recent-events panel (no `verify_chain()` since the chain is dropped per D12)
- [ ] Reciter Requests Space (`reciter_requests/` source dir) — decommissioned: stop the running Space, archive the source dir, remove `.github/workflows/forward-to-inspector.yml`, remove `INSPECTOR_FORWARD_SECRET` from Space + GH Actions secrets
- [ ] Repo `data/` finalized to slim shape per D8: only `surah_info.json`, `qpc_hafs.json`, `digital_khatt_v2_script.json`, `phoneme_sub_costs.json`, `inspector_roles.json`, `RECITERS.md`, `.release_history.json`, `qul_downloads/`, `.cache/`. Deleted: `reciters_index.json`, `riwayat.json`, `sources.json`, `styles.json`, `audio/`, `.audio_meta.json`, `.audio_durations.json`
- [ ] `inspector/CLAUDE.md` updated for two-mode policy + bucket mount + JSON state file (not SQLite)
- [ ] `data/README.md` updated for slim layout
- [ ] `CLAUDE.md` (project root) updated — drop `find_segments_pr.py` reference, drop `data/audio/` references, point at website as primary contributor path
- [ ] `CONTRIBUTING.md` (or equivalent) — website is the primary path; local Docker is the offline / maintainer fallback
- [ ] `.claude/skills/quranic-universal-audio/references/automations.md` — workflow inventory swept (drop decommissioned workflows; add `inspector-deploy.yml`, `inspector-jobs-deploy.yml`, `bucket-data-hygiene.yml`)
- [ ] `.claude/skills/quranic-universal-audio/references/hpc-and-requests.md` — drop branch convention, drop Reciter Requests Space, document GH-issue intake
- [ ] `.claude/skills/quranic-universal-audio/references/validators.md` — drop file-hash + genesis from `validate_edit_history.py`; document libraries-called-from-services pattern; document `bucket-data-hygiene.yml`
- [ ] `prod` Space cutover: same Dockerfile + bucket setup as dev; first prod publish on a `_test_*` slug to confirm end-to-end

## Out of scope

- Inspector-native reciter-request flow (D14 — explicitly deferred).
- All other deferred admin events (force-claim, force-clear-assignee, force-unmark-ready, force-revision-bump, archive/unarchive, pipeline-trigger, job-rerun).
- Re-edits of completed reciters (D5).
- Slug rename support (D9).
- Notifications fan-out (D3).
- "Your contributions" public page (D10).
- Per-job publish sub-status (D1).
- CDN front for Inspector (D12) — measured in Phase 1; only ship if metrics demand.
- Bucket archive cutover automation (D13).
- SSE for cross-tab sync (D8).
- Multi-replica scaling (D6).

## Acceptance criteria

- [ ] Maintainer hits `/admin` and sees all seven panels rendering with live data; non-maintainer hits `/admin` and gets 404 (no flash).
- [ ] Owner activates `View as → Anonymous`; the segments tab renders without claim buttons, the audio tab renders without admin actions, and the persistent yellow banner is visible on every route. `POST /api/seg/save/...` returns 423 Locked with the writes-disabled message. Owner clicks `Exit view-as`; identity restored, banner gone, writes work again.
- [ ] Owner activates `View as → Reviewer @<demo_reviewer_a>` (a synthetic persona); the segments tab for that reviewer's claimed reciter shows the active-claim banner + edit affordances; the all-reciters table groups the reviewer's claim under "Your active claim". Audit log records `admin.view_as_started` with `target_hf_user_id=demo_reviewer_a`.
- [ ] Owner activates `View as → Maintainer (synthetic)`; the admin tab still loads (chrome stays accessible so owner can exit) but admin-only panels gate to maintainer perms (force-set-state pair set narrowed, no owner-only bulk actions surfaced).
- [ ] Reviewer dropdown lists every `hf_user_id` that has ever been an assignee on a `reciter.claimed` event, sorted by most-recent activity; each row carries the cached login.
- [ ] View-as session override auto-expires at 30 min server-side; subsequent requests behave as the real owner without requiring a logout. `admin.view_as_ended` audit entry stamped with `reason="auto-expired"`.
- [ ] `scripts/inspector_v2_seed/seed_demo_personas.py` refuses to run when `INSPECTOR_BUCKET_REPO` doesn't end with `-dev`.
- [ ] Dashboard p99 ≤ 800 ms.
- [ ] Recent events log displays the last 100 audit entries; filtering by `event` and `slug` works.
- [ ] Contributor activity shows last-30-days per user; clicking a user opens their HF profile.
- [ ] Force-release/reassign/send-back/discard quick-actions on reciter cards trigger the existing endpoints; reason-required modals enforce ≥10-char reasons; discard requires typed `discard <slug>` confirmation.
- [ ] Bulk-discard scheduled by an owner has a 24h soft-lock visible to all owners; another owner can cancel during the window.
- [ ] `bucket-data-hygiene.yml` runs on the next Sunday after deploy; report posted to GH issue if CRITICAL findings; admin dashboard panel shows the latest run summary.
- [ ] `forward-to-inspector.yml` is gone; `INSPECTOR_FORWARD_SECRET` removed from Space + GH Actions secrets; Reciter Requests Space archived (or paused with deprecation banner).
- [ ] Repo `data/` slim verification: `ls data/` shows only the allowed files + dirs from D8.
- [ ] No remaining grep matches in `.claude/skills/` or repo for: `find_segments_pr`, `pr-assignee-sync`, `file_hash_after`, `update-reciter-state.yml`, `forward-to-inspector`, `inspector_owners.json`, `inspector_maintainers.json`, `INSPECTOR_FORWARD_SECRET`, `inspector/segments/<slug>/`, `audio_catalog.json.gz`, `reciter_state.sqlite`, `reciter_catalog.sqlite`, `reciters_index.json`, `data/riwayat.json`, `data/sources.json`, `data/styles.json`, `data/audio/` (or all matches are documented as v1-archive references).
- [ ] All workflows decommissioned in Phase 5 still show no runs in a 7-day observation window after Phase 6 ships.
- [ ] First prod publish on a `_test_*` slug succeeds end-to-end.
- [ ] Contributor docs (CONTRIBUTING.md, CLAUDE.md, project README) point at the website as the primary path.

## Verification

```bash
SPACE=https://hetchyy-quranic-inspector-dev.hf.space

# /admin gating
curl -fsSI -b "session=$ANON" $SPACE/admin   | head -1   # 404
curl -fsSI -b "session=$CONTRIB" $SPACE/admin | head -1  # 404
curl -fsSI -b "session=$MAINT" $SPACE/admin   | head -1  # 200

# View-as switcher (owner-only)
curl -fsS -X POST -b "session=$OWNER" \
  -H "Content-Type: application/json" \
  -d '{"kind":"anonymous"}' \
  $SPACE/api/admin/view-as
# Expect 200; subsequent requests with the same cookie behave anonymously
curl -fsS -X POST -b "session=$OWNER" $SPACE/api/seg/save/saad_al_ghamdi/1 -d '{}'
# Expect 423 Locked: writes disabled in view-as mode
curl -fsS -X DELETE -b "session=$OWNER" $SPACE/api/admin/view-as
# Expect 200; owner identity restored

# Maintainer cannot use view-as
curl -fsS -X POST -b "session=$MAINT" \
  -H "Content-Type: application/json" \
  -d '{"kind":"anonymous"}' \
  $SPACE/api/admin/view-as
# Expect 403

# Dashboard panels
curl -fsS -b "session=$MAINT" $SPACE/api/admin/health | jq
curl -fsS -b "session=$MAINT" $SPACE/api/admin/audit?limit=100 | jq 'length'

# Discard with typed confirmation
curl -fsS -X POST -b "session=$MAINT" \
  -H "Content-Type: application/json" \
  -d '{"reason":"Audio source no longer available; moving on.","confirmation_phrase":"discard _test_bad"}' \
  $SPACE/api/admin/discard/_test_bad

# Bucket-data-hygiene scheduled run
gh run list --workflow bucket-data-hygiene.yml --limit 5
# Expect at least one run in the last 7 days

# Reciter Requests teardown
gh workflow list | grep -v forward-to-inspector || echo "OK: forward-to-inspector.yml gone"
test ! -d reciter_requests   # if archive plan = delete

# Repo slim
ls data/ | sort
# Expect: .audio_durations.json gone, .audio_meta.json gone, RECITERS.md, audio/ gone,
#         digital_khatt_v2_script.json, inspector_roles.json, phoneme_sub_costs.json,
#         qpc_hafs.json, qul_downloads/, .release_history.json, riwayat.json gone,
#         sources.json gone, styles.json gone, surah_info.json

# Stale-reference grep
grep -r "find_segments_pr\|file_hash_after\|update-reciter-state\.yml\|forward-to-inspector\|inspector_owners\.json\|inspector_maintainers\.json\|INSPECTOR_FORWARD_SECRET\|reciter_state\.sqlite\|reciter_catalog\.sqlite\|reciters_index\.json\|data/audio/\|audio_catalog\.json\.gz" \
  .claude/ docs/ inspector/ scripts/ validators/ .github/ 2>/dev/null \
  | grep -v "deferred\|cleanup-registry\|deletion\|dropped\|removed\|gone"
# Expect: no matches (or only matches in archive/explanatory contexts)

# Prod publish smoke
curl -fsS -X POST -b "session=$PROD_MAINT" \
  https://hetchyy-quranic-inspector.hf.space/api/admin/publish/_test_first_prod
# Expect 200 with timestamps_job_id
```

## Risks

- **Dashboard performance at scale** — 300 reciters × 50 maintainers polling every 5 s is duplicate work. Mitigation per admin §13: ETag on `/api/admin/health` + `/api/admin/reciters`; backend caches assembly for 1 s.
- **Bulk-action mistakes** — owner accidentally discards a large batch. Mitigation: 24h soft-lock + typed confirmation + preview list + cancel-by-other-owner.
- **Reciter Requests Space teardown** — existing open issues/Notion pages need triage before the Space goes away. Migration path: maintainer reads each open issue and either acts on it (catalog add) or closes it; document in runbook.
- **Stale references in skills/docs** — easy to miss one. Use the grep verification step before marking complete; the cleanup-registry §7 Phase 6 audit list is the canonical sweep.
- **`bucket-data-hygiene.yml` cost** — weekly run scans every reciter; if reciter count grows 10× this becomes minutes of CI time. Mitigation: chunk by riwayah or by `state` filter; defer until measured.
- **View-as audit ambiguity if writes ever leak through** — every mutating endpoint MUST consult `effective_actor` AND the raw session's `view_as` field separately so a missed check can't silently stamp `actor.hf_user_id = <masquerade target>` while the real owner is the one clicking. Defense in depth: (a) the `view_as` field is checked once at request entry and returns 423 before any handler runs; (b) the `effective_actor` helper returns a sentinel `MasqueradedActor` subclass that any write helper refuses to consume. Audit on suspicious writes during view-as is logged at ERROR level so a regression is visible the same day. The seed personas (`demo_reviewer_a`, etc.) carry an `is_synthetic=true` field in the roles file so audit forensics can filter them out cleanly.
- **View-as in prod is privacy-adjacent** — masquerading as a real reviewer surfaces their queue and their unsaved edits to the owner. Mitigation: every `admin.view_as_started` with `kind=reviewer` is audited with the target's `hf_user_id` so the trail is permanent; the banner makes it impossible to forget you're inside someone else's view; this is owner-only and there are typically 1–2 owners on the project; consider a "View-as audit digest" emailed to the owners group monthly as the volume builds. (Mechanism deferred until measured.)
- **prod cutover** — first prod publish should be on a deliberately-disposable slug. Treat the prod cutover as a separate change window; document expected user-facing 503 during build.

## Reference

- [`inspector-admin-perms.md`](../inspector-admin-perms.md) §5, §6, §7 (entire admin surface)
- [`inspector-deployment-plan.md`](../inspector-deployment-plan.md) §10 Phase 6
- [`inspector-data-storage.md`](../inspector-data-storage.md) §6, §7 — final env config + image discipline
- [`inspector-deploy-runbook.md`](../inspector-deploy-runbook.md) §6 Phase 6, §9 maintenance, §10 phase checklist
- [`inspector-cleanup-registry.md`](../inspector-cleanup-registry.md) §2, §3, §5, §7 Phase 6 — the canonical sweep
- [`inspector-deferred.md`](../inspector-deferred.md) D1–D14 — what is intentionally NOT shipping in v2
