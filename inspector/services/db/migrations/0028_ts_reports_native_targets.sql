-- Native v12 report identities and removal of every positional v11 field.
--
-- A live database with reports MUST first be processed by
-- scripts/migrations/migrate_ts_reports_v12.py. The guard deliberately aborts
-- boot if even one target was not mapped exactly.

CREATE TABLE IF NOT EXISTS ts_report_v12_map (
    report_id     INTEGER PRIMARY KEY,
    reading_id   TEXT NOT NULL,
    target_kind  TEXT NOT NULL,
    target_id    TEXT NOT NULL,
    target_key   TEXT NOT NULL,
    snapshot_json TEXT NOT NULL
);

CREATE TEMP TABLE _ts_v12_guard (
    remaining INTEGER NOT NULL CHECK (remaining = 0)
);
INSERT INTO _ts_v12_guard
SELECT COUNT(*) FROM ts_reports AS report
LEFT JOIN ts_report_v12_map AS mapping ON mapping.report_id = report.id
WHERE mapping.report_id IS NULL;
DROP TABLE _ts_v12_guard;

CREATE TABLE ts_reports_v12 (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    slug                   TEXT NOT NULL,
    verse_key              TEXT NOT NULL,
    chapter                INTEGER NOT NULL,
    category               TEXT NOT NULL,
    subtype                TEXT,
    timing_onset           TEXT,
    timing_offset          TEXT,
    target_kind            TEXT NOT NULL,
    reading_id             TEXT NOT NULL,
    target_id              TEXT NOT NULL,
    target_key             TEXT NOT NULL,
    snapshot_json          TEXT NOT NULL,
    hf_user_id             TEXT REFERENCES users(hf_user_id),
    anon_token             TEXT,
    login_at_time          TEXT,
    role_at_time           TEXT,
    comment                TEXT,
    selected_rule_tags     TEXT,
    status                 TEXT NOT NULL DEFAULT 'open',
    resolved_by_hf_user_id TEXT REFERENCES users(hf_user_id),
    resolved_by_login      TEXT,
    resolver_comment       TEXT,
    resolved_at            TEXT,
    stale                  INTEGER NOT NULL DEFAULT 0,
    stale_at               TEXT,
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL,
    hidden_at              TEXT
);

INSERT INTO ts_reports_v12 (
    id, slug, verse_key, chapter, category, subtype,
    timing_onset, timing_offset, target_kind, reading_id, target_id,
    target_key, snapshot_json, hf_user_id, anon_token, login_at_time,
    role_at_time, comment, selected_rule_tags, status,
    resolved_by_hf_user_id, resolved_by_login, resolver_comment, resolved_at,
    stale, stale_at, created_at, updated_at, hidden_at
)
SELECT
    report.id, report.slug, report.verse_key, report.chapter, report.category, report.subtype,
    report.timing_onset, report.timing_offset, mapping.target_kind, mapping.reading_id,
    mapping.target_id, mapping.target_key, mapping.snapshot_json,
    report.hf_user_id, report.anon_token, report.login_at_time,
    report.role_at_time, report.comment, report.selected_rule_tags, report.status,
    report.resolved_by_hf_user_id, report.resolved_by_login, report.resolver_comment,
    report.resolved_at, report.stale, report.stale_at, report.created_at,
    report.updated_at, report.hidden_at
FROM ts_reports AS report
JOIN ts_report_v12_map AS mapping ON mapping.report_id = report.id;

DROP TABLE ts_reports;
ALTER TABLE ts_reports_v12 RENAME TO ts_reports;
DROP TABLE ts_report_v12_map;

CREATE UNIQUE INDEX ux_tsreport_user
    ON ts_reports(slug, verse_key, category, target_key, hf_user_id)
    WHERE hf_user_id IS NOT NULL;
CREATE UNIQUE INDEX ux_tsreport_anon
    ON ts_reports(slug, verse_key, category, target_key, anon_token)
    WHERE anon_token IS NOT NULL;
CREATE INDEX ix_tsreport_slug_verse ON ts_reports(slug, verse_key);
CREATE INDEX ix_tsreport_slug_status ON ts_reports(slug, status);
CREATE INDEX ix_tsreport_recheck
    ON ts_reports(slug, chapter) WHERE status = 'open' AND stale = 0;
CREATE INDEX ix_tsreport_visible
    ON ts_reports(slug, verse_key) WHERE hidden_at IS NULL;
CREATE INDEX ix_tsreport_native_target
    ON ts_reports(slug, reading_id, target_kind, target_id);
