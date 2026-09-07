-- Durable state for owner-triggered destructive recitation purges.
--
-- The delivery/catalog and immutable audit/release history remain in place so
-- Undiscard can restore the requestable identity and the historical record can
-- still explain what happened. This table tracks the mutable external purge.

CREATE TABLE recitation_discard_cleanup (
    slug                 TEXT PRIMARY KEY REFERENCES deliveries(slug),
    status               TEXT NOT NULL, -- pending | failed | completed | restored
    requested_at         TEXT NOT NULL,
    requested_by         TEXT NOT NULL REFERENCES users(hf_user_id),
    reason               TEXT NOT NULL,
    completed_at         TEXT,
    last_error           TEXT,
    CHECK (status IN ('pending', 'failed', 'completed', 'restored'))
);

CREATE INDEX ix_discard_cleanup_status
    ON recitation_discard_cleanup(status);
