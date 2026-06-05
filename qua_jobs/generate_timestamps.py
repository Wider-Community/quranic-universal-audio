#!/usr/bin/env python3
"""HF Job entrypoint: generate timestamps for one reciter, in-container.

Runs MFA forced-alignment inside the job (strategy A — stock conda base +
MFA stack pulled from a mounted private bucket), reading the reciter's
``detailed.json`` from the mounted inspector bucket and writing temporal
segment-array per-chapter shards to
``<mount>/reciters/<slug>/timestamps/<chapter>.json.gz`` (the read-path
layout). Blocks before alignment if any segment carries a compound
cross-verse ``matched_ref`` (segment shards require single-verse refs).

Launched by ``inspector/services/admin/timestamps_jobs.py`` via
``huggingface_hub.run_job``. Configured entirely through env vars.

Env:
  SLUG               (required) reciter slug
  INSPECTOR_BUCKET_MOUNT  bucket mount root (default ``/data``)
  MFA_APP_PATH       aligner app.py from the runtime bucket
                     (default ``/aux/mfa-runtime/app.py``)
  BEAMS              comma-separated beams; canonical = max (default ``50``)
  WORKERS            process-pool size (default min(cpu_count, 8))
  BATCH_SIZE / DOWNLOAD_WORKERS / PADDING / METHOD  pipeline tunables
  PERSIST_AUDIO      "1" → download missing chapter audio from the CDN and
                     write it (Xing-injected) back to reciters/<slug>/audio/
  GEN_PEAKS          "1" → also compute v3 slim peaks for EVERY chapter (not
                     just persisted ones), so the Timestamps tab never has to
                     live-ffmpeg the waveform. Independent of PERSIST_AUDIO.
  JOB_ID             HF-injected job id; used to self-write the durable
                     record at reciters/<slug>/jobs/ts/<JOB_ID>.json
  INSPECTOR_WEBHOOK_URL     (optional) Inspector endpoint to POST on success so
                            the reciter auto-publishes. Threaded in by launch()
                            only when a webhook secret is configured + a public
                            URL is resolvable (deployed). Absent in dev.
  INSPECTOR_WEBHOOK_SECRET  (optional) shared secret sent as the
                            X-Inspector-Job-Secret header with the callback.

See docs/planning/inspector-deploy/v2/phases/13-timestamps-job.md + the
side-panel plan.
"""

import datetime
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from qua_shared.timestamps_pipeline import (  # noqa: E402
    DEFAULT_BATCH_SIZE,
    DEFAULT_DOWNLOAD_WORKERS,
    DEFAULT_METHOD,
    DEFAULT_PADDING,
    LocalMfaBackend,
    download_audio,
    is_compound_cross_verse,
    process,
)

log = logging.getLogger("generate_timestamps")


def _beams(raw: str) -> list[int]:
    out = [int(t) for t in raw.replace(" ", "").split(",") if t]
    return out or [50]


def _bool_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _find_cross_verse_segments(doc: dict) -> list[tuple[str, str]]:
    """Return ``(chapter_ref, matched_ref)`` for every compound cross-verse seg.

    The segment-array shard contract requires single-verse refs; cross-verse
    segments cannot be reshaped losslessly. Editing strips cross-verse, so a
    clean reciter yields none — but the job blocks rather than write a shard
    the read path can't serve.
    """
    offenders: list[tuple[str, str]] = []
    for entry in doc.get("entries", []):
        ch_ref = str(entry.get("ref", ""))
        for seg in entry.get("segments", []):
            matched_ref = seg.get("matched_ref", "")
            if matched_ref and is_compound_cross_verse(matched_ref):
                offenders.append((ch_ref, matched_ref))
    return offenders


def _ensure_xing(src: Path, dest: Path) -> bool:
    """Remux ``src`` MP3 → ``dest`` with a Xing/Info header (browser-seekable).

    Mirror of ``.local/extraction/segments/audio_persist.py::_ensure_xing``:
    ``ffmpeg -c:a copy -f mp3`` writes the Xing TOC without re-encoding.
    Returns True on success; on any failure leaves ``dest`` absent and the
    caller falls back to copying the raw bytes.
    """
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(src), "-c:a", "copy", "-f", "mp3", "-v", "error", str(dest)],
            capture_output=True,
            timeout=180,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        log.warning("xing remux skipped: %s", exc)
        if dest.exists():
            dest.unlink()
        return False
    if result.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
        log.warning("xing remux failed (rc=%s)", result.returncode)
        if dest.exists():
            dest.unlink()
        return False
    return True


def _persist_chapter_audio(url: str, audio_dest: Path, peaks_dest: Path, gen_peaks: bool) -> bool:
    """Download ``url`` → Xing-remux to ``audio_dest`` (+ optional v3 peaks).

    Returns the local path the pipeline should align against on success
    (always ``audio_dest`` once written), or empty on failure (caller keeps
    the CDN url). Best-effort: peaks failure doesn't fail the audio persist.
    """
    import shutil

    audio_dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        tmp = download_audio(url)
        if not _ensure_xing(tmp, audio_dest):
            shutil.copyfile(tmp, audio_dest)  # raw fallback (VBR mis-seek risk)
        if gen_peaks:
            try:
                from qua_shared.peaks_compute import compute_audio_peaks, pack_slim

                hd = compute_audio_peaks(str(audio_dest))
                if hd and hd.get("peaks"):
                    peaks_dest.parent.mkdir(parents=True, exist_ok=True)
                    peaks_dest.write_bytes(pack_slim(hd))
            except Exception as exc:  # noqa: BLE001
                log.warning("peaks gen failed for %s: %s", audio_dest.name, exc)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("persist audio failed for %s: %s", audio_dest.name, exc)
        return False
    finally:
        if tmp is not None:
            try:
                Path(tmp).unlink(missing_ok=True)
            except OSError:
                pass


def _bake_missing_peaks(reciter_dir: Path, entries: list) -> None:
    """Bake slim v3 peaks for every by_surah chapter that doesn't have them yet.

    Decouples peak baking from ``PERSIST_AUDIO``: ``_persist_chapter_audio``
    only bakes for chapters it freshly downloads, so chapters that already had
    bucket audio (or that we aligned straight from the CDN url) would otherwise
    ship without peaks and force the Timestamps tab onto the 289-762ms live
    ffmpeg path per verse. Computes from ``entry["audio"]`` (local bucket file
    or CDN url), skips existing files + by_ayah refs, best-effort.
    """
    from qua_shared.peaks_compute import compute_audio_peaks, pack_slim  # noqa: E402

    peaks_dir = reciter_dir / "peaks"
    peaks_dir.mkdir(parents=True, exist_ok=True)
    baked = skipped = failed = 0
    for entry in entries:
        ref = str(entry.get("ref", ""))
        src = entry.get("audio")
        if not ref or ":" in ref or not src:
            continue
        dest = peaks_dir / f"{ref}.json.gz"
        if dest.exists():
            skipped += 1
            continue
        try:
            hd = compute_audio_peaks(str(src))
            if not hd or not hd.get("peaks"):
                failed += 1
                continue
            dest.write_bytes(pack_slim(hd))
            baked += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("peaks bake failed for ch%s: %s", ref, exc)
            failed += 1
    log.info("peaks bake pass: baked=%d skipped=%d failed=%d", baked, skipped, failed)


def _write_record(
    mount: Path,
    slug: str,
    settings: dict,
    *,
    status: str,
    started_at: str,
    error: str | None = None,
) -> None:
    """Self-write the durable job record to ``reciters/<slug>/jobs/ts/<JOB_ID>.json``.

    HF injects ``JOB_ID``; if it's absent (e.g. local dry-run) we skip — the
    launcher's initial record still exists. Best-effort: a record-write
    failure never fails the job.
    """
    job_id = os.environ.get("JOB_ID", "").strip()
    if not job_id:
        return
    try:
        from qua_shared.schemas import TsJobRecord, TsJobSettings

        rec = TsJobRecord(
            job_id=job_id,
            slug=slug,
            type="ts",
            settings=TsJobSettings.model_validate(settings),
            status=status,
            started_at=started_at,
            ended_at=_now_iso(),
            url=os.environ.get("JOB_URL") or None,
            error=error,
        )
        dest = mount / "reciters" / slug / "jobs" / "ts" / f"{job_id}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            json.dumps(rec.model_dump(exclude_none=True), ensure_ascii=False), encoding="utf-8"
        )
        log.info("wrote job record %s (status=%s)", dest, status)
    except Exception as exc:  # noqa: BLE001
        log.warning("could not write job record: %s", exc)


def _notify_complete(slug: str, status: str) -> None:
    """POST the completion callback to the Inspector so the reciter publishes.

    Best-effort: the Inspector's poll fallback releases anyway if this fails or
    isn't configured. Only fires when both the URL + secret env are present (the
    launcher threads them only in deployed mode). Short timeout — never block
    the job's exit on a slow/unreachable server.
    """
    url = os.environ.get("INSPECTOR_WEBHOOK_URL", "").strip()
    secret = os.environ.get("INSPECTOR_WEBHOOK_SECRET", "").strip()
    job_id = os.environ.get("JOB_ID", "").strip()
    if not url or not secret or not job_id:
        return
    try:
        import requests

        resp = requests.post(
            url,
            json={"slug": slug, "job_id": job_id, "status": status},
            headers={"X-Inspector-Job-Secret": secret},
            timeout=15,
        )
        log.info("completion callback %s → HTTP %s", url, resp.status_code)
    except Exception as exc:  # noqa: BLE001 — poll fallback covers a miss
        log.warning("completion callback failed: %s", exc)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    slug = os.environ.get("SLUG", "").strip()
    if not slug:
        log.error("SLUG env var is required")
        return 2

    mount = Path(os.environ.get("INSPECTOR_BUCKET_MOUNT", "/data"))
    app_path = Path(os.environ.get("MFA_APP_PATH", "/aux/mfa-runtime/app.py"))
    reciter_dir = mount / "reciters" / slug
    detailed = reciter_dir / "detailed.json"

    if not detailed.exists():
        log.error("detailed.json not found at %s", detailed)
        return 3
    if not app_path.exists():
        log.error("MFA app not found at %s (runtime bucket not mounted?)", app_path)
        return 3

    beams = _beams(os.environ.get("BEAMS", "50"))
    # Cap default workers: each pool worker extracts its own ~92 MB MFA model
    # at init, so too many OOM/race during simultaneous KalpyEngine init (16
    # crashed mid-init on cpu-upgrade; 8 verified safe). Override via WORKERS /
    # INSPECTOR_TS_JOB_WORKERS once a flavor's headroom is benched.
    workers = int(os.environ.get("WORKERS") or min(os.cpu_count() or 1, 8))
    batch_size = int(os.environ.get("BATCH_SIZE", str(DEFAULT_BATCH_SIZE)))
    dl_workers = int(os.environ.get("DOWNLOAD_WORKERS", str(DEFAULT_DOWNLOAD_WORKERS)))
    padding = os.environ.get("PADDING", DEFAULT_PADDING)
    method = os.environ.get("METHOD", DEFAULT_METHOD)
    persist_audio = _bool_env("PERSIST_AUDIO")
    gen_peaks = _bool_env("GEN_PEAKS")

    # Echoed into the durable record so the panel shows what was actually run.
    settings = {
        "beams": beams,
        "persist_audio": persist_audio,
        "gen_peaks": gen_peaks,
        "workers": workers,
        "batch_size": batch_size,
        "download_workers": dl_workers,
    }
    started_at = _now_iso()

    log.info(
        "generate_timestamps slug=%s cores=%s workers=%s beams=%s batch=%s "
        "dl_workers=%s persist_audio=%s gen_peaks=%s app=%s",
        slug,
        os.cpu_count(),
        workers,
        beams,
        batch_size,
        dl_workers,
        persist_audio,
        gen_peaks,
        app_path,
    )

    # Inject the per-chapter audio source: detailed.json entries carry no
    # ``audio`` field post-migration (#5) — URLs live in the audio manifest,
    # bytes live in the bucket. Resolve bucket file first (no CDN dependency),
    # manifest URL fallback. process() then reads it from a temp detailed.json
    # (kept named ``<slug>/`` so ``input_dir.name`` stays the slug); output
    # still goes to the real reciter dir in the bucket.
    doc = json.loads(detailed.read_text(encoding="utf-8"))

    # Block before any alignment work: the segment-array shards require
    # single-verse refs, so a compound cross-verse matched_ref can't be
    # reshaped losslessly. Record the failure + notify so the offending segs
    # surface in the Reviews tab.
    offenders = _find_cross_verse_segments(doc)
    if offenders:
        preview = ", ".join(f"ch{ch}:{ref}" for ch, ref in offenders[:10])
        more = f" (+{len(offenders) - 10} more)" if len(offenders) > 10 else ""
        msg = (
            f"{len(offenders)} compound cross-verse segment(s) found — split them "
            f"before generating timestamps: {preview}{more}"
        )
        log.error(msg)
        _write_record(mount, slug, settings, status="failed", started_at=started_at, error=msg)
        _notify_complete(slug, "failed")
        return 4

    manifest_path = mount / "catalog" / "audio_manifest" / f"{slug}.json"
    chapters_meta = {}
    if manifest_path.exists():
        try:
            chapters_meta = (json.loads(manifest_path.read_text(encoding="utf-8")) or {}).get(
                "chapters", {}
            ) or {}
        except Exception as exc:
            log.warning("could not read manifest %s: %s", manifest_path, exc)
    audio_dir = reciter_dir / "audio"
    peaks_dir = reciter_dir / "peaks"
    entries = doc.get("entries", [])
    injected = 0
    persisted = 0
    for entry in entries:
        ref = str(entry.get("ref", ""))
        local = audio_dir / f"{ref}.mp3"
        if local.exists():
            entry["audio"] = str(local)
            injected += 1
            continue
        url = (chapters_meta.get(ref) or {}).get("url")
        if not url:
            continue
        # Missing from the bucket. With persist_audio on, download + Xing-remux
        # into the bucket now and align against the persisted copy (so the
        # bytes MFA aligns == the bytes browsers will play). Otherwise inject
        # the CDN url directly (transient, process() streams it).
        if persist_audio and _persist_chapter_audio(
            url, local, peaks_dir / f"{ref}.json.gz", gen_peaks
        ):
            entry["audio"] = str(local)
            persisted += 1
        else:
            entry["audio"] = url
        injected += 1
    log.info(
        "injected audio for %d/%d chapters (persisted %d to bucket)",
        injected,
        len(entries),
        persisted,
    )

    job_input = Path(tempfile.mkdtemp()) / slug
    job_input.mkdir(parents=True, exist_ok=True)
    (job_input / "detailed.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    # In-container MFA: pool path engages when workers>1 AND mfa_app_path is
    # set (process() gates on this). LocalMfaBackend covers the serial
    # fallback. process() writes segment-array shards into reciter_dir/timestamps/.
    try:
        process(
            input_dir=job_input,
            backend=LocalMfaBackend(app_path),
            method=method,
            beams=beams,
            shared_cmvn=False,
            resume=False,
            batch_size=batch_size,
            output_dir=reciter_dir,
            padding=padding,
            refresh_verses=None,
            download_workers=dl_workers,
            workers=workers,
            mfa_app_path=app_path,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("alignment failed for %s", slug)
        _write_record(mount, slug, settings, status="failed", started_at=started_at, error=str(exc))
        # Notify the Inspector so the Reviews-tab dot lights up on the
        # (still-under_review) reciter. Best-effort; poll fallback covers a miss.
        _notify_complete(slug, "failed")
        return 1

    _write_record(mount, slug, settings, status="succeeded", started_at=started_at)
    # Peaks bake pass: independent of PERSIST_AUDIO so every chapter (incl. ones
    # that already had bucket audio or aligned straight from the CDN) gets slim
    # peaks. Runs after alignment so a slow/failed bake never risks the shards.
    if gen_peaks:
        _bake_missing_peaks(reciter_dir, entries)
    # Tell the Inspector the job succeeded so it auto-publishes the reciter.
    # Best-effort; the Inspector's poll fallback covers a missed callback.
    _notify_complete(slug, "succeeded")
    log.info("done slug=%s", slug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
