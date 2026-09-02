"""Move a reciter delivery into the maintainer Samples tab.

  admin_reciter_to_sample.py SLUG --name "Eval — Fatir (ideal)" [--discard]

Copies ``reciters/<slug>/`` content (detailed, segments, pipeline_meta, edit
history, the one chapter MP3) to ``samples/<id>/``, bakes peaks, writes the
sample manifest + export sidecar (Alignment-contract shape synthesised from the
segments), inserts the ``samples`` row owned by the dev owner, and with
``--discard`` hides the source delivery (``reciter.discarded``). Single-chapter
deliveries only.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _bootstrap as bs  # noqa: E402

FILES = ("detailed.json", "segments.json", "pipeline_meta.json",
         "edit_history.jsonl", "edit_history_peaks.jsonl")


def _alignment_from_detailed(entries: list[dict], chapter: int) -> tuple[dict, dict]:
    """Synthesise an Alignment-contract source + sidecar so export works."""
    from utils.uuid7 import uuid7

    originals: dict[str, dict] = {}
    segments: list[dict] = []
    for entry in entries:
        for i, seg in enumerate(entry.get("segments", [])):
            uid = seg.get("segment_uid") or uuid7()
            seg["segment_uid"] = uid
            ref = seg.get("matched_ref") or ""
            wraps = seg.get("wrap_word_ranges") or None
            raw = {
                "id": len(segments),
                "region": {"start_s": seg["time_start"] / 1000, "end_s": seg["time_end"] / 1000},
                "kind": ("quran" if ":" in ref else "special") if ref else None,
                "matched_ref": ref or None,
                "matched_text": "",
                "confidence": float(seg.get("confidence") or 0.0),
                "wrap_ranges": [
                    {"jump_to": w[0], "jump_from": w[1], "repeat_end": w[2] if len(w) > 2 else None}
                    for w in wraps
                ] if wraps else None,
                "findings": [],
            }
            originals[uid] = raw
            segments.append(raw)
    source = {"segments": segments, "chapter": chapter, "inventory_mode": "full", "riwayah": "hafs"}
    sidecar = {"schema_version": 1, "kind": "alignment", "pseudo_chapter": chapter,
               "originals": originals, "dropped": []}
    return source, sidecar


def _run(a, ctx) -> int:
    import orjson

    from services.db import repo_access, repo_samples
    from services.db import sync as _sync
    from services.samples import audio_ingest
    from services.state import state as state_service
    from services.storage import storage_paths as sp
    from services.storage.hf_bucket import get_backend
    from utils.references import chapter_from_ref
    from utils.uuid7 import uuid7

    backend = get_backend()
    slug = a.slug
    detailed = orjson.loads(backend.read_bytes(sp.detailed_path(slug)))
    entries = detailed["entries"]
    chapters = sorted({chapter_from_ref(e["ref"]) for e in entries})
    if len(chapters) != 1:
        print(f"refusing: {slug} spans chapters {chapters}", file=sys.stderr)
        return 2
    chapter = chapters[0]
    source, sidecar = _alignment_from_detailed(entries, chapter)

    sample_id = uuid7()
    new_slug = sp.sample_slug(sample_id)
    print(f"{slug} -> {new_slug} (chapter {chapter}, {len(source['segments'])} segments)")
    if a.dry_run:
        return 0

    mp3 = backend.read_bytes(sp.prefetched_audio_path(slug, chapter))
    fd, tmp = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    tmp_path = Path(tmp)
    try:
        tmp_path.write_bytes(mp3)
        probe = audio_ingest.probe(tmp_path)
        backend.write_bytes_atomic(sp.prefetched_audio_path(new_slug, chapter), mp3)
        audio_ingest.bake_peaks(tmp_path, new_slug, chapter)
    finally:
        tmp_path.unlink(missing_ok=True)

    backend.write_json_atomic(sp.detailed_path(new_slug), detailed)
    for name in FILES[1:]:
        src = sp.reciter_file(slug, name)
        if backend.exists(src):
            backend.copy(src, sp.reciter_file(new_slug, name))
    backend.write_json_atomic(sp.sample_source_path(sample_id), source)
    backend.write_json_atomic(sp.sample_sidecar_path(sample_id), sidecar)
    backend.write_json_atomic(sp.audio_manifest_path(new_slug), {
        "schema_version": 1,
        "slug": new_slug,
        "_meta": {"chapter_count": 1, "category": "by_surah", "moved_from": slug},
        "chapters": {str(chapter): {
            "url": f"qua-sample://{sample_id}/{chapter}",
            "size_bytes": len(mp3),
            "duration_sec": probe["duration_ms"] / 1000,
            "bitrate_kbps": probe.get("bitrate_kbps"),
            "bitrate_mode": "cbr",
        }},
    })

    with _sync.durable_transaction():
        repo_access.ensure_user(ctx.actor.hf_user_id, login=ctx.actor.login_at_time)
        repo_samples.create(
            sample_id=sample_id,
            owner_hf_user_id=ctx.actor.hf_user_id,
            name=a.name,
            audio_filename=f"{slug}-{chapter}.mp3",
            audio_duration_ms=probe["duration_ms"],
            source_schema="alignment",
            pseudo_chapter=chapter,
        )
        repo_samples.set_status(sample_id, "ready")
    print(f"sample row created: {sample_id}")

    if a.discard:
        try:
            state_service.transition(
                slug, "reciter.discarded", actor=ctx.actor,
                reason=f"moved to maintainer sample {sample_id}",
            )
            print(f"{slug} discarded")
        except state_service.InvalidTransition as exc:
            print(f"{slug} not discarded: {exc}")
    bs.after_write_banner(a)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("slug")
    p.add_argument("--name", required=True, help="sample display name")
    p.add_argument("--discard", action="store_true",
                   help="hide the source delivery after the copy (reciter.discarded)")
    bs.add_common_args(p)
    a = p.parse_args()
    return bs.run(a, lambda ctx: _run(a, ctx), need_actor=True, mutates=True, safe_write=True)


if __name__ == "__main__":
    raise SystemExit(main())
