# State Machine

Lifecycle phase + two orthogonal columns.

## Lifecycle states (column: `state`)

```
catalogued → awaiting_alignment → awaiting_review → under_review → awaiting_timestamps → completed
```

| State | Editable? | Required | Notes |
|---|---|---|---|
| `catalogued` | No | — | In catalog. No alignment yet. |
| `awaiting_alignment` | No | — | Pipeline running. |
| `awaiting_review` | No (claimable) | — | Alignment done. Bucket entry exists. No claim. |
| `under_review` | Yes (assignee, when `marked_ready=0`) | `assignee_hf_id`, `assignee_login`, `assignee_since` | Claimed. |
| `awaiting_timestamps` | No | — | Snapshot HF Job done. TS Job pending. |
| `completed` | No | — | Live on HF dataset. |

## Orthogonal columns

| Column | Type | Meaning |
|---|---|---|
| `marked_ready` | bool | When `state=under_review` and `marked_ready=1`: edits frozen, awaiting maintainer publish. Reviewer can flip back to `0`. |
| `visibility` | enum | `public` (default) / `discarded` (hidden, any state) / `archived` (post-publish soft-retire, only from `completed`) |
| `force_assignee_hf_id` | string \| null | Persisted 30-min admin force-claim lease. Survives Space restart. Auto-cleared by `claim.force_released_auto`. |

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
| `reciter.timestamps_completed` | `awaiting_timestamps` | `completed` | — | system (job callback) |
| `reciter.discarded` | (any) | (same) | `visibility=discarded`; `visibility_reason=...` | maintainer+ |
| `reciter.undiscarded` | (any with `visibility=discarded`) | (same) | `visibility=public` | maintainer+ |
| `reciter.archived` | `completed` only | (same) | `visibility=archived` | maintainer+ |
| `reciter.unarchived` | (any with `visibility=archived`) | (same) | `visibility=public` | maintainer+ |
| `claim.force_released` | `under_review` | `awaiting_review` | clear assignee_*; `marked_ready=0` | maintainer+ |
| `claim.reassigned` | `awaiting_review`, `under_review` | `under_review` | set new assignee_*; `marked_ready=0` | maintainer+ |
| `claim.force_acquired` | `under_review` | (same) | set `force_assignee_*` (30-min lease) | maintainer+ |
| `claim.force_released_auto` | (any with `force_assignee_*`) | (same) | clear `force_assignee_*` | system (timer) |
| `admin.force_set_state` | narrow allowed pairs only | (specified) | — | maintainer+ |
| `admin.force_clear_assignee` | (any with assignee_*) | (same) | clear assignee_*; `marked_ready=0` | maintainer+ |
| `admin.force_unmark_ready` | `under_review` | (same) | `marked_ready=0` | maintainer+ |
| `admin.force_revision_bump` | (any) | (same) | `revision += 1` | maintainer+ |

**`admin.force_set_state` allowed pairs** (extend the list, not the endpoint):
- `awaiting_alignment ↔ awaiting_review`
- `awaiting_timestamps ↔ completed`
- `under_review → awaiting_review` (alternative to `claim.force_released`)

Any other pair returns 400.

## What's NOT a state

- `ready_for_merge` — superseded by `marked_ready: bool` on `under_review`. Three transitions removed.
- `discarded` — superseded by `visibility='discarded'`. Round-trip preserves lifecycle.

## What's NOT a transition

- `under_review → completed` (must publish via `awaiting_timestamps`).
- `completed → under_review` (re-edits deferred — see [deferred D5](../../planning/inspector-deploy/v2/inspector-deferred.md#d5--re-edits-of-completed-reciters)).
- Wildcard `state.manual_override` — replaced by discrete `admin.force_*` events.

## Predicates (computed server-side)

| Predicate | Condition |
|---|---|
| `can_edit` | `state=under_review` ∧ `marked_ready=0` ∧ `visibility=public` ∧ `assignee_hf_id == user.hf_user_id` |
| `can_mark_ready` | `can_edit` ∧ not yet marked |
| `can_unmark_ready` | `state=under_review` ∧ `marked_ready=1` ∧ `assignee_hf_id == user.hf_user_id` |
| `can_release` | `state=under_review` ∧ `assignee_hf_id == user.hf_user_id` |
| `can_claim` | `state=awaiting_review` ∧ `visibility=public` ∧ user has no other active claim |
| `can_publish` | `role >= maintainer` ∧ `state=under_review` ∧ `marked_ready=1` |

All claim-ownership checks use `hf_user_id`, never `login`.

## See also

- [`schemas.md`](schemas.md) — full DDL of `reciters` table
- [`events.md`](events.md) — payload shapes per event
- Planning rationale: [`inspector-state-management.md`](../../planning/inspector-deploy/v2/inspector-state-management.md) §4
