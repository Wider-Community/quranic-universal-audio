#!/usr/bin/env python3
"""HF Job entrypoint: publish one recitation to the HF dataset (v2 track).

Reads the recitation's bucket artifacts (``detailed.json`` + per-chapter
``timestamps/<n>.json.gz`` + Xing-master ``audio/<n>.mp3``) and pushes a
parquet split to the public HF dataset under ``<riwayah>/<slug>``. Audio
clips are produced by ffmpeg STREAM-COPY (``-c copy``) from the bucket
chapter master — no pydub decode/re-encode, ≤26 ms boundary snap, word
timestamps re-based to the snapped boundary.

The HF Job NEVER writes ``db/inspector.db``. On success it POSTs the
completion webhook (``INSPECTOR_WEBHOOK_URL``) with the HF dataset revision
SHA in ``version``; Inspector's
``services.admin.jobs.hf_publish.complete()`` inserts the
``per_recitation_releases(track='hf', ...)`` row + fires the public
``released`` event. Webhook failure is tolerated — the 120 s poll worker
backstops via the same handler.

Env:
  SLUG                      (required) reciter slug
  INSPECTOR_BUCKET_MOUNT    bucket mount root (default ``/data``)
  JOB_ID                    HF-injected job id (forwarded in callback)
  HF_TOKEN                  HF auth (secret)
  INSPECTOR_WEBHOOK_URL     (optional) Inspector completion endpoint
  INSPECTOR_WEBHOOK_SECRET  (optional) HMAC shared secret
  LAUNCHED_BY               (optional) hf_user_id of the operator who clicked
"""

from __future__ import annotations

import datetime
import gzip
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("publish_hf")


# ---------------------------------------------------------------------------
# Static-ref loaders — qpc_hafs + surah_info are staged alongside the code by
# ``base.stage_job_code`` and land at ``/aux/code/data/`` in the container.
# ---------------------------------------------------------------------------

_QURAN_MARKERS = set("ۖۗۘۙۚۛ۞۩")


def _strip_quran_markers(text: str) -> str:
    """Strip non-recited markers (waqf signs, hizb, sajdah) from Uthmani text."""
    return "".join(ch for ch in text if ch not in _QURAN_MARKERS)


def _text_for_ref(matched_ref: str, dk_words: dict, surah_info: dict) -> str:
    """Derive Arabic text for a canonical ``surah:ayah:word-surah:ayah:word``
    matched_ref from the Digital Khatt word map.

    Mirror of ``.github/scripts/build_reciter.py::_text_for_ref`` — the
    extractor no longer writes ``matched_text`` (Migration #5), so the
    dataset re-derives it deterministically.
    """
    if not matched_ref or "-" not in matched_ref:
        return ""
    start, _, end = matched_ref.partition("-")
    sp = start.split(":")
    ep = end.split(":")
    if len(sp) != 3 or len(ep) != 3:
        return ""
    try:
        s_su, s_ay, s_w = int(sp[0]), int(sp[1]), int(sp[2])
        e_su, e_ay, e_w = int(ep[0]), int(ep[1]), int(ep[2])
    except ValueError:
        return ""

    su = s_su
    surah_meta = surah_info.get(str(su))
    if not surah_meta:
        return ""
    verses = surah_meta.get("verses", [])
    words: list[str] = []
    ay, w = s_ay, s_w
    iters = 1000
    while (su, ay, w) <= (e_su, e_ay, e_w) and iters > 0:
        entry = dk_words.get(f"{su}:{ay}:{w}")
        if entry:
            text = entry.get("text") if isinstance(entry, dict) else entry
            if text:
                words.append(text)
        w += 1
        verse_idx = ay - 1
        max_w = (
            verses[verse_idx].get("num_words", 0)
            if 0 <= verse_idx < len(verses) else 0
        )
        if w > max_w:
            w = 1
            ay += 1
        iters -= 1
    return " ".join(words)


def _cross_verse_text(matched_ref: str, full_text: str,
                      target_ayah: int, surah_info: dict, surah_num: str) -> str:
    """Slice only target_ayah's words from a cross-verse segment's full text."""
    parts = matched_ref.split("-")
    if len(parts) != 2:
        return full_text
    try:
        sp = parts[0].split(":")
        ep = parts[1].split(":")
        s_ayah, s_word = int(sp[1]), int(sp[2])
        e_ayah, e_word = int(ep[1]), int(ep[2])
    except (ValueError, IndexError):
        return full_text
    words = full_text.split()
    if target_ayah == s_ayah:
        total = surah_info[surah_num]["verses"][s_ayah - 1]["num_words"]
        n = total - s_word + 1
        return " ".join(words[:n])
    if target_ayah == e_ayah:
        return " ".join(words[-e_word:]) if e_word > 0 else ""
    return full_text


# ---------------------------------------------------------------------------
# Bucket I/O — direct path reads (bucket is mounted at /data in the job).
# ---------------------------------------------------------------------------

def _bucket_root() -> Path:
    return Path(os.environ.get("INSPECTOR_BUCKET_MOUNT", "/data"))


def _load_detailed(slug: str) -> dict:
    """Read ``reciters/<slug>/detailed.json``. Raises if missing."""
    path = _bucket_root() / "reciters" / slug / "detailed.json"
    return json.loads(path.read_bytes())


def _load_audio_manifest(slug: str) -> dict | None:
    """Read ``catalog/audio_manifest/<slug>.json`` or None if absent."""
    path = _bucket_root() / "catalog" / "audio_manifest" / f"{slug}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_bytes())
    except (json.JSONDecodeError, OSError):
        return None


def _load_timestamps_shards(slug: str) -> dict[str, dict]:
    """Read every ``reciters/<slug>/timestamps/<ch>.json.gz`` shard, project
    each to the canonical verse-map shape, and merge into one global dict.

    Returns ``{"surah:ayah": {"words": [...], "verse_start_ms", "verse_end_ms"},
    "_meta": {...}}`` — same shape build_reciter.py's ``load_data`` produces
    after reshaping.
    """
    from scripts.lib.timestamps_dedup import project_chapter_shard

    ts_dir = _bucket_root() / "reciters" / slug / "timestamps"
    out: dict[str, dict] = {}
    meta: dict = {}
    if not ts_dir.exists():
        return out
    for path in sorted(ts_dir.iterdir(),
                       key=lambda p: int(p.name.split(".", 1)[0])
                       if p.name.split(".", 1)[0].isdigit() else 0):
        name = path.name
        if not (name.endswith(".json") or name.endswith(".json.gz")):
            continue
        raw = path.read_bytes()
        if name.endswith(".gz"):
            raw = gzip.decompress(raw)
        shard = json.loads(raw)
        # Project v2 (occurrence list) → canonical verse map. v1 dicts pass through.
        canonical = project_chapter_shard(shard, full=False)
        for k, v in canonical.items():
            if k == "_meta":
                meta = v if not meta else meta
                continue
            out[k] = v
    if meta:
        out["_meta"] = meta
    return out


def _reshape_timestamps_for_rows(canonical: dict) -> dict[str, dict]:
    """Convert the canonical verse-map shape into build_rows' expected shape.

    ``canonical[ref]`` is ``{"words": [[widx, s, e, [letters], ...], ...]}``
    (the historical ``timestamps_full.json`` body). For each verse this
    returns ``{"words": [[widx, s, e], ...], "letters": [(widx, [(ch, s, e), ...])],
    "verse_start_ms": int, "verse_end_ms": int}``.
    """
    ts: dict[str, dict] = {}
    for ref, val in canonical.items():
        if ref.startswith("_"):
            continue
        words = val.get("words") if isinstance(val, dict) else val
        if not words:
            ts[ref] = {"words": [], "letters": [], "verse_start_ms": 0, "verse_end_ms": 0}
            continue
        vs = val.get("verse_start_ms") if isinstance(val, dict) else None
        ve = val.get("verse_end_ms") if isinstance(val, dict) else None
        if vs is None or ve is None:
            vs = words[0][1]
            ve = max(int(w[2]) for w in words)
        slim_words = [[int(w[0]), int(w[1]), int(w[2])] for w in words]
        letters: list[tuple] = []
        for w in words:
            letters.append((int(w[0]), w[3] if len(w) > 3 else []))
        ts[ref] = {
            "words": slim_words,
            "letters": letters,
            "verse_start_ms": int(vs),
            "verse_end_ms": int(ve),
        }
    return ts


# ---------------------------------------------------------------------------
# Row construction — port of build_reciter.py::build_rows (trimmed).
# ---------------------------------------------------------------------------

def _detailed_by_ref(detailed: dict) -> dict[str, dict]:
    """Normalize detailed.json entries to a ``surah:ayah → entry`` dict."""
    out: dict[str, dict] = {}
    for entry in detailed.get("entries", []):
        ref = entry.get("ref")
        if ref is None:
            continue
        if ":" in str(ref):
            out[ref] = entry
            continue
        # by_surah: ref is chapter number — fan out via segments' matched_ref
        for seg in entry.get("segments", []):
            mref = seg.get("matched_ref", "")
            if not mref or "-" not in mref:
                continue
            sp = mref.split("-", 1)[0].split(":")
            ep = mref.split("-", 1)[1].split(":")
            try:
                s_surah = int(sp[0]); s_ayah = int(sp[1]); e_ayah = int(ep[1])
            except (ValueError, IndexError):
                continue
            for a in range(s_ayah, e_ayah + 1):
                vref = f"{s_surah}:{a}"
                out.setdefault(vref, entry)
    return out


def _i(x):
    """Coerce ms to int (round on float, pass-through on int)."""
    return int(round(x)) if isinstance(x, float) else int(x)


def build_rows(timestamps: dict, detailed_by_ref: dict, surah_info: dict,
               dk_words: dict) -> list[dict]:
    """Build dataset row metadata in canonical verse order.

    Each row has the same column shape as v1 + ``clip_start`` (source-ms
    boundary the audio slice starts at; consumed by the slicer + persisted
    as ``source_offset_ms``).
    """
    rows: list[dict] = []
    for surah_num in sorted(surah_info, key=int):
        surah = surah_info[surah_num]
        for verse_info in surah.get("verses", []):
            ayah = verse_info["verse"]
            ref = f"{surah_num}:{ayah}"
            entry = detailed_by_ref.get(ref)
            if not entry:
                continue
            tdata = timestamps.get(ref)
            if not tdata:
                continue
            clip_start = tdata["verse_start_ms"]
            clip_end = tdata["verse_end_ms"]

            # Segments: only those overlapping the clip; trim to clip; clip-relative.
            verse_segments: list[list[int]] = []
            # detailed.json segments are reused as the "segments" column.
            for seg in entry.get("segments", []) or []:
                t_start = seg.get("time_start", 0)
                t_end = seg.get("time_end", 0)
                if t_end <= clip_start or t_start >= clip_end:
                    continue
                # Use detailed.json's word range (start/end widx). Some legacy
                # entries don't have it — derive from words instead.
                w_from = seg.get("word_from", seg.get("start_word", 1))
                w_to = seg.get("word_to", seg.get("end_word", w_from))
                verse_segments.append([
                    _i(w_from), _i(w_to),
                    _i(max(0, t_start - clip_start)),
                    _i(min(t_end, clip_end) - clip_start),
                ])

            # text_uthmani from detailed.json matched_refs, restricted to the
            # clip range; cross-verse segments use only this ayah's portion.
            text_parts: list[str] = []
            for det_seg in entry.get("segments", []) or []:
                t_start = det_seg.get("time_start", 0)
                t_end = det_seg.get("time_end", 0)
                if t_end <= clip_start or t_start >= clip_end:
                    continue
                mref = det_seg.get("matched_ref", "")
                seg_text = _text_for_ref(mref, dk_words, surah_info) \
                    if dk_words else det_seg.get("matched_text", "")
                if "-" in mref:
                    rp = mref.split("-")
                    if len(rp) == 2:
                        sa = rp[0].split(":")
                        ea = rp[1].split(":")
                        if len(sa) >= 2 and len(ea) >= 2:
                            s_ay = int(sa[1])
                            e_ay = int(ea[1])
                            if ayah < s_ay or ayah > e_ay:
                                continue
                            if s_ay != e_ay:
                                seg_text = _cross_verse_text(
                                    mref, seg_text, ayah, surah_info, surah_num)
                text_parts.append(seg_text)
            text = _strip_quran_markers(" ".join(text_parts))

            # Words (clip-relative).
            verse_words = [[_i(w[0]), _i(w[1] - clip_start), _i(w[2] - clip_start)]
                           for w in tdata["words"]]

            # Synthesize missing segments around the home segments (cross-verse).
            if verse_words and not verse_segments:
                verse_segments.append([
                    verse_words[0][0], verse_words[-1][0],
                    verse_words[0][1], verse_words[-1][2],
                ])
            elif verse_words and verse_segments:
                first_seg_start = verse_segments[0][2]
                xv_before = [w for w in verse_words if w[2] <= first_seg_start]
                if xv_before:
                    verse_segments.insert(0, [
                        xv_before[0][0], xv_before[-1][0],
                        xv_before[0][1], xv_before[-1][2],
                    ])
                last_seg_end = verse_segments[-1][3]
                xv_after = [w for w in verse_words if w[1] >= last_seg_end]
                if xv_after:
                    verse_segments.append([
                        xv_after[0][0], xv_after[-1][0],
                        xv_after[0][1], xv_after[-1][2],
                    ])

            # Letters: flatten (widx, char, start, end) — clip-relative.
            verse_letters: list[dict] = []
            for widx, letters in tdata.get("letters", []):
                for ch, s, e in letters:
                    verse_letters.append({
                        "word_idx": _i(widx),
                        "char": ch,
                        "start_ms": _i(s - clip_start),
                        "end_ms": _i(e - clip_start),
                    })

            # source_url + chapter info for slicer.
            chapter = int(surah_num)
            rows.append({
                "surah": chapter,
                "ayah": ayah,
                "duration_ms": _i(clip_end - clip_start),
                "text_uthmani": text,
                "segments": verse_segments,
                "word_timestamps": verse_words,
                "letter_timestamps": verse_letters,
                "source_url": entry.get("audio", ""),
                "chapter": chapter,
                "clip_start": clip_start,
                "clip_end": clip_end,
            })
    return rows


# ---------------------------------------------------------------------------
# Stream-copy audio slicing via ffmpeg. The bucket holds Xing-injected MP3s
# per chapter at ``reciters/<slug>/audio/<ch>.mp3``. ffmpeg ``-c copy`` snaps
# to the nearest frame boundary (~26 ms for MP3) — the snapped offset is what
# the slice starts at, so word_timestamps must be rebased to it.
# ---------------------------------------------------------------------------

def _chapter_mp3_path(slug: str, chapter: int) -> Path:
    return _bucket_root() / "reciters" / slug / "audio" / f"{chapter}.mp3"


def _stream_copy_slice(src: Path, start_ms: int, end_ms: int,
                       dst: Path) -> tuple[int, int] | None:
    """ffmpeg ``-c copy -ss X -t Y`` from ``src`` to ``dst``.

    Returns ``(actual_start_ms, actual_end_ms)`` of the produced clip — the
    snapped offsets are derived after the cut by probing the result's
    duration; the start snap is bounded by ffmpeg to the nearest frame
    boundary <= start_ms. Caller rebases word timestamps to ``actual_start_ms``.

    None on ffmpeg failure (caller drops the verse).
    """
    duration_ms = max(0, end_ms - start_ms)
    if duration_ms <= 0:
        return None
    start_s = start_ms / 1000.0
    dur_s = duration_ms / 1000.0
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-ss", f"{start_s:.6f}", "-i", str(src),
             "-t", f"{dur_s:.6f}", "-c", "copy", "-f", "mp3", str(dst)],
            capture_output=True, timeout=120,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        log.warning("ffmpeg slice failed for %s [%d,%d]: %s",
                    src.name, start_ms, end_ms, exc)
        return None
    if result.returncode != 0 or not dst.exists() or dst.stat().st_size == 0:
        log.warning("ffmpeg slice failed for %s [%d,%d] rc=%s: %s",
                    src.name, start_ms, end_ms, result.returncode,
                    result.stderr.decode("utf-8", "replace")[:200])
        return None
    # ffprobe the actual duration to bound the snap. ``-ss`` before ``-i`` in
    # stream-copy mode snaps to the previous keyframe/frame; the requested
    # start may shift back by up to one MP3 frame (~26 ms at 44.1 kHz).
    actual_dur_ms = _probe_duration_ms(dst)
    if actual_dur_ms is None:
        # Conservative fallback — assume no shift.
        return start_ms, end_ms
    # Snap heuristic: ffmpeg returned `actual_dur_ms` of audio; the requested
    # window was `duration_ms`. The snap is `actual - duration` (positive →
    # frame boundary moved earlier; the slice starts a frame before the request).
    snap_ms = max(0, actual_dur_ms - duration_ms)
    return start_ms - snap_ms, start_ms - snap_ms + actual_dur_ms


def _probe_duration_ms(path: Path) -> int | None:
    """ffprobe duration in ms, or None on failure."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if result.returncode != 0:
        return None
    try:
        return int(round(float(result.stdout.decode("utf-8").strip()) * 1000))
    except (ValueError, AttributeError):
        return None


def _rebase_row(row: dict, actual_start_ms: int) -> None:
    """Re-base clip-relative word/letter/segment times to the snapped boundary.

    ``actual_start_ms`` is the snapped source-ms the slice actually starts at
    (≤ ``row['clip_start']``). The delta is added to every clip-relative offset
    so widx i's start_ms remains correct relative to byte 0 of the audio clip.
    """
    requested = row["clip_start"]
    delta = requested - actual_start_ms  # >= 0; usually 0 or ~26 ms
    if delta == 0:
        return
    row["duration_ms"] = row["duration_ms"] + delta
    row["clip_start"] = actual_start_ms
    # clip_end is computed from clip_start + duration_ms so the invariant
    # holds after rebase. Leaving clip_end unchanged would silently de-sync
    # the row's audio-window arithmetic.
    row["clip_end"] = actual_start_ms + row["duration_ms"]
    row["word_timestamps"] = [[w[0], w[1] + delta, w[2] + delta]
                              for w in row["word_timestamps"]]
    row["segments"] = [[s[0], s[1], s[2] + delta, s[3] + delta]
                       for s in row["segments"]]
    for lt in row["letter_timestamps"]:
        lt["start_ms"] += delta
        lt["end_ms"] += delta


# ---------------------------------------------------------------------------
# Boundary validation — fatal violations abort; coverage gaps drop verses.
# ---------------------------------------------------------------------------

def _verses_for_validation(rows: list[dict]) -> dict[str, dict]:
    """Re-format rows as the ``validate_dataset`` input shape (source-ms).

    The validator operates on source-relative ms, so we re-anchor each row's
    clip-relative arrays back onto its ``clip_start`` to test the original
    upstream invariants (word-bleed, intra-segment gapless, coverage).
    """
    out: dict[str, dict] = {}
    for r in rows:
        ref = f"{r['surah']}:{r['ayah']}"
        cs = r["clip_start"]
        out[ref] = {
            "verse_start_ms": cs,
            "verse_end_ms": r["clip_end"],
            "duration_ms": r["duration_ms"],
            "words": [(w[0], w[1] + cs, w[2] + cs) for w in r["word_timestamps"]],
            "segments": [(s[0], s[1], s[2] + cs, s[3] + cs) for s in r["segments"]],
        }
    return out


# ---------------------------------------------------------------------------
# HF dataset push.
# ---------------------------------------------------------------------------

def _push_to_hf(slug: str, riwayah: str, rows: list[dict],
                audio_bytes: list[bytes]) -> str:
    """Build the parquet split and push to HF. Returns the dataset commit SHA."""
    from datasets import Audio, Dataset, Features, Sequence, Value
    from huggingface_hub import HfApi

    repo_id = _resolve_dataset_repo_id()
    api = HfApi(token=os.environ.get("HF_TOKEN"))
    api.create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True)

    data = {k: [] for k in [
        "audio", "surah", "ayah", "duration_ms", "text_uthmani",
        "segments", "word_timestamps", "letter_timestamps",
        "source_url", "source_offset_ms",
    ]}
    for i, row in enumerate(rows):
        if audio_bytes[i] is None:
            continue
        data["audio"].append({
            "bytes": audio_bytes[i],
            "path": f"{row['surah']:03d}{row['ayah']:03d}.mp3",
        })
        data["surah"].append(row["surah"])
        data["ayah"].append(row["ayah"])
        data["duration_ms"].append(row["duration_ms"])
        data["text_uthmani"].append(row["text_uthmani"])
        data["segments"].append(row["segments"])
        data["word_timestamps"].append(row["word_timestamps"])
        data["letter_timestamps"].append(row["letter_timestamps"])
        src_url = row["source_url"]
        for prefix in ("https://", "http://"):
            if src_url.startswith(prefix):
                src_url = src_url[len(prefix):]
                break
        data["source_url"].append(src_url)
        data["source_offset_ms"].append(_i(row["clip_start"]))

    # decode=False stores the raw mp3 bytes verbatim — sidesteps the
    # torchcodec/torch dependency that datasets pulls in for write-time
    # audio decoding. Consumers who want waveforms can ``cast_column`` to
    # ``Audio(decode=True)`` at load time and bring their own decoder.
    features = Features({
        "audio": Audio(decode=False),
        "surah": Value("int32"),
        "ayah": Value("int32"),
        "duration_ms": Value("int32"),
        "text_uthmani": Value("string"),
        "segments": Sequence(Sequence(Value("int32"))),
        "word_timestamps": Sequence(Sequence(Value("int32"))),
        "letter_timestamps": Sequence({
            "word_idx": Value("int32"),
            "char": Value("string"),
            "start_ms": Value("int32"),
            "end_ms": Value("int32"),
        }),
        "source_url": Value("string"),
        "source_offset_ms": Value("int32"),
    })
    ds = Dataset.from_dict(data, features=features)

    log.info("pushing %d rows to %s/%s/%s", len(data["audio"]),
             repo_id, riwayah, slug)
    ds.push_to_hub(
        repo_id, config_name=riwayah, split=slug,
        token=os.environ.get("HF_TOKEN"),
        max_shard_size="10GB",
        commit_message=f"publish {riwayah}/{slug}",
    )
    # Resolve the dataset's HEAD commit sha — the version the row landed at.
    try:
        info = api.repo_info(repo_id=repo_id, repo_type="dataset")
        return getattr(info, "sha", "") or ""
    except Exception:
        return ""


def _resolve_dataset_repo_id() -> str:
    """Resolve the HF dataset repo id from config_loader (single source of truth)."""
    from scripts.lib.config_loader import repo_config
    return repo_config()["hf_dataset"]


def _riwayah_for(audio_manifest: dict | None, detailed: dict) -> str:
    """Find the riwayah slug. Audio manifest ``_meta.riwayah`` is canonical;
    detailed.json ``_meta`` is the legacy fallback."""
    if audio_manifest:
        riw = (audio_manifest.get("_meta") or {}).get("riwayah")
        if riw:
            return riw
    riw = (detailed.get("_meta") or {}).get("riwayah")
    return riw or "hafs_an_asim"


# ---------------------------------------------------------------------------
# Completion callback.
# ---------------------------------------------------------------------------

def _post_webhook(*, slug: str, job_id: str, version: str,
                  external_uri: str, status: str = "succeeded",
                  validation_summary: dict | None = None) -> bool:
    """POST the completion webhook so Inspector commits the DB row. Returns
    True on 2xx; False on any failure (the 120s poll worker is the safety net)."""
    url = os.environ.get("INSPECTOR_WEBHOOK_URL", "").strip()
    secret = os.environ.get("INSPECTOR_WEBHOOK_SECRET", "").strip()
    if not url or not secret:
        log.info("webhook URL/secret unset — skipping callback (poll fallback applies)")
        return False
    import urllib.request
    body = {
        "kind": "hf_publish",
        "slug": slug,
        "job_id": job_id,
        "status": status,
        "version": version,
        "external_uri": external_uri,
        "launched_by": os.environ.get("LAUNCHED_BY"),
    }
    if validation_summary:
        body["validation_summary"] = validation_summary
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json",
                 "X-Inspector-Job-Secret": secret},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            log.info("webhook %s → %s", url, resp.status)
            return 200 <= resp.status < 300
    except Exception as exc:
        log.warning("webhook POST failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Preflight — bail with clear exit codes before any heavy work.
# ---------------------------------------------------------------------------

def _which(name: str) -> bool:
    """True if ``name`` is on PATH."""
    from shutil import which
    return which(name) is not None


def _preflight(slug: str) -> int:
    """Verify env, binaries, bucket inputs, static refs. Returns 0 on go,
    non-zero exit code on the first failure. Each return code maps to one
    cause so the operator can fix without diving into logs."""
    if not slug:
        log.error("SLUG env var is required"); return 2
    if not os.environ.get("HF_TOKEN", "").strip():
        log.error("HF_TOKEN secret is required"); return 10
    if not _which("ffmpeg") or not _which("ffprobe"):
        log.error("ffmpeg/ffprobe missing from PATH"); return 11
    bucket = _bucket_root()
    if not bucket.exists():
        log.error("bucket mount missing at %s", bucket); return 12
    detailed_path = bucket / "reciters" / slug / "detailed.json"
    if not detailed_path.exists():
        log.error("detailed.json missing at %s", detailed_path); return 13
    refs_dir = Path("/aux/code/data")
    if not (refs_dir / "surah_info.json").exists():
        log.error("static ref surah_info.json missing at %s", refs_dir); return 14
    if not ((refs_dir / "qpc_hafs.json.gz").exists()
            or (refs_dir / "qpc_hafs.json").exists()):
        log.error("static ref qpc_hafs.json[.gz] missing at %s", refs_dir); return 14
    return 0


# ---------------------------------------------------------------------------
# Main.
# ---------------------------------------------------------------------------

def main() -> int:
    slug = os.environ.get("SLUG", "").strip()
    job_id = os.environ.get("JOB_ID", "").strip() or "unknown"
    log.info("publish_hf: slug=%s job=%s", slug, job_id)

    rc = _preflight(slug)
    if rc != 0:
        return rc

    # 1. Load bucket artifacts.
    detailed = _load_detailed(slug)
    audio_manifest = _load_audio_manifest(slug)
    canonical = _load_timestamps_shards(slug)
    if not canonical:
        log.error("no timestamps shards on bucket for %s", slug)
        return 3
    timestamps = _reshape_timestamps_for_rows(canonical)

    # 2. Load static refs from staged code dir. qpc_hafs ships gzipped to
    # dodge HF's auto-LFS-promote on the Space repo.
    refs_dir = Path("/aux/code/data")
    surah_info = json.loads((refs_dir / "surah_info.json").read_bytes())
    qpc_path = refs_dir / "qpc_hafs.json.gz"
    if qpc_path.exists():
        dk_words = json.loads(gzip.decompress(qpc_path.read_bytes()))
    else:
        dk_words = json.loads((refs_dir / "qpc_hafs.json").read_bytes())

    # 3. Build rows.
    detailed_by_ref = _detailed_by_ref(detailed)
    rows = build_rows(timestamps, detailed_by_ref, surah_info, dk_words)
    log.info("built %d rows for %s", len(rows), slug)
    if not rows:
        log.error("no rows built — detailed.json + timestamps disagreement?")
        return 15

    # 4. Validate boundaries before any audio work.
    from scripts.lib.dataset_validation import (
        BoundaryValidationError, fatal_violations, validate_dataset,
    )
    summary = validate_dataset(_verses_for_validation(rows), surah_info=surah_info)
    fatal = fatal_violations(summary["violations"])
    if fatal:
        log.error("boundary validation failed: %d fatal violation(s)", len(fatal))
        for v in fatal[:5]:
            log.error("  %s", v)
        _post_webhook(slug=slug, job_id=job_id, version="",
                      external_uri="", status="failed",
                      validation_summary=summary)
        raise BoundaryValidationError(summary)

    # 5. Stream-copy audio per row from the bucket Xing master, rebasing each
    # row to ffmpeg's frame-snapped start. Each row spawns two subprocesses
    # (ffmpeg + ffprobe); a 6k-verse reciter is ~12k spawns, so we fan out
    # over a thread pool — stream-copy is I/O-bound on the bucket mount and
    # subprocess.run releases the GIL during wait().
    from concurrent.futures import ThreadPoolExecutor, as_completed

    audio_bytes: list[bytes | None] = [None] * len(rows)
    failed_slices: list[str] = []

    def _slice_one(i: int, row: dict, td_path: Path):
        src = _chapter_mp3_path(slug, row["chapter"])
        if not src.exists():
            return i, None, f"{row['surah']}:{row['ayah']} (no audio)"
        dst = td_path / f"{i:06d}.mp3"
        cut = _stream_copy_slice(src, row["clip_start"], row["clip_end"], dst)
        if cut is None:
            return i, None, f"{row['surah']}:{row['ayah']}"
        actual_start, _ = cut
        _rebase_row(row, actual_start)
        return i, dst.read_bytes(), None

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        workers = max(4, min(12, (os.cpu_count() or 2) * 3))
        progress_every = max(50, len(rows) // 20)
        log.info("slicing %d rows with %d workers (progress every %d)",
                 len(rows), workers, progress_every)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_slice_one, i, row, td_path)
                       for i, row in enumerate(rows)]
            done = 0
            for fut in as_completed(futures):
                idx, blob, fail = fut.result()
                done += 1
                if blob is not None:
                    audio_bytes[idx] = blob
                if fail is not None:
                    failed_slices.append(fail)
                if done % progress_every == 0 or done == len(rows):
                    log.info("  sliced %d/%d (%d failed so far)",
                             done, len(rows), len(failed_slices))
    sliced_count = sum(1 for b in audio_bytes if b is not None)
    log.info("audio: %d sliced, %d failed", sliced_count, len(failed_slices))
    if failed_slices:
        log.warning("failed slices (first 20): %s", failed_slices[:20])
    if sliced_count == 0:
        log.error("every audio slice failed — refusing to push empty dataset")
        _post_webhook(slug=slug, job_id=job_id, version="",
                      external_uri="", status="failed",
                      validation_summary=summary)
        return 16

    # 6. Push to HF — gets us a commit sha to record as ``version``.
    riwayah = _riwayah_for(audio_manifest, detailed)
    version_sha = _push_to_hf(slug, riwayah, rows, audio_bytes)

    # 7. Notify Inspector.
    repo_id = _resolve_dataset_repo_id()
    external_uri = (
        f"https://huggingface.co/datasets/{repo_id}/tree/{version_sha}"
        if version_sha else f"https://huggingface.co/datasets/{repo_id}"
    )
    _post_webhook(slug=slug, job_id=job_id, version=version_sha or job_id,
                  external_uri=external_uri, validation_summary=summary)

    log.info("publish_hf: done slug=%s version=%s", slug, version_sha)
    return 0


if __name__ == "__main__":
    sys.exit(main())
