"""Shared MFA worker-pool runtime.

Both ``probe_mfa`` and ``auto_split_precompute`` open a
``ProcessPoolExecutor`` initialised with ``_init_worker`` — each worker
process builds a qua_sdk ``MfaLocalAligner`` and warms the Kalpy dictionary
(~10-25 s wall-clock cumulative across workers, in addition to per-pass
chapter audio decode). Running both sidecars in separate processes pays
that cost twice and ends up running two ssh invocations from Katana.

``MfaRuntime`` is a small context manager that owns one pool. Callers
that want to chain multiple passes (probe → auto-split, or any future
multi-beam sidecar) pass the runtime in instead of opening their own pool.
Callers that want the old "self-contained run" behaviour keep working by
passing ``runtime=None`` and the function builds its own runtime on the
fly.

The pool is identical across passes — the (beam, refs, paths, padding)
quadruple lives on the per-call ``_worker_align`` task, so different
passes happily share the same workers.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from .timestamps_pipeline import _init_worker, _paths_from_app_path


class MfaRuntime:
    """Owns a ``ProcessPoolExecutor`` initialised with ``_init_worker``.

    Use as a context manager::

        with MfaRuntime(model_path, dictionary_path, workers=24) as runtime:
            run_probe(reciter_dir, runtime=runtime, ...)
            run_precompute(reciter_dir, runtime=runtime, ...)

    The pool warmup (kalpy import + dictionary load per worker) happens
    once at ``__enter__`` and is amortised across every pass that reuses
    the runtime. ``mfa_app_path`` is a deprecated alias — the model +
    dictionary are derived from the app.py file's directory.
    """

    def __init__(
        self,
        model_path: str | Path | None,
        dictionary_path: str | Path | None,
        workers: int,
        *,
        mfa_app_path: str | Path | None = None,
    ):
        if mfa_app_path is not None and not (model_path and dictionary_path):
            model_path, dictionary_path = _paths_from_app_path(mfa_app_path)
        if not model_path or not dictionary_path:
            raise ValueError(
                "MfaRuntime needs model_path + dictionary_path (or the deprecated mfa_app_path)"
            )
        self.model_path = str(model_path)
        self.dictionary_path = str(dictionary_path)
        self.workers = workers
        self._pool: ProcessPoolExecutor | None = None

    def __enter__(self) -> MfaRuntime:
        self._pool = ProcessPoolExecutor(
            max_workers=self.workers,
            initializer=_init_worker,
            initargs=(self.model_path, self.dictionary_path),
        )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._pool is not None:
            self._pool.shutdown()
            self._pool = None

    @property
    def pool(self) -> ProcessPoolExecutor:
        if self._pool is None:
            raise RuntimeError(
                "MfaRuntime accessed outside `with` block — call as a "
                "context manager so the pool lifecycle is bounded."
            )
        return self._pool
