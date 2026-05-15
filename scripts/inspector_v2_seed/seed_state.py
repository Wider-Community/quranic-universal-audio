"""Seed ``<bucket>/state/reciter_state.json`` from filesystem signals.

For each directory under ``data/recitation_segments/<slug>/``:

- If both ``segments.json`` and the timestamps file under
  ``data/timestamps/{by_ayah_audio,by_surah_audio}/<slug>/timestamps.json``
  are present → state ``"completed"``.
- Otherwise (segments only) → state ``"awaiting_review"``.

**Slug reconciliation.** The on-disk ``data/recitation_segments/<dir>/``
names are v1 (pre-dedup) — they may not match the catalog's canonical
delivery slugs (e.g. ``maher_al_meaqli`` was renamed to
``maher_al_muaiqly_mp3quran`` in the v2 catalog). Before writing the state
row, every v1 dir name is translated via ``CUTOVER_CANONICAL_MAP`` (which
the catalog promotion + reconcile_cutover_slugs.py also reference). Any
dir name without an entry in the map falls through to its v1 name — that
covers the 8 wip reciters which don't yet have a published canonical
counterpart.

Overwrites ``<bucket>/state/reciter_state.json`` in-place. Any in-progress
claims will be cleared — re-claim happens through the Inspector UI after
cutover.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from ._env import load_repo_env, repo_root

load_repo_env()

from scripts.lib.reciter_eligibility import (
    find_eligible_reciters,
    has_tracked_timestamps,
)
from scripts.lib.schemas import ReciterRow, ReciterState, ReciterStateFile
from inspector.services import storage_paths
from inspector.services.hf_bucket import get_backend


# v1 dir name → canonical delivery slug. All 6 completed cutover reciters
# aligned against mp3quran by_surah Hafs Murattal (confirmed via
# segments.json _meta.audio_source). The 3 entries that change reflect the
# dedup naming-style pass (114 corrections); the other 3 happen to match.
# Future v1 dirs (wip side) fall through unchanged because they don't yet
# correspond to a canonical published delivery slug.
CUTOVER_CANONICAL_MAP: dict[str, str] = {
    # 6 completed (mp3quran, by_surah, Hafs Murattal)
    "maher_al_meaqli": "maher_al_muaiqly_mp3quran",
    "mishary_alafasi": "mishary_rashid_al_afasy_mp3quran",
    "mohammed_siddiq_al_minshawi": "mohammed_siddiq_al_minshawi_mp3quran",
    "nasser_alqatami": "nasser_al_qatami_mp3quran",
    "saad_al_ghamdi": "saad_al_ghamdi_mp3quran",
    "yasser_al_dosari": "yasser_al_dosari_mp3quran",
    # 8 wip reciters — slug determined by the audio_source in their v1
    # segments.json _meta + the catalog's canonical delivery slug.
    # Dedup naming corrections renamed Ahmad→Ahmed for 2; Bandar Balilah →
    # Baleela for 1. Abdullah Ali Jabir's v1 alignment used the qul-served
    # Taraweeh recording (the only by_surah/qul delivery in catalog).
    "abdullah_ali_jabir": "abdullah_ali_jabir_taraweeh_qdc",
    "abdulwadood_haneef": "abdulwadood_haneef_mp3quran",
    "ahmad_saud": "ahmed_saud_mp3quran",
    "ahmad_talib_bin_humaid": "ahmed_talib_bin_humaid_mp3quran",
    "bandar_balilah": "bandar_baleela_mp3quran",
    "mohammed_alghazali": "mohammed_alghazali_archive",
    "mohammed_ayyub": "mohammed_ayyub_mp3quran",
    "raad_al_kurdi": "raad_al_kurdi_mp3quran",
}


def main() -> int:
    root = repo_root()
    segs_dir = root / "data" / "recitation_segments"
    if not segs_dir.is_dir():
        print(f"FAIL: {segs_dir} not found", file=sys.stderr)
        return 1

    eligible = set(find_eligible_reciters(repo_root=root))
    now = datetime.now(timezone.utc)
    rows: list[ReciterRow] = []
    for child in sorted(segs_dir.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        v1_slug = child.name
        if not (child / "segments.json").exists():
            print(f"skip {v1_slug}: no segments.json")
            continue
        canonical_slug = CUTOVER_CANONICAL_MAP.get(v1_slug, v1_slug)
        if v1_slug in eligible:
            state = ReciterState.COMPLETED
        else:
            state = ReciterState.AWAITING_REVIEW
        rows.append(ReciterRow(slug=canonical_slug, state=state, state_since=now))
        tracked_ts = "ts" if has_tracked_timestamps(v1_slug, root) else "  "
        rename = f"  (renamed from {v1_slug})" if canonical_slug != v1_slug else ""
        print(f"  {canonical_slug:45s} [{tracked_ts}] -> {state.value}{rename}")

    state_file = ReciterStateFile(reciters=rows)
    backend = get_backend()
    backend.write_json_atomic(
        storage_paths.state_path(),
        state_file.model_dump(mode="json"),
    )
    print(
        f"ok  uploaded {len(rows)} rows to {storage_paths.state_path()} "
        f"(completed={sum(1 for r in rows if r.state == ReciterState.COMPLETED)}, "
        f"awaiting_review={sum(1 for r in rows if r.state == ReciterState.AWAITING_REVIEW)})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
