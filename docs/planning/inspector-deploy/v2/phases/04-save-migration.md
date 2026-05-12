# Phase 4 — Admin overrides

> Maintainers get the four v2 admin override actions (force-release, reassign, force-set-state, send-back). Save migration was pulled into Phase 3. Validator library splits are obsolete — `validators/` was deleted; segments + timestamps validation live inside `inspector/services/validation/`, and the audio-manifest library lives at `scripts/lib/audio_manifest.py`.

**Status:** not started
**Depends on:** Phase 3 (Auth + claim + save) complete
**Blocks:** Phase 5

## Goal

The four admin events ship with reason-required modal UX: `claim.force_released`, `claim.reassigned`, `admin.force_set_state` (narrow allowed pairs only), `reciter.merge_rejected`. Reasons are surfaced in the audit log and visible in the History panel banner. No publish endpoint yet, no admin dashboard UI yet — Phase 7 wires those. Validator library work landed early as a dedicated cleanup (see `inspector-deferred.md` D30).

> **History note.** Phase 3 (originally "Auth + claim") was extended to include the save migration that this phase previously owned. Edit-history schema cleanup (drop `file_hash_after`, drop genesis, add `actor`), the `@require_edit_lock` decorator, the route audit (peaks, audio_proxy), and the `signed_in_client` test fixture all landed in Phase 3. See `phases/03-auth-and-claims.md`.

## Deliverables

### Admin override actions (maintainer+ gated)
- [ ] `POST /api/admin/claim/force-release/<slug>` — `claim.force_released`. Body `{reason}`. Reason ≥ 10 chars. Transitions `under_review → awaiting_review`; clears `assignee_*`. Audit `actor.role = "maintainer"|"owner"` + `payload.original_assignee_hf_id = <former>`.
- [ ] `POST /api/admin/claim/reassign/<slug>` — `claim.reassigned`. Body `{to_login, reason}`. Backend resolves `to_login → hf_user_id` via `/api/admin/users/lookup`. Audit captures both old and new assignee.
- [ ] `POST /api/admin/state/force-set/<slug>` — `admin.force_set_state`. Body `{to_state, reason}`. Narrow allowed pairs only (admin-perms §5.3):
  - `awaiting_alignment ↔ awaiting_review`
  - `awaiting_timestamps ↔ released`
  - `catalogued ↔ awaiting_alignment`
  - `under_review → awaiting_review`
  - Other pairs → 400. `released ↔ completed` is NOT a force-set pair — has dedicated endpoints (`publish-to-dataset` / `remove-from-dataset`) in Phase 7.
- [ ] `POST /api/admin/send-back/<slug>` — `reciter.merge_rejected`. Body `{reason}`. Flips `marked_ready=0`, retains assignee, stays in `under_review`. Reviewer banner shows the maintainer's reason.
- [ ] `POST /api/admin/users/lookup?login=<x>` — HF API proxy for `to_login → hf_user_id` resolution + display preview during reassign.

### Reason-modal UX
- [ ] `inspector/frontend/src/lib/components/AdminReasonModal.svelte` — generic confirm-with-reason modal. Configurable title, danger level, min-chars (default 10).
- [ ] All four admin actions trigger this modal before POST.
- [ ] Audit log "reason" field surfaced in the History panel batch row.

## Out of scope

- Publish endpoint + bucket move + GH dispatch + timestamps job — **Phase 5**.
- `/admin` route + dashboard panels — **Phase 7**.
- All deferred admin events: force-claim, force-clear-assignee, force-unmark-ready, archive/unarchive, pipeline-trigger, job-rerun (see admin §11 deferred list).
- Maintainer edits on `released` / `completed` (`published.edited` flow) — **Phase 7**.
- Save migration + `actor` plumbing — landed in **Phase 3**.
- `validate_edit_history` — deleted entirely (Phase-1 schema change invalidated its core checks); Phase 6 bucket-hygiene starts from scratch if needed.
- `validators/` library split — obsolete; `validators/` was deleted, segments + timestamps validators are in-process in `inspector/services/validation/`, audio-manifest validation moved to `scripts/lib/audio_manifest.py`.

## Acceptance criteria

- [ ] **Force-release:** maintainer force-releases another user's `under_review` claim; row transitions `under_review → awaiting_review`; assignee cleared; audit entry has `actor.role == "maintainer"` and `payload.original_assignee_hf_id == <former>`. Reviewer's open tab learns of the force-release within 30 s (polling).
- [ ] **Reassign:** maintainer reassigns to a different HF login; backend resolves `to_login → hf_user_id` via the HF API; row's `assignee_hf_id` is updated; audit captures both old and new assignee.
- [ ] **Force-set-state:** allowed pairs succeed; disallowed pairs return 400 with the disallowed pair surfaced in the error body.
- [ ] **Send-back:** `under_review` with `marked_ready=1` → maintainer fires send-back → `marked_ready=0`, lifecycle stays `under_review`, assignee retained; reviewer banner shows the maintainer's reason.
- [ ] All four admin endpoints write to the audit log with `actor.hf_user_id`, `actor.login_at_time`, `actor.role`, and `reason ≥ 10 chars`.
- [ ] Reason-modal: empty reason or <10 chars cannot submit (client-side); backend also validates.

## Verification

```bash
SPACE=https://hetchyy-quranic-inspector-dev.hf.space

# Force-release (maintainer cookie)
curl -fsS -X POST -b "$MAINT_COOKIE" -H "Origin: $SPACE" \
  -H "Content-Type: application/json" \
  -d '{"reason": "Reviewer unresponsive 8 days; freeing for next contributor."}' \
  $SPACE/api/admin/claim/force-release/_test_stuck

hf buckets cp hf://buckets/hetchyy/quranic-inspector-bucket-dev/state/reciter_state.json - \
  | jq '.reciters[] | select(.slug=="_test_stuck")'

# Force-set-state allowed-pair check
curl -fsS -X POST -b "$MAINT_COOKIE" -H "Origin: $SPACE" \
  -H "Content-Type: application/json" \
  -d '{"to_state": "released", "reason": "TS job recovery — manually verified."}' \
  $SPACE/api/admin/state/force-set/_test_stuck
# Expect 400 — (awaiting_review, released) not in allowed pairs.

# Send-back
# 1. Reviewer marks ready
# 2. Maintainer POST /api/admin/send-back/<slug> { reason }
# 3. Verify marked_ready=0, assignee retained, audit captures reason
```

## Risks

- **Reassign `to_login → hf_user_id`** — depends on `https://huggingface.co/api/users/<login>/overview` returning 200. If HF API is rate-limited, reassign UI shows "Could not verify login; retry" rather than guessing.
- **Force-set-state allowed-pair drift** — every new pair added needs a state-mgmt §4 entry + transition-matrix update + frontend dropdown extension. Keep the list narrow on purpose.
- **Audit log volume** — Phase 4 adds 4 more event types but no order-of-magnitude change to volume. Still single-file-per-month.

## Reference

- [`inspector-admin-perms.md`](../inspector-admin-perms.md) §5.1, §5.2, §5.3, §5.6 (the four admin actions)
- [`inspector-state-management.md`](../inspector-state-management.md) §4 (transition matrix incl. force-set allowed pairs)
- [`inspector-deploy-runbook.md`](../inspector-deploy-runbook.md) §6 Phase 5 smoke tests
- [`inspector-cleanup-registry.md`](../inspector-cleanup-registry.md) §2 (deletions), §3 (modifications)
