-- Inspector SQLite substrate — migration 0005.
--
-- Per-admin "viewed" marks for marked-ready review entries. Mirrors
-- request_views (migration 0004) but keyed by slug (not request id) and
-- carries a moving viewed_at timestamp instead of a fixed one. The
-- comparison against claims.marked_ready_at is what handles cycles: a
-- maintainer sends a row back → reviewer re-marks ready (new
-- marked_ready_at) → viewed_at < marked_ready_at → the row is unread
-- again. No GC needed; rows are durable per (slug, admin).
--
-- Conventions match prior migrations: TEXT ISO-8601 timestamps, no
-- transaction control (the runner wraps in BEGIN/COMMIT + user_version).

CREATE TABLE review_views (
    slug       TEXT NOT NULL REFERENCES delivery_states(slug),
    hf_user_id TEXT NOT NULL REFERENCES users(hf_user_id),
    viewed_at  TEXT NOT NULL,
    PRIMARY KEY (slug, hf_user_id)
);
CREATE INDEX ix_review_views_user ON review_views(hf_user_id);
