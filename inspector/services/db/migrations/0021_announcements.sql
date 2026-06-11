-- Inspector SQLite substrate — migration 0021.
--
-- Global announcements (Dashboard "My Notifications" rail). Unlike the
-- per-user `notifications` table (one materialized row per target user), an
-- announcement is a SINGLE global row composed by an owner and shown to
-- EVERYONE — including signed-out visitors — via the public GET /api/announcements
-- route. Dismiss/seen state lives entirely in the browser (localStorage), so
-- there is no per-user join table here.
--
-- An announcement stays active until an owner revokes it (revoked_at set).
-- author_* carries provenance only (no FK; the author is always an owner).
--
-- Conventions match prior migrations: TEXT ISO-8601 UTC timestamps, no
-- transaction control (the runner wraps BEGIN/COMMIT + user_version).

CREATE TABLE announcements (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    title             TEXT NOT NULL,
    body              TEXT,
    author_hf_user_id TEXT NOT NULL,
    author_login      TEXT,
    created_at        TEXT NOT NULL,
    revoked_at        TEXT
);

CREATE INDEX ix_announcements_active
    ON announcements(created_at DESC) WHERE revoked_at IS NULL;
