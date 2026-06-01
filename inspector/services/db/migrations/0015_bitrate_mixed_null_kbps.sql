-- Inspector SQLite substrate — migration 0015.
--
-- Phase 2 follow-up to 0014's BitrateMode collapse.
--
-- 0014 collapsed mostly_cbr/mostly_vbr/abr → mixed but left
-- bitrate_kbps_nominal populated with the original number, so existing rows
-- now read back as e.g. mixed/128 — which fails the Delivery pydantic
-- invariant ("bitrate_kbps_nominal must be null when bitrate_mode == mixed",
-- scripts/lib/schemas/catalog.py:178) and 500s every snapshot()-driven read
-- path (public stats / public reciters / dashboard).
--
-- Fix forward: null out kbps_nominal everywhere the mode is now mixed.
-- Plan §"`bitrate_mode` enum": "Nullable in HF catalog config (UNKNOWN → NULL)";
-- mixed semantically has no single nominal kbps, so NULL is the right value.

UPDATE deliveries
   SET bitrate_kbps_nominal = NULL
 WHERE bitrate_mode = 'mixed'
   AND bitrate_kbps_nominal IS NOT NULL;
