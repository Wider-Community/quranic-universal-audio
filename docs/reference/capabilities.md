# Inspector — Capabilities (data-driven authorization)

Authorization is a **data-driven capability matrix**, not hardcoded role tiers. An owner toggles any capability on/off per tier (anonymous / contributor / maintainer) from the **Admin → Permissions** tab; the change is durable, audited, and takes effect on the affected user's next request. **The resolver `services/auth/capabilities.py::can()` is the single source of authz** — every route, state handler, predicate, and edit-lock branch calls it. Roles still exist (`contributor < maintainer < owner`) but only as the *default* each capability ships with; an owner overrides per cell.

This doc is the **what-is** + the **convention for adding a gate so it surfaces in the UI**. For the predicate/edit-lock/redaction detail see [auth-permissions.md](auth-permissions.md); for the Permissions-tab UI see [admin-dashboard.md](admin-dashboard.md).

---

## Adding a capability — the convention

To add a new permission gate **so it automatically surfaces in the Permissions tab**, do exactly two things (three if it has a UI affordance):

1. **Register it** — add one `Capability(...)` (via the `_c(...)` helper) to `CAPABILITIES` in `qua_shared/schemas/config/capabilities.py`:
   - `id` — dot-namespaced, stable (e.g. `reciter.publish`, `claim.force_release`).
   - `group` — an existing `G_*` label (or a new one; groups render in first-appearance order).
   - `label` + `description` — human text, shown **verbatim** in the UI. Write them for an owner skimming the matrix.
   - `anon` — pass a bool only for identity-free **read** caps (→ `anon_eligible`); omit for action caps (anonymous renders N/A).
   - `contributor` / `maintainer` — the **current** default for each tier, so the empty-override baseline reproduces today's behavior (parity test enforces this).
2. **Gate the code path through the resolver** — never a hardcoded role check:

   | Where | Use |
   |---|---|
   | Route (decorator) | `@require_capability("your.cap")` (injects `user`; anon allowed iff `anon_eligible`) |
   | Route (inline) | `actions.py::_require_cap("your.cap")` or `_admin_helpers.require_capability_or_403(user, "your.cap")` |
   | State transition | `_require_capability(actor, "your.cap")` inside the `_h_*` handler **and** add the `event → cap` row to `state.py::_EVENT_CAPABILITY` |
   | Service / predicate / edit-lock | `capabilities.can(actor_or_user, "your.cap")` |

3. **(FE — only if there's a UI affordance to show/hide)** gate it on `lib/stores/capabilities.ts`: `can('your.cap')` (reactive store) or `hasCapability(user, 'your.cap')` (pure). The Permissions **tab itself needs no change** — its matrix is fully data-driven (see below).

That's the whole recipe. **No endpoint, no Permissions-tab, no migration change** — the capability appears in the matrix (label + description + per-tier toggles) on the next `GET /api/admin/permissions`, and the owner can toggle it immediately. `/api/me` picks it up in the caller's resolved `capabilities[]`.

### Don'ts
- **Don't** hardcode `permissions.is_maintainer()` / `is_owner()` / `@require_role(...)` at a **new** gate. Those bypass the registry → the gate won't surface in the Permissions tab and won't be owner-toggleable. The guard test (below) fails the build if `@require_role` reappears in `routes/`.
- Ownership checks (`is_claim_holder`, `is_claim_holder_or_maintainer`) are **not** capabilities — they ask "is this *your* row," and stay as-is. A capability governs the *tier* dimension layered on top.
- An unknown capability id passed to `can()` / `@require_capability` raises `ValueError` at call/import time — so a typo can't silently create an ungated path.

---

## How a capability surfaces in the UI (automatic)

```
CAPABILITIES (registry)
  → services/admin/permissions.py::build_matrix()   # iterates CAPABILITIES by GROUP_ORDER
  → GET /api/admin/permissions                       # grouped matrix (default ⊕ overrides)
  → PermissionsCompartment.svelte                    # renders every group/cap/tier in the response
```

The FE hardcodes **nothing** about which capabilities exist — it renders whatever the matrix returns. So a registered capability is rendered with no FE edit. `/api/me` exposes the caller's resolved `capabilities[]` for capability-aware affordance gating elsewhere.

---

## Resolver + storage (the substrate)

| Piece | Truth |
|---|---|
| Registry (data) | `qua_shared/schemas/config/capabilities.py` — `Capability{id, group, label, description, anon_eligible, owner_only_fixed, default_grants}` + `CAPABILITIES`, `CAPABILITIES_BY_ID`, `GROUP_ORDER`, `TIERS`. Backend-only; NOT codegen'd to the FE (the matrix response models in `admin_permissions.py` are). |
| Resolver | `services/auth/capabilities.py` — `tier_of(user_or_actor)` (`None`→`anonymous`), `resolve_grants() -> {(cap,tier): bool}` (baseline ⊕ overrides, cached on `db_seq`), `can(user_or_actor, cap)`, `capabilities_for(user)`. |
| Override store | `permission_overrides(capability_id, tier, allowed, set_by, set_at)` — migration `0008`, `services/db/repo_permissions.py`. **Deviations only**: absent row → default; reset = `DELETE`. |
| Cache | `services/storage/cache.py::{get,set,invalidate}_capability_matrix_cache` — single `(db_seq, matrix)` tuple. Any committed override write bumps `db_seq` → transparent invalidation, no restart. (The autouse test fixture invalidates it too.) |
| Endpoints | `GET /api/admin/permissions` + `POST /api/admin/permissions/<cap>/<tier>` (`{allowed}` or `{reset:true}`), both `@require_capability("manage_permissions")`; POST `@require_same_origin`, audited `access.permission_changed` (a `HIDDEN_EVENTS` event). Service `services/admin/permissions.py`. |

## Invariants (hold regardless of the override table)
- **Owner is a superuser** — `can(owner, anything) is True`.
- **`manage_permissions` is `owner_only_fixed`** — never grantable to a lower tier even if a row is forced in. Gates the Permissions tab + endpoints; the recovery anchor, so owners can't lock themselves out.
- **Anonymous only where `anon_eligible`** — action caps are always `False` for anonymous; only the public-read caps (`view.catalog`, `view.public_activity`) and the public Timestamps-tab report cap (`timestamps.report`, default-on for everyone) are anonymous-toggleable. `timestamps.see_reporter_identity` (owner-default) gates revealing the reporter's login on a report + its notification — the owner-facing sibling of `segments.see_flagger_identity`. `timestamps.resolve_report` (owner-default) gates the resolve action; `timestamps.view_stale_reports` (owner-default) gates filtering to reports a re-stamp invalidated.
- **Structural integrity is NOT a capability** — the last-active-owner guard + owner-on-owner revoke asymmetry (`services/admin/users.py`, `services/auth/access.py`) stay enforced even with `roles.*` toggled on.

## Guards (keep the convention honest)
- `tests/services/test_capabilities.py` — baseline parity (empty overrides == legacy), owner-superuser, `manage_permissions` immutability, anon-eligibility, override apply/clear, `_EVENT_CAPABILITY` completeness.
- `tests/test_capability_convention.py` — (a) `build_matrix()` returns **every** registry capability (registry→UI completeness — a new cap can't fail to surface); (b) **no `@require_role(` decorator** in `inspector/routes/` (forces `@require_capability`).
- `tests/routes/test_route_permissions.py` — endpoint owner-only, toggle reflected live, `manage_permissions`/anon-ineligible rejected, audit emitted.
