-- Inspector SQLite substrate — migration 0019.
--
-- Per-user "My Notifications" rail (Dashboard). One row per (target user,
-- source event), materialized at event-emit time by services/notifications:
-- lifecycle transitions (state._apply_event) and segment-flag replies
-- (services/segments/save.py). Notifications are dismissable → archived
-- (dismissed_at set, row retained + viewable) → restorable.
--
-- source_key is a generic dedup + provenance anchor, NOT an FK: lifecycle rows
-- use the transition id, flag replies use 'flag:<slug>:<segment_uid>:<at_utc>'.
-- INSERT OR IGNORE on (hf_user_id, source_key) makes emission idempotent under
-- a re-driven transaction or retried save.
--
-- Conventions match prior migrations (0010 guide_views): TEXT ISO-8601 UTC
-- timestamps, no transaction control (the runner wraps BEGIN/COMMIT +
-- user_version).

CREATE TABLE notifications (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    hf_user_id    TEXT NOT NULL REFERENCES users(hf_user_id),
    event         TEXT NOT NULL,
    slug          TEXT,
    title         TEXT NOT NULL,
    body          TEXT,
    payload       TEXT,
    source_key    TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    seen_at       TEXT,
    dismissed_at  TEXT
);

CREATE UNIQUE INDEX ux_notifications_user_source ON notifications(hf_user_id, source_key);
CREATE INDEX ix_notifications_user_active
    ON notifications(hf_user_id, created_at DESC) WHERE dismissed_at IS NULL;
CREATE INDEX ix_notifications_user_all ON notifications(hf_user_id, created_at DESC);
