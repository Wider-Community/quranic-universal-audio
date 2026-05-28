-- Inspector SQLite substrate — migration 0006.
--
-- Drop ``activity_dismissals`` — the per-admin "dismissed this card" sidecar
-- that backed the admin notifications rail. The rail is gone (admin awareness
-- lives in the Admin dashboard tabs now: Users / Requests / Reviews), so the
-- table is dead weight. Its sibling ``activity_tombstones`` stays — owner-only
-- public-feed deletes still write there.
--
-- Conventions match prior migrations: the runner wraps in BEGIN/COMMIT and
-- bumps user_version.

DROP INDEX IF EXISTS ix_activity_dismissals_user;
DROP TABLE IF EXISTS activity_dismissals;
