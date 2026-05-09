# Inspector Authentication & Claim Flow

Companion to [`inspector-deployment-plan.md`](inspector-deployment-plan.md). Implementation-grade reference for: GitHub App configuration, token lifecycle, claim/release/mark-ready endpoint contracts, optimistic UI reconciliation, identity & attribution, edge cases, and per-phase rollout.

The parent doc covers deployment architecture and the claim flow at a sketch level. [`inspector-state-management.md`](inspector-state-management.md) owns the state file, events, and transition matrix. [`inspector-admin-perms.md`](inspector-admin-perms.md) owns role/authorization. This doc owns *authentication mechanics, identity attribution, and the user-facing claim/release/mark-ready API contract*.

## 1. Model in one paragraph

A GitHub App backs both authentication and repo writes. The App's user-to-server token flow identifies the contributor (login + id) and is used for nothing else — no `repo` scope, no git operations, no collaborator status check needed. The App's installation token does all repo writes (commit pushes, state file commits, label/body mirrors). Contributors **never become repo collaborators** — author attribution comes from setting `commit.author.email = <id>+<login>@users.noreply.github.com`, which credits them in the contribution graph regardless of repo membership. The deployed Inspector exposes mutating endpoints (`/api/claim/<slug>`, `/api/release/<slug>`, `/api/mark-ready/<slug>`, `/api/unmark-ready/<slug>`) that fire `repository_dispatch` events and return 202 with optimistic state; `update-reciter-state.yml` is the only writer of `data/reciter_state.json` and reconciliation flows back via webhook + 30 s polling backstop.

## 2. GitHub App vs OAuth App — final call

**GitHub App.** Two factors decide:

1. **Author/committer split.** Setting `author = <user>` while `committer = bot` requires an installation token doing the push. With a plain OAuth App, the user's token would have to push, which means the user's OAuth token must carry `repo` scope — a heavy permission for a "fix one timestamp" contributor and a real liability if a session leaks.
2. **Granular permissions.** App permissions are per-resource; OAuth scopes are per-user-account-wide. The App can have `Contents: write` on this repo only.

Secondary wins: 1 h installation token TTL (auto-rotation via JWT mint), team-membership lookup for maintainer role works out of the box, install once on the repo (no per-user OAuth approval flow).

## 3. App configuration

### Registration

Single GitHub App registered against the org (or a personal account if no org). Settings:

- **Name:** `Quranic Inspector`
- **Webhook:** `https://<inspector_url>/api/internal/github-webhook` — receives `installation`, `installation_repositories`, `pull_request`, `push` events for cache invalidation
- **Webhook secret:** stored as `INSPECTOR_GITHUB_WEBHOOK_SECRET` — used to verify HMAC on inbound payloads
- **Callback URL:** `https://<inspector_url>/api/auth/callback` — for user-to-server flow
- **Setup URL:** `https://<inspector_url>/setup` — post-install landing
- **Request user authorization (OAuth) during installation:** ✓
- **Expire user authorization tokens:** ✓ (8 h access + 6 mo refresh)
- **Where can it be installed:** Only this account (single repo)

### Repository permissions

| Resource | Permission | Purpose |
|---|---|---|
| Contents | Read & write | github-fetch reads + Git Data API commits + state file commits |
| Pull requests | Read & write | Open PRs, set body, mirror PR-side assignee |
| Issues | Read & write | Body re-render, label flips, comments |
| Metadata | Read | Required for any API call |
| Actions | Read | Read workflow run statuses for the admin dashboard |

### Organization permissions (only if installed on an org account)

| Resource | Permission | Purpose |
|---|---|---|
| Members | Read | `<org>/inspector-maintainers` team membership lookup |

### User permissions (user-to-server)

None beyond default. The default user-to-server token can call `GET /user` (returns login + id). We do not request `email`, `read:user`, or any other scope — the no-reply email pattern doesn't need the user's verified email.

### Permissions explicitly NOT requested

- **Administration: write** — we do not invite collaborators
- **Workflows: write** — `repository_dispatch` is fired via Contents: write semantics; no separate scope needed

### Secrets stored on the deployed backend

| Env var | Source | Rotation |
|---|---|---|
| `INSPECTOR_GITHUB_APP_ID` | App registration | Never |
| `INSPECTOR_GITHUB_APP_PRIVATE_KEY` | App registration → Generate private key | On suspected compromise — minutes via App settings |
| `INSPECTOR_GITHUB_INSTALLATION_ID` | App install on repo | Stable until reinstall |
| `INSPECTOR_GITHUB_WEBHOOK_SECRET` | App registration | Quarterly |
| `INSPECTOR_SESSION_SECRET` | Generated locally | Quarterly |
| `INSPECTOR_INTERNAL_SECRET` | Generated locally | Quarterly — used for workflow → backend webhook auth |

No PATs. No long-lived OAuth tokens. The App's private key is the only long-lived credential.

## 4. Token lifecycle

| Token | Lifetime | Refresh path | Where stored | Used for |
|---|---|---|---|---|
| App installation token | 1 h | JWT signed with private key → `POST /app/installations/<id>/access_tokens` | In-memory cache, refreshed at T-5 min | All repo writes + github-fetch reads + `repository_dispatch` |
| User-to-server access token | 8 h | Refresh token → token endpoint | Encrypted server session | `GET /user` for login during sign-in; never used after session establishment |
| User-to-server refresh token | 6 mo (single-use) | Returns new pair on use | Encrypted server session | Silent re-auth on user-token expiry |
| Session cookie | 30 d sliding | Reset on every request | Signed cookie (HMAC of session id) | Maps cookie → server-side session record `{ login, github_id, refresh_token, expires_at }` |

### Installation token refresh

Single-flight cache:

```python
class AppTokenCache:
    _token: str | None = None
    _expires_at: datetime | None = None
    _lock = asyncio.Lock()

    async def get(self) -> str:
        async with self._lock:
            if not self._token or (self._expires_at - now()) < timedelta(minutes=5):
                self._token, self._expires_at = await self._mint()
            return self._token
```

Mint: JWT with `iss=APP_ID`, `iat=now`, `exp=now+10min` signed with the App's private key (RS256), exchanged at `POST /app/installations/<INSTALLATION_ID>/access_tokens` for a 1 h token.

### User-to-server flow

1. User clicks **Sign in with GitHub** → redirect to `https://github.com/login/oauth/authorize?client_id=<APP_CLIENT_ID>&redirect_uri=...&state=<csrf>`
2. User approves → callback hits `/api/auth/callback?code=<code>&state=<csrf>`
3. Backend verifies CSRF, exchanges code at `POST https://github.com/login/oauth/access_token` → `(access_token, refresh_token, expires_in)`
4. Backend calls `GET /user` with the access token → `{ login, id, ... }`
5. Backend creates server-side session, sets signed session cookie
6. Redirect back to the originating page (preserved via `state` payload)

### User token refresh

The user-to-server token is used **only at sign-in**. After that, identity comes from the session cookie. Refresh is a defensive fallback for long-lived sessions that occasionally re-validate identity. On 401:

- Use the refresh token to mint a new pair
- If refresh also returns 401: clear the session, surface re-sign-in modal

## 5. Identity and commit attribution

### Email pattern

Every Inspector commit sets:

```
author.name     = <login>
author.email    = <github_id>+<login>@users.noreply.github.com
committer.name  = github-actions[bot]
committer.email = github-actions[bot]@users.noreply.github.com
```

The `<id>+<login>` form is GitHub's documented public no-reply pattern. It:

- Ties the commit to the user's GitHub account for contribution-graph purposes
- Doesn't expose the user's verified email
- Survives display-name changes (id is permanent)
- Works for any GitHub user — no collaborator status required

### Where the user shows up

| Surface | Driven by | Works without collab? |
|---|---|---|
| User's profile contribution graph | `author.email` matching their GitHub identity | ✓ |
| Repo Insights → Contributors | Squash-merge commit's author or `Co-authored-by:` trailers on `main` | ✓ if squash-merge preserves trailers |
| `segments-pr-merged.yml` author roundup | `git log --format=%ae` on PR branch | ✓ |
| GitHub issue native assignee field | `POST /issues/.../assignees` — requires collaborator | ✗ — silently skipped for non-collabs |
| State workflow body-table "Assigned to" line | `state.reciters[<slug>].assignee` from file | ✓ |

### Squash-merge attribution requirement

Default GitHub squash-merge can lose author attribution if the merger is different from the PR's commit authors. Required repo configuration:

- **Settings → Pull Requests → Allow squash merging** — checked
- **Default to PR title and description for the squash commit message** — checked. This preserves `Co-authored-by:` trailers from the squashed commits, which is what credits the user on the Contributors tab.

Acceptance test in Phase 5a: open a test PR with a few `[wip]` commits authored by a non-collab user, squash-merge via the API/UI, verify the merged commit on `main` shows the user as author OR carries a `Co-authored-by: <login> <id+login@users.noreply.github.com>` trailer. If neither, the repo squash settings need fixing.

### CODEOWNERS interaction

Squash-merge with `Co-authored-by:` trailers is preserved regardless of CODEOWNERS rules. CODEOWNERS only affects review-required state, not attribution.

## 6. Endpoint contracts

All mutating endpoints fire `repository_dispatch` and return 202 with optimistic state. Reconciliation via state-changed webhook + 30 s polling backstop.

### `GET /api/me`

```
Auth: session cookie
Response: 200
{
  "login": "alice",
  "id": 12345,
  "noreply_email": "12345+alice@users.noreply.github.com",
  "role": "contributor" | "maintainer" | "owner",
  "active_claim": "<slug>" | null
}
```

`active_claim` is a one-claim-per-user lookup; populated if the user has any reciter where `assignee == login && state in (under_review, ready_for_merge)`.

### `GET /api/auth/login`

Initiates user-to-server flow. Sets CSRF cookie, redirects to GitHub authorize URL. Captures the `?return=<path>` query for post-login redirect.

### `GET /api/auth/callback`

Handles the GitHub redirect. Verifies CSRF, exchanges code, fetches `/user`, creates session, redirects to `return` path.

### `POST /api/auth/logout`

Clears the session cookie. Does NOT release any active claim — the user can sign back in and resume.

### `POST /api/claim/<slug>`

```
Auth: session cookie required → 401
```

1. Look up `entry = state_store.reciters[slug]`. 404 if missing.
2. State guard: `entry.state == 'awaiting_review'`. 409 with current `state` and `assignee` otherwise.
3. **One-claim-per-user**: scan `state_store` for any entry where `assignee == user.login && state in (under_review, ready_for_merge)`. If found → 409 `{ "existing_claim": "<other_slug>" }`. Maintainers and owners bypass this check (audit-logged when they hold >1).
4. Acquire in-process single-flight mutex on `slug`.
5. Re-validate inside mutex.
6. Fire `repository_dispatch`:
   ```json
   { "event_type": "reciter.claimed",
     "client_payload": { "slug": "<slug>", "login": "<login>", "id": <id>, "at": "<iso8601>" } }
   ```
7. Optimistic update on local `state_store`: set `assignee, state = under_review, assignee_since = now(), optimistic_until = now()+30s`.
8. Return 202:
   ```json
   {
     "state": "claim_dispatched",
     "optimistic": { "state": "under_review", "assignee": "<login>" },
     "expect_reconcile_within_seconds": 10
   }
   ```

### `POST /api/release/<slug>`

```
Auth: session cookie → 401
```

1. Verify `entry.state in (under_review, ready_for_merge) && entry.assignee == user.login`. 403 otherwise.
2. **Flush scratch dir** if any unflushed edits — block up to 30 s for the Git Data API commit. Required so the abandoning reviewer's last edits land on the PR branch for the next reviewer to continue from.
3. Fire `reciter.released { slug, login }`.
4. Optimistic: clear `assignee`, `state = awaiting_review`.
5. 202 with optimistic state.

Release is idempotent: a second release on a state that's already `awaiting_review` returns 200 with current state.

### `POST /api/mark-ready/<slug>`

```
Auth: session cookie → 401
```

1. Verify `entry.state == 'under_review' && entry.assignee == user.login`. 403 otherwise.
2. **Flush scratch dir** for any pending edits. The marked-ready commit should reflect everything the reviewer intends.
3. Fire `reciter.marked_ready { slug, login }`.
4. Optimistic: `state = ready_for_merge`. Assignee unchanged.
5. 202 with optimistic state.

### `POST /api/unmark-ready/<slug>`

```
Auth: session cookie → 401
```

1. Verify `entry.state == 'ready_for_merge' && entry.assignee == user.login`. 403 otherwise.
2. Fire `reciter.unmarked_ready { slug, login }`.
3. Optimistic: `state = under_review`. Assignee unchanged.
4. 202 with optimistic state.

### `GET /api/reciter-task/<slug>`

```
Auth: optional (returns view-only fields if anonymous)
```

Read-only lookup against in-memory `state_store`:

```jsonc
{
  "slug": "saad_al_ghamdi",
  "state": "under_review",
  "state_since": "...",
  "issue_number": 42,
  "pr_number": 89,
  "pr_head_sha": "abc1234",
  "assignee": "alice",
  "first_time_reviewer": false,
  "can_edit_for_current_user": false,
  "can_mark_ready_for_current_user": false,
  "can_unmark_ready_for_current_user": false,
  "can_release_for_current_user": false,
  "can_claim_for_current_user": false,
  "optimistic": false
}
```

Predicates:

```python
can_edit         = state == 'under_review'      and assignee == user.login
can_mark_ready   = state == 'under_review'      and assignee == user.login
can_unmark_ready = state == 'ready_for_merge'   and assignee == user.login
can_release      = state in ('under_review', 'ready_for_merge') and assignee == user.login
can_claim        = state == 'awaiting_review'   and user is not None and not user_has_other_active_claim
```

### Internal endpoints

```
POST /api/internal/state-changed     → workflow notifies backend; auth: shared secret
POST /api/internal/cache-invalidate  → workflow notifies backend on merge; auth: shared secret
POST /api/internal/github-webhook    → GitHub delivers events; auth: HMAC signature
```

## 7. Optimistic UI and reconciliation

Mutating endpoints return 202 immediately after firing dispatch. Frontend optimistically flips lock-banner / mark-ready button / etc. The state workflow runs (~30 s end-to-end) and POSTs `/api/internal/state-changed`. Backend re-fetches the state file. Optimistic state is replaced by authoritative state.

### Backend-side optimism

Each entry in `state_store` carries an optional `optimistic_until: datetime`. While set:

- `can_*` predicates use the optimistic values
- Reads to `/api/reciter-task` return `optimistic: true`
- After `optimistic_until` passes without reconciliation, the optimistic flag flips to "stale" and the entry is treated as authoritative-but-suspicious

When the workflow webhook fires:

- Re-fetch state file via github-fetch (forced fresh, bypassing TTL)
- Replace the entry. If authoritative state matches optimistic → silent reconciliation. If not → reconciliation diff is logged for observability.

### Frontend-side polling

After any mutating action, frontend polls `/api/reciter-task/<slug>`:

- 1 s interval for the first 10 s post-action
- 5 s interval for the next 50 s
- 30 s interval thereafter (matches global heartbeat)
- Pause when `document.hidden`

If after 60 s the backend still reports `optimistic: true`, surface a non-blocking toast: "State syncing is taking longer than usual."

### Workflow rejection

If the workflow rejects the event (e.g. business rule violation per state-mgmt §5):

- State file is unchanged
- Webhook still fires (or doesn't — workflow may exit non-zero before mirror step)
- Backend's poll sees authoritative state diverging from optimistic
- Frontend toast: "Action failed: <reason from workflow comment>"

## 8. UX flows

### A. Anonymous → claim (returning contributor with active session)

1. Click **Claim**.
2. Page optimistically flips to edit mode, banner: "You're reviewing X. [Mark ready] [Release]".
3. Within ~10 s authoritative state replaces optimistic — invisible to user.

**1 click.**

### B. Anonymous → claim (first-time visitor)

1. Click **Claim** → modal: "Sign in with GitHub to claim. [Continue]".
2. Click Continue → GitHub App authorize page.
3. Approve → land back on reciter page in optimistic edit mode.

**3 clicks (Claim → Continue → Authorize).** No invite, no waiting tab, no polling for collaborator status.

### C. Mark ready

1. Reviewer finishes → click **Mark ready** in banner.
2. Confirm modal: "Mark this reciter as ready for maintainer review? Your last edits will be committed first. [Mark ready] [Cancel]"
3. Backend flushes scratch, fires dispatch, returns 202.
4. Banner flips to: "Awaiting maintainer review. [Continue editing] [Release]". Save buttons disabled.

### D. Maintainer merges → reviewer sees state advance

1. Reviewer leaves the tab open.
2. Maintainer clicks Squash & Merge on github.com.
3. `segments-pr-merged.yml` fires `reciter.review_merged`.
4. State file updates to `awaiting_timestamps`.
5. Reviewer's tab polls, sees state advance. Banner: "Merged ✓ — pending timestamps."

### E. Send back from ready

1. Maintainer reviews PR, requests changes (admin force or simply notifies the reviewer to unmark themselves).
2. Reviewer (or maintainer-fired admin event per [`inspector-admin-perms.md`](inspector-admin-perms.md) §5.10) calls `unmark-ready` → state flips back to `under_review`.
3. Reviewer's banner: "Reviewing X. [Mark ready] [Release]". Save re-enabled.

### F. Release (abandon)

1. Reviewer realizes they can't finish → click **Release**.
2. Confirm modal: "Release this claim? Your last edits will be committed to the PR for the next reviewer. [Release] [Cancel]"
3. Backend flushes, fires dispatch.
4. Banner removed, page in view-only mode. Reciter back on the Available tab.

### G. Session expiry mid-edit

1. User-to-server token silent-refresh on backend if the stored refresh token is still valid.
2. If refresh token also expired (>6 mo): non-blocking modal "Your sign-in expired. [Sign in to continue]".
3. Edits buffered in localStorage during the expired window.
4. Re-auth flow in popup.
5. On return, replay buffered edits via normal save endpoint. The user's claim survives — `state.assignee` still equals their `login`.

### H. App access revoked by user (github.com → settings → applications → revoke)

1. Backend's stored refresh token returns 401 on next use.
2. UI shows: "GitHub access was revoked. Sign in again to continue."
3. Re-authorize → new tokens issued, claim still active.
4. If user removes access permanently and walks away: their claim sits idle until a maintainer force-releases ([`inspector-admin-perms.md`](inspector-admin-perms.md) §5.1) or the 14-day reconciler flag fires.

## 9. Edge cases

| Scenario | Behavior |
|---|---|
| **Concurrent claims** on same `awaiting_review` reciter | State workflow `concurrency: { group: reciter-state }` serializes. First event wins. Second rejected by §5 business rule. Loser's frontend reconciles to authoritative on next poll → toast "Already claimed by @other". |
| **One claim per user** violation | API returns 409 `existing_claim: <slug>`. Frontend toast: "Release [other] first to claim [this]." |
| **Same user, two tabs, same reciter** | In-process mutex on `(slug, login)` serializes save bursts. Both tabs see same authoritative state. |
| **Same user, two tabs, claim + release race** | Fired sequentially through dispatch; state workflow serializes. Loser sees stale optimistic flip-then-reconcile. Acceptable. |
| **Mark-ready while save in flight** | `/api/mark-ready` flushes scratch first. If a save POST is mid-flight and not-yet-debounced, mark-ready waits for the in-flight save to land in scratch, then flushes. Bounded by HTTP timeout. |
| **Branch force-pushed externally** | Git Data API commit's `force: false` returns 422. Modal: "Branch changed externally. [Reload latest] [Download edits as JSON]". Branch protection rule blocks force-push from non-App actors. |
| **PR closed without merging** | No event currently fires; reconciler flags drift > 24 h. Maintainer fixes via `state.manual_override` to `awaiting_review` (claim cleared) or `discarded`. |
| **PR merged while reviewer has unflushed edits** | `segments-pr-merged.yml` sends `cache-invalidate`. Backend's debounce timer still fires for the now-merged branch — Git Data API commit fails (branch is closed or unborn). Edits saved to localStorage; modal: "Merged before your last edits flushed. [Download edits as JSON]". |
| **App installation removed by org admin** | Installation tokens return 401. All write endpoints 503 with banner: "Inspector temporarily offline — App installation removed. Maintainers notified." Read endpoints serve stale state from in-memory cache; recover when App re-installed. |
| **GitHub team API outage** (maintainer role check fails) | Fail-closed — treat as `contributor`. Maintainer affordances temporarily unavailable. Owner role still works (file-based, no API call). |
| **State workflow run never fires** (dispatch lost) | Reconciler cron sweeps daily; backfills missing transitions. Worst case 24 h latency to detection. |
| **Workflow runs but webhook to backend dropped** | 30 s polling backstop catches it. |
| **Stuck `ready_for_merge`** (maintainer never merges) | Reconciler flags >7 days; admin dashboard surfaces in stalled-reciters tab. No automatic action. |
| **Reviewer marks ready, then walks away forever** | Maintainer can merge, send back via admin override, or release on their behalf via force-release ([`inspector-admin-perms.md`](inspector-admin-perms.md) §5.1). |
| **User clicks claim twice rapidly** | Single-flight mutex serializes. Second call sees `state == under_review && assignee == self`, returns 200 idempotently. |
| **Email leakage** | Always `<id>+<login>@users.noreply.github.com`. We never read the user's primary email; `email` scope not requested. |
| **Forged identity claim** | Backend never trusts user-supplied `login`. Identity comes from the GitHub-validated session cookie. Authorization checks (`is_team_member`, etc.) go through the App, not the user's view. |

## 10. Security model

### Threat: session theft

Mitigations:

- Session cookie is HttpOnly + Secure + SameSite=Lax, signed with HMAC.
- Server-side session record holds the actual identity; cookie is just an opaque session id.
- Logout invalidates the session record server-side.
- Sessions expire after 30 days of inactivity.

### Threat: CSRF on mutating endpoints

Mitigations:

- All mutating endpoints require either a same-site session cookie + origin/referer check, or an explicit CSRF token in the request header.
- The OAuth flow's `state` parameter prevents CSRF on auth itself.

### Threat: malicious contributor pushing destructive edits

Limits:

- Edit lock enforces one writer per reciter, per state-mgmt §5.
- All edits land on a PR branch, never on `main`. Squash-merge is gated by maintainer review.
- Edit history is append-only and signed by `author = user`. Audit trail is permanent.
- Force-push blocked on `reciter/*` for non-App actors via branch protection.

### Threat: App private key leaked

Mitigations:

- Stored as a Fly.io secret (encrypted at rest, only injected at runtime).
- Rotation is a 5-minute operation in App settings.
- The key only mints installation tokens; no user data exposure.

### Threat: maintainer impersonation

Mitigations:

- Role resolution always queries the GitHub team membership API (not a user-supplied claim).
- The owners list lives in `data/inspector_owners.json` and is owner-edit-gated via CODEOWNERS.
- Audit log captures every elevated action with `actor` field set from the GitHub-validated session.

## 11. Phased rollout

### Phase 0 — App registration

- Register the GitHub App against the org.
- Generate private key, store as `INSPECTOR_GITHUB_APP_PRIVATE_KEY` secret.
- Install on the repo; capture installation id as `INSPECTOR_GITHUB_INSTALLATION_ID`.
- Configure repo squash-merge to use "PR title and description" for commit message (preserves `Co-authored-by:`).
- Add branch protection rule blocking force-push on `reciter/*` branches except for the App.

**Acceptance:** App installation id is documented; private key rotates cleanly via App settings UI; squash-merge of a test PR preserves `Co-authored-by:` trailers.

### Phase 1 — Read-only deploy

Out of scope of this doc. github-fetch uses the App installation token; backend boots with the App credentials; no user auth yet.

### Phase 3 — Auth + claim flow

In scope of this doc:

- `/api/auth/login`, `/api/auth/callback`, `/api/auth/logout`
- Session cookie + server-side session store
- `/api/me` endpoint
- `/api/claim/<slug>`, `/api/release/<slug>`, `/api/mark-ready/<slug>`, `/api/unmark-ready/<slug>` — all firing dispatch and returning 202 with optimistic state
- Optimistic state machine in `state_store`
- Frontend polling cadence on `/api/reciter-task/<slug>`
- Single-flight mutex per slug
- One-claim-per-user enforcement (with maintainer/owner bypass + audit)

**Acceptance:**

- A first-time visitor can claim a reciter in 3 clicks; no collaborator invite is sent.
- Returning user with active session claims in 1 click.
- Two simultaneous claims on the same reciter: one succeeds, one rejected with toast within 10 s.
- Mark-ready → unmark-ready round-trip preserves assignee and edit state.
- Release after mark-ready clears assignee and returns reciter to `awaiting_review`.
- Sign-out + sign-in preserves an active claim.
- App revoked by user → re-auth flow surfaces; claim survives.

### Phase 5a — Writes

Saves enabled. Edit-lock decorator uses `state_store.assignee` lookup. Out of scope of this doc beyond the flush semantics on release/mark-ready.

**Acceptance test specific to attribution:**

- Reviewer with no prior repo collaboration completes a save → debounced commit on PR branch shows `author = <id>+<login>@users.noreply.github.com`, `committer = github-actions[bot]`.
- Squash-merge of the PR → `main` commit carries `Co-authored-by: <login> <id+login@users.noreply.github.com>` trailer.
- Reviewer's GitHub profile contribution graph credits the merge.
- Reviewer appears in the repo's Contributors tab.

### Phase 6 — Cleanup

- Audit `data/inspector_owners.json` membership.
- Set up quarterly App credentials rotation reminder.
- Add CI check that fails if `Administration: write` shows up in the App's permissions snapshot (regression guard).

## 12. Risks and open questions

### Squash-merge attribution regression

Repo squash-merge settings can be silently changed by a maintainer with admin rights. If switched away from "PR title and description," `Co-authored-by:` trailers stop preserving and contribution credit breaks. Mitigation: a CI check that periodically verifies the repo settings via the API, OR documentation in the maintainer onboarding.

### App revoked by user mid-debounce

User revokes App while a debounce timer is pending. Their installation token is still valid (per-installation, not per-user), so the commit lands fine. But the user's session is broken on next request. Edits land, state persists, user sees the re-auth flow. No data loss.

### Bot loop on mirror failure

State workflow's mirror step fails (e.g. issue locked manually). Workflow exits non-zero. State file commit landed; mirror didn't. Drift. Mitigation: mirror step is idempotent and re-runnable; `update-reciter-state.yml` has a `--repair` mode invoked by the reconciler that re-applies mirrors for any state file entry whose mirrored fields disagree.

### Frontend over-polling on stuck workflow

If many users hit a stuck claim simultaneously, each polls `/api/reciter-task/<slug>` at 1 s for 10 s. With backend in-memory cache that's fine; with cache-miss every time, GitHub rate limit hit. Mitigation: server-side cache for `/api/reciter-task` returns recent in-memory snapshot; only invalidates on webhook.

### Session store sizing

30 days × N concurrent users × ~1 KB/session = small. With a single backend node and modest scale (≤100 active users), in-memory dict is fine. With multi-node or larger scale, move to Redis/Postgres/Fly.io's KV. Decision: defer until measured.

### CSRF gap during dev

Local-dev cookie isn't `Secure`, and if the dev server runs on a non-localhost domain, SameSite=Lax may allow cross-site POST. Document: dev mode only on `localhost` or same-origin.

### One-claim-per-user too restrictive for power users

Maintainers/owners bypass the rule with audit-log entry on each additional claim. Contributors are capped at 1 to prevent ghost claims accumulating across the dataset.

### Self-revocation of claim on sign-out

Currently sign-out preserves the claim. Argument for: user signs back in, picks up where they left off. Argument against: if they sign out at a shared computer, their claim sits forever. Resolution: keep current behavior (claim survives sign-out); the 14-day stalled-claim reconciler is the safety net.

### CLI fallback contributors

Users who prefer git CLI to the web Inspector still need write access to push. They get invited as collaborators by a maintainer manually, on request — not auto-invited by the website. The `/claim` and `/confirm` issue-comment commands remain wired through `issue-commands.yml`, which fires the same `reciter.claimed` / `reciter.released` events as the web endpoints.
