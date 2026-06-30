-- Inspector SQLite substrate — migration 0027.
--
-- `selected_rule_tags` for tajweed "wrong rule" reports: the internal tajweed
-- tag id(s) the reporter picked as wrong on the targeted cell (JSON array of
-- strings). Distinct from `snap_*` (the staleness fingerprint of the cell's
-- actual content at report time) — this is the reporter's claim about WHICH
-- rule is wrong, keyed by the internal data-model tag, not a display label.
-- NULL for every non-tajweed / non-wrong_rule report.

ALTER TABLE ts_reports ADD COLUMN selected_rule_tags TEXT;  -- json array, NULL = none
