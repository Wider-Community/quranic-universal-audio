-- Inspector SQLite substrate — migration 0014.
--
-- Dataset and releases v2 tables.
--
-- Three new tables capture the v2 publish-tracks model:
--   * per_recitation_releases — TS gen + HF dataset push history per slug.
--   * gh_releases             — global GH release snapshots.
--   * gh_release_recitations  — frozen membership of each gh_release.
--
-- Plus two existing-vocab tweaks:
--   * channels.gh_release_eligible — data-driven public-CDN allow-list.
--   * deliveries.bitrate_mode — collapse legacy mostly_cbr/mostly_vbr/abr → mixed.
--
-- Conventions match prior migrations: TEXT ISO-8601 UTC timestamps, INTEGER 0/1
-- booleans, partial-unique indexes for "at-most-one-current" (mirrors the
-- ux_role_active / ux_claim_open_slug / ux_request_pending_slug pattern). The
-- runner wraps in BEGIN/COMMIT + user_version.
--
-- See docs/reference/dataset-and-releases.md.

-- ---------------------------------------------------------------------------
-- Per-recitation publish history (TS gen + HF dataset push).
-- ---------------------------------------------------------------------------
CREATE TABLE per_recitation_releases (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    track               TEXT    NOT NULL,                  -- 'ts' | 'hf'
    slug                TEXT    NOT NULL REFERENCES deliveries(slug),
    version             TEXT    NOT NULL,                  -- ts seq int | hf commit sha
    produced_at         TEXT    NOT NULL,                  -- ISO-8601 UTC
    produced_by         TEXT    NOT NULL,                  -- hf_user_id | SYSTEM
    produced_by_job_id  TEXT,                              -- HF Job id
    launched_by         TEXT,                              -- hf_user_id from launch payload
    external_uri        TEXT,                              -- HF revision URL | bucket path
    superseded_at       TEXT,
    stale_since         TEXT,                              -- HF row stale when slug's TS regenerated
    source_catalog_rev  TEXT,
    validation_summary  TEXT,                              -- JSON
    CHECK (track IN ('ts', 'hf'))
);
-- One current row per (track, slug). Mirrors ux_claim_open_slug / ux_request_pending_slug.
CREATE UNIQUE INDEX ux_per_recitation_current
    ON per_recitation_releases(track, slug) WHERE superseded_at IS NULL;
CREATE INDEX ix_per_recitation_slug_track
    ON per_recitation_releases(slug, track) WHERE superseded_at IS NULL;
-- Full-row lookup by slug (FK + historical queries that scan all versions).
CREATE INDEX ix_per_recitation_slug
    ON per_recitation_releases(slug);
CREATE INDEX ix_per_recitation_stale
    ON per_recitation_releases(stale_since) WHERE stale_since IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Global GH release snapshots.
-- ---------------------------------------------------------------------------
CREATE TABLE gh_releases (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    version             TEXT    NOT NULL,                  -- 'v0.5.3'
    produced_at         TEXT    NOT NULL,
    produced_by         TEXT    NOT NULL,
    produced_by_job_id  TEXT,
    launched_by         TEXT,
    external_uri        TEXT,                              -- GH release URL
    superseded_at       TEXT,
    source_catalog_rev  TEXT,
    operator_note       TEXT,                              -- optional global note for CHANGELOG
    validation_summary  TEXT
);
CREATE UNIQUE INDEX ux_gh_releases_current
    ON gh_releases(version) WHERE superseded_at IS NULL;

-- ---------------------------------------------------------------------------
-- Frozen membership of each GH release. Rows NEVER change after the cut commits.
-- ---------------------------------------------------------------------------
CREATE TABLE gh_release_recitations (
    release_id           INTEGER NOT NULL REFERENCES gh_releases(id) ON DELETE CASCADE,
    slug                 TEXT    NOT NULL REFERENCES deliveries(slug),
    catalog_snapshot     TEXT    NOT NULL,                 -- JSON, frozen catalog row at cut time
    zip_sha256           TEXT    NOT NULL,
    zip_bytes            INTEGER NOT NULL,
    coverage_ayahs       INTEGER NOT NULL,
    content_hash         TEXT,                             -- SHA-256(letter_tier.json.gz || catalog.json); NULL only for legacy-migrated rows
    ts_version           TEXT    NOT NULL,                 -- per_recitation_releases.version at cut time
    change_kind          TEXT    NOT NULL,                 -- 'added' | 'refresh' | 'unchanged'
    stale_since          TEXT,                             -- set on TS regen for slugs in most-recent release
    PRIMARY KEY (release_id, slug),
    CHECK (change_kind IN ('added', 'refresh', 'unchanged')),
    CHECK (zip_bytes > 0),
    CHECK (coverage_ayahs >= 0 AND coverage_ayahs <= 6236)
);
CREATE INDEX ix_gh_release_recitations_slug
    ON gh_release_recitations(slug);
CREATE INDEX ix_gh_release_recitations_stale
    ON gh_release_recitations(stale_since) WHERE stale_since IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Channel.gh_release_eligible — data-driven public-CDN allow-list.
--
-- A delivery is eligible for GH release iff its channel has this bit set.
-- Seed catalog public CDNs to 1; future non-public channels default to 0.
-- ---------------------------------------------------------------------------
ALTER TABLE channels ADD COLUMN gh_release_eligible INTEGER NOT NULL DEFAULT 0;
UPDATE channels SET gh_release_eligible = 1
    WHERE slug IN ('mp3quran', 'everyayah', 'tarteel', 'quranicaudio', 'tvquran', 'archive_org');

-- ---------------------------------------------------------------------------
-- Collapse legacy bitrate_mode values to the v2 enum (cbr | vbr | mixed | unknown).
-- ---------------------------------------------------------------------------
UPDATE deliveries SET bitrate_mode = 'mixed'
    WHERE bitrate_mode IN ('mostly_cbr', 'mostly_vbr', 'abr');
