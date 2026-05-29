-- Inspector SQLite substrate — migration 0006.
--
-- Drop ``activity_dismissals`` — the per-admin "dismissed this card" sidecar
-- that backed the admin notifications rail. The rail is gone (admin awareness
-- lives in the Admin dashboard tabs now: Users / Requests / Reviews), so the
-- table is dead weight. Its sibling ``activity_tombstones`` stays — owner-only
-- public-feed deletes still write there.
--
-- 0001_init.sql created the table with only its composite PRIMARY KEY (no
-- named secondary index), so DROP TABLE alone is enough — SQLite drops the
-- auto-index alongside the table.
--
-- Conventions match prior migrations: the runner wraps in BEGIN/COMMIT and
-- bumps user_version.

DROP TABLE IF EXISTS activity_dismissals;
