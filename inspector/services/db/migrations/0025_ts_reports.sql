-- Inspector SQLite substrate — migration 0025.
--
-- Categorized, cell-addressable Timestamps-tab reports (the rework of the
-- verse-level-comment-only `ts_verse_flags`). A report names a category
-- (audio / timing / mapping / tajweed / other) and points at a flexible target:
-- the whole verse, a word, a letter/grapheme cell, a phoneme, a grapheme↔phoneme
-- column, or a co-timed cell-group (`share_group`). Owners resolve a report
-- (single terminal `resolved` outcome + optional comment); the reporter is notified.
--
-- Classification differs by category: `tajweed` uses `subtype`; `timing` uses two
-- boundary axes (`timing_onset` / `timing_offset`, each early|late, ≥1 set) from
-- which the human label is derived; audio/mapping/other carry neither.
--
-- Identity mirrors `ts_verse_flags`: EITHER a signed-in HF account
-- (`hf_user_id` + cookie snapshot in `login_at_time`/`role_at_time`) OR an
-- anonymous browser token (`anon_token`). Exactly one is set. Multiple reports
-- per identity per verse are allowed — uniqueness is per (identity, category,
-- target), not per verse — so a user can file distinct issues independently.
--
-- `target_key` is a canonical string of the target descriptor
-- ("kind:wi:sli:ci:pi:sg", NULLs as empty) so the per-identity uniqueness can
-- be enforced by a single partial index per identity column.
--
-- `snap_*` is a denormalized snapshot of the targeted shard content captured at
-- create time. There is no per-cell hash anywhere, so the snapshot IS the
-- drift fingerprint: when a reciter's shards are regenerated, each open report's
-- target is re-resolved against the new shard and the report is marked `stale`
-- iff its category-relevant fields changed (see services/ts_reports/
-- ts_target_snapshot.py + services/admin/timestamps_jobs.py).
--
-- Conventions match prior migrations: TEXT ISO-8601 UTC timestamps, nullable
-- FK to users, no transaction control (the runner wraps BEGIN/COMMIT +
-- user_version).

CREATE TABLE ts_reports (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    slug                  TEXT NOT NULL,
    verse_key             TEXT NOT NULL,                       -- "surah:ayah", e.g. "2:45"
    chapter               INTEGER NOT NULL,                    -- surah, denormalized for stale-scoping

    -- Classification
    category              TEXT NOT NULL,                       -- audio|timing|mapping|tajweed|other
    subtype               TEXT,                                -- tajweed enum; NULL for audio/timing/mapping/other

    -- Timing boundary axes (timing category only; NULL elsewhere). A timing
    -- report flags the onset (start) and/or offset (end); at least one is set.
    -- The human label (too short/long, shifted, starts/finishes early/late) is
    -- derived from the pair (qua_shared/schemas/wire/ts_reports.py::timing_label).
    timing_onset          TEXT,                                -- early|late|NULL (NULL = start is fine)
    timing_offset         TEXT,                                -- early|late|NULL (NULL = end is fine)

    -- Target descriptor (all nullable; a verse-level report leaves them NULL)
    target_kind           TEXT NOT NULL,                       -- verse|word|cell|phoneme|column|cell_group
    word_index            INTEGER,                             -- 0-based word position in the verse
    source_letter_index   INTEGER,                             -- anchoring letter within the word
    cell_index            INTEGER,                             -- index into the word's cells[]
    phoneme_flat_index    INTEGER,                             -- word-local indexable-phone index
    share_group           INTEGER,                             -- co-timed cell-group id
    target_key            TEXT NOT NULL,                       -- canonical descriptor key for ON CONFLICT

    -- Denormalized snapshot of the targeted shard content (drift fingerprint)
    snap_chars            TEXT,
    snap_role             TEXT,
    snap_status           TEXT,
    snap_tag              TEXT,
    snap_secondary_tags   TEXT,                                -- json array
    snap_phoneme_rule_tags TEXT,                               -- json array (parallel to phoneme_indices)
    snap_phones           TEXT,                                -- json array of mapped phones (column binding)
    snap_share_group      INTEGER,
    snap_word_text        TEXT,
    snap_verse_text       TEXT,
    snap_schema_version   INTEGER,
    snap_onset_ms         INTEGER,                             -- target start ms at create (timing boundary-shift fp)
    snap_offset_ms        INTEGER,                             -- target end ms at create

    -- Reporter identity (exactly one of hf_user_id / anon_token)
    hf_user_id            TEXT REFERENCES users(hf_user_id),   -- NULL for anonymous
    anon_token            TEXT,                                -- set for anon, NULL for signed-in
    login_at_time         TEXT,                                -- actor cookie snapshot (NULL for anon)
    role_at_time          TEXT,                                -- actor role snapshot (NULL for anon)

    -- Report content
    comment               TEXT,                                -- optional/mandatory per category (enforced in wire/route)

    -- Resolution (single terminal `resolved` outcome)
    status                TEXT NOT NULL DEFAULT 'open',        -- open|resolved
    resolved_by_hf_user_id TEXT REFERENCES users(hf_user_id),
    resolved_by_login     TEXT,
    resolver_comment      TEXT,                                -- optional owner note
    resolved_at           TEXT,

    -- Staleness (set when a regeneration changed the targeted content)
    stale                 INTEGER NOT NULL DEFAULT 0,          -- 0|1
    stale_at              TEXT,

    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
);

-- One report per (identity, category, target). NULLs compare distinct in
-- SQLite, so uniqueness is split into one partial index per identity column.
CREATE UNIQUE INDEX ux_tsreport_user
    ON ts_reports(slug, verse_key, category, target_key, hf_user_id)
    WHERE hf_user_id IS NOT NULL;
CREATE UNIQUE INDEX ux_tsreport_anon
    ON ts_reports(slug, verse_key, category, target_key, anon_token)
    WHERE anon_token IS NOT NULL;

CREATE INDEX ix_tsreport_slug_verse ON ts_reports(slug, verse_key);
CREATE INDEX ix_tsreport_slug_status ON ts_reports(slug, status);
-- Stale-recheck after a regen scans the slug's open reports by chapter.
CREATE INDEX ix_tsreport_recheck ON ts_reports(slug, chapter) WHERE status = 'open' AND stale = 0;
