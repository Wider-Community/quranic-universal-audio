-- Inspector SQLite substrate — migration 0029.
--
-- Maintainer-uploaded alignment samples: one audio + one aligner-contract JSON,
-- converted to the bucket segment schema under `samples/<id>/` and edited with
-- the Segments view under the slug `sample--<id>`. The row carries ownership,
-- ingest status and the two timestamps that drive the "changed since export"
-- badge. Bucket content is the source of truth for segments; this table only
-- indexes it.
--
-- Conventions match prior migrations: TEXT ISO-8601 UTC timestamps, FK to
-- users, no transaction control (the runner wraps BEGIN/COMMIT + user_version).

CREATE TABLE samples (
    id                TEXT PRIMARY KEY,                       -- uuid7; slug is `sample--` + id
    owner_hf_user_id  TEXT NOT NULL REFERENCES users(hf_user_id),
    name              TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'processing',     -- processing | ready | failed
    error             TEXT,                                   -- ingest failure detail
    audio_filename    TEXT NOT NULL,                          -- original upload name
    audio_duration_ms INTEGER,
    source_schema     TEXT NOT NULL,                          -- alignment | alignment_resource
    pseudo_chapter    INTEGER NOT NULL,
    created_at        TEXT NOT NULL,
    last_save_at      TEXT,
    last_export_at    TEXT
);

CREATE INDEX ix_samples_created ON samples(created_at DESC);
