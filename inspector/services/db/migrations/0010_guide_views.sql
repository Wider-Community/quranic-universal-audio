-- Inspector SQLite substrate — migration 0010.
--
-- Per-user "read" marks for the validation-accordion help guides. One row per
-- (guide view_key, user) the first time that user opens the guide. Drives two
-- FE behaviours, both global-per-user and durable across devices/browsers:
--   * the cyan "unread" border on each accordion's ? button, and
--   * the first-edit onboarding gate (read every required guide once, ever).
--
-- Mirrors review_views (0005) / request_views (0004): a small (key, user)
-- junction with a viewed_at timestamp. INSERT OR IGNORE on write — once read,
-- always read; there is no unread transition (unlike review_views' cycle).
-- view_key is an app-level enum (no FK); low_confidence_v2 is collapsed into
-- low_confidence before storage so the table never holds the alias.
--
-- Conventions match prior migrations: TEXT ISO-8601 timestamps, no transaction
-- control (the runner wraps in BEGIN/COMMIT + user_version).

CREATE TABLE guide_views (
    view_key   TEXT NOT NULL,
    hf_user_id TEXT NOT NULL REFERENCES users(hf_user_id),
    viewed_at  TEXT NOT NULL,
    PRIMARY KEY (view_key, hf_user_id)
);
CREATE INDEX ix_guide_views_user ON guide_views(hf_user_id);
