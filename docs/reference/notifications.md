# Per-user notifications

The Dashboard **"My Notifications"** rail — events that happened *to* the
signed-in user, distinct from the global, identity-redacted "Recent activity"
feed. Per-user, dismissable, archived-on-dismiss.

Rail placement: right column, under the admin-dashboard button, above Recent
activity (`tabs/dashboard/components/NotificationsRail.svelte`, rendered inside
`ActivityRail.svelte`'s `.rail-wrap`). Hidden for anonymous users.

## Model

Notifications are **materialized** — one `notifications` row per (target user,
source event), written at emit time, NOT derived on read. The target user is
only reliably knowable at emit time: the pending request is archived and the
claim's assignee is cleared in the *same* transaction that fires the event.

SQLite table `notifications` (migration `0019_notifications.sql`):

| Column | Notes |
|---|---|
| `id` | PK |
| `hf_user_id` | target user (FK `users`) |
| `event` | source event name, or `flag.reply` |
| `slug` | delivery slug to link to; `NULL` for slugless intake |
| `title` | frozen collapsed-view summary (always names the reciter) |
| `body` | frozen detail (admin reason / reply text); nullable |
| `payload` | JSON extras (e.g. `segment_uid`); nullable |
| `source_key` | dedup + provenance: transition id, or `flag:<slug>:<uid>:<at_utc>` |
| `created_at` / `seen_at` / `dismissed_at` | ISO-8601 UTC; `dismissed_at IS NOT NULL` ⇒ archived |

Dedup: `UNIQUE(hf_user_id, source_key)` + `INSERT OR IGNORE` — a re-driven
transaction or retried save can't double-insert. Retention: `prune_for_user`
(called from `create`) keeps the newest 200 *dismissed* rows per user; active
rows are never auto-pruned.

Repo: `services/db/repo_notifications.py` (caller owns the txn). Routes:
`routes/auth/notifications.py` — `GET /api/me/notifications` (active + unread,
marks seen), `GET .../archived`, `POST .../<id>/dismiss`, `POST .../<id>/restore`
(all signed-in + owner-scoped). `/api/me` carries `notifications_unread` for the
first-load badge.

## Emission

`services/notifications/emit.py` has two entry points, one per source
write-path. Both are **best-effort** — wrapped in try/except-log so a
notification failure never rolls back the motivating transition or save.

1. **`emit_for_event(conn, record, *, before, extra)`** — called from
   `state._apply_event` (inside the live durable transaction, after
   `repo_transitions.append`) and from `intake.resolve`. A `_RESOLVERS` table
   maps event name → target user(s). Self-suppression drops a target equal to
   the actor, except where a resolver sets `keep_self`.
2. **`notify_flag_reply(...)`** — called from `services/segments/save.py` after
   a successful save (segment saves write the bucket, not SQLite, so this opens
   its **own** `durable_transaction`).

Every title names its reciter, resolved once via `catalog.display_name(slug)`
(or the proposed name in the request payload for slugless intake).

### Event → target

| Event | Target | Copy |
|---|---|---|
| `reciter.request_rejected_soft` | pending requester | "Your request for X was sent back" + reason |
| `reciter.request_rejected_hard` | pending requester | "Your request for X was discarded" + reason |
| `reciter.alignment_completed` | pending requester (non-auto-claim only) | "X is ready for review" |
| `reciter.claimed` (auto-claim fold) | requester (`keep_self`) | "You've been assigned to X" |
| `claim.force_released` | prior assignee (`before.assignee_hf_id`) | "Your review of X was released — it hadn't been active for a while" |
| `request.intake_returned` | requester (`requests.requester_id`) | "Your submission for X was sent back" + reason |
| `request.intake_discarded` | requester | "Your submission for X was discarded" + reason |
| `flag.reply` | original flagger | "New reply on a segment you flagged in X" + reply text |

The requester for the reject/alignment events is captured in `_apply_event`
**before** the handler runs (the pending row is archived mid-handler). The
auto-claim fold is marked with `payload.notify_auto_claim` so the
`reciter.claimed` resolver distinguishes it from a manual self-claim (which
notifies no one).

Deliberately **excluded**: `claim.reassigned` (event unused), `reciter.published`
(already on the public activity rail), `reciter.merge_rejected`, and all
admin/catalog/self events.

## Tests

- `tests/notifications/test_emit_resolvers.py` — resolver target correctness,
  self-suppression, SYSTEM-actor alignment, auto-claim keep-self, dedup,
  flag-reply self-suppression.
- `tests/db/test_repo_notifications.py` — retention prune, dedup.
- `tests/routes/test_route_notifications.py` — auth, list/mark-seen,
  dismiss/restore, owner-scoping.
- `tests/services/test_state_request_events.py::test_reject_soft_notifies_requester`
  — end-to-end through `transition()`.
