#!/usr/bin/env python3
"""Render the first-push timestamps validation comment from validator JSON.

Reads JSON output from `validate_timestamps.py --json` on stdin (or a file
via --stats), plus required --reciter / --audio-category arguments, and
writes the rendered Markdown comment to stdout (or --out).
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.lib.config_loader import load_template  # noqa: E402

_MAX_FAILURES_SHOWN = 5


def _format_failures(failures: list[dict]) -> str:
    if not failures:
        return "_None — all segments aligned cleanly._\n"
    shown = failures[:_MAX_FAILURES_SHOWN]
    extra = len(failures) - len(shown)
    lines = []
    for f in shown:
        verse = f.get("verse", "?")
        ref = f.get("ref", "?")
        seg = f.get("seg", "?")
        err = f.get("error", "?")
        lines.append(f"- `{verse}` [`{ref}`] seg {seg} — `{err}`")
    if extra > 0:
        lines.append(f"- … and {extra} more")
    return "\n".join(lines) + "\n"


def render(stats: dict, *, reciter: str, audio_category: str) -> str:
    template = load_template("workflows/timestamps-validation-comment")
    missing = stats.get("missing", 0)
    mfa_failures = stats.get("_mfa_failures", []) or []
    failures_count = stats.get("mfa_failures", len(mfa_failures))
    total_verses = stats.get("total_verses", 0)
    verses_present = total_verses - missing
    clean = (missing == 0 and failures_count == 0)
    return template.format(
        header_glyph="✅" if clean else "⚠️",
        reciter=reciter,
        audio_category=audio_category,
        aligner_model=stats.get("aligner_model", "quran_aligner_model"),
        verses_present=verses_present,
        total_verses=total_verses,
        missing_verses=missing,
        word_coverage_issues=stats.get("word_coverage_issues", 0),
        forward_gap_verses=stats.get("forward_gap_verses", 0),
        zero_duration_words=stats.get("zero_duration_words", 0),
        mfa_failures_count=failures_count,
        mfa_failures_block=_format_failures(mfa_failures),
        ts_path=f"data/timestamps/{audio_category}/{reciter}/timestamps.json",
        ts_full_path=f"data/timestamps/{audio_category}/{reciter}/timestamps_full.json",
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reciter", required=True)
    ap.add_argument("--audio-category", required=True,
                    choices=["by_surah_audio", "by_ayah_audio"])
    ap.add_argument("--stats", type=Path,
                    help="Path to validate_timestamps --json output "
                         "(default: read stdin).")
    ap.add_argument("--out", type=Path,
                    help="Output file (default: stdout).")
    args = ap.parse_args()

    if args.stats:
        stats = json.loads(args.stats.read_text(encoding="utf-8"))
    else:
        stats = json.loads(sys.stdin.read())

    body = render(stats, reciter=args.reciter,
                  audio_category=args.audio_category)
    if args.out:
        args.out.write_text(body, encoding="utf-8")
    else:
        sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
