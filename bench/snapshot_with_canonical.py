"""One-off: snapshot ground-truth with the phonemic side of boundary_adj
captured (matches the WIP ground-truth pattern, since WIP snapshots were
taken before the validate runtime switched to ``canonical=None``).

Mechanic: temporarily stamp ``is_boundary_adj`` on each seg using
``compute_is_boundary_adj(canonical=loaded)`` in-memory only (no bucket
write), populate the seg cache so validate reads the stamped values, then
snapshot. This produces ground truth that the canonical-loaded backfill
will drift-match byte-for-byte.

Targets published slugs by default (since WIP already has correct GT).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSPECTOR = REPO_ROOT / "inspector"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(INSPECTOR))

from adapters.detailed_json import load_entries_from_bytes  # noqa: E402
from services import cache, data_dir  # noqa: E402
from services import state as state_service  # noqa: E402
from services.data_loader import get_word_counts  # noqa: E402
from services.phonemizer_service import get_canonical_phonemes  # noqa: E402
from services.validation import validate_reciter_segments  # noqa: E402
from services.validation.classifier import compute_is_boundary_adj  # noqa: E402

from snapshot import normalize  # noqa: E402

GROUND_TRUTH = REPO_ROOT / "bench" / "ground_truth"


def _stamp(entries: list[dict], single_word_verses: set, canonical: dict | None) -> int:
    """Stamp is_boundary_adj on every seg in place; return fire count."""
    fires = 0
    for entry in entries:
        for seg in entry.get("segments", []):
            matched_ref = seg.get("matched_ref") or ""
            parts = matched_ref.split("-")
            if len(parts) != 2:
                seg["is_boundary_adj"] = False
                continue
            sp = parts[0].split(":")
            ep = parts[1].split(":")
            if len(sp) != 3 or len(ep) != 3:
                seg["is_boundary_adj"] = False
                continue
            try:
                surah = int(sp[0]); s_ayah = int(sp[1])
                s_word = int(sp[2]); e_word = int(ep[2])
            except ValueError:
                seg["is_boundary_adj"] = False
                continue
            val = compute_is_boundary_adj(
                seg, surah, s_ayah, s_word, e_word, single_word_verses, canonical,
            )
            seg["is_boundary_adj"] = val
            if val:
                fires += 1
    return fires


def snapshot_published_with_phonemes() -> int:
    state_service.hydrate()
    GROUND_TRUTH.mkdir(parents=True, exist_ok=True)

    wc = get_word_counts()
    single_word_verses = {k for k, v in wc.items() if v == 1}

    pub_slugs = sorted(data_dir.list_slugs("published"))
    print(f"Re-snapshotting {len(pub_slugs)} published slug(s) with canonical loaded...\n")

    for slug in pub_slugs:
        raw = data_dir.read_detailed_bytes(slug)
        if raw is None:
            print(f"  {slug:<45s} MISSING")
            continue
        meta, entries = load_entries_from_bytes(raw)

        canonical = get_canonical_phonemes(slug)
        canon_status = f"canonical={'loaded' if canonical else 'missing'}"
        fires = _stamp(entries, single_word_verses, canonical)

        # Populate cache so validate reads our stamped entries (in-memory only).
        cache.invalidate_seg_caches(slug)
        cache.set_seg_cache(slug, entries)
        if meta:
            cache.set_seg_meta(slug, meta)

        snap = normalize(validate_reciter_segments(slug))
        out = GROUND_TRUTH / f"{slug}.json"
        out.write_text(
            json.dumps(snap, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        cc = snap.get("category_counts", {}) if snap else {}
        print(
            f"  {slug:<45s} {canon_status:<22s}  "
            f"phonemic_fires={fires}  boundary_adj={cc.get('boundary_adj', 0)}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(snapshot_published_with_phonemes())
