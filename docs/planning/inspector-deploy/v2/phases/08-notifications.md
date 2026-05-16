# Phase 8 — Notifications (in-app)

> Signed-in users get a `/notifications` top-level tab with an unread badge in the nav. Notifications are derived on demand from the audit log via per-user filter rules + a `last_read_at` pointer — no separate write path. Per-reciter and global "any published reciter" subscriptions, discoverable from the public reciter detail page + dashboard hero stats card. No email in v2; the HF OAuth `email` scope from Phase 3 primes the verified email for a follow-up email-delivery phase.

**Status:** not started
**Depends on:** Phase 7 (Admin dashboard) complete; Phase 3 `email` scope deliverable wired into the session
**Blocks:** Future email-delivery phase

## Goal

Signed-in users have a single place to see actions affecting them (claim lifecycle, request milestones, subscription matches, maintainer ops alerts) without polling state pages by hand. Storage is minimal: only a `last_read_at` pointer and a subscription list per user; the notification list itself is derived on every request by filtering the audit log against rules. Maintainers additionally receive synthetic `alerts.*` events emitted by daily sweeps for stalled reciters and stuck jobs. Email delivery, anonymous subscriptions, and category subscriptions are deferred — the schema is shaped to extend without rework.

## Deliverables

### Per-user state

- [ ] `<bucket>/users/<hf_user_id>.json` — per-user record: `{ last_read_at, subscriptions: [{ id, type: 'reciter'|'global', target?: slug, created_at }] }`
- [ ] `inspector/schemas/` pydantic model for the user record
- [ ] `inspector/services/user_state.py` — load/save with per-user `threading.Lock` + atomic-write-then-rename + `huggingface_hub.upload_file()` (mirrors `state.py` from Phase 1)
- [ ] User record auto-created on demand (first `/api/notifications` hit or first subscription)

### Notification derivation

- [ ] `inspector/services/notifications.py::derive_for_user(user_record, role, hf_user_id)` — pure function returning a chronological list of `{ id, ts, category, slug?, event_type, copy, read }` cards
- [ ] Reads `<bucket>/audit/<YYYY>-<MM>.jsonl` for the current + previous month; results capped per page (default 50)
- [ ] Cursor-paginated; cursor encodes `{ month, line_offset }`
- [ ] `category` ∈ `{lifecycle, subscription, request, maintainer}` for frontend filter chips
- [ ] Notification `copy` mirrors the public-activity-feed phrasing where the event overlaps (e.g. "*X* is now published"); diverges only when context demands ("**Your** reciter *X* was sent back: …")

### Filter rules (pure functions on `(audit_event, user_context)` → bool)

- [ ] **Active reviewer:** `reciter.merge_rejected` (assignee=you), `claim.force_released` (former assignee=you), `claim.reassigned` (from OR to assignee=you), `admin.unlocked_for_revision` (previous_assignee=you), `reciter.timestamps_completed` (assignee=you at publish time), `reciter.dataset_published` (assignee=you at publish time)
- [ ] **Subscriber:** any audit event whose slug matches a per-reciter subscription, filtered to `reciter.timestamps_completed` + `alignment.completed` (the "now published" and "now available to claim" milestones). Global subscription matches `reciter.timestamps_completed` for any slug.
- [ ] **Request submitter:** `catalog.reciter_added` (requester=you), `alignment.completed` (requester=you), `reciter.timestamps_completed` (requester=you) — requires the catalog/state row to carry `requested_by_hf_id`; until D14 (Inspector-native intake) lands, this field is `null` and the rule matches no one (no-op)
- [ ] **Maintainer:** `reciter.marked_ready`, `alerts.reciter_stalled`, `alerts.job_stuck`, `alerts.hygiene_critical`, `alerts.roles_fetch_failed`, plus the new-reciter-request audit event when D14 ships
- [ ] All filter rules live in `inspector/services/notification_rules.py`; covered by unit tests against synthetic audit lines

### Synthetic alert events (sweeps)

- [ ] `inspector/services/stall_sweep.py` — daily-scheduled background task; reads state rows + last activity (audit log scan or state-row `last_state_change_at` field); emits `alerts.reciter_stalled` audit lines when slugs cross thresholds. Thresholds: `awaiting_alignment` > 7 d, `awaiting_review` > 14 d, `under_review` (no save activity) > 30 d, `awaiting_timestamps` > 24 h
- [ ] Sweep idempotency: emit only on threshold *crossing*; track `last_alert_at` per slug + threshold in `<bucket>/notifications/alert_state.json` so repeat daily runs don't spam
- [ ] `inspector/services/job_health.py` — periodic check (every ~15 min) of in-flight `awaiting_timestamps` job ids via HF Jobs API; emits `alerts.job_stuck` when a job has been running > 24 h or HF API reports failure; idempotent per `timestamps_job_id`
- [ ] `inspector/services/role.py` emits `alerts.roles_fetch_failed` to audit on cache-miss fetch failure (single emission per outage window)
- [ ] `bucket-data-hygiene.yml` (Phase 7) extended to additionally append `alerts.hygiene_critical` audit lines for CRITICAL findings (in addition to opening a GH issue)

### API

- [ ] `GET /api/notifications?limit=50&cursor=...` — paginated notification cards + cursor; respects `last_read_at` for `read: bool` marking
- [ ] `GET /api/notifications/unread-count` — fast endpoint for nav badge; cached for ~5 s per user
- [ ] `POST /api/notifications/mark-read` — body `{ up_to_ts? }` (default: most recent visible card); bumps `last_read_at`
- [ ] `GET /api/subscriptions` — current user's subscription list
- [ ] `POST /api/subscriptions` — body `{ type, target? }`; returns the created sub; rejects duplicates with 409
- [ ] `DELETE /api/subscriptions/<id>` — remove
- [ ] All endpoints return 401 for anonymous; maintainer-only audit events are filtered out of non-maintainer responses

### Frontend

- [ ] New top-level `/notifications` tab; bell icon in nav with unread-count badge (poll `/api/notifications/unread-count` every 30 s while signed in)
- [ ] `/notifications` list view — category filter chips, per-card read indicator, "Mark all read" action, infinite scroll via cursor; click a card to deep-link to the affected reciter
- [ ] `/notifications/subscriptions` settings sub-view — list current subs, unsubscribe inline; no "add subscription" form here (entry lives on the dashboard / detail page)
- [ ] Subscribe affordance on `/reciter/<slug>` public detail page — "🔔 Notify me when this reciter is published or available to claim"; toggles to "🔔 Unsubscribe" when active
- [ ] Subscribe affordance on dashboard hero stats card — "🔔 Notify me when any new reciter is published" (global subscription); toggle UX same as per-reciter
- [ ] Empty state for `/notifications` ("You're all caught up." + link to dashboard)

### Cross-phase wiring

- [ ] Phase 3 OAuth `email` scope must be live in the session before this phase ships (already a Phase 3 deliverable; verify the cookie carries `verified_email`)
- [ ] Phase 1 user-record pydantic schema added in this phase (was not in Phase 1's scope)
- [ ] Activity-feed redaction in Phase 6 unchanged — public activity feed continues to filter to the six public event types; `/api/notifications` is its own filtered surface

## Out of scope

- Email delivery — separate follow-up phase; `verified_email` is captured in session but no outbound mail in v2
- Anonymous email subscriptions — depends on email phase
- Category subscriptions (riwayah / source / qira'ah / style) — deferred; subscription schema's `type` is shaped to extend
- Server-Sent Events for live updates (D8) — 30 s poll is sufficient
- Browser push / mobile push notifications
- Notification grouping / digest UI — track loud-alert risk; promote to follow-up only if measured
- Per-event delivery toggles (in-app vs email) — meaningless without email; ship with the email phase
- Snooze / pin per notification

## Acceptance criteria

- [ ] Signed-in user with no notifications sees `/notifications` empty state + no nav badge
- [ ] Triggering an event that affects the user (admin force-releases their claim) results in the bell badge incrementing and a new card appearing on `/notifications` within 30 s
- [ ] "Mark all read" clears the badge; page reload preserves the cleared state via `last_read_at` in `<bucket>/users/<hf_user_id>.json`
- [ ] User subscribes to a reciter via `/reciter/<slug>`; that reciter's `reciter.timestamps_completed` produces a notification for that user within 30 s of the job callback
- [ ] User holds the global subscription; any reciter hitting `released` produces a notification for them
- [ ] Subscriber for a slug also gets notified when that slug transitions to `awaiting_review` (via `alignment.completed`) — useful for claim hunters
- [ ] Unsubscribing flips the affordance state and suppresses future matching events for that user
- [ ] Stall sweep run with a manually-aged `awaiting_review` slug emits exactly one `alerts.reciter_stalled` line; rerunning the sweep on the same day does not duplicate
- [ ] Job-health sweep emits `alerts.job_stuck` for an `awaiting_timestamps` slug aged > 24 h; once the job completes the alert is not re-emitted
- [ ] Anonymous `/api/notifications*` requests return 401
- [ ] Non-maintainer requesting `/api/notifications` does not receive `alerts.*` or `reciter.marked_ready` events
- [ ] `/api/notifications/unread-count` p99 ≤ 100 ms; `/api/notifications?limit=50` p99 cold ≤ 300 ms
- [ ] Filter rule unit tests cover: active reviewer, subscriber (reciter + global), request submitter (no-op while D14 unshipped), maintainer-only

## Verification

```bash
SPACE=https://hetchyy-quranic-inspector-dev.hf.space
COOKIE_USER=$(jq -r '.test_user_session' .local/inspector/test_cookies.json)
COOKIE_MAINT=$(jq -r '.test_maintainer_session' .local/inspector/test_cookies.json)

# Anonymous gating
curl -fsSI $SPACE/api/notifications | head -1   # expect 401

# Empty state
curl -fsS -b "session=$COOKIE_USER" $SPACE/api/notifications/unread-count | jq '.count'   # 0

# Subscribe + trigger
curl -fsS -X POST -b "session=$COOKIE_USER" \
  -H "Content-Type: application/json" \
  -d '{"type":"reciter","target":"_test_notif_target"}' \
  $SPACE/api/subscriptions
# (maintainer publishes _test_notif_target through the normal flow; wait for job callback)
sleep 35
curl -fsS -b "session=$COOKIE_USER" $SPACE/api/notifications/unread-count | jq '.count'   # 1
curl -fsS -b "session=$COOKIE_USER" "$SPACE/api/notifications?limit=10" | jq '.cards[0].event_type'   # "reciter.timestamps_completed"

# Mark read
curl -fsS -X POST -b "session=$COOKIE_USER" $SPACE/api/notifications/mark-read
curl -fsS -b "session=$COOKIE_USER" $SPACE/api/notifications/unread-count | jq '.count'   # 0

# User record round-trip
hf buckets cp hf://buckets/hetchyy/quranic-inspector-bucket-dev/users/<hf_user_id>.json - | jq

# Stall sweep manual invocation
python -m inspector.services.stall_sweep --bucket --dry-run    # preview
python -m inspector.services.stall_sweep --bucket              # emit
hf buckets cp hf://buckets/hetchyy/quranic-inspector-bucket-dev/audit/$(date +%Y-%m).jsonl - \
  | grep alerts.reciter_stalled | tail -5

# Maintainer-only event redaction
curl -fsS -b "session=$COOKIE_USER" "$SPACE/api/notifications?limit=200" | jq '.cards[].event_type' | grep -c alerts   # 0 (non-maintainer)
curl -fsS -b "session=$COOKIE_MAINT" "$SPACE/api/notifications?limit=200" | jq '.cards[].event_type' | grep -c alerts   # > 0
```

## Risks

- **Audit log scan latency at scale** — same risk profile as Phase 6's activity feed. Mitigation lever: cache the last-7-days audit tail in process memory + refresh on every audit write. Measure first; add only if `/api/notifications` cold path misses the p99 budget.
- **Stall sweep emitting duplicates** — must track `last_alert_at` per slug + threshold; choosing `<bucket>/notifications/alert_state.json` over a state-row field keeps the alert bookkeeping out of the per-reciter row. Decided here, not Phase 1.
- **Alert events landing in the wrong audit month-shard** — sweeps run at UTC start-of-day to avoid midnight rollover races.
- **Maintainer alert flood** — bucket hygiene CRITICAL + multiple stall thresholds firing on the same sweep day can produce many cards. Mitigation: frontend category filter + a follow-up "digest mode" if the measured rate is noisy.
- **Subscribe-then-trigger race** — atomic-write per-user record + per-user lock cover this; a ~few-second window exists where a freshly-created subscription may miss an in-flight event. Acceptable.
- **Per-user record growth** — bounded; only stores `last_read_at` + subscription list. No notification history persisted.

## Reference

- [`06-public-dashboard.md`](06-public-dashboard.md) — activity feed pattern this phase mirrors (different filter rules, same audit-log-derived architecture)
- [`07-admin-dashboard.md`](07-admin-dashboard.md) — stalled-reciter panel + bucket-data-hygiene workflow backing maintainer alerts
- [`03-auth-and-claims.md`](03-auth-and-claims.md) — HF OAuth `email` scope (groundwork for the email follow-up phase)
- [`inspector-state-management.md`](../inspector-state-management.md) §4 — event list backing filter rules
- [`inspector-data-storage.md`](../inspector-data-storage.md) §8 — audit log layout
- [`inspector-deferred.md`](../inspector-deferred.md) D3 — original "notifications fan-out" deferred item, now landing here
