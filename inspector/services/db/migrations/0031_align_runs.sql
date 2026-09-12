-- Native align pipeline runs (acquire → align → sidecars → assemble), one
-- durable row per run. Stage transitions are the only writes: per-chapter
-- progress lives in staged bucket files + process memory, so a whole-mushaf
-- run does not push the DB to the bucket once per chapter.

CREATE TABLE align_runs (
    run_id          TEXT PRIMARY KEY,
    slug            TEXT NOT NULL REFERENCES deliveries(slug),
    stage           TEXT NOT NULL,   -- acquire | align | sidecars | assemble | done
    status          TEXT NOT NULL,   -- pending | running | failed | succeeded | canceled
    requested_by    TEXT NOT NULL,
    params_json     TEXT NOT NULL,
    acquire_job_id  TEXT,
    attempt         INTEGER NOT NULL DEFAULT 1,
    chapters_total  INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    started_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    ended_at        TEXT,
    CHECK (stage IN ('acquire', 'align', 'sidecars', 'assemble', 'done')),
    CHECK (status IN ('pending', 'running', 'failed', 'succeeded', 'canceled'))
);

-- One live run per slug: a failed run stays "active" until retried or canceled.
CREATE UNIQUE INDEX ux_align_runs_active
    ON align_runs(slug) WHERE status IN ('pending', 'running', 'failed');

CREATE INDEX ix_align_runs_status ON align_runs(status);
