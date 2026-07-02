"""Timestamps cell-drift scanner — predict (and explain) the FE "snap" bug.

A Timestamps analysis row renders per-letter/per-phoneme cells from each shard
word's 6th ``cells`` slot. When that slot is empty but the word has phones, the
FE falls back to a synthetic per-letter base and **snaps** every phoneme onto the
first letter's column — and, because the drop is per gap-run, every following word
in the run breaks too.

A run's cells are dropped by the SDK cell-stamper (``qua_sdk …/lib/cells.py
::_stamp_cells``) whenever a word's STORED indexable-phone count (shard slot 4,
the qalqala render-only ``Q`` excluded) disagrees with the phonemizer's per-word
count for that gap-run. So the snap is fully predictable from bucket data + the
current phonemizer — no rendering needed.

This scanner reads every ``reciters/<slug>/timestamps/<ch>.json.gz`` shard on a
bucket, re-derives each gap-run's phonemizer mapping (the SAME call the stamper
uses, so it reflects the CURRENT phonemizer), and for every run whose per-word
counts diverge it reports:

  - WHERE  — chapter:verse:word, with the stored vs phonemizer phone sequence.
  - WHAT   — an inferred divergence TYPE, so a pattern is visible at a glance:
      wasl_ibtida        hamzat-waṣl pronounced at run start (phonemizer adds
                         ``ʔ``+vowel the shard lacks) — ibtidāʾ context
      glide_ibtida       leading ``w``/``j`` glide at run start the shard lacks
      waqf_tail          continuation tail at run end (connecting ḥaraka / tanwīn
                         nasal) the phonemizer drops at waqf — stop context
      waqf_tanwin_madd   tanwīn→nasal (continuation) vs tanwīn→madd-iwaḍ (waqf)
      merger_reattrib    a cross-word merger vowel attributed to a different word
                         (run total preserved; the per-word guard still drops it)
      tafkheem           emphatic/heaviness value change (phonemization domain)
      domain_contextual  interior phoneme change — contextual / special-word
                         pronunciation (e.g. started-on ٱئْتُونِى)
      wordcount          phonemizer vs shard word count differ in the run
      other              unclassified

Because it runs against the CURRENT phonemizer + the CURRENT shards, the same
command is the A/B harness: run it before and after a phonemizer change or a
re-stamp and the drift list shrinks (or moves) exactly where the change bit. A
clean reciter exits 0; any drift exits 1, so it gates CI / verifies a fix.

CLI:
    python scripts/diagnostics/ts_cell_drift.py [--bucket dev|prod]
        [--reciters slugA,slugB | (default: every reciter on the bucket)]
        [--chapters 1,2,46] [--max-examples N] [--json] [-v]

Read-only. Prod is read-only here, so ``INSPECTOR_ALLOW_PROD_BUCKET=1`` is set
automatically for ``--bucket prod``. Needs ``HF_TOKEN`` (env or ``.env``) and a
local ``qua_sdk`` + ``quranic_phonemizer`` (the same pair the TS job stages).
Run from the repo root.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("ts_cell_drift")

_BUCKETS = {
    "dev": "hetchyy/quranic-inspector-bucket-dev",
    "prod": "hetchyy/quranic-inspector-bucket",
}


def _setup_paths_and_env(bucket: str) -> None:
    """Insert repo root + inspector/ on sys.path; pin the bucket; load ``.env``.

    The prod bucket is refused by ``resolve_bucket_repo`` for non-deployed
    processes unless acknowledged; this scanner only ever reads, so it sets the
    acknowledgement automatically for ``--bucket prod``.
    """
    here = Path(__file__).resolve()
    repo = here.parents[2]
    inspector = repo / "inspector"
    if not inspector.is_dir():
        raise SystemExit(f"inspector/ not found at {inspector}")
    sys.path.insert(0, str(inspector))
    sys.path.insert(0, str(repo))

    env_path = repo / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    # Force the bucket backend even when ``.env`` pins ``INSPECTOR_BACKEND=
    # filesystem`` for local fixture dev — this scanner reads real bucket shards.
    os.environ["INSPECTOR_BACKEND"] = "bucket"
    os.environ["INSPECTOR_BUCKET_REPO"] = _BUCKETS[bucket]
    if bucket == "prod":
        os.environ["INSPECTOR_ALLOW_PROD_BUCKET"] = "1"


# ---------------------------------------------------------------------------
# Phone helpers (mirror the SDK's indexable-unit coordinate space)
# ---------------------------------------------------------------------------


def _is_indexable(phone: str) -> bool:
    from quranic_phonemizer import is_render_only

    return bool(phone) and not is_render_only(phone)


# Ikhfāʾ/iqlab tanwīn nasals the phonemizer does NOT tilde-mark (so
# ``is_nasalised`` returns False) but which still signal a continuation liaison
# at a tanwīn — needed so the waqf-tanwīn classification catches e.g. سبقًا (ŋ).
_IKHFA_NASALS = {"ŋ", "ɴ"}


def _is_nasal(phone: str) -> bool:
    from quranic_phonemizer import is_nasalised

    try:
        return bool(phone) and (is_nasalised(phone) or phone in _IKHFA_NASALS)
    except Exception:  # noqa: BLE001 — predicate is best-effort for classification
        return False


_SHORT_VOWELS = {"a", "i", "u", "aˤ", "iˤ", "uˤ"}
_MADD = {"a:", "i:", "u:", "aˤ:", "iˤ:", "uˤ:"}
_GLIDES = {"w", "j"}
_MADD_OF = {"a": "a:", "i": "i:", "u": "u:", "aˤ": "aˤ:", "iˤ": "iˤ:", "uˤ": "uˤ:"}
# Every consonant a tanwīn can surface as at a continuation liaison — the plain
# nūn/mīm (iẓhār), the ikhfāʾ velars, and the tilde idghām/iqlab mergers.
_TANWIN_NASALS = {"n", "m", "ŋ", "ɴ", "m̃", "ñ", "j̃", "w̃"}


def _stored_idx(phones) -> list[str]:
    """The word's indexable phone strings (render-only ``Q`` excluded)."""
    return [ph[0] for ph in (phones or []) if ph and _is_indexable(ph[0])]


def _phon_idx(word_phonemes) -> list[str]:
    return [p for p in word_phonemes if _is_indexable(p)]


def _gap_runs(words: list) -> list[list]:
    """Split a segment's words into runs contiguous in BOTH widx and time —
    identical to ``_stamp_cells``'s gap-run split (a timing gap is a waqf)."""
    runs: list[list] = []
    run: list = []
    for wd in words:
        if run and (wd[0] != run[-1][0] + 1 or wd[1] != run[-1][2]):
            runs.append(run)
            run = []
        run.append(wd)
    if run:
        runs.append(run)
    return runs


# ---------------------------------------------------------------------------
# Divergence classification
# ---------------------------------------------------------------------------


def _emphatic(phones: list[str]) -> bool:
    return any("ˤ" in p for p in phones)


def _classify(stored: list[str], phon: list[str], *, is_first: bool) -> str:
    """Infer the divergence TYPE for one word's stored vs phonemizer phones.

    Shape-driven: a leading/trailing/interior diff against the common prefix +
    suffix maps to a waqf / ibtidāʾ / domain cause. ``is_first`` (run-initial)
    gates the ibtidāʾ cases. ``merger_reattrib`` is decided at run level (it needs
    the neighbour) and never reaches here.
    """
    if stored == phon:
        return "ok"

    cp = 0
    while cp < len(stored) and cp < len(phon) and stored[cp] == phon[cp]:
        cp += 1
    cs = 0
    while cs < len(stored) - cp and cs < len(phon) - cp and stored[-1 - cs] == phon[-1 - cs]:
        cs += 1
    s_mid = stored[cp : len(stored) - cs]
    p_mid = phon[cp : len(phon) - cs]

    # run-start ibtidāʾ — the phonemizer prepends a pronounced hamzat-waṣl
    # (``ʔ``+vowel) or a leading glide the shard lacks. Checked first + by
    # position so it still fires when an interior change co-occurs (ٱلله: the
    # waṣl AND the Allah tafkhīm change together).
    if is_first and len(phon) > len(stored) and phon and (not stored or phon[0] != stored[0]):
        if phon[0] == "ʔ" and len(phon) >= 2 and phon[1] in _SHORT_VOWELS:
            return "wasl_ibtida"
        if phon[0] in _GLIDES:
            return "glide_ibtida"

    # clean leading add: stored is a pure suffix of the phonemizer sequence
    if not s_mid and p_mid and cp == 0:
        if len(p_mid) == 1 and p_mid[0] in _GLIDES:
            return "glide_ibtida"
        if p_mid[0] == "ʔ":
            return "wasl_ibtida"
        return "other"

    # tanwīn at a stop: shard ends ``[short vowel + nasal]`` (continuation
    # liaison), phonemizer ends in the corresponding madd-iwaḍ long vowel (waqf)
    # — e.g. غرقًا ``…aˤ w̃`` vs ``…aˤ:``, غدًا ``…a n`` vs ``…a:``.
    if (
        len(p_mid) == 1
        and len(s_mid) >= 2
        and s_mid[-1] in _TANWIN_NASALS
        and _MADD_OF.get(s_mid[-2]) == p_mid[0]
    ):
        return "waqf_tanwin_madd"

    # shard carries a TRAILING continuation tail the phonemizer drops at waqf
    # (a connecting ḥaraka or a tanwīn nasal)
    if not p_mid and s_mid and cs == 0:
        if all(p in _SHORT_VOWELS for p in s_mid) or any(_is_nasal(p) for p in s_mid):
            return "waqf_tail"
        return "other"

    # equal length, value-only change (emphatic → heaviness / else contextual)
    if len(stored) == len(phon):
        return "tafkheem" if (_emphatic(s_mid) or _emphatic(p_mid)) else "domain_contextual"

    # interior length/value change (contextual / special-word pronunciation)
    if cp > 0 and cs > 0:
        return "domain_contextual"
    return "other"


@dataclass
class WordDrift:
    ref: str  # chapter:verse:word
    widx: int
    text: str
    stored: list[str]
    phon: list[str]
    dtype: str


@dataclass
class RunDrift:
    ref: str  # the gap-run ref handed to the phonemizer
    words: list[WordDrift] = field(default_factory=list)
    word_count_mismatch: bool = False


def _detect_reattrib(pairs: list[tuple[list[str], list[str]]]) -> set[int]:
    """Indices of words whose divergence is a cross-word merger re-attribution:
    word i loses a tail phone X that word i+1 gains at its head (the run total is
    preserved across the pair). Both words are marked."""
    reattrib: set[int] = set()
    for i in range(len(pairs) - 1):
        s_i, p_i = pairs[i]
        s_j, p_j = pairs[i + 1]
        if s_i == p_i and s_j == p_j:
            continue
        # word i: stored has one extra trailing phone vs phonemizer
        if len(s_i) == len(p_i) + 1 and s_i[:-1] == p_i:
            x = s_i[-1]
            # word i+1: phonemizer has that phone at the head, stored doesn't
            if len(p_j) == len(s_j) + 1 and p_j[0] == x and p_j[1:] == s_j:
                reattrib.add(i)
                reattrib.add(i + 1)
    return reattrib


def analyze_run(verse_key: str, run: list, mapping_for_ref) -> RunDrift | None:
    """Compare a gap-run's stored phones against the phonemizer; return a
    ``RunDrift`` if any word diverges (the run's cells would be dropped), else
    ``None``."""
    lo, hi = run[0][0], run[-1][0]
    ref = f"{verse_key}:{lo}" if lo == hi else f"{verse_key}:{lo}-{verse_key}:{hi}"
    try:
        m = mapping_for_ref(ref)
    except Exception as e:  # noqa: BLE001
        log.debug("phonemizer error on %s: %s", ref, e)
        return RunDrift(ref=ref, word_count_mismatch=True)
    pw = m.words
    if len(pw) != len(run):
        return RunDrift(ref=ref, word_count_mismatch=True)

    pairs = [(_stored_idx(wd[4]), _phon_idx(w.phonemes)) for wd, w in zip(run, pw, strict=False)]
    if all(s == p for s, p in pairs):
        return None

    reattrib = _detect_reattrib(pairs)
    drift = RunDrift(ref=ref)
    for i, (wd, w) in enumerate(zip(run, pw, strict=False)):
        s, p = pairs[i]
        if s == p:
            continue
        if i in reattrib:
            dtype = "merger_reattrib"
        else:
            dtype = _classify(s, p, is_first=(i == 0))
        # stored letters can be empty on a broken re-stamp — fall back to the
        # phonemizer's word text so the word stays identifiable in the report
        text = "".join(c[0] for c in (wd[3] or [])) or getattr(w, "text", "")
        drift.words.append(
            WordDrift(
                ref=f"{verse_key}:{wd[0]}",
                widx=wd[0],
                text=text,
                stored=s,
                phon=p,
                dtype=dtype,
            )
        )
    return drift if drift.words else None


# ---------------------------------------------------------------------------
# Per-reciter scan
# ---------------------------------------------------------------------------


@dataclass
class ShardReport:
    chapter: int
    schema_version: int | None
    runs: list[RunDrift] = field(default_factory=list)
    total_words: int = 0
    empty_letter_words: int = 0  # words with no letter rows — a broken re-stamp

    @property
    def has_issue(self) -> bool:
        return bool(self.runs) or self.empty_letter_words > 0


@dataclass
class ReciterReport:
    slug: str
    shards: list[ShardReport] = field(default_factory=list)

    @property
    def n_drift_words(self) -> int:
        return sum(len(r.words) for s in self.shards for r in s.runs)

    @property
    def n_empty_letter_words(self) -> int:
        return sum(s.empty_letter_words for s in self.shards)

    @property
    def drift_chapters(self) -> list[int]:
        return [s.chapter for s in self.shards if s.runs]

    @property
    def empty_letter_chapters(self) -> list[int]:
        return [s.chapter for s in self.shards if s.empty_letter_words]


def scan_reciter(backend, slug: str, chapters: set[int] | None, mapping_for_ref) -> ReciterReport:
    rep = ReciterReport(slug=slug)
    ts_dir = f"reciters/{slug}/timestamps"
    try:
        files = backend.list_dir(ts_dir)
    except Exception as e:  # noqa: BLE001
        log.warning("%s: cannot list %s: %s", slug, ts_dir, e)
        return rep
    shard_files = sorted(
        (f for f in files if f.endswith(".json.gz") and f.split(".", 1)[0].isdigit()),
        key=lambda f: int(f.split(".", 1)[0]),
    )
    for fname in shard_files:
        ch = int(fname.split(".", 1)[0])
        if chapters is not None and ch not in chapters:
            continue
        try:
            doc = json.loads(gzip.decompress(backend.read_bytes(f"{ts_dir}/{fname}")))
        except Exception as e:  # noqa: BLE001
            log.warning("%s ch%d: read/parse failed: %s", slug, ch, e)
            continue
        sv = (doc.get("_meta") or {}).get("schema_version")
        shard = ShardReport(chapter=ch, schema_version=sv)
        for seg in doc.get("segments", []) or []:
            verse_key = seg.get("ref")
            words = seg.get("words", []) or []
            for wd in words:
                shard.total_words += 1
                if not (wd[3] if len(wd) > 3 else []):
                    shard.empty_letter_words += 1
            for run in _gap_runs(words):
                # only bother when the run has a word with phones but no cells
                if not any((len(wd) <= 5 or not wd[5]) and _stored_idx(wd[4]) for wd in run):
                    continue
                d = analyze_run(verse_key, run, mapping_for_ref)
                if d is not None:
                    shard.runs.append(d)
        if shard.has_issue:
            rep.shards.append(shard)
    return rep


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _type_tally(reports: list[ReciterReport]) -> dict[str, int]:
    tally: dict[str, int] = {}
    for rep in reports:
        for s in rep.shards:
            for run in s.runs:
                if run.word_count_mismatch:
                    tally["wordcount"] = tally.get("wordcount", 0) + 1
                for w in run.words:
                    tally[w.dtype] = tally.get(w.dtype, 0) + 1
    return dict(sorted(tally.items(), key=lambda kv: -kv[1]))


def _render(reports: list[ReciterReport], *, max_examples: int) -> str:
    out: list[str] = []
    total_words = 0
    for rep in reports:
        if not rep.shards:
            out.append(f"\n[{rep.slug}]  clean — no cell drift")
            continue
        summary = f"{rep.n_drift_words} drift word(s) in chapters {rep.drift_chapters}"
        if rep.n_empty_letter_words:
            summary += (
                f"  |  BROKEN: {rep.n_empty_letter_words} word(s) with NO letters "
                f"in chapters {rep.empty_letter_chapters}"
            )
        out.append(f"\n[{rep.slug}]  {summary}")
        for s in rep.shards:
            if s.empty_letter_words:
                out.append(
                    f"  ch{s.chapter:>3} sv={s.schema_version}  ✗ STRUCTURAL: "
                    f"{s.empty_letter_words}/{s.total_words} words have empty "
                    f"letter rows (broken re-stamp — renders nothing per-letter)"
                )
            for run in s.runs:
                if run.word_count_mismatch:
                    out.append(
                        f"  ch{s.chapter:>3} sv={s.schema_version}  {run.ref}  "
                        f"✗ WORD-COUNT mismatch (phonemizer ≠ shard)"
                    )
                    continue
                head = f"  ch{s.chapter:>3} sv={s.schema_version}  {run.ref}"
                out.append(head)
                for w in run.words[:max_examples]:
                    total_words += 1
                    out.append(
                        f"      {w.ref:>10} {w.text:<12} [{w.dtype}]\n"
                        f"          stored : {w.stored}\n"
                        f"          phonem.: {w.phon}"
                    )
                extra = len(run.words) - max_examples
                if extra > 0:
                    out.append(f"      … +{extra} more word(s)")
    return "\n".join(out)


def _to_json(reports: list[ReciterReport]) -> dict:
    return {
        "reciters": [
            {
                "slug": rep.slug,
                "drift_words": rep.n_drift_words,
                "drift_chapters": rep.drift_chapters,
                "empty_letter_words": rep.n_empty_letter_words,
                "empty_letter_chapters": rep.empty_letter_chapters,
                "shards": [
                    {
                        "chapter": s.chapter,
                        "schema_version": s.schema_version,
                        "total_words": s.total_words,
                        "empty_letter_words": s.empty_letter_words,
                        "runs": [
                            {
                                "ref": run.ref,
                                "word_count_mismatch": run.word_count_mismatch,
                                "words": [
                                    {
                                        "ref": w.ref,
                                        "text": w.text,
                                        "type": w.dtype,
                                        "stored": w.stored,
                                        "phonemizer": w.phon,
                                    }
                                    for w in run.words
                                ],
                            }
                            for run in s.runs
                        ],
                    }
                    for s in rep.shards
                ],
            }
            for rep in reports
        ],
        "type_tally": _type_tally(reports),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--bucket",
        choices=sorted(_BUCKETS),
        default="dev",
        help="Bucket to scan (default: dev). Prod is read-only here.",
    )
    ap.add_argument(
        "--reciters",
        default="",
        help="Comma-separated slugs (default: every reciter on the bucket).",
    )
    ap.add_argument(
        "--chapters",
        default="",
        help="Comma-separated chapter numbers to limit the scan (default: all).",
    )
    ap.add_argument(
        "--max-examples",
        type=int,
        default=40,
        help="Max diverging words printed per run (default: 40).",
    )
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    ap.add_argument("-v", "--verbose", action="store_true", help="Debug logging.")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 — already utf-8 or a non-reconfigurable stream
        pass
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    _setup_paths_and_env(args.bucket)

    try:
        from qua_sdk.domain.char_cells import mapping_for_ref
    except Exception as e:  # noqa: BLE001
        raise SystemExit(
            f"qua_sdk / quranic_phonemizer not importable ({e}). This scanner needs "
            "the same pair the TS job stages — install them in this environment."
        ) from e

    from services.storage.hf_bucket import get_backend

    backend = get_backend()
    bucket_id = _BUCKETS[args.bucket]

    if args.reciters.strip():
        slugs = [s.strip() for s in args.reciters.split(",") if s.strip()]
    else:
        from services.storage import data_dir

        slugs = sorted(Path(p).name for p in data_dir.list_slugs())

    chapters = (
        {int(c) for c in args.chapters.split(",") if c.strip()} if args.chapters.strip() else None
    )

    reports = [scan_reciter(backend, slug, chapters, mapping_for_ref) for slug in slugs]

    if args.json:
        print(json.dumps(_to_json(reports), indent=2, ensure_ascii=False))
    else:
        print("=" * 78)
        print(f"TS cell-drift scan — bucket={bucket_id}  reciters={len(slugs)}")
        print("=" * 78)
        print(_render(reports, max_examples=args.max_examples))
        tally = _type_tally(reports)
        total = sum(r.n_drift_words for r in reports)
        broken = sum(r.n_empty_letter_words for r in reports)
        n_dirty = sum(1 for r in reports if r.shards)
        print("\n" + "─" * 78)
        print(f"SUMMARY: {total} drift word(s) across {n_dirty}/{len(slugs)} reciter(s)")
        if tally:
            print("  by type: " + "  ".join(f"{k}={v}" for k, v in tally.items()))
        elif not broken:
            print("  no drift — every scanned shard's cells match the phonemizer")
        if broken:
            print(
                f"  STRUCTURAL: {broken} word(s) with empty letter rows "
                "(broken re-stamp — renders nothing per-letter)"
            )

    return 1 if any(r.shards for r in reports) else 0


if __name__ == "__main__":
    raise SystemExit(main())
