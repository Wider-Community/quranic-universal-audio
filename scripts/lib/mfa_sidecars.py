"""Run all post-extraction MFA sidecars in one shot, sharing the worker pool.

Today there are two:

* ``low_confidence_v2.json`` — tight-beam (default beam=2) probe over every
  segment in ``detailed.json``. Flags segments whose audio fails to align
  under the tight beam — Inspector surfaces these in the *Low Confidence
  v2* accordion.
* ``auto_split_v1.json``     — wide-beam (default beam=50) precompute over
  cross-verse + repetition candidates only. Provides word-level boundaries
  so Inspector's Auto Split tool can position cut cursors instantly.

Both passes import the local MFA Space app and warm the Kalpy dictionary
inside every worker. Opening one ``ProcessPoolExecutor`` (via
:class:`scripts.lib.mfa_runtime.MfaRuntime`) and reusing it across both
passes amortises that startup. Audio decode is still per-pass — both
passes read from the same on-disk per-chapter MP3s, so OS page cache
makes the second pass effectively free for I/O.

CLI::

    python3 -m scripts.lib.mfa_sidecars \
        --reciter-dir /srv/scratch/.../<slug> \
        --audio-dir   /srv/scratch/.../<slug>/audio \
        --mfa-app-path .local/spaces/mfa_aligner/app.py

Both ``run_probe`` and ``run_precompute`` keep working standalone (when
called without a runtime they self-manage). This orchestrator is the
preferred entry point for the post-extraction stage of the segments
flow; the individual scripts are for re-runs / ad-hoc analysis.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from scripts.lib.mfa_runtime import MfaRuntime
from scripts.lib.probe_mfa import (
    DEFAULT_BATCH_SIZE as PROBE_BATCH_SIZE,
    DEFAULT_DOWNLOAD_WORKERS as PROBE_DL_WORKERS,
    DEFAULT_PROBE_BEAM,
    run_probe,
)
from scripts.lib.auto_split_precompute import (
    DEFAULT_BATCH_SIZE as SPLIT_BATCH_SIZE,
    DEFAULT_BEAM as SPLIT_BEAM,
    DEFAULT_DOWNLOAD_WORKERS as SPLIT_DL_WORKERS,
    run_precompute,
)

log = logging.getLogger(__name__)

# Default worker count for the orchestrator. Matches probe_mfa /
# auto_split standalone defaults — the canonical path is the PBS job
# (``mfa_sidecars.pbs``) where the allocation gives 96 GB on a compute
# node, so 24 workers × ~250 MB after kalpy dictionary load is well
# within budget. The login-node wrapper (``katana_mfa_sidecars.sh``)
# exists only for ad-hoc / tiny by-ayah reciters and should pass
# ``--workers 8`` explicitly to fit the 4 GiB per-user cgroup cap there.
DEFAULT_WORKERS = 24


def run_all_sidecars(
    reciter_dir: Path,
    *,
    mfa_app_path: Path,
    audio_dir: Path | None = None,
    repo_root: Path | None = None,
    probe_beam: int = DEFAULT_PROBE_BEAM,
    split_beam: int = SPLIT_BEAM,
    workers: int = DEFAULT_WORKERS,
    download_workers: int = PROBE_DL_WORKERS,
    probe_batch_size: int = PROBE_BATCH_SIZE,
    split_batch_size: int = SPLIT_BATCH_SIZE,
    skip_probe: bool = False,
    skip_auto_split: bool = False,
) -> tuple[Path | None, Path | None]:
    """Run probe + auto-split with a shared :class:`MfaRuntime`.

    Returns ``(probe_sidecar_path, auto_split_sidecar_path)``. Either
    side may be ``None`` if the corresponding pass was skipped or the
    input directory was empty.

    Worker / batch / download knobs are forwarded to each pass; if you
    need per-pass workers (e.g. fewer workers for the smaller auto-split
    candidate set), call the underlying functions directly.
    """
    reciter_dir = Path(reciter_dir).resolve()
    if not (reciter_dir / "detailed.json").exists():
        log.error("detailed.json not found in %s — nothing to do", reciter_dir)
        return None, None

    if skip_probe and skip_auto_split:
        log.error("both --skip-probe and --skip-auto-split set; nothing to do")
        return None, None

    probe_path: Path | None = None
    split_path: Path | None = None

    with MfaRuntime(mfa_app_path, workers) as runtime:
        if not skip_probe:
            log.info("=== probe (beam=%d) ===", probe_beam)
            probe_path = run_probe(
                reciter_dir,
                mfa_app_path=mfa_app_path,
                audio_dir=audio_dir,
                beam=probe_beam,
                batch_size=probe_batch_size,
                workers=workers,
                download_workers=download_workers,
                runtime=runtime,
            )
        if not skip_auto_split:
            log.info("=== auto-split precompute (beam=%d) ===", split_beam)
            split_path = run_precompute(
                reciter_dir,
                mfa_app_path=mfa_app_path,
                audio_dir=audio_dir,
                repo_root=repo_root,
                beam=split_beam,
                batch_size=split_batch_size,
                workers=workers,
                download_workers=download_workers,
                runtime=runtime,
            )

    return probe_path, split_path


def _main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Run probe + auto-split sidecars sharing one MFA pool.",
    )
    p.add_argument("--reciter-dir", type=Path, required=True,
                   help="Directory containing detailed.json (and audio/ for fast-path).")
    p.add_argument("--audio-dir", type=Path, default=None,
                   help="Per-chapter MP3 directory. Defaults to <reciter-dir>/audio.")
    p.add_argument("--mfa-app-path", type=Path, required=True,
                   help="Path to the local MFA aligner module.")
    p.add_argument("--repo-root", type=Path, default=None,
                   help="Repo root (for auto-split's verse word counts).")
    p.add_argument("--probe-beam", type=int, default=DEFAULT_PROBE_BEAM)
    p.add_argument("--split-beam", type=int, default=SPLIT_BEAM)
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                   help="MFA process pool size (shared across passes). "
                        f"Default {DEFAULT_WORKERS} fits the 4 GiB login-node "
                        "cgroup; bump under PBS where the allocation is larger.")
    p.add_argument("--download-workers", type=int, default=PROBE_DL_WORKERS)
    p.add_argument("--probe-batch-size", type=int, default=PROBE_BATCH_SIZE)
    p.add_argument("--split-batch-size", type=int, default=SPLIT_BATCH_SIZE)
    p.add_argument("--skip-probe", action="store_true",
                   help="Skip the probe pass; only run auto-split.")
    p.add_argument("--skip-auto-split", action="store_true",
                   help="Skip the auto-split pass; only run probe.")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    audio_dir = args.audio_dir or (args.reciter_dir / "audio")
    if not audio_dir.is_dir():
        log.warning("audio_dir %s missing; will fall back to URLs in detailed.json", audio_dir)
        audio_dir = None

    probe_path, split_path = run_all_sidecars(
        args.reciter_dir,
        mfa_app_path=args.mfa_app_path,
        audio_dir=audio_dir,
        repo_root=args.repo_root,
        probe_beam=args.probe_beam,
        split_beam=args.split_beam,
        workers=args.workers,
        download_workers=args.download_workers,
        probe_batch_size=args.probe_batch_size,
        split_batch_size=args.split_batch_size,
        skip_probe=args.skip_probe,
        skip_auto_split=args.skip_auto_split,
    )

    if probe_path is None and split_path is None:
        return 1
    log.info("done — probe=%s  auto_split=%s",
             probe_path or "(skipped)", split_path or "(skipped)")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
