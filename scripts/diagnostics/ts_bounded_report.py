"""What a bounded-equivalence run found, and how it reads.

One ``Diff`` per difference, a ``Report`` that tallies them by family, by kind
and by the reasons declared one at a time, and the check that no count moved in
a direction ``ts_bounded_vocab`` did not allow.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from scripts.diagnostics.ts_bounded_vocab import (
    CELLS_DROPPED,
    CORPUS,
    COUNT_FIXED,
    EXPECTED,
    MEMBERS,
)


@dataclass(frozen=True)
class Diff:
    """One difference, and the family that owns it."""

    kind: str
    ref: str
    text: str
    detail: str
    family: str | None
    reason: str = ""


@dataclass
class Report:
    """Every difference a run turned up, plus the tallies that ride on top."""

    shards: int = 0
    words: int = 0
    diffs: list[Diff] = field(default_factory=list)
    timing_moved: list[str] = field(default_factory=list)
    count_moved: list[str] = field(default_factory=list)
    runs_dropped: list[str] = field(default_factory=list)
    cells_dropped: list[str] = field(default_factory=list)
    boundary_retimed: list[str] = field(default_factory=list)
    count_fixed: list[str] = field(default_factory=list)

    @property
    def unclassified(self) -> list[Diff]:
        return [d for d in self.diffs if d.family is None]

    @property
    def families(self) -> Counter:
        return Counter(d.family for d in self.diffs if d.family)

    @property
    def kinds(self) -> Counter:
        return Counter(d.kind for d in self.diffs)

    @property
    def hard_failures(self) -> int:
        return len(self.timing_moved) + len(self.count_moved) + len(self.runs_dropped)

    def _words_by(self, key) -> Counter:
        """Distinct words per key -- a change can show on one word several times."""
        seen: dict[str, set[str]] = defaultdict(set)
        for diff in self.diffs:
            group = key(diff)
            if group:
                seen[group].add(diff.ref)
        return Counter({group: len(refs) for group, refs in seen.items()})

    @property
    def family_words(self) -> Counter:
        return self._words_by(lambda d: d.family)

    @property
    def kind_words(self) -> Counter:
        return self._words_by(lambda d: d.kind)

    def ledger(self, family: str) -> Counter:
        """Reason -> words carrying it, for a family declared one member at a time."""
        return self._words_by(lambda d: d.reason if d.family == family else None)


def _moved(label: str, got: int, direction: str, expected: int) -> str | None:
    if direction == "exact" and got != expected:
        return f"{label}: {got} != {expected}"
    if direction == "at_most" and got > expected:
        return f"{label}: {got} > {expected}"
    if direction == "at_least" and got < expected:
        return f"{label}: {got} < {expected}"
    return None


def count_violations(rep: Report) -> list[str]:
    """Counts that moved in a direction nobody declared.

    Only asked of a run over the whole declared corpus: a subset has no
    expected count, and a floor read off part of the shards means nothing.
    """
    if (rep.shards, rep.words) != (CORPUS["shards"], CORPUS["words"]):
        return []
    seen = rep.ledger("residue") + rep.ledger("fix")
    checks = [(family, rep.families[family], *rule) for family, rule in EXPECTED.items()]
    checks += [(reason, seen[reason], *rule) for reason, rule in MEMBERS.items()]
    checks.append(("words without cells", len(rep.cells_dropped), *CELLS_DROPPED))
    checks.append(("counts a fix moved", len(rep.count_fixed), *COUNT_FIXED))
    return [row for row in (_moved(*check) for check in checks) if row]


def _hard_assertions(rep: Report, max_examples: int) -> list[str]:
    out = [
        "HARD ASSERTIONS",
        f"  word timings unmoved      {rep.words - len(rep.timing_moved)}/{rep.words}",
        f"  indexable counts agree    {rep.words - len(rep.count_moved)}/{rep.words}",
        f"  runs the stamper kept     {rep.words - len(rep.runs_dropped)}/{rep.words}",
        f"  words that got cells      {rep.words - len(rep.cells_dropped)}/{rep.words}",
    ]
    if rep.count_fixed:
        out.append(
            f"  counts a fix moved        {len(rep.count_fixed)} (listed by ref, with the reading)"
        )
    if rep.boundary_retimed:
        out.append(
            f"  waṣl boundaries retimed   {len(rep.boundary_retimed)} "
            "(outer span held, the words still meet)"
        )
    for label, rows in (
        ("timing moved", rep.timing_moved),
        ("count moved", rep.count_moved),
        ("run dropped", rep.runs_dropped),
        ("no cells", rep.cells_dropped),
    ):
        out += [f"    x {label}: {row}" for row in rows[:max_examples]]
    return out


def _tallies(rep: Report) -> list[str]:
    out = ["", "FAMILIES                differences    words   declared"]
    words = rep.family_words
    for family, count in rep.families.most_common():
        direction, expected = EXPECTED.get(family, ("", 0))
        out.append(f"  {family:20s} {count:11d} {words[family]:8d}   {direction} {expected}")
    kinds = rep.kind_words
    out += ["", "KINDS                   differences    words"]
    for kind, count in rep.kinds.most_common():
        out.append(f"  {kind:20s} {count:11d} {kinds[kind]:8d}")
    out += ["", "DECLARED ONE AT A TIME (words)"]
    for family in ("residue", "fix"):
        for reason, count in rep.ledger(family).most_common():
            direction, expected = MEMBERS.get(reason, ("", 0))
            out.append(f"  {count:8d}  {family}: {reason}  [{direction} {expected}]")
    return out


def render(rep: Report, max_examples: int) -> str:
    out = [
        "=" * 78,
        f"bounded equivalence - {rep.shards} shard(s), {rep.words} word(s)",
        "=" * 78,
        "",
    ]
    out += _hard_assertions(rep, max_examples)
    out += _tallies(rep)
    out += ["", f"UNCLASSIFIED {len(rep.unclassified)}"]
    grouped: dict[tuple[str, str], list[Diff]] = defaultdict(list)
    for diff in rep.unclassified:
        grouped[(diff.kind, diff.detail if diff.kind != "token" else "")].append(diff)
    for key, diffs in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
        out.append(f"  {len(diffs):8d}  {key[0]} {key[1]}")
        out += [f"            {d.ref} {d.text} {d.detail}" for d in diffs[:max_examples]]
    out += [f"  x count: {violation}" for violation in count_violations(rep)]
    return "\n".join(out)


def to_json(rep: Report) -> dict:
    return {
        "shards": rep.shards,
        "words": rep.words,
        "families": dict(rep.families),
        "family_words": dict(rep.family_words),
        "kinds": dict(rep.kinds),
        "kind_words": dict(rep.kind_words),
        "residues": dict(rep.ledger("residue")),
        "fixes": dict(rep.ledger("fix")),
        "timing_moved": rep.timing_moved,
        "count_moved": rep.count_moved,
        "runs_dropped": rep.runs_dropped,
        "cells_dropped": rep.cells_dropped,
        "boundary_retimed": rep.boundary_retimed,
        "count_fixed": rep.count_fixed,
        "count_violations": count_violations(rep),
        "unclassified": [
            {"kind": d.kind, "ref": d.ref, "text": d.text, "detail": d.detail}
            for d in rep.unclassified
        ],
    }
