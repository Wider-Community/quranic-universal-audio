# Phase 3 — Auth + claim + save

> HF OAuth + claim/release/mark/unmark + save migration land together. Contributors can claim and edit end-to-end against the bucket. Admin overrides stay in Phase 4.

**Status:** code complete (local tests green); dev Space cutover pending push
**Depends on:** Phase 2 (Deployable image) complete
**Blocks:** Phase 4

## Goal

Identity is HF OAuth, sessions are self-contained signed cookies (no server-side session record). Claim transitions are synchronous, write the bucket JSON via `huggingface_hub.upload_file()`, and append to `<bucket>/audit/<YYYY>-<MM>.jsonl`. Lock ownership is keyed on `assignee_hf_id` everywhere — login renames don't break locks. Role resolution uses `<bucket>/access/inspector_roles.json` via `services/access.py` (in-memory cache hydrated at startup; sole-writer pattern means cache is correct by construction). Save flow points at `<bucket>/wip/<slug>/...` via the resolver — same code path as local mode; `@require_edit_lock(admin_bypass=True)` gates the route, batches carry an `actor: {hf_user_id, login_at_time, role}` block. At the end of this phase a contributor can claim, mark-ready, unmark, release, **and save segment edits** through the website end-to-end. A maintainer can edit on top of any active claim (`under_review && !marked_ready`).

## Deliverables

### Identity + session
- [ ] `inspector/services/auth.py` — Authlib `OAuth` client + `itsdangerous.URLSafeTimedSerializer` helpers; payload `{login, hf_user_id, iat}` (no role, no csrf); `User` dataclass + `current_user()` which resolves role fresh via `access.resolve_role` every call.
- [ ] OAuth endpoints in `inspector/routes/auth.py`: `GET /api/auth/login`, `GET /api/auth/callback`, `POST /api/auth/logout`, `GET /api/me`.
- [ ] Authlib OAuth-state store on Flask-Session tmpfs (`/tmp/inspector-flask-sessions/`, ~30 s lifetime).
- [ ] Space `README.md` frontmatter `hf_oauth: true` + `hf_oauth_expiration_minutes: 10080` (1 week).
- [ ] `inspector/app.py` — `werkzeug.middleware.proxy_fix.ProxyFix(x_for=1, x_proto=1, x_host=1)` gated by `INSPECTOR_BEHIND_PROXY=1`; Flask errorhandlers map `InvalidTransition`→400, `NotAuthorizedForTransition`→403.
- [ ] `inspector/Dockerfile` — `INSPECTOR_BEHIND_PROXY=1` env.

### Locking + claim
- [ ] `inspector/utils/decorators.py` — `require_same_origin()` (Origin/Referer check) + `require_edit_lock(reciter_param='reciter', admin_bypass=False)` (only used on save/undo; sets `g.current_user`, `g.current_row`).
- [ ] `inspector/routes/claims.py` — Blueprint `/api`. **No `@require_edit_lock`** on these — `state.py` handlers enforce preconditions; route maps exceptions to HTTP status via app-level errorhandler.
  - `POST /api/claim/<slug>` — pre-checks `state.has_other_active_claim` → 409 with `existing_claim`; then `state.transition(slug, "reciter.claimed", actor=...)`.
  - `POST /api/release/<slug>` — `reciter.released`.
  - `POST /api/mark-ready/<slug>` — `reciter.marked_ready`.
  - `POST /api/unmark-ready/<slug>` — `reciter.unmarked_ready`.
- [ ] `GET /api/reciter-task/<slug>` — full row + `can_*` predicates (state-mgmt §8 plus new `can_edit_as_admin`).
- [ ] `inspector/services/predicates.py` — pure functions for the predicates above.
- [ ] One-claim-per-user enforcement at the `/api/claim` route.

### Save migration
- [ ] `inspector/services/save.py` — `save_seg_data(reciter, chapter, updates, *, actor: Actor)`; `_persist_and_record(..., *, actor)`; batch dict carries `"actor": actor.model_dump(mode='json')`.
- [ ] `inspector/services/undo.py` — `undo_batch(*, actor)`, `undo_ops(*, actor)`, `_append_revert_record(*, actor, ...)`; revert dict carries `actor` block.
- [ ] `inspector/utils/io.py` — delete `file_sha256` + `backup_file` (no callers remain in worktree).
- [ ] `inspector/routes/segments_edit.py` — `@require_same_origin` → `@require_edit_lock(reciter_param='reciter', admin_bypass=True)` → `@_gate_local_writes` on `seg_save`, `seg_undo_batch`, `seg_undo_ops`; build `actor` from `g.current_user`, pass to services.
- [ ] `inspector/routes/peaks.py` — same decorator chain on `POST /history-peaks/<reciter>` (writes `edit_history_peaks.jsonl`).
- [ ] `inspector/routes/audio_proxy.py` — `@require_same_origin` + signed-in check on `POST /prepare-audio/<reciter>` and `DELETE /delete-audio-cache/<reciter>`; no lock (cache-warm utilities, not bucket mutators).
- [ ] `inspector/routes/segments_validation.py` — delete `POST /stats/<reciter>/save-chart` (debug-only).

### Access admin (backend-only; UI lands Phase 7)
- [ ] `inspector/routes/access_admin.py` — Blueprint `/api/admin/access`: `POST /grant`, `POST /revoke`, `POST /update`. Each requires reason ≥ 10 chars.
- [ ] `POST /api/admin/access/revoke` — **force-releases any active claim held by the revoked user** via `state.transition(slug, "reciter.released", actor=revoking_actor)` for every UNDER_REVIEW row where `assignee_hf_id == hf_user_id`. Audit captures both `access.role_revoked` and `reciter.released`.

### Frontend
- [ ] `inspector/frontend/src/lib/stores/current-user.ts` + `loadCurrentUser()` boot fetch from `/api/me`.
- [ ] `inspector/frontend/src/lib/api/{auth-client,reciter-task,claims-client}.ts`.
- [ ] `inspector/frontend/src/lib/components/{SignInModal,ReviewerBanner,ClaimButton,ToastHost}.svelte`.
- [ ] `inspector/frontend/src/lib/stores/editing-mode.ts` — `syncEditingMode(currentUser, task)` helper; extend `ViewReason` with `'released' | 'marked_ready'`.
- [ ] `inspector/frontend/src/lib/components/EditAffordancePopover.svelte` — copy for new viewReasons.
- [ ] `inspector/frontend/src/tabs/segments/SegmentsTab.svelte` — mount banner; reciter-task polling (30 s); wrap save button in `{#if $editingMode.kind !== 'view'}`.
- [ ] `inspector/frontend/src/tabs/segments/components/history/{HistoryBatch,HistoryOp}.svelte` — wrap Undo/Discard buttons in `{#if $editingMode.kind !== 'view'}`.
- [ ] Toast host in `App.svelte`; SignInModal mounted at root.

### Tests
- [ ] `inspector/tests/conftest.py` — `signed_in_client` fixture (mints session cookie; seeds `access.ACCESS_STORE`).
- [ ] `inspector/tests/routes/test_route_auth.py` — `/api/me` anonymous + signed-in, callback flow (mocked), logout, live role refresh after revoke.
- [ ] `inspector/tests/routes/test_route_claims.py` — happy path, 409 other active, 400 invalid transition, 403 non-assignee, mark/unmark round-trip, predicates for all three roles, audit `actor`.
- [ ] `inspector/tests/routes/test_route_save.py` — 401 anonymous, 403 non-assignee, 403 marked-ready, 403 discarded, happy path with `actor`, maintainer override.
- [ ] `inspector/tests/routes/test_route_history_peaks_lock.py` — POST history-peaks requires edit lock.
- [ ] `inspector/tests/routes/test_route_access_admin.py` — grant/revoke/update RBAC, revoke force-releases claim, short reason rejected.
- [ ] `inspector/frontend/src/lib/stores/__tests__/editing-mode.test.ts` — 8 branches of `syncEditingMode`.
- [ ] Extend `inspector/frontend/src/lib/actions/__tests__/editGate.test.ts` for `'released'` + `'marked_ready'` popover copy.

### Config / secrets
- [ ] `scripts/inspector_v2_seed/setup_space.py:64` — `hf_oauth_expiration_minutes: 480` → `10080`.
- [ ] `INSPECTOR_SESSION_SECRET` already provisioned by Phase 2 — verify.

## Out of scope

- Four admin override actions (force-release, reassign, force-set-state, send-back) + reason-modal UX — **Phase 4**.
- Validator library-refactor of `validate_audio` and `validate_timestamps` — **Phase 4**.
- Maintainer edits on `released` / `completed` (`published.edited` route surface) — **Phase 7** admin dashboard.
- `/admin` route + dashboard panels — **Phase 7**.
- Publish endpoint + bucket move + TS HF Job — **Phase 5**.
- Force-claim mechanism — deferred (D15).
- Server-Sent Events for cross-tab state sync — deferred (D8).
- `validate_edit_history` inline-from-save — chain-style premise gone; replay-style check deferred to Phase 6 `bucket-data-hygiene.yml`.

## Acceptance criteria

- [ ] First-time visitor signs in and claims a reciter in **3 clicks max** (Claim → Continue modal → HF Authorize).
- [ ] Returning user with active session claims in **1 click**.
- [ ] After claim, `<bucket>/state/reciter_state.json` shows `assignee_hf_id == <user's HF sub>`, `assignee_login == <login>`.
- [ ] After claim, `<bucket>/audit/<YYYY>-<MM>.jsonl` has a `reciter.claimed` line with `actor.hf_user_id`.
- [ ] Two simultaneous claim attempts from different sessions on the same reciter: first wins, second 409.
- [ ] One-claim-per-user violation returns 409 `{existing_claim: <other_slug>}`.
- [ ] Mark-ready → unmark round-trip preserves `assignee_*`.
- [ ] Release after mark-ready clears `assignee_*`, sets `marked_ready=0`, transitions to `awaiting_review`.
- [ ] Save POST as active reviewer → 200, bucket `wip/<slug>/detailed.json` + `segments.json` + new `edit_history.jsonl` line with `actor: {hf_user_id, login_at_time, role}`; **no `file_hash_after`**; **no genesis record**.
- [ ] Save POST during `(under_review, marked_ready=1)` → 403 with a clear `error` message body.
- [ ] Save POST as a maintainer on someone else's active claim → 200; audit batch carries `actor.role: "maintainer"`.
- [ ] Save POST as a non-assignee contributor → 403.
- [ ] Existing on-disk v1-schema `edit_history.jsonl` (with genesis + `file_hash_after`) still parses via `parse_history_file` — History panel renders for `saad_al_ghamdi`.
- [ ] `assignee_hf_id` is the only field used for ownership comparison (grep verifies no `assignee_login == user.login` patterns).
- [ ] Session cookie survives container restart (signed; not server-side).
- [ ] Role refresh: maintainer signs in → revoked via `/api/admin/access/revoke` → `/api/me` reflects `role: contributor` on the very next request (no re-login). Any active claim is force-released as part of revoke.
- [ ] Logout clears the cookie; the user's claim is NOT released by logout (deliberate).
- [ ] `editGate` default already passes through for `editor | maintainer | owner`; admin gets save/undo affordances for free without extending the action.
- [ ] Frontend: no "Currently claimed by @x" lock banner. Claim button is hidden when not claimable.
- [ ] Frontend: save button + History panel Undo/Discard hidden whenever `$editingMode.kind === 'view'`.

## Edge cases

- **Maintainer revoked while holding active claim** → `access.revoke()` route handler auto-fires `reciter.released` for every UNDER_REVIEW row assigned to them. Audit reflects both `access.role_revoked` and `reciter.released`.
- **Cookie role staleness** — cookie payload does NOT carry `role`. `current_user()` resolves role on every request via in-memory `access.resolve_role`. No drift possible.
- **HF token revoked by user mid-session** — signed cookie keeps working until expiry (we never store the user's HF token). Their claim survives. Documented in runbook §3.
- **Login rename mid-claim** — `assignee_hf_id` is canonical. `assignee_login` is a display cache. Lock-ownership comparisons compare `hf_user_id` only.
- **Concurrent claim race** — per-slug `threading.Lock` in `state.py::transition` serializes; first wins, second gets `InvalidTransition` → 400.
- **`(under_review, marked_ready=1)` save attempt** — `require_edit_lock` returns 403 (not 410 — keeps decorator semantics auth-shaped; phase doc supersedes earlier 410 proposal).

## Verification

```bash
SPACE=https://hetchyy-quranic-inspector-dev.hf.space

# 1. Health
curl -fsS $SPACE/healthz | jq '{oauth_configured, state_loaded, reciters_count}'

# 2. Sign in via browser as test HF account; copy session cookie.
COOKIE='session=...'

# 3. Identity
curl -fsS -b "$COOKIE" $SPACE/api/me | jq

# 4. Claim
curl -fsS -X POST -b "$COOKIE" -H "Origin: $SPACE" $SPACE/api/claim/_test_round_trip | jq '.state'
# "under_review"

hf buckets cp \
    hf://buckets/hetchyy/quranic-inspector-bucket-dev/state/reciter_state.json - \
  | jq '.reciters[] | select(.slug=="_test_round_trip")'

hf buckets cp \
    hf://buckets/hetchyy/quranic-inspector-bucket-dev/audit/$(date +%Y-%m).jsonl - \
  | tail -3 | jq 'select(.event=="reciter.claimed" and .slug=="_test_round_trip")'

# 5. Concurrent claim (two cookies)
for i in 1 2; do
  curl -fsS -X POST -b "$COOKIE_$i" -H "Origin: $SPACE" $SPACE/api/claim/_test_concurrent &
done; wait
# Expect: one 200, one 409.

# 6. Mark-ready / unmark / release round-trip via UI.

# 7. Save end-to-end (manual): trim a segment in chapter 1 → save → verify
hf buckets cp \
    hf://buckets/hetchyy/quranic-inspector-bucket-dev/wip/_test_round_trip/edit_history.jsonl - \
  | tail -1 | jq '.actor'

# 8. Maintainer override
# Sign in as a separate HF account previously granted maintainer via:
#   POST /api/admin/access/grant { hf_user_id, login, role: "maintainer", reason }
# Save the same reciter from that session — expect actor.role == "maintainer".

# 9. Revoke-force-release
# Grant maintainer to a test account → claim → owner revokes → state row's
# assignee_hf_id is null again; audit has both access.role_revoked and reciter.released.

# 10. Mixed-schema reading
curl -fsS -b "$COOKIE" $SPACE/api/seg/edit-history/saad_al_ghamdi | jq '.batches | length'
```

## Risks

- **HF behind-proxy host detection.** `ProxyFix(x_for=1, x_proto=1, x_host=1)` covers `X-Forwarded-*`. If HF does something nonstandard, `redirect_uri` will be wrong. Mitigation: log resolved `redirect_uri` in `/api/auth/login` for the first smoke test; fall back to a hardcoded `SPACE_HOST` env var if needed.
- **`huggingface_hub.upload_file()` p95 on save** — Phase 1's `force_flush_on_write` adds an HF round-trip per save. If p95 climbs >2 s on dev, contributors will feel save lag. Measure during Drop C smoke; mitigate via background-thread flush.
- **Authlib's OAuth-state store on tmpfs** — Container restart during the ~30 s authorize→callback window loses the state. Acceptable.
- **Test fixture churn** — Every existing `inspector/tests/routes/test_route_*.py` POSTing to a mutating endpoint needs `signed_in_client` migration. The fixture lands in Drop A; per-route migrations happen in their owning drops.
- **Polling-cadence noise** — 30 s polling × every signed-in user. Today 1–2 users. When concurrent sessions >20, revisit (SSE per D8).

## Reference

- [`inspector-deployment-plan.md`](../inspector-deployment-plan.md) §4 (auth + claim flow), §5 (locking model), §7 (edit-history simplifications)
- [`inspector-state-management.md`](../inspector-state-management.md) §4 (events + transition matrix), §5 (state machine impl), §8 (API endpoints + predicates), §9 (authorization)
- [`inspector-deploy-runbook.md`](../inspector-deploy-runbook.md) §3 (HF OAuth setup), §6 Phase 3 smoke tests
- [`inspector-admin-perms.md`](../inspector-admin-perms.md) §3 (single roles file)
- [`inspector-data-storage.md`](../inspector-data-storage.md) §5 (save flow), §6 (env vars)
- [`inspector-cleanup-registry.md`](../inspector-cleanup-registry.md) §2 (deletions), §3 (modifications)

## Outcomes

Phase 3 landed on the `dev` branch (sharp-curie worktree) across **8 commits** as four feature-pair drops + a docs prelude. End-to-end browser smoke against the dev Space is pending — the code is staged but not yet pushed; the dev-deploy GH Action fires on `dev` push.

### Commits

| # | Commit | Summary |
|---|---|---|
| 1 | `83249914` | docs: merge save migration into phase 3; bump oauth expiry to 1 week |
| 2 | `f6b7475f` | feat(inspector): hf oauth + signed-cookie session (Drop A1) |
| 3 | `4c145b0b` | feat(inspector-frontend): auth boot + sign-in modal + toast host (Drop A2) |
| 4 | `e828df0c` | feat(inspector): claim/release/mark-ready endpoints + reciter-task predicates (Drop B1) |
| 5 | `53628a38` | feat(inspector-frontend): claim button + reviewer banner + reciter-task polling (Drop B2) |
| 6 | `8f2fb873` | feat(inspector): wire edit-lock + actor plumbing into save/undo (Drop C) |
| 7 | `349137e1` | feat(inspector): access admin endpoints + revoke-force-release (Drop D) |
| 8 | (this commit) | docs(inspector): phase 3 outcomes — code complete |

### What shipped

- **Auth backend (Drop A1):** `services/auth.py` with Authlib OAuth + itsdangerous signed-cookie session; `routes/auth.py` with `/api/auth/{login,callback,logout}` + `/api/me`; `utils/decorators.py::require_same_origin`; ProxyFix middleware gated on `INSPECTOR_BEHIND_PROXY=1` (Dockerfile sets it); errorhandlers map `InvalidTransition`→400 / `NotAuthorizedForTransition`→403 / `UnknownReciter`→404; `/healthz` reports `oauth_configured`. **No `role` or `csrf` in the cookie** — both are derived per request (role via `access.resolve_role`; csrf via Origin/Referer check). Cookie max-age: 1 week (`hf_oauth_expiration_minutes: 10080`).
- **Sign-in UI (Drop A2):** `currentUser` / `signInModal` / `toast` stores; `signIn`/`signOut` clients; SignInModal + ToastHost components mounted at app root; header shows login + Sign out for signed-in users, "Sign in with HF" CTA for anonymous.
- **Claim endpoints (Drop B1):** `routes/claims.py` with `/api/{claim,release,mark-ready,unmark-ready}/<slug>` dispatching through `state.transition` (no decorator duplicate of state.py gating); one-claim-per-user 409; `/api/reciter-task/<slug>` returns the row + 6 server-side predicates including the new `can_edit_as_admin`.
- **Claim UI (Drop B2):** `getReciterTaskStore(slug)` with 30s polling tied to subscriber count; `claims-client.ts` maps 401→sign-in modal + toast, 409→"release X first" toast, others→error toast; `ClaimButton` (visible only when claimable; hint-mode when user holds another claim); `ReviewerBanner` for active reviewers (Mark ready / Continue editing / Release); `editing-mode.ts::syncEditingMode(user, task)` with new ViewReasons `'released'` + `'marked_ready'` + `'not-claimable'` and matching popover copy.
- **Save migration (Drop C):** `require_edit_lock(reciter_param, admin_bypass=True)` chained with `require_same_origin` + `_gate_local_writes` on `seg_save`/`seg_undo_batch`/`seg_undo_ops` + `POST /api/seg/history-peaks/<reciter>`; `services/save.py::save_seg_data` + `services/undo.py::undo_batch/undo_ops/_append_revert_record` all take kw-only `actor: Actor`; every new history batch + revert record carries `actor: {hf_user_id, login_at_time, role}`; `inspector/utils/io.py::{file_sha256,backup_file}` deleted (zero remaining callers); `routes/audio_proxy.py` POST/DELETE now require signed-in + Origin; **History panel undo + Save button hidden when `$editingMode.kind === 'view'`** (in addition to the `editGate` popover surface).
- **Access admin (Drop D):** `routes/access_admin.py` with `POST /api/admin/access/{grant,revoke,update}`; role-gated (owner-only for OWNER role, maintainer+ for MAINTAINER); reason ≥10 chars; **revoke side effect:** force-releases every UNDER_REVIEW claim held by the revoked user via `state.transition(slug, "reciter.released", actor=revoking_actor)`, surfaced in the response as `auto_released_slugs`.
- **`signed_in_client` test fixture:** Phase 3's load-bearing addition to `tests/conftest.py` — mints a session cookie + seeds `access.ACCESS_STORE` with the requested role; pairs with `tmp_reciter_dir.install(slug, fixture, under_review_for=<hf_user_id>)` and the new `tmp_reciter_dir.seed_under_review(slug, hf_user_id)` helper.

### Test outcomes

| Surface | Result |
|---|---|
| Backend pytest | **191 passed**, 14 failed (all D19 — pre-existing subprocess/scripts.lib failures unchanged from Phase 1), 4 errors (D19 audio_meta) |
| Frontend vitest | **403 passed**, 15 todo |
| Frontend tsc | clean |
| Frontend `vite build` | clean (393 KB JS gzipped 123 KB, 40 KB CSS gzipped 8 KB) |
| App boot smoke | `/api/auth/{login,callback,logout}`, `/api/me`, `/api/claim`, `/api/release`, `/api/mark-ready`, `/api/unmark-ready`, `/api/reciter-task/<slug>`, `/api/admin/access/{grant,revoke,update}` all registered; `/healthz` reports `oauth_configured` |

New test files: `test_route_auth.py` (8 cases), `test_route_claims.py` (17 cases), `test_route_access_admin.py` (13 cases), `test_route_history_peaks_lock.py` (5 cases), `editing-mode.test.ts` (13 cases on `syncEditingMode`).

Migrated test files (`signed_in_client` + Origin header + `under_review_for=...`): `test_route_save.py`, `test_route_undo.py`, `test_route_history.py`, `test_patch_undo.py`, `test_apply_command.py`, `test_auto_suppress.py`, `test_command_per_op.py`, `test_detailed_schema.py`, `test_save_clears_ignores.py`, `test_segments_json.py`, `test_uid_backfill.py`.

### Drift from contract (accepted)

- **`/api/reciter-task/<slug>` response shape.** Plan said "row + predicates"; landed as `{row, predicates}` (two top-level keys). Cleaner client-side parse than flattening.
- **`audio_proxy.py` cache-utility auth.** Plan said "require_same_origin + signed-in". Landed with both, inline check instead of a `require_signed_in` decorator — kept consistent with the route's existing one-off style.
- **`save-chart` route deletion.** Plan listed it for deletion; turns out it was already removed in Phase 1 cleanup.
- **`validate_edit_history` inline integration in `save.py`.** Plan deferred this. Confirmed not in the save path.

### Carried forward to follow-up phases / deferred

- **Browser smoke against dev Space.** Code is staged on the local worktree; `.github/workflows/inspector-deploy.yml` fires on `dev` push and rebuilds the Space. Pending: push, verify `/healthz` shows `oauth_configured: true`, sign in as `hetchyy`, claim a `_test_*` reciter, save end-to-end, verify audit log carries `actor`.
- **D19 deferred subprocess tests.** Unchanged from Phase 1 outcomes — still fail with `ModuleNotFoundError: scripts.lib` because subprocess Python doesn't add the repo root to `sys.path`. Not in Phase 3 scope.
- **D29 maintainer-edit-on-released/completed.** Documented as a new deferred item. `_h_published_edited` state-machine handler exists; no route surface yet. Phase 7 admin dashboard wires it.
- **Phase 4 admin overrides.** Four endpoints (force-release, reassign, force-set-state, send-back) + AdminReasonModal UX + validator-library splits for `validate_audio` / `validate_timestamps`.
- **Authlib OAuth callback exchange in tests.** The callback is integration-shaped (network round-trip to HF). Test coverage of that exact flow is deferred to manual browser smoke; unit tests cover the session encode/decode + identity surface.
- **SSE for cross-tab state sync (D8).** 30s polling is sufficient at current scale.

### Risks observed during local testing

- **Backend log noise.** `_hydrate_bucket_stores()` warns "state file missing on bucket" during tests that don't seed it. Harmless (degrades to empty in-memory model) but verbose in pytest output. Future cleanup could quiet this with a TESTING env check.
- **Test fixture coupling.** `signed_in_client` and `tmp_reciter_dir` both mutate `access` / `state` module-level singletons. The teardown order matters; if a test mutates after the fixture's setup it must work *with* the seeded state, not replace it. Documented inline in the access-admin tests.
- **`role` cookie staleness.** Resolved by design: `current_user()` always re-resolves role. Verified by `test_me_role_reflects_live_access_revoke`.

