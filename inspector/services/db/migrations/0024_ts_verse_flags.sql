-- Inspector SQLite substrate — migration 0024.
--
-- Public verse-level flags on the Timestamps tab. Any visitor — including
-- anonymous — can flag the verse currently playing on a published recitation
-- and leave an optional comment describing the timestamps issue. One row per
-- (slug, verse_key, identity); multiple users flag the same verse, so a verse
-- accumulates multiple comments, all globally viewable.
--
-- Identity is EITHER a signed-in HF account (`hf_user_id`, with the cookie
-- snapshot in `login_at_time`/`role_at_time`) OR an anonymous browser token
-- (`anon_token`, minted + persisted in the visitor's localStorage so the same
-- browser can edit/delete its own comment). Exactly one of the two is set.
--
-- Conventions match prior migrations: TEXT ISO-8601 UTC timestamps, nullable
-- FK to users, no transaction control (the runner wraps BEGIN/COMMIT +
-- user_version).

CREATE TABLE ts_verse_flags (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    slug           TEXT NOT NULL,
    verse_key      TEXT NOT NULL,                       -- "surah:ayah", e.g. "2:45"
    hf_user_id     TEXT REFERENCES users(hf_user_id),   -- NULL for anonymous
    anon_token     TEXT,                                -- set for anon, NULL for signed-in
    login_at_time  TEXT,                                -- actor cookie snapshot (NULL for anon)
    role_at_time   TEXT,                                -- actor role snapshot (NULL for anon)
    comment        TEXT,                                -- optional
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

-- One comment per verse per identity. NULLs compare distinct in SQLite, so the
-- uniqueness is split into one partial index per identity column.
CREATE UNIQUE INDEX ux_tsflag_user ON ts_verse_flags(slug, verse_key, hf_user_id)
    WHERE hf_user_id IS NOT NULL;
CREATE UNIQUE INDEX ux_tsflag_anon ON ts_verse_flags(slug, verse_key, anon_token)
    WHERE anon_token IS NOT NULL;
CREATE INDEX ix_tsflag_slug ON ts_verse_flags(slug);
