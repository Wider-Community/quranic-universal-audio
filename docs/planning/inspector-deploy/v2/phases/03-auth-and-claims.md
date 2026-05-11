# Phase 3 — Auth + claim flow

> HF OAuth lands. Signed-in contributors can claim/release/mark-ready/unmark-ready a reciter, and the bucket state file reflects it within the request handler. No save endpoint yet, no admin actions yet — but the lock decorator, role resolution, and audit log are all live.

**Status:** not started
**Depends on:** Phase 2 (Deployable image) complete
**Blocks:** Phase 4

## Goal

Identity is HF OAuth, sessions are self-contained signed cookies (no server-side session record). Claim transitions are synchronous, write the bucket JSON via `huggingface_hub.upload_file()`, and append to `<bucket>/audit/<YYYY>-<MM>.jsonl`. Lock ownership is keyed on `assignee_hf_id` everywhere — login renames don't break locks. Role resolution uses `<bucket>/access/inspector_roles.json` via `services/access.py` (in-memory cache hydrated at startup; Inspector is sole writer so the cache is correct by construction — no force-refresh endpoint needed). At the end of this phase a contributor can claim, mark-ready, unmark, and release through the website end-to-end.

## Deliverables

- [ ] `inspector/services/auth.py` — Authlib + Flask `itsdangerous` signed-cookie session carrying `{login, hf_user_id, role, expires_at, csrf}`
- [ ] `inspector/services/access.py` — sole-writer for `<bucket>/access/inspector_roles.json`; in-memory cache hydrated at startup + replaced on every Inspector write; grant/revoke/update admin endpoints land here
- [ ] OAuth endpoints: `GET /api/auth/login`, `GET /api/auth/callback`, `POST /api/auth/logout`
- [ ] `GET /api/me` — returns `{ login, hf_user_id, role, active_claim }`
- [ ] Authlib OAuth-state store on Flask-Session (tmpfs, ~30 s lifetime, `/tmp/inspector-flask-sessions/`)
- [ ] `Space README.md` frontmatter `hf_oauth: true` + `hf_oauth_expiration_minutes: 480`
- [ ] `inspector/utils/decorators.py::require_edit_lock(reciter_param='reciter')` — keyed on `assignee_hf_id == user.hf_user_id`, additionally checks `state == 'under_review'`, `not marked_ready`, `visibility == 'public'`
- [ ] Claim endpoints (all return 200 with authoritative row; per-slug `threading.Lock` from Phase 1):
  - `POST /api/claim/<slug>` — `reciter.claimed`
  - `POST /api/release/<slug>` — `reciter.released`
  - `POST /api/mark-ready/<slug>` — `reciter.marked_ready` (no state transition)
  - `POST /api/unmark-ready/<slug>` — `reciter.unmarked_ready`
- [ ] `GET /api/reciter-task/<slug>` — full row + `can_*` predicates per state-mgmt §8
- [ ] One-claim-per-user enforcement on `/api/claim/<slug>`
- [ ] Claim-flow UI: "Claim" button on Available reciter rows, sign-in modal, post-callback redirect to original page in edit mode, banner "You're reviewing X. [Mark ready] [Release]"
- [ ] Lock banner UX for non-assignees on a claimed reciter ("Currently claimed by @<login>")
- [ ] Frontend polls `/api/reciter-task/<slug>` every 30 s while on a reciter page (state freshness)
- [ ] Audit log writes via `services/audit.py` from Phase 1 — every claim/release/mark/unmark appends a line with `actor: {hf_user_id, login_at_time, role}`
- [ ] `INSPECTOR_SESSION_SECRET` set on dev Space; signed-cookie verification working

## Out of scope

- Save endpoint (`/api/seg/save`) — Phase 4.
- Any admin override actions (force-release, reassign, force-set-state, send-back) — Phase 4.
- `/admin` route + dashboard panels — Phase 7.
- Publish endpoint — Phase 5.
- Force-claim mechanism — deferred entirely (per D15).
- Server-Sent Events for cross-tab state sync — deferred (D8).

## Acceptance criteria

- [ ] First-time visitor signs in and claims a reciter in **3 clicks max** (Claim → Continue modal → HF Authorize).
- [ ] Returning user with active session claims in **1 click**.
- [ ] After claim, `<bucket>/state/reciter_state.json` shows `assignee_hf_id == <user's HF sub>`, `assignee_login == <login>`.
- [ ] After claim, `<bucket>/audit/<YYYY>-<MM>.jsonl` has a `reciter.claimed` line with the user's `hf_user_id`.
- [ ] Two simultaneous claim attempts on the same reciter from different sessions: first wins, second receives `409 existing_claim` immediately (no propagation lag).
- [ ] One-claim-per-user violation returns `409 existing_claim: <other_slug>` with toast "Release [other] first to claim [this]".
- [ ] Mark-ready (`marked_ready=1`) → unmark (`marked_ready=0`) round-trip preserves `assignee_*` fields.
- [ ] Release after mark-ready clears `assignee_*`, sets `marked_ready=0`, transitions `under_review → awaiting_review`.
- [ ] Lock decorator returns 403 if a non-assignee POSTs to a claim endpoint with someone else's slug.
- [ ] Session cookie survives container restart (signed; not server-side).
- [ ] Logout clears the cookie; the user's claim is NOT released by logout (deliberate — release is a separate action).
- [ ] Role resolution reads `<bucket>/access/inspector_roles.json` at startup into in-memory cache; subsequent writes from `services/access.py` keep the cache fresh (sole-writer pattern → no external refresh).
- [ ] `assignee_hf_id` is the only field used for ownership comparison anywhere in the request path (grep verifies no `assignee_login == user.login` patterns).

## Verification

```bash
SPACE=https://hetchyy-quranic-inspector-dev.hf.space

# 1. Sign in to dev Space with a test HF account in browser.
# 2. Click Claim on an _test_* reciter in awaiting_review.
# 3. Verify in another shell:
hf buckets cp \
    hf://buckets/hetchyy/quranic-inspector-bucket-dev/state/reciter_state.json - \
  | jq '.reciters[] | select(.slug == "_test_<slug>")'
# Expect assignee_hf_id == <your sub>, state == "under_review", marked_ready == false

hf buckets cp \
    hf://buckets/hetchyy/quranic-inspector-bucket-dev/audit/$(date +%Y-%m).jsonl - \
  | tail -20 | jq 'select(.event == "reciter.claimed" and .slug == "_test_<slug>")'

# Concurrent claim test (curl with cookie jar)
for i in 1 2; do
  curl -fsS -X POST -b "session=$COOKIE_$i" $SPACE/api/claim/_test_concurrent &
done; wait
# Expect: one 200, one 409

# Mark-ready / unmark round-trip
curl -fsS -X POST -b "session=$COOKIE" $SPACE/api/mark-ready/_test_<slug> | jq '.marked_ready'    # true
curl -fsS -X POST -b "session=$COOKIE" $SPACE/api/unmark-ready/_test_<slug> | jq '.marked_ready'  # false

# Login-rename safety: simulate by POSTing /api/release with a stale cookie
# whose login differs from the bucket's assignee_login but hf_user_id matches.
# Should succeed (hf_user_id-keyed).
```

## Risks

- **Authlib + Flask + signed cookies** — the OAuth-state store between `/authorize` and `/callback` needs server-side persistence on tmpfs. Container restart mid-flow loses it; ~30 s window. Acceptable.
- **Cookie max-age vs HF token lifetime** — cookie expiry is enforced by Inspector; HF token revocation by the user mid-session does NOT log them out (the cookie keeps working until expiry). Document in runbook §3.
- **Role refresh-on-cache-miss** — if GitHub raw is down at the moment of a cache miss, the request blocks ~30 s on the fetch. Mitigation: short HTTP timeout + baked-snapshot fallback. Implement timeout explicitly.
- **`active_claim` lookup** — `/api/me` needs to know if the current user holds any claim. Linear scan over the in-memory state_store is fine at 300 reciters; add an index later if it ever appears in a perf trace.

## Reference

- [`inspector-deployment-plan.md`](../inspector-deployment-plan.md) §4 (auth + claim flow), §5 (locking model)
- [`inspector-state-management.md`](../inspector-state-management.md) §4 (events + transition matrix), §5 (state machine impl), §8 (API endpoints + predicates), §9 (authorization)
- [`inspector-deploy-runbook.md`](../inspector-deploy-runbook.md) §3 (HF OAuth setup), §6 Phase 3 smoke tests
- [`inspector-admin-perms.md`](../inspector-admin-perms.md) §3 (single roles file)
