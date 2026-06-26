"""Shared per-verse timing layout — the single reconstruction both release
channels consume so they cannot drift.

The HF dataset (``qua_jobs/publish_hf.py``) and the GitHub release
(``qua_jobs/cut_release.py``) used to reconstruct verse geometry independently.
They agree on the source (the canonical ``project_segment_shard`` projection,
completion-based occasion dedup) but had two copies of the loader, the
projection→rows reshape, and the clip-window math — which is exactly where they
drifted. This module owns all three so there is one source of truth.

``build_verse_layouts`` returns, per verse, SOURCE-relative ms:

  - ``clip_start`` / ``clip_end`` — the padded verse window. Outer headroom is
    carved from the real inter-verse silence with a ratio-preserving fit
    (``_fit_boundary``) so adjacent verse windows keep >= ``min_gap`` and never
    overlap. This is the audio clip in the HF dataset AND the verse bound in the
    GH release, computed once — so the two channels agree by construction.
  - ``segments`` — post-MFA byte-exact segments (gapless within a segment, a gap
    only across boundaries). Boundaries come from the projection's per-segment
    occurrence spans so a repeated boundary word can't collapse to the wrong
    occurrence. The two outer segments are stretched to the clip edges so they
    absorb the pad while every internal boundary stays byte-exact with a word.
    The HF dataset publishes these; the GH release uses them only to validate
    gaplessness (it does not publish a segment tier).
  - ``words`` / ``letters`` — straight from the projection (psil-filtered).

The HF dataset rebases these to clip-relative and slices audio; the GH release
keeps them source-relative. Neither re-derives the geometry.
"""

from __future__ import annotations

import gzip
import json
import os
from collections.abc import Callable
from pathlib import Path

from qua_shared.letter_vocab import to_external_char
from qua_shared.ts_shard_letters import iter_letters

#: Default clip-edge knobs (ms). pad_start before the first word, pad_end after
#: the last word, min_gap minimum silence kept between adjacent verse clips.
PAD_DEFAULTS = {"pad_start": 100, "pad_end": 300, "min_gap": 100}


def pad_params_from_env() -> dict[str, int]:
    """The three release clip-edge knobs from the job env — shared by both
    channels so a "Release settings" change reaches the HF publish AND the GH
    cut identically. Unset/empty falls back to ``PAD_DEFAULTS``.
    """
    return {
        "pad_start": int(os.environ.get("PUBLISH_PAD_START", "").strip() or PAD_DEFAULTS["pad_start"]),
        "pad_end": int(os.environ.get("PUBLISH_PAD_END", "").strip() or PAD_DEFAULTS["pad_end"]),
        "min_gap": int(os.environ.get("PUBLISH_MIN_GAP", "").strip() or PAD_DEFAULTS["min_gap"]),
    }


def _i(x) -> int:
    """Coerce ms to int (round on float, pass-through on int)."""
    return int(round(x)) if isinstance(x, float) else int(x)


def _fit_boundary(
    left_end: int, right_start: int, pad_end: int, pad_start: int, min_gap: int
) -> tuple[float, float]:
    """Split the true silence between two adjacent verses (verse N's MFA
    last-letter end → verse N+1's MFA first-letter start) into
    ``(tail_pad for N, lead_pad for N+1)``.

    Hands ``pad_end`` to N's tail and ``pad_start`` to N+1's lead while keeping
    at least ``min_gap`` of silence between the two clips. When they would
    overflow the available silence the pads scale down proportionally (the
    ``pad_end : pad_start`` ratio is preserved) so the clips never leak into each
    other (their gap then equals exactly ``min_gap``).
    """
    sil = right_start - left_end
    if pad_end + min_gap + pad_start <= sil:
        return float(pad_end), float(pad_start)
    budget = max(0.0, sil - min_gap)
    total = pad_end + pad_start
    if total <= 0:
        return 0.0, 0.0
    return budget * pad_end / total, budget * pad_start / total


def load_canonical_verses(ts_dir: Path) -> dict[str, dict]:
    """Read every ``<ts_dir>/<ch>.json.gz`` segment-array shard, project each to
    the canonical verse map (completion-based occasion dedup, the EARLIEST
    completing occasion), and merge into one global dict.

    Returns ``{ref: {"words", "verse_start_ms", "verse_end_ms", "segments"}}``;
    ``segments`` carries the per-segment occurrence spans (see
    ``timestamps_dedup._canonical_verse``). Both release channels load shards
    through here so the dedup + merge are identical.
    """
    from qua_shared.timestamps_dedup import project_segment_shard

    out: dict[str, dict] = {}
    if not ts_dir.exists():
        return out
    for path in sorted(
        ts_dir.iterdir(),
        key=lambda p: int(p.name.split(".", 1)[0]) if p.name.split(".", 1)[0].isdigit() else 0,
    ):
        name = path.name
        if not (name.endswith(".json") or name.endswith(".json.gz")):
            continue
        raw = path.read_bytes()
        if name.endswith(".gz"):
            raw = gzip.decompress(raw)
        out.update(project_segment_shard(json.loads(raw)))
    return out


def reshape_canonical(canonical: dict) -> dict[str, dict]:
    """Convert the canonical verse-map shape into ``build_verse_layouts`` input.

    ``canonical[ref]`` is the projection body
    (``{"words": [[widx, s, e, letters, ...], ...], "verse_start_ms",
    "verse_end_ms", "segments"}``). For each verse this returns
    ``{"words": [[widx, s, e], ...], "letters": [(widx, letters), ...],
    "verse_start_ms": int, "verse_end_ms": int, "seg_spans": [...] | None}``.
    """
    ts: dict[str, dict] = {}
    for ref, val in canonical.items():
        if ref.startswith("_"):
            continue
        words = val.get("words") if isinstance(val, dict) else val
        if not words:
            ts[ref] = {"words": [], "letters": [], "verse_start_ms": 0,
                       "verse_end_ms": 0, "seg_spans": []}
            continue
        vs = val.get("verse_start_ms") if isinstance(val, dict) else None
        ve = val.get("verse_end_ms") if isinstance(val, dict) else None
        if vs is None or ve is None:
            vs = words[0][1]
            ve = max(int(w[2]) for w in words)
        slim_words = [[int(w[0]), int(w[1]), int(w[2])] for w in words]
        letters = [(int(w[0]), w[3] if len(w) > 3 else []) for w in words]
        ts[ref] = {
            "words": slim_words,
            "letters": letters,
            "verse_start_ms": int(vs),
            "verse_end_ms": int(ve),
            # Per-segment occurrence spans (None for legacy word-only inputs) —
            # the faithful source for segment boundaries when a boundary word
            # index repeats; build_verse_layouts falls back to the word-index map.
            "seg_spans": val.get("segments") if isinstance(val, dict) else None,
        }
    return ts


def build_verse_layouts(
    timestamps: dict,
    *,
    pad_start: int = 100,
    pad_end: int = 300,
    min_gap: int = 100,
    seg_word_range: Callable[[str, str, int], tuple[int, int] | None] | None = None,
    detailed_by_ref: dict | None = None,
) -> dict[str, dict]:
    """Build SOURCE-relative per-verse layouts from the reshaped canonical map.

    ``timestamps`` is ``reshape_canonical`` output. ``seg_word_range`` +
    ``detailed_by_ref`` are only consulted for legacy inputs that carry no
    occurrence spans (``seg_spans``); the real projection path always carries
    them. Returns ``{ref: {clip_start, clip_end, verse_start, verse_end,
    segments, words, letters}}`` — see the module docstring.
    """
    detailed_by_ref = detailed_by_ref or {}
    layouts: dict[str, dict] = {}
    for ref, tdata in timestamps.items():
        if ref.startswith("_"):
            continue
        words = tdata.get("words") or []
        if not words:
            continue
        try:
            surah_num, ayah_s = ref.split(":", 1)
            ayah = int(ayah_s)
        except (ValueError, AttributeError):
            continue
        verse_start = int(tdata["verse_start_ms"])
        verse_end = int(tdata["verse_end_ms"])

        # Clip edges from MFA times (not VAD): pad the verse's outer edges with
        # ratio-fit headroom shared against the neighbour verses, so adjacent
        # windows keep >= min_gap of silence and never leak. Chapter-edge verses
        # just pad. (Clamp to the source start; the upper clamp to audio length
        # is the slicer's job — the layout stays geometry-only.)
        prev = timestamps.get(f"{surah_num}:{ayah - 1}")
        nxt = timestamps.get(f"{surah_num}:{ayah + 1}")
        if prev and prev.get("words"):
            _, lead_pad = _fit_boundary(
                int(prev["verse_end_ms"]), verse_start, pad_end, pad_start, min_gap)
        else:
            lead_pad = float(pad_start)
        if nxt and nxt.get("words"):
            tail_pad, _ = _fit_boundary(
                verse_end, int(nxt["verse_start_ms"]), pad_end, pad_start, min_gap)
        else:
            tail_pad = float(pad_end)
        clip_start = max(0, int(round(verse_start - lead_pad)))
        clip_end = int(round(verse_end + tail_pad))

        # Segments: prefer the projection's per-segment OCCURRENCE spans (a
        # repeated boundary word can't collapse to the wrong occurrence). Fall
        # back to the word-index map for legacy word-only inputs.
        seg_spans = tdata.get("seg_spans")
        segments: list[list[int]] = []
        if seg_spans:
            for sp in seg_spans:
                segments.append(
                    [_i(sp["w_from"]), _i(sp["w_to"]),
                     _i(int(sp["start_ms"])), _i(int(sp["end_ms"]))]
                )
        elif seg_word_range is not None:
            word_by_idx = {int(w[0]): (int(w[1]), int(w[2])) for w in words}
            for seg in (detailed_by_ref.get(ref) or {}).get("segments", []) or []:
                wr = seg_word_range(seg.get("matched_ref", ""), surah_num, ayah)
                if wr is None:
                    continue
                w_from, w_to = wr
                if w_from not in word_by_idx or w_to not in word_by_idx:
                    continue
                segments.append(
                    [_i(w_from), _i(w_to),
                     _i(word_by_idx[w_from][0]), _i(word_by_idx[w_to][1])]
                )

        verse_words = [[_i(w[0]), _i(w[1]), _i(w[2])] for w in words]

        # Synthesize missing segments around the home segments (cross-verse).
        if verse_words and not segments:
            segments.append(
                [verse_words[0][0], verse_words[-1][0], verse_words[0][1], verse_words[-1][2]]
            )
        elif verse_words and segments:
            first_seg_start = segments[0][2]
            xv_before = [w for w in verse_words if w[2] <= first_seg_start]
            if xv_before:
                segments.insert(
                    0,
                    [xv_before[0][0], xv_before[-1][0], xv_before[0][1], xv_before[-1][2]],
                )
            last_seg_end = segments[-1][3]
            xv_after = [w for w in verse_words if w[1] >= last_seg_end]
            if xv_after:
                segments.append(
                    [xv_after[0][0], xv_after[-1][0], xv_after[0][1], xv_after[-1][2]]
                )

        # Outer-edge headroom: the first segment starts at the clip start and the
        # last ends at the clip end, so the two outer segments absorb the lead/
        # tail pads while every internal boundary stays byte-exact with a word.
        if segments:
            segments[0][2] = clip_start
            segments[-1][3] = clip_end

        # Letters: flatten (widx, char, start, end) — source-relative. Read via
        # the named accessor; the shard's trailing ``silent`` flag isn't exposed.
        verse_letters: list[tuple[int, str, int, int]] = []
        for widx, letters in tdata.get("letters", []):
            for lt in iter_letters(letters):
                verse_letters.append(
                    (int(widx), to_external_char(lt.char), int(lt.start_ms), int(lt.end_ms))
                )

        layouts[ref] = {
            "clip_start": clip_start,
            "clip_end": clip_end,
            "verse_start": verse_start,
            "verse_end": verse_end,
            "segments": segments,
            "words": verse_words,
            "letters": verse_letters,
        }
    return layouts
