"""Turn a staged generation run into the bytes ``promote_run.py`` publishes.

The build half of promote: fetch and verify ``staging/<slug>/<run-id>/``, then
derive every artifact ``reciters/<slug>/`` needs. Nothing here writes to the
bucket — ``promote_run.py`` owns the guards, the publish and the teardown, and
``--dry-run`` stops after this module has run.

Every Inspector-side derivation the batch pipeline deliberately leaves undone
happens here, through Inspector's own writers rather than a second copy of them:
``services.segments.stamping`` for the persisted classifier fields,
``domain.identity.derive_uid`` for segment identity, ``services.audio.peaks`` +
``peaks_slim`` for chapter peaks, ``services.audio.op_peaks`` for the per-op
history-peaks records, and ``adapters.segments_json`` for ``segments.json``.
The staged shapes are read through ``qua_shared.schemas.bucket.staged_run``.

The one derivation that needs care is the waqf-sakt UID: it is derived once from
``final_index`` and reaches both the persisted row and the published operation,
never by assignment onto the read-only event model. See ``stamp_waqf_uids``.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
for _p in (str(_REPO), str(_REPO / "inspector"), str(Path(__file__).parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from qua_shared.schemas.bucket.staged_run import (  # noqa: E402
    ChapterCandidateDoc,
    PipelineAuditEvent,
    RunManifestDoc,
    stamp_operation,
)

STAGING_PREFIX = "staging"
MANIFEST_NAME = "manifest.json"

# Constant actor on every published pipeline batch — the offline writer's stamp.
_PIPELINE_ACTOR = {"hf_user_id": "pipeline", "login_at_time": "pipeline", "role": "pipeline"}

# Staged sidecars publish under their bare names at the reciter root.
_SIDECARS = ("low_confidence_v2.json", "auto_split_v1.json")


def dumps(obj: Any) -> bytes:
    """Serialise a published JSON artifact the way the pipeline writer did."""
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


def _jsonl_bytes(records: list[dict]) -> bytes:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records).encode("utf-8")


# ---------------------------------------------------------------------------
# Fetch and verify the staged run
# ---------------------------------------------------------------------------


def fetch_staged_run(backend, slug: str, run_id: str, dest: Path) -> RunManifestDoc:
    """Materialise ``staging/<slug>/<run-id>/`` under *dest*, verifying as it goes.

    Every declared artifact must be present with the manifest's size and digest,
    and every path in ``required`` must be declared. Raises before a single byte
    of ``reciters/<slug>/`` is touched — the inversion of "guess what should be
    here" into "everything declared is present and hashes match".
    """
    prefix = f"{STAGING_PREFIX}/{slug}/{run_id}"
    manifest = RunManifestDoc.model_validate(
        json.loads(backend.read_bytes(f"{prefix}/{MANIFEST_NAME}"))
    )
    if manifest.slug != slug:
        raise ValueError(f"manifest slug {manifest.slug!r} does not match {slug!r}")

    declared = {a.path for a in manifest.artifacts}
    undeclared = [p for p in manifest.required if p not in declared]
    if undeclared:
        raise ValueError(f"required paths absent from artifacts: {undeclared}")

    for entry in manifest.artifacts:
        try:
            data = backend.read_bytes(f"{prefix}/{entry.path}")
        except Exception as e:  # noqa: BLE001 — any read failure is the same abort
            raise ValueError(f"staged artifact unreadable: {entry.path} ({e})") from e
        if len(data) != entry.bytes:
            raise ValueError(f"{entry.path}: {len(data)} bytes, manifest says {entry.bytes}")
        digest = hashlib.sha256(data).hexdigest()
        if digest != entry.sha256:
            raise ValueError(f"{entry.path}: sha256 {digest} != manifest {entry.sha256}")
        out = dest / entry.path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
    return manifest


# ---------------------------------------------------------------------------
# The _meta block, built once for both artifacts
# ---------------------------------------------------------------------------


def _segmentation_knobs(profile: Any) -> dict[str, Any]:
    """The profile's segmentation params — where the ``_meta`` knobs live."""
    knobs = profile.get("segmentation") if isinstance(profile, dict) else None
    if not isinstance(knobs, dict):
        raise ValueError("manifest.profile carries no 'segmentation' params block")
    return knobs


def build_meta(manifest: RunManifestDoc) -> dict[str, Any]:
    """Project the run manifest onto the ``_meta`` block both artifacts carry.

    One construction, one dict, written verbatim into ``detailed.json`` and
    ``segments.json`` — exactly as the pipeline writer did. ``created_at`` is the
    run's own stamp, never promote's clock. The five segmentation knobs are read
    with ``.get()``: the boundary-head arm carries no ``min_silence_ms``, and
    ``exclude_none=True`` drops what it does not have. ``DetailedMeta`` is
    ``extra="forbid"``, so a mapping mistake raises here rather than publishing a
    silently empty provenance block.
    """
    from qua_shared.schemas.bucket.segment import DetailedMeta

    knobs = _segmentation_knobs(manifest.profile)
    return DetailedMeta(
        created_at=manifest.created_at,
        asr_model=manifest.model_revisions.get("asr"),
        vad_model=manifest.model_revisions.get("vad"),
        min_silence_ms=knobs.get("min_silence_ms"),
        min_speech_ms=knobs.get("min_speech_ms"),
        pad_left_ms=knobs.get("pad_left_ms"),
        pad_right_ms=knobs.get("pad_right_ms"),
        min_silence_floor_ms=knobs.get("min_silence_floor_ms"),
        audio_source=manifest.inputs.audio_source,
    ).model_dump(exclude_none=True)


# ---------------------------------------------------------------------------
# Candidates, classifier stamps, waqf UIDs
# ---------------------------------------------------------------------------


def read_entries(run_dir: Path, manifest: RunManifestDoc) -> tuple[list[dict], dict[int, dict]]:
    """Validate every candidate and build the ``detailed.json`` entry list.

    Each candidate segment validates as a ``DetailedSegment`` unchanged — the
    producer already writes that model's field names and integer-millisecond
    units — so there is no rename step between the two validations. Returns the
    entries in chapter order plus a chapter index the waqf stamping joins on.
    """
    from qua_shared.schemas.bucket.segment import DetailedSegment

    by_chapter: dict[int, dict] = {}
    for chapter in sorted(manifest.inputs.chapters):
        path = run_dir / "candidates" / f"{chapter}.json"
        doc = ChapterCandidateDoc.model_validate(json.loads(path.read_bytes()))
        for entry in doc.entries:
            key = int(str(entry.ref).split(":")[0])
            if key in by_chapter:
                raise ValueError(f"chapter {key} appears in more than one candidate file")
            by_chapter[key] = {
                "ref": entry.ref,
                "segments": [
                    DetailedSegment.model_validate(seg).model_dump(exclude_none=True)
                    for seg in entry.segments
                ],
            }
    return [by_chapter[ch] for ch in sorted(by_chapter)], by_chapter


def stamp_waqf_uids(
    by_chapter: dict[int, dict], events: list[PipelineAuditEvent]
) -> dict[int, str]:
    """Derive one UID per waqf-sakt event and write it to the persisted row.

    The merged row's position in the published list is ``final_index`` — the
    pre-strip ``index_at_save`` minus the specials removed before it — and the
    UID is derived from that index once, here. The same string reaches the
    published operation through ``stamp_operation``'s ``after_uid``; nothing is
    ever assigned onto the read-only event model, which declares no
    ``segment_uid`` and would raise.

    The ``time_start`` check is the exact cross-check: a wrong ``final_index``
    stops the promote instead of publishing an operation whose UID resolves to
    no row.
    """
    from domain.identity import derive_uid

    uids: dict[int, str] = {}
    for n, ev in enumerate(events):
        if ev.kind != "waqf_sakt":
            continue
        snap = ev.targets_after[0]
        index = snap.final_index
        if index is None:
            raise ValueError(f"waqf_sakt event {n} (chapter {ev.chapter}) carries no final_index")
        entry = by_chapter.get(ev.chapter)
        if entry is None:
            raise ValueError(f"waqf_sakt event {n}: no candidate entry for chapter {ev.chapter}")
        rows = entry["segments"]
        if not 0 <= index < len(rows):
            raise ValueError(
                f"waqf_sakt event {n}: final_index {index} outside chapter "
                f"{ev.chapter}'s {len(rows)} rows"
            )
        row = rows[index]
        if row["time_start"] != snap.time_start:
            raise ValueError(
                f"waqf_sakt event {n}: chapter {ev.chapter} row {index} starts at "
                f"{row['time_start']}ms, the snapshot at {snap.time_start}ms"
            )
        uid = derive_uid(ev.chapter, index, row["time_start"])
        row["segment_uid"] = uid
        uids[n] = uid
    return uids


def finalise_entries(entries: list[dict]) -> list[dict]:
    """Round-trip every seg through ``DetailedSegment`` for the on-disk shape."""
    from qua_shared.schemas.bucket.segment import DetailedSegment

    return [
        {
            "ref": e["ref"],
            "segments": [
                DetailedSegment.model_validate(s).model_dump(exclude_none=True)
                for s in e["segments"]
            ],
        }
        for e in entries
    ]


# ---------------------------------------------------------------------------
# The published edit history
# ---------------------------------------------------------------------------


def replay_events(
    events: list[PipelineAuditEvent],
    waqf_uids: dict[int, str],
    source_urls: dict[int, str],
    saved_at_utc: str,
) -> list[dict]:
    """Stamp every pipeline event into published ``edit_history.jsonl`` batches.

    Waqf-sakt merges go one batch per chapter; the specials strip goes in one
    ``strip_specials`` batch spanning every chapter it touched — the shape the
    pipeline writer produced. A delete's single ``targets_before`` snapshot gets
    a UID derived from its pre-strip index (that row does not exist post-strip
    and nothing joins to the value); a waqf's get none, as published.
    """
    from domain.identity import derive_uid
    from qua_shared.schemas.bucket.edit_history import EditHistoryBatch
    from utils.uuid7 import uuid7

    waqf_by_chapter: dict[int, list[dict]] = {}
    deletes: list[dict] = []
    delete_chapters: set[int] = set()

    for n, ev in enumerate(events):
        url = source_urls.get(ev.chapter)
        if not url:
            raise ValueError(f"event {n}: chapter {ev.chapter} has no chapter_sources.json url")
        before_uids = (
            [derive_uid(ev.chapter, s.index_at_save, s.time_start) for s in ev.targets_before]
            if ev.kind == "delete_segment"
            else None
        )
        op = stamp_operation(
            ev, op_id=uuid7(), audio_url=url, after_uid=waqf_uids.get(n), before_uids=before_uids
        )
        if ev.kind == "waqf_sakt":
            waqf_by_chapter.setdefault(ev.chapter, []).append(op)
        else:
            deletes.append(op)
            delete_chapters.add(ev.chapter)

    def _batch(**fields) -> dict:
        base = {"schema_version": 1, "batch_id": uuid7(), "saved_at_utc": saved_at_utc}
        return EditHistoryBatch.model_validate(
            {**base, "actor": _PIPELINE_ACTOR, **fields}
        ).model_dump(exclude_none=True)

    batches = [_batch(chapter=ch, operations=waqf_by_chapter[ch]) for ch in sorted(waqf_by_chapter)]
    if deletes:
        batches.append(
            _batch(
                batch_type="strip_specials",
                chapter=None,
                chapters=sorted(delete_chapters),
                operations=deletes,
            )
        )
    return batches


# ---------------------------------------------------------------------------
# Chapter peaks and per-op history peaks
# ---------------------------------------------------------------------------


def build_chapter_peaks(
    run_dir: Path, source_urls: dict[int, str]
) -> tuple[list[int], dict[str, dict]]:
    """Bake ``peaks/<ch>.json.gz`` beside the staged audio; return the envelopes.

    The envelopes are keyed by the **raw** ``chapter_sources.json`` url — the
    identical string stamped as the ops' ``audio_url``, so ``build_op_records``
    finds them. Normalisation happens only in the emitted record's ``url``,
    where it always did.

    A url claimed by more than one chapter (a combined source file) is ambiguous
    under a url-keyed provider, so it gets no envelope and its ops fall back to
    lazy-on-play rather than being sliced from a sibling chapter's waveform.
    Reported, never silent.
    """
    from services.audio.peaks import compute_audio_peaks
    from services.audio.peaks_slim import pack_slim, unpack_slim_envelope

    peaks_dir = run_dir / "peaks"
    peaks_dir.mkdir(parents=True, exist_ok=True)

    chapters: list[int] = []
    envelopes: dict[str, dict] = {}
    shared: set[str] = set()
    for mp3 in sorted((run_dir / "audio").glob("*.mp3"), key=lambda p: int(p.stem)):
        chapter = int(mp3.stem)
        hd = compute_audio_peaks(str(mp3))
        if hd is None:
            raise ValueError(f"chapter {chapter}: ffmpeg produced no peaks for {mp3}")
        blob = pack_slim(hd)
        (peaks_dir / f"{chapter}.json.gz").write_bytes(blob)
        chapters.append(chapter)

        url = source_urls.get(chapter)
        if not url:
            continue
        if url in envelopes or url in shared:
            envelopes.pop(url, None)
            shared.add(url)
            continue
        env = unpack_slim_envelope(blob)
        if env is not None:
            envelopes[url] = env
    for url in sorted(shared):
        print(f"  note: {url} covers several chapters — per-op peaks left to lazy-on-play")
    return chapters, envelopes


def build_peaks_records(
    slug: str, batches: list[dict], source_urls: dict[int, str], envelopes: dict[str, dict]
) -> list[dict]:
    """Slice the in-memory envelopes into per-op history-peaks records.

    Reuses Inspector's own record builder through its envelope provider. The
    default provider reads baked peaks off the bucket, where this run's do not
    exist yet — every op would take the skip branch and the promote would
    succeed with an empty ``edit_history_peaks.jsonl``.
    """
    from services.audio import op_peaks

    ops = [op for batch in batches for op in batch.get("operations", [])]
    if not ops:
        return []
    return op_peaks.build_op_records(slug, ops, dict(source_urls), env_provider=envelopes.get)


# ---------------------------------------------------------------------------
# The whole build
# ---------------------------------------------------------------------------


def build_artifacts(run_dir: Path, manifest: RunManifestDoc, slug: str) -> dict[str, bytes]:
    """Every JSON/JSONL artifact promote publishes, keyed by reciter-relative name."""
    from adapters.segments_json import build_segments_doc
    from config import DK_SCRIPT_PATH, SURAH_INFO_PATH
    from qua_shared.schemas.bucket.pipeline_meta import PipelineMeta
    from services.segments import stamping

    for path in (SURAH_INFO_PATH, DK_SCRIPT_PATH):
        if not Path(path).is_file():
            raise ValueError(f"reference data missing: {path} — every stamp would be empty")

    entries, by_chapter = read_entries(run_dir, manifest)
    n_segs = sum(len(e["segments"]) for e in entries)
    n_stamped = stamping.stamp_entries(entries)
    if n_stamped != n_segs:
        raise ValueError(f"stamped {n_stamped} of {n_segs} segments")

    events = [
        PipelineAuditEvent.model_validate(e)
        for e in json.loads((run_dir / "events.json").read_bytes())
    ]
    waqf_uids = stamp_waqf_uids(by_chapter, events)
    disk_entries = finalise_entries(entries)

    meta = build_meta(manifest)
    source_urls = {
        int(ch): rec["url"]
        for ch, rec in json.loads((run_dir / "chapter_sources.json").read_bytes()).items()
    }
    batches = replay_events(events, waqf_uids, source_urls, manifest.created_at)

    built: dict[str, bytes] = {
        "detailed.json": dumps({"_meta": meta, "entries": disk_entries}),
        "segments.json": dumps(build_segments_doc(disk_entries, meta, with_repeated=True)),
        "pipeline_meta.json": dumps(
            PipelineMeta(
                schema_version=1,
                # The run's stamp, not promote's clock — one run, one timestamp.
                generated_at=manifest.created_at,
                deleted_basmala_chapters=sorted(manifest.deleted_basmala_chapters),
            ).model_dump(mode="json")
        ),
        "chapter_sources.json": (run_dir / "chapter_sources.json").read_bytes(),
    }
    coverage = run_dir / "coverage_report.json"
    if coverage.is_file():
        built["coverage_report.json"] = coverage.read_bytes()
    for name in _SIDECARS:
        sidecar = run_dir / "sidecars" / name
        if sidecar.is_file():
            built[name] = sidecar.read_bytes()
    if batches:
        built["edit_history.jsonl"] = _jsonl_bytes(batches)

    chapters, envelopes = build_chapter_peaks(run_dir, source_urls)
    records = build_peaks_records(slug, batches, source_urls, envelopes)
    if records:
        built["edit_history_peaks.jsonl"] = _jsonl_bytes(records)
    print(
        f"  built {len(chapters)} chapter(s), {n_segs} segment(s), "
        f"{len(batches)} batch(es), {len(records)} peaks record(s)"
    )
    return built
