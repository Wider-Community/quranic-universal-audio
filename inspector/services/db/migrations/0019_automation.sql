-- Owner-configurable release automations.
--
-- automation_config: single-row JSON blob (the owner's AutomationConfig). The
--   CHECK(id=1) pins it to one row; the reconciler + the Releases-tab Automation
--   section read/write this. Absent row → engine uses schema defaults.
-- automation_state: per-automation runtime (last fire time + result). Drives
--   the FE status line and the scheduled-cadence gate. Written ONLY when an
--   automation acts (idle ticks never touch it, so no per-tick bucket upload).
--   next_run_at is NOT stored — the route computes it live from config so idle
--   ticks stay write-free.

CREATE TABLE automation_config (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    config_json TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    updated_by  TEXT NOT NULL
);

CREATE TABLE automation_state (
    automation_id TEXT PRIMARY KEY,
    last_run_at   TEXT,
    last_status   TEXT,
    last_detail   TEXT,
    updated_at    TEXT NOT NULL
);
