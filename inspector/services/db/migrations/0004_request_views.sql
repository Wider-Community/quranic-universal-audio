-- Inspector SQLite substrate — migration 0004.
--
-- Per-admin "viewed" marks for requests. Mirrors activity_dismissals
-- (migration 0001): a (request, admin) pair, written the first time an admin
-- inline-expands a request in the Admin dashboard → Requests tab. A pending
-- request is "unviewed" for an admin until such a row exists; that drives the
-- per-admin unviewed-count badge on the Requests tab + the dot on the
-- Admin-dashboard entry button.
--
-- Conventions match 0001: TEXT ISO-8601 timestamps, no transaction control
-- (the migration runner wraps the script in BEGIN/COMMIT + the user_version
-- bump). Stale rows for resolved (non-pending) requests are harmless — the
-- unviewed count joins on status='pending' — so no GC is required.

CREATE TABLE request_views (
    request_id TEXT NOT NULL REFERENCES requests(id),
    hf_user_id TEXT NOT NULL REFERENCES users(hf_user_id),
    viewed_at  TEXT NOT NULL,
    PRIMARY KEY (request_id, hf_user_id)
);
CREATE INDEX ix_request_views_user ON request_views(hf_user_id);
