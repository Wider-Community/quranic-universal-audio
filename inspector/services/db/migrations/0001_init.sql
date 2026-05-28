-- Inspector SQLite substrate — initial schema (migration 0001).
--
-- Collapses the 7 bucket-resident JSON stores (state, catalog, access,
-- pending_requests, 3x request_archive, activity_state) + the audit JSONL
-- into one DB. Per-reciter content (wip/<slug>/, published/<slug>/) stays
-- JSON-on-bucket and is NOT modelled here.
--
-- Conventions:
--   * datetimes are TEXT, ISO-8601 UTC (matches pydantic model_dump(mode="json")
--     so round-trips are byte-stable and lexical ordering == chronological).
--   * booleans are INTEGER 0/1.
--   * JSON-valued columns are TEXT (orjson-encoded).
--   * NO CHECK on free-vocabulary columns (transitions.event, requests.kind,
--     claims.close_reason) so new event/request kinds need zero migration —
--     validity is enforced in the pydantic/app layer.
--
-- See docs/proposals/inspector-substrate-redesign.md and the build plan.

-- ---------------------------------------------------------------------------
-- runtime metadata (db_seq monotonic counter, container nonce, etc.)
-- ---------------------------------------------------------------------------
CREATE TABLE db_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- db_seq: bumped on every committed write txn; the CAS guard for bucket upload.
INSERT INTO db_meta(key, value) VALUES ('db_seq', '0');

-- ---------------------------------------------------------------------------
-- identity + access
-- ---------------------------------------------------------------------------
CREATE TABLE users (
    hf_user_id  TEXT PRIMARY KEY,
    login_cache TEXT,
    first_seen  TEXT,
    last_seen   TEXT
);

CREATE TABLE role_assignments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    hf_user_id  TEXT NOT NULL REFERENCES users(hf_user_id),
    role        TEXT NOT NULL,            -- 'maintainer' | 'owner'
    granted_at  TEXT NOT NULL,
    granted_by  TEXT REFERENCES users(hf_user_id),
    revoked_at  TEXT,
    revoked_by  TEXT REFERENCES users(hf_user_id),
    reason      TEXT
);
-- one active role per user
CREATE UNIQUE INDEX ux_role_active ON role_assignments(hf_user_id)
    WHERE revoked_at IS NULL;
CREATE INDEX ix_role_user ON role_assignments(hf_user_id);

-- ---------------------------------------------------------------------------
-- catalog vocab (FK targets for deliveries.*) — full fidelity, not just code+label
-- ---------------------------------------------------------------------------
CREATE TABLE riwayahs (
    slug  TEXT PRIMARY KEY,
    short TEXT NOT NULL,
    name  TEXT NOT NULL
);
CREATE TABLE styles (
    slug  TEXT PRIMARY KEY,
    short TEXT NOT NULL,
    name  TEXT NOT NULL
);
CREATE TABLE sources (
    slug             TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    url              TEXT,
    audio_categories TEXT NOT NULL DEFAULT '[]'   -- JSON array
);
CREATE TABLE channels (
    slug          TEXT PRIMARY KEY,
    short         TEXT NOT NULL,
    name          TEXT NOT NULL,
    host_patterns TEXT NOT NULL DEFAULT '[]'      -- JSON array
);
CREATE TABLE recording_contexts (
    slug TEXT PRIMARY KEY,                 -- studio|broadcast|prayer|taraweeh|mixed
    name TEXT NOT NULL
);

-- catalog-level metadata — single row id=1.
-- ``derived`` (e.g. source_channels) is PERSISTED verbatim (JSON) rather than
-- reconstructed, so the full ReciterCatalog.model_dump() round-trips byte-for-byte
-- through the migration parity gate; it's refreshed when deliveries change.
CREATE TABLE catalog_meta (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    schema_version INTEGER NOT NULL DEFAULT 2,
    generated_at   TEXT,
    derived        TEXT NOT NULL DEFAULT '{"source_channels": []}'
);
INSERT INTO catalog_meta(id, schema_version, generated_at, derived)
    VALUES (1, 2, NULL, '{"source_channels": []}');

CREATE TABLE catalog_aliases (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,                    -- 'slug' | 'reciter_id'
    old  TEXT NOT NULL,
    new  TEXT NOT NULL,
    ts   TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- catalog: reciters + deliveries
-- ---------------------------------------------------------------------------
CREATE TABLE reciters (
    reciter_id TEXT PRIMARY KEY,
    name_en    TEXT NOT NULL,
    name_ar    TEXT,
    country    TEXT,
    notes      TEXT
);

CREATE TABLE deliveries (
    slug                 TEXT PRIMARY KEY,
    reciter_id           TEXT NOT NULL REFERENCES reciters(reciter_id),
    riwayah              TEXT NOT NULL REFERENCES riwayahs(slug),
    style                TEXT NOT NULL REFERENCES styles(slug),
    source               TEXT NOT NULL REFERENCES sources(slug),
    channel              TEXT NOT NULL REFERENCES channels(slug),
    recording_context    TEXT REFERENCES recording_contexts(slug),
    recording_year       INTEGER,
    variant_label        TEXT,
    audio_category       TEXT NOT NULL,    -- by_surah | by_ayah
    chapter_count        INTEGER NOT NULL,
    codec                TEXT NOT NULL DEFAULT 'mp3',
    container            TEXT NOT NULL DEFAULT 'mp3',
    sample_rate_hz       INTEGER,
    channels             INTEGER,
    bitrate_mode         TEXT NOT NULL DEFAULT 'unknown',
    bitrate_kbps_nominal INTEGER,
    total_duration_sec   INTEGER,
    added_at             TEXT NOT NULL,
    added_by_hf_id       TEXT NOT NULL
);
CREATE INDEX ix_deliveries_reciter ON deliveries(reciter_id);

-- ---------------------------------------------------------------------------
-- canonical event log (replaces audit/<YYYY>-<MM>.jsonl)
-- ---------------------------------------------------------------------------
CREATE TABLE transitions (
    seq                  INTEGER PRIMARY KEY AUTOINCREMENT,  -- ordering / tie-break
    id                   TEXT NOT NULL UNIQUE,               -- stable external ref (was audit request_id)
    ts                   TEXT NOT NULL,
    slug                 TEXT REFERENCES deliveries(slug),   -- nullable (role grants etc.)
    event                TEXT NOT NULL,                      -- NO CHECK: free vocabulary
    from_state           TEXT,
    to_state             TEXT,
    actor_id             TEXT REFERENCES users(hf_user_id),
    actor_login_snapshot TEXT,
    actor_role_snapshot  TEXT,
    reason               TEXT,
    result               TEXT NOT NULL DEFAULT 'ok',         -- 'ok' | 'error'
    payload              TEXT NOT NULL DEFAULT '{}',         -- JSON
    content_hash         TEXT                                -- sha1(ts|event|slug|actor_hf|result)[:16]
);
CREATE INDEX ix_transitions_slug_ts ON transitions(slug, ts);
CREATE INDEX ix_transitions_ts      ON transitions(ts DESC);
CREATE INDEX ix_transitions_event   ON transitions(event, ts);
CREATE INDEX ix_transitions_hash    ON transitions(content_hash);

-- ---------------------------------------------------------------------------
-- lifecycle: current projection only
-- ---------------------------------------------------------------------------
CREATE TABLE delivery_states (
    slug                     TEXT PRIMARY KEY REFERENCES deliveries(slug),
    state                    TEXT NOT NULL,    -- catalogued|awaiting_alignment|awaiting_review|
                                               --   under_review|awaiting_timestamps|released
    state_since              TEXT NOT NULL,
    visibility               TEXT NOT NULL DEFAULT 'public',   -- public | discarded
    visibility_reason        TEXT,
    last_save_at             TEXT,
    created_by_transition_id TEXT REFERENCES transitions(id),
    -- RETAINED (live handlers still write these; drop only when kill-features ship):
    timestamps_job_ids       TEXT NOT NULL DEFAULT '[]',       -- JSON array
    prefetch_purge_at        TEXT,
    revision_in_progress     TEXT,                             -- JSON (RevisionContext) or NULL
    CHECK (visibility IN ('public', 'discarded')),
    CHECK (visibility <> 'discarded' OR visibility_reason IS NOT NULL)
);
CREATE INDEX ix_delivery_states_state ON delivery_states(state);

-- ---------------------------------------------------------------------------
-- claims first-class (current + history)
-- ---------------------------------------------------------------------------
CREATE TABLE claims (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    slug                    TEXT NOT NULL REFERENCES deliveries(slug),
    assignee_id             TEXT NOT NULL REFERENCES users(hf_user_id),
    assignee_login_snapshot TEXT,             -- login at claim time; NOT a live users.login_cache join
    claimed_at              TEXT NOT NULL,
    released_at             TEXT,
    marked_ready_at         TEXT,
    close_reason            TEXT,             -- NO CHECK: released|published|force_released|reassigned|...
    opened_by_transition_id TEXT REFERENCES transitions(id),
    closed_by_transition_id TEXT REFERENCES transitions(id)
);
-- one open claim per slug
CREATE UNIQUE INDEX ux_claim_open_slug ON claims(slug) WHERE released_at IS NULL;
-- one open claim per assignee (one-claim-per-non-owner is enforced in the txn;
-- owners are exempt by policy so this is NOT a DB unique index)
CREATE INDEX ix_claim_open_assignee ON claims(assignee_id) WHERE released_at IS NULL;

-- ---------------------------------------------------------------------------
-- requests collapse: pending + 3 archives → one table (forward-compatible)
-- ---------------------------------------------------------------------------
CREATE TABLE requests (
    id                      TEXT PRIMARY KEY,
    kind                    TEXT NOT NULL,    -- NO CHECK: existing_combo_edit|existing_reciter_new_combo|new_reciter|...
    slug                    TEXT REFERENCES deliveries(slug),  -- NULL for new_reciter (no slug yet)
    requester_id            TEXT NOT NULL REFERENCES users(hf_user_id),
    submitted_at            TEXT NOT NULL,
    status                  TEXT NOT NULL,    -- pending | accepted | returned | discarded
    resolved_at             TEXT,
    resolved_by_id          TEXT REFERENCES users(hf_user_id),
    resolution_reason       TEXT,
    auto_claim              INTEGER NOT NULL DEFAULT 0,
    comments                TEXT,
    payload                 TEXT NOT NULL DEFAULT '{}',  -- JSON: proposed_edits + source + new_reciter + future
    opened_by_transition_id TEXT REFERENCES transitions(id),
    closed_by_transition_id TEXT REFERENCES transitions(id)
);
-- one open (pending) request per existing slug; slugless (new_reciter) exempt
CREATE UNIQUE INDEX ux_request_pending_slug ON requests(slug)
    WHERE status = 'pending' AND slug IS NOT NULL;
CREATE INDEX ix_requests_status ON requests(status);
CREATE INDEX ix_requests_slug   ON requests(slug);

-- ---------------------------------------------------------------------------
-- activity feed sidecars (reference the content-hash string the FE already uses)
-- ---------------------------------------------------------------------------
CREATE TABLE activity_dismissals (
    audit_content_hash TEXT NOT NULL,
    hf_user_id         TEXT NOT NULL REFERENCES users(hf_user_id),
    ts                 TEXT NOT NULL,
    PRIMARY KEY (audit_content_hash, hf_user_id)
);

CREATE TABLE activity_tombstones (
    audit_content_hash TEXT PRIMARY KEY,
    deleted_by_id      TEXT REFERENCES users(hf_user_id),
    reason             TEXT,
    ts                 TEXT NOT NULL
);
