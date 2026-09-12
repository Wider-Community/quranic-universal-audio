"""Stage 3 — the two MFA sidecars, computed reciter-wide on the aligner Space.

Builds every chapter's ``ChapterCandidate`` from the staged aligner results (the
same adaptation assemble uses, so the sidecars index exactly the rows that get
published) and streams ``POST /api/v1/extraction/sidecars``. The Space runs one
sidecar job at a time; a 409 waits and retries.
"""

from __future__ import annotations

import logging
import time

import requests

from services.storage.hf_bucket import resolve_bucket_repo

from . import adapt, progress, staging
from .aligner_client import AlignerClient, AlignerError
from .params import AlignParams

log = logging.getLogger("inspector")

LOW_CONFIDENCE_FILE = "low_confidence_v2.json"
AUTO_SPLIT_FILE = "auto_split_v1.json"
BUSY_RETRY_S = 60
BUSY_MAX_WAIT_S = 6 * 3600
TRANSIENT_ATTEMPTS = 3


class SidecarsStageError(RuntimeError):
    pass


def candidates_for(
    slug: str, run_id: str, chapters: list[int], sources: dict[int, str], riwayah: str
) -> dict[str, dict]:
    docs = staging.read_chapters(slug, run_id, chapters)
    out: dict[str, dict] = {}
    for ch in chapters:
        candidate, _events, _basmala = adapt.adapt_chapter(
            ch, docs[ch], source_url=sources[ch], riwayah=riwayah
        )
        out[str(ch)] = candidate
    return out


def run(
    slug: str,
    run_id: str,
    params: AlignParams,
    chapters: list[int],
    sources: dict[int, str],
) -> None:
    if staging.read_json(staging.sidecar_path(slug, run_id, AUTO_SPLIT_FILE)) is not None:
        log.info("align %s: sidecars already staged, skipped", run_id)
        return
    body = {
        "slug": slug,
        "riwayah": params.riwayah,
        "audio": {
            "repo": resolve_bucket_repo(),
            "path_tpl": f"reciters/{slug}/audio/{{chapter}}.mp3",
        },
        "candidates": candidates_for(slug, run_id, chapters, sources, params.riwayah),
    }
    result = _call(run_id, body)
    # A non-Hafs delivery gets no low-confidence probe (D12 — the Space answers
    # ``null``): its question is Hafs-only, and the assemble stage publishes
    # whatever sidecars are staged.
    if result.get("low_confidence_v2") is not None:
        staging.write_json(
            staging.sidecar_path(slug, run_id, LOW_CONFIDENCE_FILE), result["low_confidence_v2"]
        )
    staging.write_json(staging.sidecar_path(slug, run_id, AUTO_SPLIT_FILE), result["auto_split_v1"])
    log.info("align %s: sidecars staged", run_id)


def _call(run_id: str, body: dict) -> dict:
    client = AlignerClient()
    waited = 0
    transient = 0

    def on_progress(ev: dict) -> None:
        progress.set_detail(run_id, sidecar_stage=ev.get("stage"))

    while True:
        progress.check_cancel(run_id)
        try:
            return client.sidecars(body, on_progress)
        except AlignerError as exc:
            if exc.status == 409 and waited < BUSY_MAX_WAIT_S:
                progress.set_detail(run_id, sidecar_stage="waiting_for_space")
                time.sleep(BUSY_RETRY_S)
                waited += BUSY_RETRY_S
                continue
            raise SidecarsStageError(str(exc)) from exc
        except (requests.ConnectionError, requests.Timeout) as exc:
            transient += 1
            if transient >= TRANSIENT_ATTEMPTS:
                raise SidecarsStageError(f"transport: {exc}") from exc
            log.warning("align %s: sidecars transport error, retrying: %s", run_id, exc)
            time.sleep(BUSY_RETRY_S)
