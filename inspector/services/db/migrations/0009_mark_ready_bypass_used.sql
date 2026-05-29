-- Inspector SQLite substrate — mark-ready owner bypass flag (migration 0009).
--
-- Adds ``mark_ready_bypass_used`` to ``claims``. Set to 1 when an owner (or a
-- tier granted the ``claim.mark_ready_skip_gates`` capability) submitted
-- mark-ready without satisfying the form checklist or the zero-count
-- blocking-validation gate. Set on the OPEN claim when the bypass was used,
-- cleared together with ``marked_ready_at`` + the other mark-ready submission
-- columns on unmark / release / force-release / reassign. Preserved on closed
-- history rows so admins can audit past bypass cycles from the Reviews drawer.
--
-- Nullable INTEGER (0/1, NULL when no submission) — matches the existing three
-- ``mark_ready_*`` columns added in migration 0007.
--
-- Conventions match prior migrations: INTEGER 0/1 booleans, no transaction
-- control (the runner wraps the script in BEGIN/COMMIT and bumps user_version).

ALTER TABLE claims ADD COLUMN mark_ready_bypass_used INTEGER;  -- 0/1; NULL when no submission
