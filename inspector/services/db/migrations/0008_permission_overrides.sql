-- Inspector SQLite substrate — migration 0008.
--
-- Owner-configurable capability overrides. Backs the Admin dashboard →
-- Permissions tab. Stores ONLY deviations from the registry default
-- (scripts/lib/schemas/capabilities.py): the absence of a row means "use the
-- baseline default", and a reset is a DELETE. So an empty table reproduces
-- the legacy hardcoded authorization bit-for-bit.
--
-- (Numbered 0008: dev already ships 0007_mark_ready_submission.sql — this
-- must be the next free number so it applies on DBs already at user_version=7.)
--
-- OWNER is never a key here (owners are superusers — always allowed). The
-- ``manage_permissions`` capability is never a key here (owner-only fixed —
-- the recovery anchor that keeps owners from ever locking themselves out).
-- Both invariants are enforced in the app layer (resolver + route), NOT the
-- DDL — same "free vocabulary, no CHECK" convention as transitions.event, so
-- adding a capability needs no migration.
--
-- Conventions match prior migrations: TEXT ISO-8601 timestamps, INTEGER 0/1
-- booleans, no transaction control (the runner wraps the script in
-- BEGIN/COMMIT and bumps user_version).

CREATE TABLE permission_overrides (
    capability_id TEXT    NOT NULL,
    tier          TEXT    NOT NULL,   -- 'anonymous' | 'contributor' | 'maintainer'
    allowed       INTEGER NOT NULL,   -- 0/1
    set_by        TEXT    NOT NULL REFERENCES users(hf_user_id),
    set_at        TEXT    NOT NULL,
    PRIMARY KEY (capability_id, tier)
);
