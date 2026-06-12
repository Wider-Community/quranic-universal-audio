#!/usr/bin/env python3
"""HF Job entrypoint: generate timestamps for one reciter, in-container.

Runs MFA forced-alignment inside the job (strategy A — stock conda base +
MFA stack pulled from a mounted private bucket), reading the reciter's
``detailed.json`` from the mounted inspector bucket and writing temporal
segment-array per-chapter shards to
``<mount>/reciters/<slug>/timestamps/<chapter>.json.gz`` (the read-path
layout). Blocks before alignment if any segment carries a compound
cross-verse ``matched_ref`` (segment shards require single-verse refs).

Alignment-only: the job never persists audio nor bakes peaks. Chapter audio
and waveform peaks are populated offline (katana extraction → bucket); a
chapter missing from the bucket is aligned transiently from its CDN url.

Launched by ``inspector/services/admin/timestamps_jobs.py`` via
``huggingface_hub.run_job``. Configured entirely through env vars.

Env:
  SLUG               (required) reciter slug
  INSPECTOR_BUCKET_MOUNT  bucket mount root (default ``/data``)
  MFA_MODEL_PATH     acoustic model zip from the runtime bucket
                     (default ``/aux/mfa-runtime/quran_aligner_model.zip``)
  MFA_DICTIONARY_PATH  pronunciation dictionary
                     (default ``/aux/mfa-runtime/dictionary.txt``)
  MFA_APP_PATH       legacy fallback: when the two paths above are unset,
                     the model + dictionary are derived from this file's dir
                     (default ``/aux/mfa-runtime/app.py``)
  BEAMS              comma-separated beams; canonical = max (default ``50``)
  WORKERS            process-pool size (default min(cpu_count, 8))
  BATCH_SIZE / DOWNLOAD_WORKERS / PADDING / METHOD  pipeline tunables
  CHAPTERS           comma-separated surahs for affected-only regen (absent =
                     full reciter)
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
    MFA_DICTIONARY_FILENAME,
    MFA_MODEL_FILENAME,
    LocalMfaBackend,
    is_compound_cross_verse,
    process,
)

log = logging.getLogger("generate_timestamps")


def _beams(raw: str) -> list[int]:
    out = [int(t) for t in raw.replace(" ", "").split(",") if t]
    return out or [50]


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
            chapters_refreshed=settings.get("chapters"),
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
    reciter_dir = mount / "reciters" / slug
    detailed = reciter_dir / "detailed.json"

    # MFA runtime resolution, in priority order:
    #   1. model catalog (MFA_RUNTIME_DIR store + MFA_MODEL_ID) — selectable model
    #   2. explicit MFA_MODEL_PATH/DICTIONARY_PATH env
    #   3. legacy MFA_APP_PATH dir derive
    # keep_q is derived from the model itself by the aligner — no flag needed.
    model_id = os.environ.get("MFA_MODEL_ID", "").strip() or None
    model_path = dictionary_path = None
    try:
        from qua_sdk.components.timing.models import load_catalog

        cat = load_catalog(os.environ.get("MFA_RUNTIME_DIR") or None)
        try:
            m = cat.resolve(model_id)
        except KeyError:
            log.warning("aligner model %r not in catalog; using default %r",
                        model_id, cat.default_id)
            m = cat.resolve(None)
        model_path, dictionary_path = Path(m.model_path), Path(m.dictionary_path)
        log.info("aligner model %r (keep_q=%s, label=%s)", m.id, m.keep_q, m.label)
    except Exception as exc:  # noqa: BLE001 — degrade to the env paths
        log.info("model catalog unavailable (%s); using env model paths", exc)
        model_env = os.environ.get("MFA_MODEL_PATH", "").strip()
        dict_env = os.environ.get("MFA_DICTIONARY_PATH", "").strip()
        if model_env and dict_env:
            model_path, dictionary_path = Path(model_env), Path(dict_env)
        else:
            runtime_dir = Path(os.environ.get("MFA_APP_PATH", "/aux/mfa-runtime/app.py")).parent
            model_path = runtime_dir / MFA_MODEL_FILENAME
            dictionary_path = runtime_dir / MFA_DICTIONARY_FILENAME

    if not detailed.exists():
        log.error("detailed.json not found at %s", detailed)
        return 3
    for p, label in ((model_path, "MFA model"), (dictionary_path, "MFA dictionary")):
        if not p.exists():
            log.error("%s not found at %s (runtime bucket not mounted?)", label, p)
            return 3

    import importlib.metadata

    import qua_sdk

    log.info(
        "mfa runtime: model=%s dictionary=%s qua_sdk=%s quranic-phonemizer=%s",
        model_path,
        dictionary_path,
        qua_sdk.__version__,
        importlib.metadata.version("quranic-phonemizer"),
    )

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
    # Affected-only regen: process just these chapters (untouched shards stay,
    # ts_validation.json is merged not clobbered). Empty/absent = full reciter.
    refresh_chapters: set[int] | None = None
    raw_chapters = os.environ.get("CHAPTERS", "").strip()
    if raw_chapters:
        refresh_chapters = {int(c) for c in raw_chapters.split(",") if c.strip()}

    # Echoed into the durable record so the panel shows what was actually run.
    settings = {
        "beams": beams,
        "chapters": sorted(refresh_chapters) if refresh_chapters else None,
        "workers": workers,
        "batch_size": batch_size,
        "download_workers": dl_workers,
    }
    started_at = _now_iso()

    log.info(
        "generate_timestamps slug=%s cores=%s workers=%s beams=%s batch=%s dl_workers=%s",
        slug,
        os.cpu_count(),
        workers,
        beams,
        batch_size,
        dl_workers,
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
    entries = doc.get("entries", [])
    injected = 0
    for entry in entries:
        ref = str(entry.get("ref", ""))
        local = audio_dir / f"{ref}.mp3"
        if local.exists():
            # Bucket audio present — align against the persisted bytes.
            entry["audio"] = str(local)
            injected += 1
            continue
        # Missing from the bucket: align transiently from the CDN url
        # (process() streams it). The job never persists it — audio is
        # populated offline; the Releases tab warns if it's still missing.
        url = (chapters_meta.get(ref) or {}).get("url")
        if not url:
            continue
        entry["audio"] = url
        injected += 1
    log.info("injected audio for %d/%d chapters", injected, len(entries))

    job_input = Path(tempfile.mkdtemp()) / slug
    job_input.mkdir(parents=True, exist_ok=True)
    (job_input / "detailed.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    # In-container MFA: the pool path engages when workers>1 (process() gates
    # on the model/dictionary pair). The backend is constructed in the PARENT
    # even in pool mode: its eager KalpyEngine warm-up imports kalpy/MFA and
    # extracts the model pre-fork, which the forked pool workers inherit —
    # without it all workers deadlock importing kalpy inside fork children
    # while parent download threads are live. process() writes segment-array
    # shards into reciter_dir/timestamps/.
    try:
        backend = LocalMfaBackend(model_path, dictionary_path)
        process(
            input_dir=job_input,
            backend=backend,
            method=method,
            beams=beams,
            shared_cmvn=False,
            resume=False,
            batch_size=batch_size,
            output_dir=reciter_dir,
            padding=padding,
            refresh_verses=None,
            refresh_chapters=refresh_chapters,
            download_workers=dl_workers,
            workers=workers,
            mfa_model_path=model_path,
            mfa_dictionary_path=dictionary_path,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("alignment failed for %s", slug)
        _write_record(mount, slug, settings, status="failed", started_at=started_at, error=str(exc))
        # Notify the Inspector so the Reviews-tab dot lights up on the
        # (still-under_review) reciter. Best-effort; poll fallback covers a miss.
        _notify_complete(slug, "failed")
        return 1

    _write_record(mount, slug, settings, status="succeeded", started_at=started_at)
    # Tell the Inspector the job succeeded so it auto-publishes the reciter.
    # Best-effort; the Inspector's poll fallback covers a missed callback.
    _notify_complete(slug, "succeeded")
    log.info("done slug=%s", slug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
