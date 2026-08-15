"""Bounded-equivalence gate — replay frozen shards through the current producer.

The producer's vocabulary changed on purpose, so byte parity is the wrong
question. The right one is: **is every change one we named in advance?** This
scanner replays a directory of frozen legacy shards through the live producer
(the same ``annotate_ordered_segments`` the pipeline runs) and sorts every
difference into a declared family. Anything it cannot name exits 1.

What counts as a difference, per word:

  tag       a rule the legacy cells named that the replayed ones do not, or the
            reverse, or a producer rule no cell carries
  bucket    a phone the re-attribution moved from one word to its neighbour
  token     a stored phone whose string the producer no longer produces
  silence   a written letter whose ``silent`` flag moved

The families:

  rename              one legacy tag, one new tag, mechanically mapped
  collapse            a legacy noon/tanween pair folded onto one cell tag
  new_rule            an allowlisted tag legacy had no name for
  dropped             a producer rule the shard vocabulary carries no tag for
  merger_attribution  a merged sound hosted on the word whose letter carries it
  fix                 a listed correction: the new reading is right, legacy was not
  residue             a listed exception, declared with its reason

Two assertions ride on top and are nobody's family. Either one failing fails the
run outright:

  1. Word timings are byte-identical -- ``words[i][1]`` / ``words[i][2]`` may not
     move for any word, including across a merger. This is the whole safety
     claim of the uniform merger attribution.
  2. Every word's stored indexable-phone count equals the producer's, so the
     cell stamper writes cells for each word instead of dropping a whole run.

CLI:
    python scripts/diagnostics/ts_bounded_equivalence.py SHARD_DIR
        [--chapters 1,2,46] [--max-examples N] [--json]

``SHARD_DIR`` holds ``<chapter>.json.gz`` / ``<chapter>.shard.json`` files. It is
read-only and never fetched from a bucket: point it at a local corpus. Needs a
local ``qua_sdk`` + ``quranic_phonemizer``. Family counts are only asserted when
the run covers the whole declared corpus. Run from the repo root.

``qua_shared/tests/test_bounded_equivalence.py`` drives all of this; its corpus
run reads the same directory from ``QUA_FROZEN_SHARDS`` and skips without it.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.diagnostics.ts_bounded_report import (  # noqa: E402
    Diff,
    Report,
    count_violations,
    render,
    to_json,
)
from scripts.diagnostics.ts_bounded_vocab import (  # noqa: E402
    CARRIER_WAW,
    DROPPED_RULES,
    FIX_HEAVY_HUM,
    FIX_QALQALA_AT_STOP,
    FIX_REFS,
    LABIAL_MERGER,
    LEGACY_SILENCE_TAGS,
    MERGER_CELL_TAGS,
    NEW_RULE_TAGS,
    RESIDUE_REFS,
    family_of_legacy,
    targets_of_legacy,
)

# --- shard readers ----------------------------------------------------------


def legacy_tags(word: list) -> set[str]:
    """Every rule a legacy cell row named: the one primary tag it had to pick,
    the per-phoneme tags, and the secondaries that lost the pick."""
    out: set[str] = set()
    for cell in word[5] if len(word) > 5 and word[5] else []:
        if len(cell) > 5 and cell[5]:
            out.add(cell[5])
        for slot in (7, 8):
            if len(cell) > slot and cell[slot]:
                out |= {tag for tag in cell[slot] if tag}
    return out


def new_tags(word: list) -> set[str]:
    """Every rule the replayed cell rows carry. A v11 cell names them in a
    list; anything else is a row the replay did not write."""
    out: set[str] = set()
    for cell in word[5] if len(word) > 5 and word[5] else []:
        if len(cell) > 5 and isinstance(cell[5], list):
            out |= {tag for tag in cell[5] if tag}
    return out


def has_cells(word: list) -> bool:
    """Did the replay write this word's cells? A word the stamper declined
    keeps whatever it held, which is not an answer to compare against."""
    cells = word[5] if len(word) > 5 else None
    return bool(cells) and all(isinstance(c[5], list) for c in cells if len(c) > 5)


def word_text(word: list) -> str:
    return "".join(letter[0] for letter in word[3])


def silence_flips(old_word: list, new_word: list) -> list[str]:
    """The letters whose ``silent`` flag moved, as ``char:was->is``."""
    out = []
    for old, new in zip(old_word[3], new_word[3], strict=True):
        was = bool(old[3]) if len(old) > 3 else False
        now = bool(new[3]) if len(new) > 3 else False
        if was != now:
            out.append(f"{old[0]}:{was}->{now}")
    return out


# --- what the producer says -------------------------------------------------


@dataclass(frozen=True)
class ProducerWord:
    """One word as the producer reads it, in the shard's own coordinates."""

    tokens: list[str]
    rules: list[str]
    partners: frozenset[int]
    #: A merger crosses a waṣl join into this word, from the segment before.
    joined: bool = False


def _mfa_tokens(phonemes) -> list[str]:
    """A display surface's tokens on the aligner's inventory, render-only
    markers dropped -- the space a shard's stored phones live in."""
    from qua_sdk.integrations.phonemizer import DISPLAY_ONLY_TOKENS
    from qua_sdk.integrations.tokens import is_indexable

    return [DISPLAY_ONLY_TOKENS.get(p, p) for p in phonemes if is_indexable(p)]


def _pairing_word(res, pairing, hosts) -> int | None:
    """The word a pairing belongs to, decided as the cell rows decide it."""
    if pairing.glyphs:
        return res.glyphs[pairing.glyphs[0]].word
    for sound in pairing.sounds:
        word = hosts.get(sound)
        if word is not None:
            return word
    return None


def _rules_by_word(res, n_words: int) -> list[list[str]]:
    """Every rule instance the producer fired, per word, named as the producer
    names it -- before the shard vocabulary has had its say."""
    from qua_sdk.integrations.projection import host_word_of_sound

    hosts = host_word_of_sound(res)
    seen: list[set[int]] = [set() for _ in range(n_words)]
    for pairing in res.alignment(text="source", grouping="glyph"):
        if not pairing.rules:
            continue
        word = _pairing_word(res, pairing, hosts)
        if word is not None and word < n_words:
            seen[word].update(pairing.rules)
    return [[res.rules[i].rule.value for i in sorted(indices)] for indices in seen]


def _partners_by_word(res, n_words: int) -> list[frozenset[int]]:
    """The word on the other side of every cross-word merger, per word."""
    from qua_sdk.integrations.projection import mergers

    out: list[set[int]] = [set() for _ in range(n_words)]
    for merger in mergers(res):
        if merger.source_word < n_words and merger.host_word < n_words:
            out[merger.source_word].add(merger.host_word)
            out[merger.host_word].add(merger.source_word)
    return [frozenset(partners) for partners in out]


def producer_view(
    verse_key: str,
    words: list,
    wasl_prev_ref: str | None = None,
    wasl_cont_ref: str | None = None,
) -> list[ProducerWord | None]:
    """One ``ProducerWord`` per shard word, phonemized as the cell stamper does.

    Gap-bounded runs, each on its own ref, so a run's last word stops -- except
    at a waṣl join, where the stamper reads across it and so must this. A
    reciter who never joins a verse to the next hides the difference; one who
    does reads a tanween into the next word's letter and the run's last word
    keeps no iwad.

    A run whose word count disagrees with the shard leaves ``None`` in its
    slots -- the stamper drops that run's cells, which the caller reports as a
    hard failure rather than as a family.
    """
    from qua_sdk.components.timing.lib.cells import _extend_ref, _gap_runs
    from qua_sdk.integrations.phonemizer import result_for_ref
    from qua_sdk.integrations.projection import words as phon_words

    out: list[ProducerWord | None] = [None] * len(words)
    pos = 0
    runs = _gap_runs(words)
    for index, run in enumerate(runs):
        lo, hi = run[0][0], run[-1][0]
        base = f"{verse_key}:{lo}" if lo == hi else f"{verse_key}:{lo}-{verse_key}:{hi}"
        ref, skip = _extend_ref(
            base,
            wasl_prev_ref if index == 0 else None,
            wasl_cont_ref if index == len(runs) - 1 else None,
        )
        res = result_for_ref(ref, display=True)
        whole = phon_words(res)
        phoned = whole[skip : skip + len(run)]
        if len(phoned) == len(run):
            rules = _rules_by_word(res, len(whole))[skip : skip + len(run)]
            partners = _partners_by_word(res, len(whole))[skip : skip + len(run)]
            for i, word in enumerate(phoned):
                # A merger realized on the word appended across the join belongs
                # to the next segment; only this run's partners are ours.
                shifted = frozenset(
                    p - skip + pos for p in partners[i] if skip <= p < skip + len(run)
                )
                joined = any(not skip <= p < skip + len(run) for p in partners[i])
                out[pos + i] = ProducerWord(
                    _mfa_tokens(word.phonemes), rules[i], shifted, joined
                )
        pos += len(run)
    return out


def legacy_buckets(new_words: list) -> list[list[str]]:
    """The per-word phone streams legacy attribution would have produced.

    Legacy hosted the labial idgham on the word before; every other merged
    sound already sat on the word whose letter carries it. Walking forward
    handles a chain of them, where one word both gives and takes.
    """
    out = [[phone[0] for phone in word[4]] for word in new_words]
    for i in range(1, len(new_words)):
        head = new_words[i][4][0] if new_words[i][4] else None
        if head and len(head) > 5 and head[5] == LABIAL_MERGER and out[i]:
            out[i - 1].append(out[i].pop(0))
    return out


# --- classification ---------------------------------------------------------


@dataclass(frozen=True)
class WordView:
    """Everything one word's classification is decided from."""

    ref: str
    text: str
    legacy: set[str]
    current: set[str]
    rules: list[str]
    flips: list[str]
    bucket_moved: bool
    bucket_is_merger: bool
    partner_tags: set[str]
    joined: bool


def classify_word(view: WordView) -> list[Diff]:
    """Every difference on one word, each with the family that owns it."""
    out = [
        Diff("rule", view.ref, view.text, rule, "dropped")
        for rule in view.rules
        if rule in DROPPED_RULES
    ]
    if view.bucket_moved:
        family = "merger_attribution" if view.bucket_is_merger else None
        out.append(Diff("bucket", view.ref, view.text, "phone re-attributed", family))
    out += _silence_diffs(view)
    out += _tag_diffs(view)
    return out


def _silence_reason(flip: str | None) -> str:
    """Why a carrier letter's silence moved. Legacy silenced a waw carrying a
    dagger alif but sounded a yaa doing the same job; the projection is
    consistent where legacy was not."""
    if flip is None:
        return "a carrier letter's silence moved"
    char, _, move = flip.partition(":")  # `char:was->is`
    if move.endswith("->True"):
        return "a carrier letter legacy sounded is greyed"
    if char.startswith(CARRIER_WAW):
        return "the waw carrying a dagger alif is sounded"
    return "a carrier letter legacy greyed is sounded"


def _silence_family(view: WordView, flip: str | None) -> tuple[str, str]:
    """A letter's silence moved because a merger re-hosted its sound, or
    because the projection greys carrier letters where legacy did not."""
    if view.bucket_moved:
        return "merger_attribution", ""
    return "residue", _silence_reason(flip)


def _silence_diffs(view: WordView) -> list[Diff]:
    out = []
    for flip in view.flips:
        family, reason = _silence_family(view, flip)
        out.append(Diff("silence", view.ref, view.text, flip, family, reason))
    return out


def _tag_diffs(view: WordView) -> list[Diff]:
    """A legacy tag is named when the tag it maps to is on the word now; a new
    tag is named when some legacy tag maps to it, or when the producer grew a
    rule legacy had no word for."""
    out: list[Diff] = []
    accounted: set[str] = set()
    for tag in sorted(view.legacy - view.current):
        targets = targets_of_legacy(tag) & view.current
        if targets:
            out.append(Diff("tag", view.ref, view.text, f"-{tag}", family_of_legacy(tag)))
            accounted |= targets
            continue
        family, reason, became = _unpaired_legacy(view, tag)
        out.append(Diff("tag", view.ref, view.text, f"-{tag}", family, reason))
        accounted |= became
    for tag in sorted(view.current - view.legacy - accounted):
        family, reason = _unpaired_new(view, tag)
        out.append(Diff("tag", view.ref, view.text, f"+{tag}", family, reason))
    return out


def _unpaired_legacy(view: WordView, tag: str) -> tuple[str | None, str, set[str]]:
    """A legacy tag whose new name is nowhere on the word: its family, the
    reason, and the new tag it turned into if it turned into one."""
    if tag in LEGACY_SILENCE_TAGS and (view.flips or view.bucket_moved):
        family, reason = _silence_family(view, view.flips[0] if view.flips else None)
        return family, reason, set()
    if view.ref in RESIDUE_REFS:
        return "residue", RESIDUE_REFS[view.ref], set()
    if tag in FIX_REFS.get(view.ref, ()):
        return "fix", FIX_REFS[view.ref][tag], set()
    if tag == "madd_arid_lissukun" and "madd_tabii" in view.current:
        return "fix", "a stop keeps the vowel's own length", {"madd_tabii"}
    return None, "", set()


def _unpaired_new(view: WordView, tag: str) -> tuple[str | None, str]:
    """A new tag no legacy tag maps onto."""
    if tag in NEW_RULE_TAGS:
        return "new_rule", ""
    weight, hiding = FIX_HEAVY_HUM
    if tag == weight and hiding in view.current:
        # Asked before the merger question: a hum's weight has nothing to do
        # with a merger, and a partner carrying tafkheem would claim it.
        return "fix", "the hum a hidden noon leaves before istilaa is heavy"
    if tag in view.partner_tags:
        return "merger_attribution", ""
    if view.joined and tag in MERGER_CELL_TAGS:
        return "merger_attribution", ""
    if tag in FIX_REFS.get(view.ref, ()):
        return "fix", FIX_REFS[view.ref][tag]
    if tag == FIX_QALQALA_AT_STOP and tag not in view.legacy:
        return "fix", "a stop on a qalqala letter legacy left unnamed"
    return None, ""


# --- the scan ---------------------------------------------------------------


def scan_segment(
    old_seg: dict,
    new_seg: dict,
    rep: Report,
    wasl_prev_ref: str | None = None,
    wasl_cont_ref: str | None = None,
    retimed: frozenset[str] = frozenset(),
) -> None:
    """Every difference between one segment before and after the replay."""
    from qua_sdk.integrations.tokens import is_indexable

    verse_key = old_seg["ref"]
    view = producer_view(verse_key, new_seg["words"], wasl_prev_ref, wasl_cont_ref)
    legacy_phones = legacy_buckets(new_seg["words"])
    pairs = zip(old_seg["words"], new_seg["words"], strict=True)
    for pos, (old, new) in enumerate(pairs):
        rep.words += 1
        ref = f"{verse_key}:{old[0]}"
        if (old[1], old[2]) != (new[1], new[2]):
            moved = rep.boundary_retimed if ref in retimed else rep.timing_moved
            moved.append(f"{ref} {(old[1], old[2])} -> {(new[1], new[2])}")
        produced = view[pos]
        if produced is None:
            rep.runs_dropped.append(ref)
            continue
        stored = [phone[0] for phone in new[4] if is_indexable(phone[0])]
        if len(stored) != len(produced.tokens):
            listed = FIX_REFS.get(ref, {}).get("count")
            where = rep.count_fixed if listed else rep.count_moved
            note = f" -- {listed}" if listed else ""
            where.append(
                f"{ref} stored {len(stored)} != producer {len(produced.tokens)}{note}"
            )
            continue
        if not has_cells(new):
            # The stamper refused this word -- its letters do not match the
            # ones the projection writes -- so it carries no reading to sort.
            rep.cells_dropped.append(ref)
            continue
        text = word_text(old)
        if stored != produced.tokens:
            family, reason = _token_family(ref)
            rep.diffs.append(
                Diff("token", ref, text, f"{stored} -> {produced.tokens}", family, reason)
            )
        was = [phone[0] for phone in old[4]]
        rep.diffs += classify_word(
            WordView(
                ref=ref,
                text=text,
                legacy=legacy_tags(old),
                current=new_tags(new),
                rules=produced.rules,
                flips=silence_flips(old, new),
                bucket_moved=was != [phone[0] for phone in new[4]],
                bucket_is_merger=was == legacy_phones[pos],
                partner_tags={
                    tag for p in produced.partners for tag in new_tags(new_seg["words"][p])
                },
                joined=produced.joined,
            )
        )


def _token_family(ref: str) -> tuple[str | None, str]:
    listed = FIX_REFS.get(ref, {})
    if "token" in listed:
        return "fix", listed["token"]
    return None, ""


def wasl_refs(segments: list[dict]) -> list[tuple[str | None, str | None]]:
    """The waṣl-adjacent word refs per segment, as ``annotate_ordered_segments``
    derives them -- the replay reads across a join, so the re-derive must too."""
    from qua_sdk.components.timing.lib.cells import _next_verse_key

    out: list[tuple[str | None, str | None]] = []
    for i, seg in enumerate(segments):
        key = seg["ref"]
        prev_ref = cont_ref = None
        if i > 0 and segments[i - 1].get("wasl"):
            pkey, pwords = segments[i - 1]["ref"], segments[i - 1]["words"]
            if pwords and (pkey == key or _next_verse_key(pkey) == key):
                prev_ref = f"{pkey}:{pwords[-1][0]}"
        if seg.get("wasl") and i + 1 < len(segments):
            nkey, nwords = segments[i + 1]["ref"], segments[i + 1]["words"]
            if nwords and (nkey == key or _next_verse_key(key) == nkey):
                cont_ref = f"{nkey}:{nwords[0][0]}"
        out.append((prev_ref, cont_ref))
    return out


def retimed_joins(before: list[dict], after: list[dict], rep: Report) -> frozenset[str]:
    """The two word refs at each waṣl join whose shared boundary legitimately
    moved, so the first word holds through the ghunnah of a merger that starts
    the second.

    The move is a boundary and not a drift: the pair's outer span is what it
    was and the two words still meet. Where that does not hold the refs are
    left out, and the caller reports the move as a timing failure.
    """
    out: set[str] = set()
    for i, seg in enumerate(after):
        if not seg.get("wasl") or i + 1 >= len(after):
            continue
        prev_old, prev_new = before[i]["words"][-1], seg["words"][-1]
        next_old, next_new = before[i + 1]["words"][0], after[i + 1]["words"][0]
        if (prev_old[1], prev_old[2]) == (prev_new[1], prev_new[2]) and (
            next_old[1],
            next_old[2],
        ) == (next_new[1], next_new[2]):
            continue  # nothing moved here
        held = (prev_old[1], next_old[2]) == (prev_new[1], next_new[2])
        if not held or prev_new[2] != next_new[1]:
            rep.timing_moved.append(
                f"{seg['ref']}:{prev_new[0]} waṣl boundary moved the pair's span"
            )
            continue
        out.add(f"{seg['ref']}:{prev_new[0]}")
        out.add(f"{after[i + 1]['ref']}:{next_new[0]}")
    return frozenset(out)


def scan_doc(doc: dict, rep: Report) -> None:
    from qua_sdk.components.timing.lib.cells import annotate_ordered_segments

    before = copy.deepcopy(doc["segments"])
    joins = wasl_refs(doc["segments"])
    annotate_ordered_segments(
        [(seg["ref"], seg["words"], bool(seg.get("wasl"))) for seg in doc["segments"]]
    )
    rep.shards += 1
    retimed = retimed_joins(before, doc["segments"], rep)
    for (old_seg, new_seg), (prev_ref, cont_ref) in zip(
        zip(before, doc["segments"], strict=True), joins, strict=True
    ):
        scan_segment(old_seg, new_seg, rep, prev_ref, cont_ref, retimed)


def _load(path: Path) -> dict:
    raw = path.read_bytes()
    if path.suffix == ".gz":
        raw = gzip.decompress(raw)
    return json.loads(raw)


def shard_paths(directory: Path, chapters: set[int] | None) -> list[Path]:
    """Every ``<chapter>.json.gz`` / ``<chapter>.shard.json`` in ``directory``."""
    out = []
    for path in sorted(directory.iterdir()):
        stem = path.name.split(".", 1)[0]
        if not stem.isdigit() or not path.name.endswith((".gz", ".json")):
            continue
        if chapters is None or int(stem) in chapters:
            out.append(path)
    return sorted(out, key=lambda p: int(p.name.split(".", 1)[0]))


def scan(directory: Path, chapters: set[int] | None = None) -> Report:
    rep = Report()
    for path in shard_paths(directory, chapters):
        scan_doc(_load(path), rep)
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("shard_dir", help="local directory of frozen shards")
    ap.add_argument("--chapters", default="", help="comma-separated chapters (default: all)")
    ap.add_argument("--max-examples", type=int, default=10, help="examples printed per group")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 — already utf-8 or not reconfigurable
        pass
    logging.basicConfig(level=logging.ERROR, format="%(levelname)s %(name)s: %(message)s")

    chapters = (
        {int(c) for c in args.chapters.split(",") if c.strip()} if args.chapters.strip() else None
    )
    rep = scan(Path(args.shard_dir), chapters)
    if args.json:
        print(json.dumps(to_json(rep), indent=2, ensure_ascii=False))
    else:
        print(render(rep, args.max_examples))
    return 1 if rep.unclassified or rep.hard_failures or count_violations(rep) else 0


if __name__ == "__main__":
    raise SystemExit(main())
