#!/usr/bin/env python3
"""CI/HF-Space entrypoint for timestamp extraction.

Shared logic lives in qua_shared.timestamps_pipeline. Invoked from
`.github/workflows/timestamps-refresh.yml`. Single-process serial path
(HF Space backend); for true CPU parallelism use
``.local/extraction/extract_timestamps_local.py``.
"""

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from qua_shared.timestamps_pipeline import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_BEAMS,
    DEFAULT_DOWNLOAD_WORKERS,
    DEFAULT_METHOD,
    DEFAULT_PADDING,
    DEFAULT_SPACE_URL,
    SpaceMfaBackend,
    process,
)


def _parse_beams(s: str) -> list[int]:
    out = [int(t.strip()) for t in s.split(",") if t.strip()]
    if not out:
        raise argparse.ArgumentTypeError("must specify at least one beam")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract word/letter/phoneme timestamps via the MFA HF Space."
    )
    parser.add_argument("--input", required=True,
                        help="Path to reciter directory containing detailed.json")
    parser.add_argument("--space-url", default=DEFAULT_SPACE_URL,
                        help=f"MFA HF Space URL (default: {DEFAULT_SPACE_URL})")
    parser.add_argument("--method", default=DEFAULT_METHOD,
                        help=f"Alignment method (default: {DEFAULT_METHOD})")
    parser.add_argument("--beams", type=_parse_beams,
                        default=list(DEFAULT_BEAMS),
                        help=("Comma-separated list of beam values. First is "
                              "canonical; the rest are probes. Default: "
                              f"{','.join(str(b) for b in DEFAULT_BEAMS)}"))
    parser.add_argument("--shared-cmvn", action="store_true",
                        help="Compute shared CMVN across batch (kalpy only)")
    parser.add_argument("--padding",
                        choices=["forward", "symmetric", "none"],
                        default=DEFAULT_PADDING,
                        help=f"Phoneme gap-padding strategy (default: {DEFAULT_PADDING})")
    parser.add_argument("--resume", action="store_true",
                        help="Skip already-completed chapters")
    parser.add_argument("--refresh-verses",
                        help="Comma-separated verse keys to re-extract (e.g. 1:1,37:151,37:152)")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                        help=f"Segments per MFA upload batch (default: {DEFAULT_BATCH_SIZE})")
    parser.add_argument("--download-workers", type=int,
                        default=DEFAULT_DOWNLOAD_WORKERS,
                        help=f"Parallel audio download/decode workers "
                             f"(default: {DEFAULT_DOWNLOAD_WORKERS})")
    parser.add_argument("-o", "--output", default=None,
                        help="Output directory (default: auto-derived from input path)")

    args = parser.parse_args()
    refresh = set(args.refresh_verses.split(",")) if args.refresh_verses else None
    process(
        input_dir=Path(args.input).resolve(),
        backend=SpaceMfaBackend(args.space_url),
        method=args.method,
        beams=args.beams,
        shared_cmvn=args.shared_cmvn,
        resume=args.resume,
        batch_size=args.batch_size,
        output_dir=Path(args.output).resolve() if args.output else None,
        padding=args.padding,
        refresh_verses=refresh,
        download_workers=args.download_workers,
        workers=1,
        mfa_app_path=None,
    )


if __name__ == "__main__":
    main()
