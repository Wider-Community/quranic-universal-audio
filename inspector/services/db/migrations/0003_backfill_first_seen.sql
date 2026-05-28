-- Backfill users.first_seen from the earliest historical evidence (migration 0003).
--
-- WHY: the one-shot JSON→SQLite migration (scripts/migrate_json_to_sqlite.py)
-- calls ensure_user without a historical timestamp, so every migrated user got
-- first_seen = the cutover run time. The admin Users panel surfaces first_seen
-- as the "Joined" column, which made the whole legacy cohort look like it
-- joined on cutover day. All the real timestamps already live in the DB
-- (role grants, claims, requests, transitions), so recompute first_seen to the
-- earliest of them.
--
-- Only corrects BACKWARDS (e.s.t < current first_seen), so post-cutover users
-- whose first_seen is already accurate are untouched, and the statement is
-- idempotent (re-running finds nothing earlier). A user with no activity rows
-- keeps their existing first_seen.
--
-- NOTE: this is the single source of truth for the backfill — build() in
-- scripts/migrate_json_to_sqlite.py reads + executes THIS file at the end of a
-- fresh migration (schema migrations run before build() populates rows, so a
-- fresh build needs the recompute applied after its inserts). Keep it ONE
-- statement so conn.execute() can run it.
--
-- The runner wraps this file in BEGIN/…/PRAGMA user_version=3/COMMIT — do NOT
-- add transaction control or a user_version pragma here.

WITH earliest(hf_user_id, ts) AS (
    SELECT hf_user_id, MIN(ts) FROM (
        SELECT hf_user_id,   granted_at   AS ts FROM role_assignments
        UNION ALL SELECT assignee_id,  claimed_at         FROM claims
        UNION ALL SELECT requester_id, submitted_at       FROM requests
        UNION ALL SELECT actor_id,     ts                 FROM transitions WHERE actor_id IS NOT NULL
    ) WHERE ts IS NOT NULL
    GROUP BY hf_user_id
)
UPDATE users
   SET first_seen = (SELECT ts FROM earliest WHERE earliest.hf_user_id = users.hf_user_id)
 WHERE EXISTS (
     SELECT 1 FROM earliest e
      WHERE e.hf_user_id = users.hf_user_id
        AND e.ts IS NOT NULL
        AND (users.first_seen IS NULL OR e.ts < users.first_seen)
 );
