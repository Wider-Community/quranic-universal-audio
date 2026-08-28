"""Normalize accepted aligner segments for the native shard builder."""

from __future__ import annotations

from typing import Any

from qua_shared.timestamps_pipeline import _matched_ref_to_output_key, _normalize_from_results

V2_SCHEMA_VERSION = 2
_TRANSITION_KEY = "_transitions"


def build_raw_v2(
    chapters: list[dict],
    results_by_ch: dict[int, list[tuple[int, dict]]],
    audio_category: str,
) -> dict[str, Any]:
    """Return every accepted timing occurrence without a display projection."""
    normalized, failures = _normalize_from_results(chapters, results_by_ch, audio_category)
    raw: dict[str, Any] = {}
    for occurrences in normalized.values():
        for occurrence in occurrences:
            key = _matched_ref_to_output_key(occurrence["matched_ref"]) or _TRANSITION_KEY
            raw.setdefault(key, []).append(occurrence)
    for key in raw:
        raw[key].sort(key=lambda row: (row["ch_ref"], row["seg_index"]))
    raw["_meta"] = {"mfa_failures": failures, "schema_version": V2_SCHEMA_VERSION}
    return raw


__all__ = ["V2_SCHEMA_VERSION", "build_raw_v2"]
