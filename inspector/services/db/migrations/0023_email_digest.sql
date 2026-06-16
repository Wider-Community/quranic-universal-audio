-- Inspector SQLite substrate — migration 0023.
--
-- Email digest buffer. A burst of publishes / TS regenerations would otherwise
-- send one immediate email per event; instead the two high-volume events
-- (`recitation_published`, `timestamps_regenerated`) buffer one row per matched
-- recipient here and a background sweep flushes each (email, event_kind) group
-- as a single batched email once its window ages past EMAIL_DIGEST_WINDOW_MINUTES
-- (tumbling window opened by the earliest unsent row). Rows are deleted on flush.
--
-- One row per (recipient × event_kind × reciter). `manage_token` + `reciter_name`
-- are captured at buffer time so the flush needs no re-resolution. `reciter_id`
-- is the dedup key within a window. Riwayah-follow events stay immediate and
-- never land here.
--
-- Conventions match prior migrations: TEXT ISO-8601 UTC timestamps, no
-- transaction control (the runner wraps BEGIN/COMMIT + user_version).

CREATE TABLE email_digest (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL,                 -- normalized lowercase destination
    manage_token  TEXT NOT NULL,                 -- per-recipient manage/unsubscribe handle
    event_kind    TEXT NOT NULL,                 -- 'recitation_published' | 'timestamps_regenerated'
    reciter_id    TEXT NOT NULL,                 -- dedup key within a window
    reciter_name  TEXT NOT NULL,                 -- display, captured at buffer time
    buffered_at   TEXT NOT NULL                  -- ISO-8601 UTC
);

CREATE INDEX ix_email_digest_flush ON email_digest(event_kind, email, buffered_at);
