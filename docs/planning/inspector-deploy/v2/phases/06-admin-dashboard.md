# Phase 6 — Admin dashboard + cleanup

> The `/admin` route lights up with all dashboard panels (system health, reciters, stalled, recent events, contributor activity, active timestamps refresh). Bucket data hygiene runs weekly. Reciter Requests Space is decommissioned. Contributor docs migrate to "the website is the primary path." Final v2 cleanup ships.

**Status:** not started
**Depends on:** Phase 5 (Publish pipeline) complete
**Blocks:** —

## Goal

Maintainers get a single coherent admin surface at `/admin` with all the read-only views (sourced from bucket state + audit log + in-memory caches) plus the four admin override actions (force-release, reassign, force-set-state, send-back) wired into UI affordances. Discard/undiscard ships. The `bucket-data-hygiene.yml` workflow runs weekly, surfacing CRITICAL findings as GitHub issues. Repo `data/` slims to just static reference + roles file. Reciter Requests Space and `forward-to-inspector.yml` go away. Contributor onboarding now points at the website.

## Deliverables

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
- **prod cutover** — first prod publish should be on a deliberately-disposable slug. Treat the prod cutover as a separate change window; document expected user-facing 503 during build.

## Reference

- [`inspector-admin-perms.md`](../inspector-admin-perms.md) §5, §6, §7 (entire admin surface)
- [`inspector-deployment-plan.md`](../inspector-deployment-plan.md) §10 Phase 6
- [`inspector-data-storage.md`](../inspector-data-storage.md) §6, §7 — final env config + image discipline
- [`inspector-deploy-runbook.md`](../inspector-deploy-runbook.md) §6 Phase 6, §9 maintenance, §10 phase checklist
- [`inspector-cleanup-registry.md`](../inspector-cleanup-registry.md) §2, §3, §5, §7 Phase 6 — the canonical sweep
- [`inspector-deferred.md`](../inspector-deferred.md) D1–D14 — what is intentionally NOT shipping in v2
