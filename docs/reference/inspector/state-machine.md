# State Machine

Lifecycle phase + two orthogonal columns.

## Lifecycle states (column: `state`)

```
catalogued → awaiting_alignment → awaiting_review → under_review → awaiting_timestamps → released → completed
```

| State | Editable? | Required | Notes |
|---|---|---|---|
| `catalogued` | No | — | In catalog. No alignment yet. |
| `awaiting_alignment` | No | — | Pipeline running. |
| `awaiting_review` | No (claimable) | — | Alignment done. Bucket entry exists. No claim. |
| `under_review` | Yes (assignee, when `marked_ready=0`) | `assignee_hf_id`, `assignee_login`, `assignee_since` | Claimed. |
| `awaiting_timestamps` | No | — | Publish bucket move done. TS Job pending. |
| `released` | No (maintainer-only direct-edit) | — | Files + timestamps ready on bucket; visible publicly via Inspector but **not yet** in HF dataset. |
| `completed` | No (maintainer-only direct-edit) | — | Also published to HF dataset. |

## Orthogonal columns

| Column | Type | Meaning |
|---|---|---|
| `marked_ready` | bool | When `state=under_review` and `marked_ready=1`: edits frozen, awaiting maintainer publish. Reviewer can flip back to `0`. |
| `visibility` | enum | `public` (default) / `discarded` (hidden, any state). `archived` is **deferred** (only `public` and `discarded` ship in v2). |
| `timestamps_job_ids` | list[str] | Append-on-refresh — every MFA timestamps job dispatched for this slug. |
| `revision_in_progress` | sub-struct \| null | Set on `admin.unlocked_for_revision`, cleared on re-publish. Carries `unlocked_from_state` (`released` or `completed`), `unlocked_at`, `unlocked_by_hf_id`, `original_assignee_hf_id`. Lets re-publish auto-restore the prior state. |

## Transition matrix

| Event | From | To | Other column changes | Actor role |
|---|---|---|---|---|
| `catalog.added` | (no row) | `catalogued` | — | system |
| `reciter.alignment_requested` | `catalogued` | `awaiting_alignment` | — | system (forward webhook) |
| `reciter.alignment_completed` | `awaiting_alignment` | `awaiting_review` | — | system (pipeline) |
| `reciter.claimed` | `awaiting_review` | `under_review` | set assignee_*; `marked_ready=0` | contributor+ |
| `reciter.released` | `under_review` | `awaiting_review` | clear assignee_*; `marked_ready=0` | claim-holder OR maintainer+ |
| `reciter.marked_ready` | `under_review` | (same) | `marked_ready=1` | claim-holder |
| `reciter.unmarked_ready` | `under_review` | (same) | `marked_ready=0` | claim-holder |
| `reciter.merge_rejected` | `under_review` (`marked_ready=1`) | (same) | `marked_ready=0` | maintainer+ |
| `reciter.published` | `under_review` (`marked_ready=1`) | `awaiting_timestamps` | clear assignee_*; `marked_ready=0` | maintainer+ |
| `reciter.timestamps_completed` | `awaiting_timestamps` | `released` | append to `timestamps_job_ids` | system (job callback) |
| `reciter.dataset_published` | `released` | `completed` | — | maintainer+ (single or batch via `POST /api/admin/publish-to-dataset`) |
| `admin.unlocked_for_revision` | `released`, `completed` | `awaiting_review` | set `revision_in_progress = {unlocked_from_state, unlocked_at, unlocked_by_hf_id, original_assignee_hf_id}`; copy `published/<slug>/` → `wip/<slug>/` (published files retained) | maintainer+ (reason ≥10 chars) |
| `reciter.removed_from_dataset` | `completed` | `released` | dispatch `sync-dataset.yml` rebuild dropping slug | maintainer+ (reason ≥10 chars) |
| `reciter.unpublished` | `released`, `completed` | `awaiting_review` | move `published/<slug>/` → `wip/<slug>/`; if was `completed`, also dispatch dataset rebuild | maintainer+ (reason ≥10 chars + typed `unpublish <slug>` confirmation) |
| `published.edited` | `released`, `completed` | (same) | maintainer-only direct edit on a published reciter; saves write to `published/<slug>/`; emitted per save batch | maintainer+ |
| `reciter.discarded` | (any) | (same) | `visibility=discarded`; `visibility_reason=...` | maintainer+ |
| `reciter.undiscarded` | (any with `visibility=discarded`) | (same) | `visibility=public` | maintainer+ |
| `claim.force_released` | `under_review` | `awaiting_review` | clear assignee_*; `marked_ready=0` | maintainer+ |
| `claim.reassigned` | `awaiting_review`, `under_review` | `under_review` | set new assignee_*; `marked_ready=0` | maintainer+ |
| `admin.force_set_state` | narrow allowed pairs only | (specified) | — | maintainer+ |

**Deferred (not in v2):** `reciter.archived` / `reciter.unarchived` (no `archived` visibility), `claim.force_acquired` / `claim.force_released_auto` (force-claim entirely deferred — no `force_assignee_*` columns, no 30-min lease), `admin.force_clear_assignee`, `admin.force_unmark_ready`, `admin.force_revision_bump`. See [`../../planning/inspector-deploy/v2/inspector-deferred.md`](../../planning/inspector-deploy/v2/inspector-deferred.md).

**`admin.force_set_state` allowed pairs** (extend the list, not the endpoint):
- `awaiting_alignment ↔ awaiting_review`
- `awaiting_timestamps ↔ released`
- `released ↔ completed` (alternative to `reciter.dataset_published` / `reciter.removed_from_dataset` for force-correction without dispatching dataset rebuild)
- `under_review → awaiting_review` (alternative to `claim.force_released`)

Any other pair returns 400.

## What's NOT a state

- `ready_for_merge` — superseded by `marked_ready: bool` on `under_review`. Three transitions removed.
- `discarded` — superseded by `visibility='discarded'`. Round-trip preserves lifecycle.

## What's NOT a transition

- `under_review → released` (must go via `awaiting_timestamps`).
- `under_review → completed` (must go via `awaiting_timestamps` and `released`).
- Wildcard `state.manual_override` — replaced by discrete `admin.force_*` events.
- Direct re-edit of `completed` reciters via the contributor flow (re-edits are admin-only via `admin.unlocked_for_revision`).

## Predicates (computed server-side)

| Predicate | Condition |
|---|---|
| `can_edit` | `state=under_review` ∧ `marked_ready=0` ∧ `visibility=public` ∧ `assignee_hf_id == user.hf_user_id` |
| `can_mark_ready` | `can_edit` ∧ not yet marked |
| `can_unmark_ready` | `state=under_review` ∧ `marked_ready=1` ∧ `assignee_hf_id == user.hf_user_id` |
| `can_release` | `state=under_review` ∧ `assignee_hf_id == user.hf_user_id` |
| `can_claim` | `state=awaiting_review` ∧ `visibility=public` ∧ user has no other active claim |
| `can_publish` | `role >= maintainer` ∧ `state=under_review` ∧ `marked_ready=1` |
| `can_publish_to_dataset` | `role >= maintainer` ∧ `state=released` |
| `can_remove_from_dataset` | `role >= maintainer` ∧ `state=completed` |
| `can_unlock_for_revision` | `role >= maintainer` ∧ `state ∈ {released, completed}` |
| `can_admin_edit` | `role >= maintainer` ∧ `state ∈ {released, completed}` (direct edit on published reciters) |

All claim-ownership checks use `hf_user_id`, never `login`.

## See also

- [`schemas.md`](schemas.md) — full DDL of `reciters` table
- [`events.md`](events.md) — payload shapes per event
- Planning rationale: [`inspector-state-management.md`](../../planning/inspector-deploy/v2/inspector-state-management.md) §4
