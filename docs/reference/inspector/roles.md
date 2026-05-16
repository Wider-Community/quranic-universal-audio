# Roles + Permissions

Single map of who can do what, and where the check lives. For state-changing events see [`state-machine.md`](state-machine.md); this doc covers the authorization machinery itself.

## Role tiers

```
contributor < maintainer < owner
```

Defined in [`scripts/lib/schemas/access.py::Role`](../../../scripts/lib/schemas/access.py). `contributor` is implicit (any signed-in HF user not in the roles file); `maintainer` and `owner` are explicit rows in `<bucket>/access/inspector_roles.json`.

| Tier | Inherits | Can do (in addition to lower tier) |
|---|---|---|
| `contributor` | — | sign in, claim a row, edit own claim, mark/unmark own claim ready, release own claim |
| `maintainer` | contributor | admin overrides (force-release, reassign, force-set-state on allowed pairs, merge-rejected, unlock-for-revision, publish, dataset publish/remove, unpublish, discard/undiscard); admin activity rail; grant/revoke maintainers; per-user dismiss on admin rail |
| `owner` | maintainer | grant/revoke other owners; see actor identity on both activity rails; delete cards from the public activity rail; **edit any public non-frozen reciter regardless of `ReciterState` (no claim required)**; **hold multiple active claims simultaneously** |

## Predicates

All predicates live in [`inspector/services/auth/permissions.py`](../../../inspector/services/auth/permissions.py) — Flask-free, exception-free except on programmer error. Both the state layer and the route layer call into these.

| Predicate | Returns |
|---|---|
| `role_of(obj)` | `Role` enum (normalizes str/enum/Member) |
| `is_owner(obj)` | True iff role == OWNER |
| `is_maintainer(obj)` | True iff role ∈ {MAINTAINER, OWNER} — the elevated-action tier |
| `is_contributor_or_higher(obj)` | True iff role is recognised (sanity check vs anonymous) |
| `has_role(obj, *allowed)` | Generic membership test |
| `is_claim_holder(obj, row)` | True iff `row.assignee_hf_id == obj.hf_user_id` |
| `is_claim_holder_or_maintainer(obj, row)` | Composition; the only pre-composed helper |
| `normalize_reason(raw, min_chars=10)` | Trimmed reason or `None` |

### `services/auth/predicates.py` — reciter-task predicates

| Predicate | Condition |
|---|---|
| `can_claim` | `awaiting_review` + `public` + signed in + (owner OR no other active claim) |
| `can_edit` | `under_review` + not `marked_ready` + `public` + user is assignee |
| `can_edit_as_admin` | maintainer/owner + `under_review` + not `marked_ready` + `public` |
| `can_edit_as_owner` | owner + not `marked_ready` + `public` (any `ReciterState`) |
| `can_mark_ready` | same as `can_edit` + row not already marked |
| `can_unmark_ready` | `under_review` + `marked_ready` + user is assignee |
| `can_release` | `under_review` + user is assignee |

Comparisons always use `hf_user_id` (canonical, immutable). Never `login` (mutable on HF).

## Where role gating is enforced

Same predicate set, different error contract per layer:

| Layer | Wrapper | Failure surface |
|---|---|---|
| Domain (state handlers) | inline `permissions.has_role(...)` call | raises `NotAuthorizedForTransition` |
| Route handler | [`utils/decorators.py::@require_role(*roles)`](../../../inspector/utils/decorators.py) (stacks with `@require_same_origin`) | 401 anonymous / 403 wrong tier; injects `user` as first arg |
| Route helper (legacy) | [`routes/_admin_helpers.py::require_signed_in_or_401` + `require_role_or_403`](../../../inspector/routes/_admin_helpers.py) | returns `(jsonify, status)` tuples |
| Edit-lock decorator | [`utils/decorators.py::require_edit_lock(admin_bypass=True)`](../../../inspector/utils/decorators.py) | `flask.abort(403)` |
| Frontend (global) | `isAdmin` / `isOwner` derived stores in [`lib/stores/current-user.ts`](../../../inspector/frontend/src/lib/stores/current-user.ts) | hides/disables UI |
| Frontend (per-reciter) | `editingMode` store in [`lib/stores/editing-mode.ts`](../../../inspector/frontend/src/lib/stores/editing-mode.ts) | `editGate` action routes clicks to popover |

**Adding a new gated action** = one predicate call + one wrapper. Never duplicate `Role(...) in (...)` membership tests.

## Reason discipline

Admin actions that mutate state require a reason ≥ `permissions.MIN_REASON_CHARS` (= 10). The reason is validated once (`normalize_reason` returning `None` ⇒ 400) and persisted on the audit record. There is no wildcard "manual override" — new recovery scenarios get a new named event with its own reason check.

## Frontend role surface

| Store | Source | Use |
|---|---|---|
| `currentUser` | `/api/me` at boot + after `setDevRole` | identity + role + active_claim |
| `isSignedIn(u)` | function predicate | gate sign-in modal |
| `isAdmin` derived | role ∈ {maintainer, owner} | dashboard-level admin UI (admin activity rail) |
| `isOwner` derived | role == owner | owner-only affordances (actor login, public-feed delete) |
| `editingMode` | per-reciter (`syncEditingMode(user, task)`) | save/undo gating inside a reciter; emits `kind ∈ {view, editor, maintainer, owner}` |

`isAdmin` and `isOwner` are *global* (driven by the user). `editingMode.isAdmin` is *reciter-scoped* and only true when the row is also in an editable state. Don't conflate.

#### `syncEditingMode` branch order

| Priority | Condition | Result |
|---|---|---|
| 1 | user == null or task == null | `view / unauthenticated` |
| 2 | `visibility == discarded` | `view / discarded` |
| 3 | role == owner + `marked_ready` | `view / marked_ready` |
| 4 | role == owner | `owner` (any state, no claim required) |
| 5 | state == completed | `view / completed` |
| 6 | state == released | `view / released` |
| 7 | `under_review` + `marked_ready` + assignee | `view / marked_ready` |
| 8 | `under_review` + not `marked_ready` + assignee | `editor` |
| 9 | role == maintainer + `under_review` + not `marked_ready` | `maintainer` |
| 10 | catalogued / awaiting_* | `view / not-claimable` |
| 11 | else | `view / wrong-assignee` |

## Identity resolution: HF Space vs local dev

| Mode | Source of identity | `hf_user_id` value |
|---|---|---|
| HF Space (`INSPECTOR_DEV_MODE` unset) | Signed `inspector_session` cookie minted on HF OAuth callback; role resolved fresh per request via `access.resolve_role(hf_user_id)` | Real HF OIDC sub |
| Local dev (`INSPECTOR_DEV_MODE=1`) | Plain `inspector_dev_role` cookie set by the in-app switcher | `dev-<role>` (`dev-owner` / `dev-maintainer` / `dev-contributor`) |

Role tier resolution is identical in both modes; only the identity source differs. Per-role synthetic `hf_user_id` in dev mode means role-switcher flips simulate distinct admin users — per-user dismissals, claim ownership, and audit actor records all scope correctly.

Anonymous in either mode → `current_user()` returns `None`. Dev cookie value `"anonymous"` is the explicit opt-out (otherwise an unset cookie defaults to `"owner"` in dev mode).

## Audit actor record

Every mutation writes one [`AuditRecord`](../../../scripts/lib/schemas/audit.py) carrying `Actor{hf_user_id, login_at_time, role}`. `login_at_time` is a snapshot of the cookie at the time of the action (never refetched); the audit log preserves the historical login even after rename. `role` is also frozen at action time.

## Per-user state

The only per-user state outside claims is **admin activity rail dismissals**:

- Stored in `<bucket>/activity/state.json` (5th bucket store), keyed by `hf_user_id`.
- `services/activity_state.dismiss(audit_id, actor)` writes an `activity.dismissed` audit event and adds the id to the user's list.
- The audit log itself stays append-only — dismissals and tombstones are external filter state.

Global tombstones (`activity_state.deleted`) are owner-only and apply to the public activity rail for everyone.

## Admin endpoints by tier

| Endpoint | Required | Reason ≥10 | Audit event |
|---|---|---|---|
| `POST /api/admin/claim/force-release/<slug>` | maintainer+ | yes | `claim.force_released` |
| `POST /api/admin/claim/reassign/<slug>` | maintainer+ | yes | `claim.reassigned` |
| `POST /api/admin/state/force-set/<slug>` | maintainer+ | yes | `admin.force_set_state` |
| `POST /api/admin/send-back/<slug>` | maintainer+ | yes | `reciter.merge_rejected` |
| `POST /api/admin/users/lookup` | maintainer+ | — | (no mutation) |
| `POST /api/admin/prefetch/rerun/<slug>` | maintainer+ | — | — |
| `GET  /api/admin/activity` | maintainer+ | — | — |
| `POST /api/admin/activity/dismiss` | maintainer+ | — | `activity.dismissed` |
| `POST /api/admin/activity/undismiss` | maintainer+ | — | `activity.undismissed` |
| `DELETE /api/public/activity/<audit_id>` | **owner** | yes | `admin.activity_deleted` |
| `GET /api/public/reciter/<reciter_id>` | open | — | (read) — maintainer+ gets admin shape with `discarded_deliveries` array; lower tiers get the redacted public shape |
| `POST /api/admin/access/grant` | maintainer+; OWNER role requires owner | yes | `access.role_granted` |
| `POST /api/admin/access/revoke` | maintainer+; revoking OWNER requires owner | yes | `access.role_revoked` |
| `POST /api/admin/access/update` | maintainer+; granting OWNER requires owner | yes | `access.role_updated` |

State-changing events (`reciter.published`, `reciter.unpublished`, `reciter.dataset_published`, `admin.unlocked_for_revision`, etc.) are covered in [`state-machine.md`](state-machine.md) with their own role columns.

## See also

- [`state-machine.md`](state-machine.md) — transition matrix + per-event actor role
- [`schemas/`](schemas/) — `access/inspector_roles.json`, audit record, activity state
