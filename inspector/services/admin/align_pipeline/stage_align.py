"""Stage 2 — align every chapter on the aligner Space, staging each raw result.

One alignment-only batch, one streamed item per chapter by bucket reference
(``hf://buckets/<repo>/reciters/<slug>/audio/<ch>.mp3``). Chapters already staged
are skipped, so a resumed or retried run only pays for what is left. Transient
transport failures retry the chapter; a ``batch_not_found`` (the Space restarted,
or its in-memory registry expired) recreates the batch; a ZeroGPU quota refusal
flips the rest of the run to the CPU lane.
"""

from __future__ import annotations

import logging
import time

import requests

from services.storage.hf_bucket import resolve_bucket_repo

from . import progress, staging
from .aligner_client import AlignerClient, AlignerError
from .params import AlignParams

log = logging.getLogger("inspector")

CHAPTER_ATTEMPTS = 3
RETRY_SLEEP_S = 30
_RECREATE_CODES = ("batch_not_found",)
_CPU_FALLBACK_CODES = ("gpu_quota_exhausted",)
_TRANSIENT = (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError)


class AlignStageError(RuntimeError):
    pass


def audio_ref(slug: str, chapter: int) -> str:
    return f"hf://buckets/{resolve_bucket_repo()}/reciters/{slug}/audio/{chapter}.mp3"


class _Batch:
    """The live batch handle, recreated on demand (owner = Space-side IP hash)."""

    def __init__(self, client: AlignerClient, params: AlignParams):
        self.client = client
        self.params = params
        self.device = "GPU"
        self.batch_id: str | None = None

    def id(self) -> str:
        if self.batch_id is None:
            self.batch_id = self.client.create_batch(self.params.batch_body(device=self.device))
        return self.batch_id

    def reset(self, *, cpu: bool = False) -> None:
        self.batch_id = None
        if cpu:
            self.device = "CPU"


def run(slug: str, run_id: str, params: AlignParams, chapters: list[int]) -> None:
    client = AlignerClient()
    batch = _Batch(client, params)
    done = set(staging.staged_chapters(slug, run_id))
    progress.set_detail(run_id, chapters_done=len(done), chapter=None)
    for chapter in chapters:
        if chapter in done:
            continue
        progress.check_cancel(run_id)
        result = _align_chapter(batch, slug, run_id, chapter)
        staging.write_json(staging.chapter_path(slug, run_id, chapter), result)
        done.add(chapter)
        progress.set_detail(
            run_id, chapters_done=len(done), chapter=None, device=result.get("device")
        )
        log.info(
            "align %s: chapter %d staged (%d segs, %s)",
            run_id,
            chapter,
            len(result.get("segments") or []),
            result.get("device"),
        )


def _align_chapter(batch: _Batch, slug: str, run_id: str, chapter: int) -> dict:
    last: Exception | None = None
    for attempt in range(1, CHAPTER_ATTEMPTS + 1):
        progress.set_detail(run_id, chapter=chapter, attempt=attempt, aligner_stage="queued")

        def on_progress(ev: dict) -> None:
            progress.set_detail(run_id, aligner_stage=ev.get("stage"))

        try:
            return batch.client.align_item(
                batch.id(), chapter, audio_ref(slug, chapter), on_progress
            )
        except AlignerError as exc:
            last = exc
            if exc.code in _RECREATE_CODES:
                log.warning("align %s: batch vanished (%s); recreating", run_id, exc.code)
                batch.reset()
                continue
            if exc.code in _CPU_FALLBACK_CODES and batch.device != "CPU":
                log.warning("align %s: GPU quota exhausted; rest of run on CPU", run_id)
                batch.reset(cpu=True)
                continue
            if exc.status is not None and exc.status < 500:
                break  # a request the Space refuses will not succeed on retry
            log.warning("align %s: chapter %d attempt %d failed: %s", run_id, chapter, attempt, exc)
        except _TRANSIENT as exc:
            last = exc
            log.warning(
                "align %s: chapter %d attempt %d transport error: %s", run_id, chapter, attempt, exc
            )
            batch.reset()  # the Space may have restarted; a new batch is cheap
        if attempt < CHAPTER_ATTEMPTS:
            time.sleep(RETRY_SLEEP_S)
    raise AlignStageError(f"chapter {chapter}: {last}")
