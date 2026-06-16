-- Inspector SQLite substrate — migration 0022.
--
-- Email-notification subscriptions. One row per destination email address —
-- NOT keyed on the HF account, so anonymous visitors can subscribe. `hf_user_id`
-- is an optional association set when the saver is signed in (used to match the
-- `request_aligned` event to the requester). `prefs` is the JSON EmailPreferences
-- blob (the FE EmailPrefs shape, minus the email which is the key).
--
-- `manage_token` is the stable per-subscription secret: it powers the one-click
-- unsubscribe link and the email "manage" deep-link, and lets a returning
-- anonymous visitor re-fetch fresh server state. Minted once on first save.
--
-- Conventions match prior migrations: TEXT ISO-8601 UTC timestamps, no
-- transaction control (the runner wraps BEGIN/COMMIT + user_version).

CREATE TABLE email_subscriptions (
    email          TEXT PRIMARY KEY,                   -- normalized lowercase
    hf_user_id     TEXT REFERENCES users(hf_user_id),  -- nullable association
    prefs          TEXT NOT NULL,                       -- JSON: EmailPreferences blob
    manage_token   TEXT NOT NULL,                       -- unsubscribe + manage handle
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE UNIQUE INDEX ux_email_subs_token ON email_subscriptions(manage_token);
CREATE INDEX ix_email_subs_hf_user ON email_subscriptions(hf_user_id)
    WHERE hf_user_id IS NOT NULL;
