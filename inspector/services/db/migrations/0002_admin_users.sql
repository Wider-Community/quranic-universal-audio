-- Inspector SQLite substrate — admin Users panel + visitor analytics (migration 0002).
--
-- Adds:
--   * users.last_login_at / last_entry_at — login + page-entry recency (Tier 1).
--     last_login_at is bumped in the OAuth callback; last_entry_at is bumped
--     (debounced ~15 min) on /api/me so we track "everyone who logged in" and
--     "active recently" without a write per page load.
--   * visitor_daily — per-UTC-day rollup of anon vs signed-in traffic (Tier 2/3).
--     Written by an HOURLY in-memory→DB flush daemon (one txn/hour = one bucket
--     upload/hour; never per request). unique_* are upper-bound estimates — a
--     visitor active across multiple hours is counted once per hour-flush
--     (documented + accepted for v1; FE renders unique-anon with a ~ marker).
--   * indexes the admin-users aggregations need (none existed at 0001):
--     transitions(actor_id, ts), requests(requester_id), claims(assignee_id full).
--
-- The runner wraps this file in BEGIN/…/PRAGMA user_version=2/COMMIT — do NOT
-- add transaction control or a user_version pragma here.

-- ---------------------------------------------------------------------------
-- identity recency (Tier 1)
-- ---------------------------------------------------------------------------
ALTER TABLE users ADD COLUMN last_login_at TEXT;   -- bumped in OAuth callback
ALTER TABLE users ADD COLUMN last_entry_at TEXT;   -- bumped (debounced) in /api/me

-- ---------------------------------------------------------------------------
-- visitor traffic rollup (Tier 2/3)
-- ---------------------------------------------------------------------------
CREATE TABLE visitor_daily (
    date             TEXT PRIMARY KEY,             -- 'YYYY-MM-DD' UTC
    signed_in_hits   INTEGER NOT NULL DEFAULT 0,
    anon_hits        INTEGER NOT NULL DEFAULT 0,
    unique_signed_in INTEGER NOT NULL DEFAULT 0,   -- distinct hf_user_id that day
    unique_anon      INTEGER NOT NULL DEFAULT 0    -- distinct anon_id that day (estimate)
);

-- ---------------------------------------------------------------------------
-- indexes for the admin-users aggregations
-- ---------------------------------------------------------------------------
-- serves MAX(ts) GROUP BY actor_id (list) + WHERE actor_id=? ORDER BY (detail).
-- mark-ready reviews count is served by the existing ix_transitions_event.
CREATE INDEX ix_transitions_actor_ts ON transitions(actor_id, ts);
-- request counts/history per requester.
CREATE INDEX ix_requests_requester   ON requests(requester_id);
-- FULL claims-by-assignee (lifetime history + turnaround); distinct from the
-- partial open-claim index ix_claim_open_assignee (WHERE released_at IS NULL).
CREATE INDEX ix_claims_assignee      ON claims(assignee_id);
