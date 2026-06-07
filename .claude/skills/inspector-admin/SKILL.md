---
name: inspector-admin
description: Headless one-off Inspector admin operations — wraps the same services/admin/* and state.transition the UI calls. Use for quick patches when the Reviews/Users/Permissions/Requests UI surface isn't enough — publish a finished TS job, force-unlock a released reciter, cancel + relaunch a stuck HF job, force-release a stale claim, grant a role, run raw DB SQL.
---

# inspector-admin

Headless one-off admin ops. Every script wraps the same `inspector/services/admin/*` + `inspector/services/state/state.transition` the UI calls — no parallel logic, no schema drift. Use when:

- a quick prod patch is needed and walking through the UI is wasteful
- the UI doesn't expose an op you need (raw SQL, bulk state flip, lookup-by-id)
- iterating on something that just failed (cancel stuck job, force-publish, etc.)

## Knowledge — pointers, not narration

Don't re-derive subsystem facts in this skill. Open the reference doc.

| Concept | Reference |
|---|---|
| State machine — lifecycle states, valid events per state, payload shape, `transition()` semantics | [`docs/reference/state-machine.md`](../../../docs/reference/state-machine.md) |
| Capabilities — which gate guards which action, owner-only set, the resolver | [`docs/reference/capabilities.md`](../../../docs/reference/capabilities.md) |
| Auth / OAuth / actor — `Actor` record, edit-lock, CSRF, role tiers | [`docs/reference/auth-permissions.md`](../../../docs/reference/auth-permissions.md) |
| Admin UI surface — Users / Reviews / Permissions / Requests compartments, `/api/admin/*` shape | [`docs/reference/admin-dashboard.md`](../../../docs/reference/admin-dashboard.md) |
| SQLite substrate — `durable_transaction`, db_seq CAS, bucket sync mechanics | [`docs/reference/database.md`](../../../docs/reference/database.md) |
| Catalog layers + slug convention + audio manifest sidecar | [`docs/reference/catalog.md`](../../../docs/reference/catalog.md) |
| TS-job format + lifecycle + webhook + poll fallback + publish path | [`docs/reference/timestamps-job.md`](../../../docs/reference/timestamps-job.md) |
| Env vars + `INSPECTOR_BUCKET_REPO` / `INSPECTOR_ALLOW_PROD_BUCKET` semantics | [`docs/reference/config-deploy.md`](../../../docs/reference/config-deploy.md) |

Always open the matching reference before invoking a mutation — the event name + payload shape come from `state-machine.md`, the gate comes from `capabilities.md`. Don't guess.

## Scripts

Every script:
- defaults to the dev bucket; `--prod` for prod
- mutating ops against prod additionally require `--yes-prod` on the command line (no env opt-in)
- `--dry-run` runs the handler up to (but not through) `durable_transaction`
- writes audit entries as the real `INSPECTOR_DEV_OWNER_HF_ID`/`_LOGIN` from `.env` so prod audit doesn't show `dev-owner`

| Script | What it does |
|---|---|
| `scripts/admin_state.py SLUG --event EVENT [--reason R] [--payload '{...}']` | Generic `state.transition` wrapper. Event names → see `state-machine.md`. |
| `scripts/admin_publish.py SLUG --job-id JOB_ID` | `complete_timestamps_job`: under_review+marked_ready → released. Used when the deployed Space's webhook missed a callback. |
| `scripts/admin_ts_job.py {launch,cancel,status,record,history,publish,monitor} SLUG [JOB_ID] [...]` | TS-job lifecycle CLI (one home for what `launch_ts_job.py` used to do, plus cancel/status/publish). |
| `scripts/admin_release.py {preview,cut,monitor} [JOB_ID] [...]` | GH release preview + cut helper using the shared release-preview renderer and cut-release job service. |
| `scripts/admin_claim.py SLUG {show,release,reassign} [--to LOGIN]` | Force-release or reassign a claim. |
| `scripts/admin_users.py {list,show,grant,revoke} [--hf-id ID] [--login L] [--role owner\|maintainer\|contributor]` | User mgmt — list, look up, change role. |
| `scripts/admin_requests.py {list,show,resolve} [REQUEST_ID]` | Browse and act on the request queue. |
| `scripts/admin_perms.py {matrix,set,reset} [--cap ID --tier T --allowed {0,1}]` | Owner-only capability overrides. |
| `scripts/admin_db.py exec "SQL" [--write]` | Raw SQL against the pulled DB. Read-only by default; `--write` opens the writer + syncs back. |
| `scripts/admin_reciter.py SLUG` | One-shot dump: state row, claim, recent transitions, linked TS-job ids+statuses, bucket file inventory. |

## Common recipes

```
# Publish a finished TS job whose webhook never reached the deployed Space
python .claude/skills/inspector-admin/scripts/admin_publish.py <slug> --job-id <hf-job-id> --prod --yes-prod

# Reopen a released reciter for editing (admin.unlocked_for_revision)
python .claude/skills/inspector-admin/scripts/admin_state.py <slug> --event admin.unlocked_for_revision --reason "fix qalqala letters" --prod --yes-prod

# Cancel a stuck TS job + relaunch with safer settings
python .claude/skills/inspector-admin/scripts/admin_ts_job.py cancel <slug> <job_id> --prod --yes-prod
python .claude/skills/inspector-admin/scripts/admin_ts_job.py launch <slug> --beams 30,2 --workers 4 --dl-workers 4 --prod --yes-prod --monitor

# Look up the full state of one reciter
python .claude/skills/inspector-admin/scripts/admin_reciter.py <slug> --prod

# Preview and cut a global GH release
python .claude/skills/inspector-admin/scripts/admin_release.py preview --prod
python .claude/skills/inspector-admin/scripts/admin_release.py cut --prod --yes-prod --monitor

# Emergency read-only SQL
python .claude/skills/inspector-admin/scripts/admin_db.py exec "select slug, state, marked_ready from delivery_states where state='under_review'" --prod
```

## Prod writes MUST be single-writer (`prod_safe_setup`)

The DB sync goes through `durable_transaction` so the new bytes land on the bucket before the script returns. **But** a bare `setup()` write against prod is *not durable*: the deployed Space is a second, live writer whose `db_seq` advances on every commit (visitor/activity heartbeats), so it overtakes the sync CAS — which only refuses a *lower* seq — and **clobbers the out-of-band edit within a minute or two**. (Observed: a reconcile of 11 ledger rows reverted to 5 after the Space's next write.)

The safe path is **single-writer**: pause the Space → pull fresh → mutate → resume. Wrap every prod mutation in `prod_safe_setup` (in `_bootstrap.py`):

```python
from _bootstrap import prod_safe_setup, add_common_args
add_common_args(p); a = p.parse_args()
with prod_safe_setup(a, need_actor=False) as ctx:   # prod: pauses Space, pulls fresh
    with durable_transaction() as con:
        con.execute(...)                            # any bucket-DB mutation
# Space auto-resumes here (in finally) → boots + re-pulls the corrected DB.
```

`prod_safe_setup` pauses BEFORE the pull (snapshot = the Space's final state), runs the mutation as the sole writer, and **always resumes in `finally`** (a failed edit never leaves prod paused). On `--dev` it's a plain `setup()` — dev has no live Space, single-writer already. The Space re-pulls on boot (app.py boot = pull+migrate), so the edit is durable with no manual restart. Bare `setup()` remains for read-only ops (`admin_db exec` without `--write`, previews).
