# Per-user notifications

The Dashboard **"My Notifications"** rail — events that happened *to* the
signed-in user, distinct from the global, identity-redacted "Recent activity"
feed. Per-user, dismissable, archived-on-dismiss.

Rail placement: right column, under the admin-dashboard button, above Recent
activity (`tabs/dashboard/components/NotificationsRail.svelte`, rendered inside
`ActivityRail.svelte`'s `.rail-wrap`). Hidden for anonymous users.

## Click-through (event-aware redirects)

Each notification card shows title + body inline (no expand) with a redirect
icon (`↗`) beside the dismiss/restore icon; its tooltip is the destination, so
the redirect is transparent on hover (`NotificationsRail.navTarget`):

| Event | Tooltip | Destination |
|---|---|---|
| `reciter.alignment_completed`, `reciter.claimed` | "Review in Segments" | `gotoSegments(slug)` — Segments tab, reciter loaded (mirrors the post-claim redirect) |
| `reciter.marked_ready` | "Review submission" | `gotoSegments(slug, {openMarkReadyReview})` — Segments tab + the read-only `MarkReadyReviewModal` (the reviewer's free-text notes, no checklist) |
| `flag.reply`, `flag.created`, `flag.replied` | "Open flagged segment" | `gotoSegments(slug, {openFlagged, focusFlaggedUid})` — Segments tab + Flagged accordion open + scrolled to the flagged segment |
| `request.received` | (none) | informational — no click-through; a type pill (`payload.kind`) names the request kind |
| everything else | "View reciter" | dashboard detail modal (`openDetail`), when the reciter is still catalogued |

A `cardBadge(n)` helper renders a small type pill next to the title:
`request.received` → the kind (Edit existing combo / New riwāyah · style / New
reciter), `reciter.marked_ready` → "Has notes", `flag.created` → "Flag · comment",
`flag.replied` → "Flag · reply".

The flag deep-link is a cross-tab handoff: `gotoSegments` writes
`pendingSegmentsDeepLink` (`lib/utils/goto-segments.ts`); `ValidationPanel`
consumes it once the reciter's flagged segments load — opens the `__flagged__`
accordion and scrolls the `[data-flag-uid=...]` card into view. It waits for the
target uid to appear so a stale (previous-reciter) flag list never triggers it.
`flag.reply` / `flag.created` / `flag.replied` notifications carry
`payload.segment_uid` for this. The `openMarkReadyReview` variant is consumed by
`SegmentsTab` (not `ValidationPanel`) — once the reciter is switched in it mounts
`MarkReadyReviewModal` and clears the pending intent.

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
| `reciter.marked_ready` | review-alert recipients (only when a comment box is non-empty) | "X marked ready — reviewer left notes" + the notes |

## Owner review alerts

Three event types fan out to **review-alert recipients** — everyone holding the
`notifications.receive_review_alerts` capability (owner-default-on, delegatable
to maintainers from the Permissions tab). `emit._review_alert_recipients()` →
`capabilities.users_with_capability(...)`. Per-target self-suppression drops the
acting user (an owner's own request / mark-ready / flag never notifies them).

| Event | Fired from | Copy |
|---|---|---|
| `request.received` | `notify_owners_new_request` — called from the slug-based edit-request route AND `intake.submit` (NOT a `reciter.requested` resolver, which re-fires on ingest) | "New request · X" + a body detail; `payload.kind` = `existing_combo_edit` / `existing_reciter_new_combo` / `new_reciter` |
| `reciter.marked_ready` | `_r_marked_ready` resolver (only when `comment_checks` or `comment_issues` is non-empty) | "X marked ready — reviewer left notes" + the notes; `payload.openMarkReadyReview` |
| `flag.created` / `flag.replied` | `notify_owners_flag_activity` — from the segment-save flow for `set` / `followup` flag ops | "New flag on X" / "New reply on a flag · X" + `surah:ayah — comment`; `payload.segment_uid` |

**Auto-archive.** `request.received` cards are informational. When the reciter
reaches `awaiting_review` (the `reciter.alignment_completed` event), the request
has been handled, so `emit._archive_request_alerts(slug)` dismisses every
owner's card for it — `repo_requests.ids_for_slug(slug)` →
`repo_notifications.dismiss_by_source_key("request:<id>")` (one source_key shared
across all recipients, so one call clears the whole fan-out). The intake row's
slug is back-filled at ingest, so both request paths are reachable by slug.

The old per-admin **Requests-tab unviewed badge** (entry-button dot, tab count,
per-row dot, `/api/admin/requests/unviewed-count`, the `request_views` writer)
was retired in favour of these alerts — "new request" awareness lives only on
the rail now.

The requester for the reject/alignment events is captured in `_apply_event`
**before** the handler runs (the pending row is archived mid-handler). The
auto-claim fold is marked with `payload.notify_auto_claim` so the
`reciter.claimed` resolver distinguishes it from a manual self-claim (which
notifies no one).

Deliberately **excluded**: `claim.reassigned` (event unused), `reciter.published`
(already on the public activity rail), `reciter.merge_rejected`, and all
admin/catalog/self events.

## Announcements (global broadcast)

The same rail also shows **announcements** — an owner-composed broadcast that
reaches **everyone, including signed-out visitors**. Unlike per-user
notifications (one materialized row per target), an announcement is a **single
global row**; there is no per-user fan-out, so it also reaches anonymous users
who have no `hf_user_id`.

**Model.** SQLite table `announcements` (migration `0021_announcements.sql`):
`id`, `title`, `body` (nullable), `author_hf_user_id` + `author_login`
(provenance, no FK), `created_at`, `revoked_at` (NULL ⇒ active). An announcement
stays active until an owner revokes it. Repo `services/db/repo_announcements.py`
(`create` / `list_active` / `list_all` / `revoke`); service
`services/announcements.py` (Flask-free; writes open their own
`durable_transaction`, validates title non-empty).

**Routes.**
- Public read: `GET /api/announcements` (`routes/announcements.py`) — **ungated**,
  anonymous-reachable (mirrors `/api/static/*`); serves the active rows as the
  public `Announcement` wire shape (`id`/`title`/`body`/`created_at`).
- Owner compose/manage (`routes/admin/announcements.py`, all gate
  `announcements.send`): `GET /api/admin/announcements` (active + revoked, the
  `AnnouncementAdmin` shape), `POST /api/admin/announcements` (compose, validates
  via `AnnouncementCreate`), `POST /api/admin/announcements/<id>/revoke`. The two
  POSTs also carry `@require_same_origin`.

`announcements.send` is a `G_ADMIN` capability, **owner-only by default but
toggleable** (an owner can delegate to maintainers from the Permissions tab).

**Dismiss / seen — client-side only.** There is **no** server-side per-user
dismiss state. The browser tracks it in localStorage
(`insp_dismissed_announcements`, `insp_seen_announcements`); dismissing hides an
announcement permanently on that browser. The store
(`tabs/dashboard/stores/announcements.svelte.ts`) polls the public route on the
same 30s visibility-aware cadence and computes `unread` against a page-load
snapshot of the seen-set, so a freshly-arrived announcement reads as "new" for
the session without the always-visible rail clearing it instantly.

**Rail rendering.** Announcements render as **normal notification cards** (not a
separate group): in the Active view they merge with personal notifications,
newest-first, styled identically — each with a dismiss `✕` (no nav-target, no
archive/restore). The whole rail (`NotificationsRail.svelte`, mounted
unconditionally inside the public `ActivityRail`) shows for anonymous users
whenever ≥1 announcement is active; the Active/Archive toggle + personal list
stay signed-in-only. Compose UI: the Admin → **Announcements** tab
(`AnnouncementsCompartment.svelte`).

## Email preferences (frontend)

The rail header carries an **envelope button** (signed-in only,
`NotificationsRail.svelte`) that opens `EmailPrefsModal.svelte`
(`tabs/dashboard/components/`) — a per-user opt-in to no-reply emails for
catalog + workflow events, distinct from the in-app rail above.

**This is frontend wiring only.** The modal reads/writes through a typed client
(`lib/api/email-prefs.ts`, the `EmailPrefs` shape) against
`GET/POST /api/me/email-preferences`; that contract is the spec. The backend
half — a prefs table, the email emitter, SMTP/no-reply delivery, and seeding the
destination `email` from the HF account on first GET — is **not built yet**.

**Model.** One destination `email`, six event settings, and two *shared*
selections that several events reuse (pick once, applies to both):

| Field | Type | Event |
|---|---|---|
| `request_aligned` | bool | A request you submitted finishes alignment |
| `recitation_published` | `off`/`all`/`selected` | A recitation is published |
| `timestamps_regenerated` | `off`/`all`/`selected` | A reciter's timestamps are regenerated |
| `github_release` | bool | A new GitHub release is cut |
| `riwayah_new_recitation` | bool | New recitation in a followed riwayah |
| `riwayah_first_available` | bool | A followed riwayah becomes available (one-time) |
| `reciters` | `reciter_id[]` | shared target for every `selected`-scope event |
| `riwayahs` | slug[] | shared follow-list for both riwayah events |

A `selected` scope with an empty `reciters` list (or a riwayah event with an
empty `riwayahs` list) is a no-op — the modal warns inline rather than blocking
save. The reciter/riwayah option sets are derived client-side from the loaded
catalog (`PublicReciter.reciter_id` / the distinct `riwayat`).

Reusable primitives added for the modal: `lib/components/Segmented.svelte`
(scope selector) and `lib/components/ChipMultiSelect.svelte` (searchable
multi-select chips); envelope glyph at `lib/icons/mail.svg`.

**Backend follow-up:** add the `email_preferences` store + `GET/POST
/api/me/email-preferences` (owner-scoped, `@require_same_origin` on POST, GET
seeds `email` from the HF cookie), then an emitter that fans the six events out
to subscribed addresses via a no-reply SMTP path.

## Tests

- `tests/db/test_repo_announcements.py` — announcement create / list_active /
  revoke (active⇄all, no-op double-revoke).
- `tests/routes/test_route_announcements.py` — public read anon-reachable,
  compose gated owner-only (maintainer/contributor 403, anon 401), revoke drops
  from the public list, empty title 400.
- `tests/notifications/test_emit_resolvers.py` — resolver target correctness,
  self-suppression, SYSTEM-actor alignment, auto-claim keep-self, dedup,
  flag-reply self-suppression.
- `tests/db/test_repo_notifications.py` — retention prune, dedup.
- `tests/routes/test_route_notifications.py` — auth, list/mark-seen,
  dismiss/restore, owner-scoping.
- `tests/services/test_state_request_events.py::test_reject_soft_notifies_requester`
  — end-to-end through `transition()`.
