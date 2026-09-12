"""Bucket paths + I/O for a run's staged files (``staging/<slug>/<run_id>/``).

Per-chapter progress is durable here, not in the DB: a chapter whose raw aligner
result is staged is done, so a retried or resumed run skips it. Everything is
deleted by assemble once ``reciters/<slug>/`` is written.
"""

from __future__ import annotations

import json
import logging

from services.storage.hf_bucket import StorageNotFound, get_backend

log = logging.getLogger("inspector")

STAGING_PREFIX = "staging"
ACQUIRE_FILE = "acquire.json"
CHAPTERS_DIR = "chapters"
SIDECARS_DIR = "sidecars"


def run_prefix(slug: str, run_id: str) -> str:
    return f"{STAGING_PREFIX}/{slug}/{run_id}"


def acquire_path(slug: str, run_id: str) -> str:
    return f"{run_prefix(slug, run_id)}/{ACQUIRE_FILE}"


def chapter_path(slug: str, run_id: str, chapter: int) -> str:
    return f"{run_prefix(slug, run_id)}/{CHAPTERS_DIR}/{chapter}.json"


def sidecar_path(slug: str, run_id: str, name: str) -> str:
    return f"{run_prefix(slug, run_id)}/{SIDECARS_DIR}/{name}"


def read_json(path: str) -> dict | None:
    try:
        return json.loads(get_backend().read_bytes(path))
    except StorageNotFound:
        return None


def write_json(path: str, doc: dict) -> None:
    get_backend().write_bytes_atomic(path, json.dumps(doc, ensure_ascii=False).encode("utf-8"))


def staged_chapters(slug: str, run_id: str) -> list[int]:
    """Chapters whose raw aligner result is on the bucket, ascending."""
    try:
        names = get_backend().list_dir(f"{run_prefix(slug, run_id)}/{CHAPTERS_DIR}")
    except Exception:  # noqa: BLE001 — a missing dir is "nothing staged"
        return []
    out = []
    for name in names:
        stem = name.rsplit("/", 1)[-1]
        if stem.endswith(".json") and stem[:-5].isdigit():
            out.append(int(stem[:-5]))
    return sorted(out)


def read_chapters(slug: str, run_id: str, chapters: list[int]) -> dict[int, dict]:
    docs: dict[int, dict] = {}
    for ch in chapters:
        doc = read_json(chapter_path(slug, run_id, ch))
        if doc is None:
            raise FileNotFoundError(f"staged chapter {ch} missing for {slug}/{run_id}")
        docs[ch] = doc
    return docs


def delete_run(slug: str, run_id: str) -> None:
    """Best-effort teardown of the run's staging tree."""
    backend = get_backend()
    prefix = run_prefix(slug, run_id)
    for sub in (CHAPTERS_DIR, SIDECARS_DIR):
        try:
            names = backend.list_dir(f"{prefix}/{sub}")
        except Exception:  # noqa: BLE001
            names = []
        for name in names:
            leaf = name.rsplit("/", 1)[-1]
            _delete(f"{prefix}/{sub}/{leaf}")
    _delete(acquire_path(slug, run_id))


def _delete(path: str) -> None:
    try:
        get_backend().delete(path)
    except Exception as exc:  # noqa: BLE001 — teardown never fails the run
        log.warning("align staging: delete %s failed: %s", path, exc)
