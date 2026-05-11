# Phase 4 — Save migration + admin actions

> Active claim-holders can edit reciters end-to-end against the bucket. Edit-history schema is cleaned up. Maintainers get the four v2 admin override actions (force-release, reassign, force-set-state, send-back). Validators run as libraries on every save.

**Status:** not started
**Depends on:** Phase 3 (Auth + claim flow) complete
**Blocks:** Phase 5

## Goal

Save flow points at `<bucket>/wip/<slug>/...` via the resolver. Atomic write + per-save `huggingface_hub.upload_file()` provides durability across container rebuilds. Edit history drops `file_hash_after`, drops genesis records, gains a per-batch `actor: {hf_user_id, login_at_time, role}` block. Validators (`validate_segments`, `validate_audio`, `validate_edit_history`, `validate_timestamps`) are called as library functions from `services/save.py` and `services/catalog.py` on every relevant write. The four admin events ship: `claim.force_released`, `claim.reassigned`, `admin.force_set_state` (narrow allowed pairs only), `reciter.merge_rejected`. No publish endpoint yet, no admin dashboard UI yet.

## Deliverables

- [ ] `inspector/services/save.py` — uses `data_dir.resolve(slug)`; deployed mode resolves to `<bucket>/wip/<slug>/`
- [ ] `inspector/services/save.py` — drops `file_hash_after` writes in `_persist_and_record` and the revert-record path
- [ ] `inspector/services/save.py` — drops `backup_file()` calls in deployed save path (`audit/` is the recovery surface)
- [ ] `inspector/services/save.py` — drops genesis-record write in `_init_history`
- [ ] `inspector/services/save.py` — adds `actor: {hf_user_id, login_at_time, role}` to every batch written to `edit_history.jsonl`
- [ ] `inspector/services/save.py` — calls `huggingface_hub.upload_file()` per affected file when `INSPECTOR_FORCE_FLUSH_ON_SAVE=1` (default in deployed mode)
- [ ] `inspector/services/save.py` — calls `validate_segments` and `validate_edit_history` library functions inline; surfaces results in the response
- [ ] `inspector/services/undo.py` — same path indirection + drop `file_hash_after` writes
- [ ] `validators/validate_edit_history.py` — drop `check_file_hash` + `check_genesis_record`; library entry point + thin CLI wrapper
- [ ] `validators/validate_segments.py` — library entry point + thin CLI wrapper
- [ ] `validators/validate_audio.py` — library entry point + thin CLI wrapper
- [ ] `validators/validate_timestamps.py` — library entry point + thin CLI wrapper
- [ ] `inspector/utils/io.py::file_sha256` — deleted (last caller was the dropped chain)
- [ ] `seg_save_chart` route + `analysis/*.png` writes — deleted
- [ ] Save endpoint gated by `@require_edit_lock`: `POST /api/seg/save/<reciter>/<chapter>` accepts only when `assignee_hf_id == user.hf_user_id` and `marked_ready == false`
- [ ] Save endpoint returns 410 when reciter is `under_review` with `marked_ready=1`
- [ ] Admin endpoints (maintainer+ gated):
  - `POST /api/admin/claim/force-release/<slug>` — `claim.force_released`
  - `POST /api/admin/claim/reassign/<slug>` — `claim.reassigned`
  - `POST /api/admin/state/force-set/<slug>` — `admin.force_set_state` (narrow allowed pairs only — see admin §5.3)
  - `POST /api/admin/send-back/<slug>` — `reciter.merge_rejected` (flips `marked_ready=0`, retains assignee)
- [ ] `POST /api/admin/users/lookup?login=<x>` — proxy to HF API for `to_login → hf_user_id` resolution + display preview during reassign
- [ ] Reason-required modal UX for the four admin actions (all reasons ≥ 10 chars; surfaced in audit)
- [ ] Frontend `editingDisabled` derived store flips to `false` for the active reviewer; History panel undo buttons unlocked
- [ ] `INSPECTOR_FORCE_FLUSH_ON_SAVE=1` set as default in deployed Dockerfile ENV
- [ ] Migration: copy any existing in-flight `data/recitation_segments/<slug>/` files into the dev bucket's flat `wip/<slug>/` layout (one-shot)

## Out of scope

- Publish endpoint + bucket move + GH dispatch + timestamps job — Phase 5.
- `/admin` route + dashboard panels — Phase 7.
- All deferred admin events: force-claim, force-clear-assignee, force-unmark-ready, archive/unarchive, pipeline-trigger, job-rerun (see admin §11 deferred list).
- HF dataset publishing — gone for good per D4.

## Acceptance criteria

- [ ] A signed-in volunteer reviewer claims a `_test_*` reciter, edits a segment (trim, split, merge, or delete), and the change is visible to a second viewer's browser within seconds (force-flush eliminates the 30 s mount window for save-data).
- [ ] Save POST returns 200 with the new state; bucket has the latest `detailed.json`, `segments.json`, `edit_history.jsonl` within seconds (verify via `hf buckets cp`).
- [ ] New `edit_history.jsonl` lines have **no `file_hash_after`**, **no genesis record**, and carry an `actor: {hf_user_id, login_at_time, role}` block per batch.
- [ ] Existing on-disk `edit_history.jsonl` files (with old genesis + hash chain schema) still parse correctly via `parse_history_file` — no migration script needed.
- [ ] Save POST during `(under_review, marked_ready=1)` returns 410 with a clear message ("Reciter is frozen for publish review").
- [ ] Backend container restart mid-edit: bucket has the last-saved state intact (force-flush guarantees); only typing since the last save is lost.
- [ ] Validator findings appear inline in the save response; `bucket-data-hygiene.yml` is NOT yet running (lands in Phase 6).
- [ ] Force-release: maintainer force-releases another user's `under_review` claim; row transitions `under_review → awaiting_review`; assignee cleared; audit entry has `actor.role == "maintainer"` and `original_assignee_hf_id == <former assignee>`.
- [ ] Reassign: maintainer reassigns to a different HF login; backend resolves `to_login → hf_user_id` via the HF API; row's `assignee_hf_id` is updated; audit captures both old and new assignee.
- [ ] Force-set-state: maintainer transitions `awaiting_alignment ↔ awaiting_review` and `awaiting_timestamps ↔ released` and `catalogued ↔ awaiting_alignment` and `under_review → awaiting_review`. Other pairs return 400. (`released ↔ completed` has its own dedicated endpoints — `publish-to-dataset` / `remove-from-dataset` in Phase 7 — so it is not a force-set pair.)
- [ ] Send-back: `under_review` with `marked_ready=1` → maintainer fires send-back → `marked_ready=0`, lifecycle stays `under_review`, assignee retained; reviewer banner shows the maintainer's reason.
- [ ] All four admin endpoints write to the audit log with `actor.hf_user_id`, `actor.login_at_time`, `actor.role`, and a `reason` ≥ 10 chars.

## Verification

```bash
SPACE=https://hetchyy-quranic-inspector-dev.hf.space

# 1. Volunteer end-to-end (manual; in browser)
#    - Sign in as test contributor
#    - Claim _test_round_trip
#    - Trim a segment in chapter 1
#    - Verify save 200, banner reflects updated state

# 2. Bucket round-trip
hf buckets cp \
    hf://buckets/hetchyy/quranic-inspector-bucket-dev/wip/_test_round_trip/edit_history.jsonl - \
  | tail -1 | jq
# Expect actor block; no file_hash_after; no genesis record on the latest line

# 3. Force-release (maintainer cookie)
curl -fsS -X POST -b "session=$MAINT_COOKIE" \
  -H "Content-Type: application/json" \
  -d '{"reason": "Reviewer unresponsive 8 days; freeing for next contributor."}' \
  $SPACE/api/admin/claim/force-release/_test_stuck

# Verify state row
hf buckets cp \
    hf://buckets/hetchyy/quranic-inspector-bucket-dev/state/reciter_state.json - \
  | jq '.reciters[] | select(.slug == "_test_stuck")'
# Expect state: "awaiting_review", assignee_hf_id: null

# 4. Force-set-state allowed-pair check
curl -fsS -X POST -b "session=$MAINT_COOKIE" \
  -H "Content-Type: application/json" \
  -d '{"to_state": "released", "reason": "TS job recovery — manually verified output."}' \
  $SPACE/api/admin/state/force-set/_test_stuck
# Expect 400 — (awaiting_review, released) is NOT in the allowed-pairs list

# 5. Frozen save
curl -fsS -X POST -b "session=$REVIEWER_COOKIE" \
  -H "Content-Type: application/json" -d '{"ops": []}' \
  $SPACE/api/seg/save/_test_marked_ready/1
# Expect 410

# 6. Mixed-schema reading
hf buckets cp \
    hf://buckets/hetchyy/quranic-inspector-bucket-dev/wip/<existing_slug>/edit_history.jsonl - \
  | jq -s 'length'  # has older v1 records (genesis + file_hash_after)
# Inspector should still parse and render the History panel.
```

## Risks

- **Two on-disk `edit_history.jsonl` schemas coexist** for the migration window — old records have genesis + `file_hash_after`; new records have neither + an `actor` block. Backend `parse_history_file` is already tolerant; verify with the existing-slug test above.
- **Validator latency on every save** — `validate_segments` cold cost is 300–600 ms (data-storage §11). On free-tier CPU this could double save round-trip. Measure in Phase 4; if the p95 is bad, gate `validate_segments` to "delta-only" runs (only re-validate touched segments) before Phase 5.
- **`huggingface_hub.upload_file()` per save** — adds network round-trip per save. Save flow target is "edits visible within seconds"; if `upload_file()` p95 is >2 s, force-flush becomes user-noticeable. Measure; if bad, drop to mount-flush + periodic upload.
- **Reassign `to_login → hf_user_id`** — depends on `https://huggingface.co/api/users/<login>/overview` returning 200. If HF API is rate-limited, reassign UI shows "Could not verify login; retry" rather than guessing.

## Reference

- [`inspector-data-storage.md`](../inspector-data-storage.md) §5 (save flow), §6 (env vars)
- [`inspector-deployment-plan.md`](../inspector-deployment-plan.md) §7 (edit-history simplifications)
- [`inspector-state-management.md`](../inspector-state-management.md) §4 (transition matrix incl. force-set allowed pairs)
- [`inspector-admin-perms.md`](../inspector-admin-perms.md) §5.1, §5.2, §5.3, §5.6 (the four admin actions)
- [`inspector-deploy-runbook.md`](../inspector-deploy-runbook.md) §6 Phase 5 smoke tests
- [`inspector-cleanup-registry.md`](../inspector-cleanup-registry.md) §2 (deletions), §3 (modifications)
