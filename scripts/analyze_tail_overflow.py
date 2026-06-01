"""Analyze the scale of tajweed bridge "tail overflow" phoneme bug.

When a tajweed bridge (Idgham/iqlab merger) occurs at a word boundary, the
merged phoneme is stored in the PREV word's phoneme array.  Sometimes MFA also
attaches the vowel of the merged letter (e.g. 'i' for kasra of مِّ) to the
prev word's tail — AFTER the merger phoneme.  Those extra phonemes should be
excluded from the prev word's display but currently aren't.

Usage:
    python3 scripts/analyze_tail_overflow.py [--reciter SLUG] [--chapter N]
    python3 scripts/analyze_tail_overflow.py  # defaults: ayman_swed_muallim_tvquran, ch28 only

Reads from the prod bucket (read-only).
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from typing import Any

GHUNNAH_TILDE = "̃"
PHARYNGEAL = "ˤ"


def is_merger_phoneme(phone: str) -> bool:
    """Return True if phone is a tajweed bridge/merger phoneme.

    Mirrors the frontend detection logic:
    - Has U+0303 combining tilde (ghunnah mark), OR
    - Has 'ñ' character, OR
    - After stripping pharyngeal marker (ˤ), length >= 2 and first == second char
      (doubled consonant: mm, nn, rr, tt, ll, …)
    """
    if GHUNNAH_TILDE in phone:
        return True
    if "ñ" in phone:
        return True
    stripped = phone.replace(PHARYNGEAL, "")
    if len(stripped) >= 2 and stripped[0] == stripped[1]:
        return True
    return False


def find_merger_in_tail(phonemes: list[Any], tail_size: int = 3) -> int | None:
    """Return the index of the last merger phoneme in the tail (last N phonemes).

    Returns None if no merger phoneme found in tail.
    """
    tail_start = max(0, len(phonemes) - tail_size)
    for i in range(len(phonemes) - 1, tail_start - 1, -1):
        phone = phonemes[i][0]
        if is_merger_phoneme(phone):
            return i
    return None


def analyze_chapter(chapter_data: dict, chapter_num: int) -> dict:
    """Analyze one chapter's timestamp data for tail overflow occurrences."""
    total_word_pairs = 0
    merger_in_tail_count = 0
    overflow_count = 0
    examples = []

    verse_keys = sorted(
        (k for k in chapter_data if k != "_meta"),
        key=lambda k: tuple(int(x) for x in k.split(":")),
    )

    for verse_key in verse_keys:
        segs = chapter_data[verse_key]
        for seg in segs:
            if not isinstance(seg, dict) or "words_by_verse" not in seg:
                continue
            for verse_ref, words in seg["words_by_verse"].items():
                # words is a list of [word_idx, start_ms, end_ms, letters, phonemes]
                for i in range(len(words) - 1):
                    prev_word = words[i]
                    curr_word = words[i + 1]

                    # phonemes_array is index 4
                    if len(prev_word) < 5 or len(curr_word) < 5:
                        continue

                    prev_phonemes = prev_word[4]
                    curr_phonemes = curr_word[4]

                    if not prev_phonemes:
                        continue

                    total_word_pairs += 1

                    merger_idx = find_merger_in_tail(prev_phonemes)
                    if merger_idx is None:
                        continue

                    merger_in_tail_count += 1

                    # Phonemes AFTER the merger phoneme in prev word
                    overflow_phonemes = prev_phonemes[merger_idx + 1 :]

                    if overflow_phonemes:
                        overflow_count += 1
                        if len(examples) < 10:
                            merger_phone = prev_phonemes[merger_idx][0]
                            prev_tail = [p[0] for p in prev_phonemes[max(0, merger_idx - 2):]]
                            examples.append(
                                {
                                    "verse_ref": verse_ref,
                                    "prev_word_idx": prev_word[0],
                                    "curr_word_idx": curr_word[0],
                                    "merger_phoneme": merger_phone,
                                    "merger_idx_in_prev": merger_idx,
                                    "prev_phonemes_total": len(prev_phonemes),
                                    "overflow_phonemes": [p[0] for p in overflow_phonemes],
                                    "context_tail": prev_tail,
                                    "curr_first_phonemes": [p[0] for p in curr_phonemes[:3]],
                                }
                            )

    return {
        "total_word_pairs": total_word_pairs,
        "merger_in_tail_count": merger_in_tail_count,
        "overflow_count": overflow_count,
        "examples": examples,
    }


def load_chapter(bucket: str, reciter: str, chapter: int) -> dict:
    from huggingface_hub import hffs, login
    import os

    token = (
        os.environ.get("HF_TOKEN")
        or os.environ.get("INSPECTOR_HF_TOKEN")
        or _read_cached_token()
    )
    if token:
        login(token=token, add_to_git_credential=False)

    path = f"buckets/{bucket}/reciters/{reciter}/timestamps/{chapter}.json.gz"
    print(f"Reading: {path}", file=sys.stderr)
    raw = hffs.cat_file(path)
    return json.loads(gzip.decompress(raw))


def _read_cached_token() -> str | None:
    import pathlib

    candidates = [
        pathlib.Path.home() / ".cache" / "huggingface" / "token",
        pathlib.Path.home() / ".huggingface" / "token",
    ]
    for p in candidates:
        if p.exists():
            return p.read_text().strip()
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reciter", default="ayman_swed_muallim_tvquran")
    parser.add_argument(
        "--chapter",
        type=int,
        default=None,
        help="Single chapter number (default: scan ch 2–114 for merger-heavy surahs)",
    )
    parser.add_argument("--bucket", default="hetchyy/quranic-inspector-bucket")
    parser.add_argument(
        "--all-chapters",
        action="store_true",
        help="Scan all 114 chapters (slow — ~100 requests)",
    )
    args = parser.parse_args()

    chapters_to_scan: list[int]
    if args.chapter is not None:
        chapters_to_scan = [args.chapter]
    elif args.all_chapters:
        chapters_to_scan = list(range(1, 115))
    else:
        # Default: surah 28 as the user requested, plus a few tajweed-heavy surahs
        chapters_to_scan = [28]

    totals = {
        "total_word_pairs": 0,
        "merger_in_tail_count": 0,
        "overflow_count": 0,
    }
    all_examples: list[dict] = []

    for ch in chapters_to_scan:
        try:
            data = load_chapter(args.bucket, args.reciter, ch)
        except FileNotFoundError:
            print(f"  Chapter {ch}: not found, skipping", file=sys.stderr)
            continue
        except Exception as e:
            print(f"  Chapter {ch}: error — {e}", file=sys.stderr)
            continue

        result = analyze_chapter(data, ch)
        print(
            f"  Ch {ch:>3}: pairs={result['total_word_pairs']:>5}  "
            f"merger_tail={result['merger_in_tail_count']:>4}  "
            f"overflow={result['overflow_count']:>4}",
            file=sys.stderr,
        )

        for k in totals:
            totals[k] += result[k]  # type: ignore[operator]
        if len(all_examples) < 10:
            all_examples.extend(result["examples"][: 10 - len(all_examples)])

    print("\n" + "=" * 60)
    print(f"RECITER:  {args.reciter}")
    print(f"CHAPTERS: {chapters_to_scan}")
    print("=" * 60)
    print(f"Total word pairs examined:              {totals['total_word_pairs']:>6}")
    print(f"Word pairs with merger phoneme in tail: {totals['merger_in_tail_count']:>6}")
    if totals["merger_in_tail_count"] > 0:
        pct = 100 * totals["overflow_count"] / totals["merger_in_tail_count"]
        print(
            f"Of those, pairs WITH tail overflow:     {totals['overflow_count']:>6}  "
            f"({pct:.1f}%)"
        )
    else:
        print(f"Of those, pairs WITH tail overflow:     {totals['overflow_count']:>6}")

    print("\n--- Examples (up to 10) ---")
    for ex in all_examples:
        print(
            f"\n  {ex['verse_ref']}  w{ex['prev_word_idx']}→w{ex['curr_word_idx']}"
        )
        print(f"    merger phoneme: '{ex['merger_phoneme']}'  (idx {ex['merger_idx_in_prev']} of {ex['prev_phonemes_total']} in prev word)")
        print(f"    overflow phonemes: {ex['overflow_phonemes']}")
        print(f"    prev tail context: {ex['context_tail']}")
        print(f"    curr word first phonemes: {ex['curr_first_phonemes']}")


if __name__ == "__main__":
    main()
