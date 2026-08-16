"""The bounded-equivalence gate: its classifier, its mirrors, and the corpus run.

Three tiers, so the parts that can run anywhere do:

  - the classifier is pure, so every family is exercised on synthetic words with
    neither the producer nor a shard present;
  - the declared vocabulary is a mirror of the producer's, so ``needs_producer``
    tests compose the live one and assert they agree (as
    ``test_cell_vocab_parity`` does for the shard tag enums);
  - the corpus run needs the frozen shards, which are not committed. Point
    ``QUA_FROZEN_SHARDS`` at a local directory of them and the gate runs for
    real; without it that test skips.

    QUA_FROZEN_SHARDS=/path/to/shards python -m pytest qua_shared/tests/test_bounded_equivalence.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.diagnostics import ts_bounded_equivalence as gate
from scripts.diagnostics import ts_bounded_vocab as vocab


def _has_producer() -> bool:
    try:
        import quranic_phonemizer  # noqa: F401
        from qua_sdk.integrations import vocabulary  # noqa: F401
    except ImportError:
        return False
    return True


needs_producer = pytest.mark.skipif(
    not _has_producer(), reason="phonemizer / qua_sdk not installed"
)

_SHARDS = os.environ.get("QUA_FROZEN_SHARDS", "")
needs_shards = pytest.mark.skipif(
    not (_SHARDS and Path(_SHARDS).is_dir()),
    reason="QUA_FROZEN_SHARDS is not a local directory of frozen shards",
)


def _view(**over) -> gate.WordView:
    base = dict(
        ref="1:1:1",
        text="بسم",
        legacy=set(),
        current=set(),
        rules=[],
        flips=[],
        bucket_moved=False,
        bucket_is_merger=False,
        partner_tags=set(),
        joined=False,
    )
    return gate.WordView(**{**base, **over})


def _families(view: gate.WordView) -> list[str | None]:
    return [d.family for d in gate.classify_word(view)]


# --- the classifier, on synthetic words ------------------------------------


def test_rename_pairs_a_legacy_tag_with_its_new_name():
    view = _view(legacy={"hamza_wasl_silent"}, current={"hamza_wasl_elision"})
    assert _families(view) == ["rename"]


def test_collapse_folds_a_noon_tanween_pair_onto_one_tag():
    for legacy in ("ikhfaa_noon", "ikhfaa_tanween"):
        assert _families(_view(legacy={legacy}, current={"ikhfaa"})) == ["collapse"]


def test_the_wasl_hamza_answers_to_the_vowel_it_takes():
    view = _view(legacy={"hamza_wasl_vowel"}, current={"hamza_wasl_kasra"})
    assert _families(view) == ["rename"]


def test_new_rule_names_a_tag_legacy_had_no_word_for():
    assert _families(_view(current={"pausal_sukun"})) == ["new_rule"]


def test_dropped_names_a_producer_rule_no_cell_carries():
    view = _view(rules=["lam_qamariyyah", "madd_tabii"])
    assert _families(view) == ["dropped"]


def test_a_merged_sound_names_both_letters():
    """The rule reaches the word that gave the letter up and the one that hosts
    it, so a tag the partner carries is the merger's, not a new rule."""
    view = _view(current={"idgham_bi_ghunnah"}, partner_tags={"idgham_bi_ghunnah"})
    assert _families(view) == ["merger_attribution"]


def test_a_merger_moves_a_letters_silence_and_its_phone():
    view = _view(bucket_moved=True, bucket_is_merger=True, flips=["م:False->True"])
    assert _families(view) == ["merger_attribution", "merger_attribution"]


def test_a_carrier_letter_moving_its_silence_is_a_declared_residue():
    diffs = gate.classify_word(_view(flips=["و:True->False"]))
    assert [d.family for d in diffs] == ["residue"]
    assert diffs[0].reason in vocab.MEMBERS


def test_a_listed_correction_is_a_fix():
    view = _view(ref="89:4:3", legacy={"tafkheem"}, current=set())
    diffs = gate.classify_word(view)
    assert [d.family for d in diffs] == ["fix"]
    assert diffs[0].reason in vocab.MEMBERS


def test_a_bucket_move_that_is_not_a_merger_is_unclassified():
    assert _families(_view(bucket_moved=True, bucket_is_merger=False)) == [None]


def test_an_undeclared_tag_is_unclassified():
    """The gate's whole point: a rule nobody named fails rather than passes."""
    assert _families(_view(current={"invented_rule"})) == [None]
    assert _families(_view(legacy={"invented_rule"})) == [None]


def test_legacy_buckets_undo_a_chain_of_labial_mergers():
    """Two idgham shafawi in a row: the middle word both gives and takes."""

    def word(*phones):
        return [0, 0, 0, [], list(phones)]

    words = [
        word(["k", 0, 1], ["u", 1, 2]),
        word(["m̃", 2, 3, None, None, "idgham_shafawi"], ["i", 3, 4]),
        word(["m̃", 4, 5, None, None, "idgham_shafawi"], ["a", 5, 6]),
    ]
    assert gate.legacy_buckets(words) == [["k", "u", "m̃"], ["i", "m̃"], ["a"]]


# --- shard readers ----------------------------------------------------------


def test_legacy_tags_read_every_slot_a_legacy_cell_used():
    word = [
        1,
        0,
        10,
        [],
        [],
        [
            ["ن", "base", "present", [0], 0, "ikhfaa_noon", None],
            ["ا", "madd", "present", [1], 1, "madd_tabii", None, ["madd_lazim"], ["tafkheem"]],
        ],
    ]
    assert gate.legacy_tags(word) == {"ikhfaa_noon", "madd_tabii", "madd_lazim", "tafkheem"}


def test_new_tags_read_the_seven_slot_rule_list():
    word = [1, 0, 10, [], [], [["ا", "madd", "present", [1], 1, ["madd_lazim", "tafkheem"], None]]]
    assert gate.new_tags(word) == {"madd_lazim", "tafkheem"}


# --- the declared tables hold together --------------------------------------


def _declared_targets() -> set[str]:
    targets = set(vocab.RENAMED_TAGS.values()) | set(vocab.COLLAPSED_TAGS.values())
    return targets | vocab.WASL_VOWEL_TAGS | vocab.NEW_RULE_TAGS | {vocab.FIX_QALQALA_AT_STOP}


def test_no_legacy_tag_is_named_twice_or_maps_to_itself():
    both = set(vocab.RENAMED_TAGS) & set(vocab.COLLAPSED_TAGS)
    assert not both, f"named in two tables: {sorted(both)}"
    for table in (vocab.RENAMED_TAGS, vocab.COLLAPSED_TAGS):
        assert not [k for k, v in table.items() if k == v]


def test_every_family_the_classifier_emits_has_a_declared_count():
    """A family with no row in ``EXPECTED`` would grow unwatched."""
    emitted = {
        "rename",
        "collapse",
        "new_rule",
        "dropped",
        "merger_attribution",
        "fix",
        "residue",
    }
    assert set(vocab.EXPECTED) == emitted


def test_every_listed_reason_has_a_declared_count():
    """Every reason a difference can be filed under is one `MEMBERS` bounds.

    A `count` reason is not one of them: it explains a word the hard assertion
    would otherwise fail on, and `COUNT_FIXED` bounds those instead.
    """
    listed = {
        reason for tags in vocab.FIX_REFS.values() for key, reason in tags.items() if key != "count"
    }
    listed |= set(vocab.RESIDUE_REFS.values())
    assert listed <= set(vocab.MEMBERS), f"undeclared: {sorted(listed - set(vocab.MEMBERS))}"


def test_a_count_a_fix_moved_is_listed_by_ref_and_bounded():
    assert "count" in vocab.FIX_REFS["10:15:11"]
    assert vocab.COUNT_FIXED[0] == "at_most"


# --- the declared tables mirror the producer's ------------------------------


def _live_shard_tags() -> set[str]:
    """Every tag the producer can put in a cell's ``rules`` list."""
    from qua_sdk.integrations import vocabulary
    from quranic_phonemizer import tajweed_rules

    live = set()
    for rule_id, _en, _ar in tajweed_rules("hafs"):
        if rule_id in vocabulary.DROPPED:
            continue
        if rule_id == "wasl_start":
            live |= set(vocabulary.WASL_START_BY_QUALITY.values())
            continue
        live.add(vocabulary.RENAMED.get(rule_id, rule_id))
    return live


@needs_producer
def test_dropped_rules_mirror_the_sdk_vocabulary():
    from qua_sdk.integrations.vocabulary import DROPPED

    assert vocab.DROPPED_RULES == DROPPED


@needs_producer
def test_implied_tags_mirror_the_sdk_vocabulary():
    """Inverted: the gate asks which tag carries a new one, the producer which
    tag a cell's own name brings with it."""
    from qua_sdk.integrations.vocabulary import IMPLIED

    assert vocab.IMPLIED_TAGS == {added: by for by, added in IMPLIED.items()}


@needs_producer
def test_every_declared_target_is_a_tag_the_producer_writes():
    live = _live_shard_tags()
    assert _declared_targets() <= live, f"not shard tags: {sorted(_declared_targets() - live)}"


@needs_producer
def test_no_legacy_name_is_also_a_current_one():
    """A legacy tag in the rename/collapse tables must be gone, or the gate
    would be mapping a name the producer still writes."""
    legacy = set(vocab.RENAMED_TAGS) | set(vocab.COLLAPSED_TAGS) | {vocab.LEGACY_WASL_VOWEL}
    live = _live_shard_tags()
    assert not legacy & live, f"still current: {sorted(legacy & live)}"


# --- the waṣl join ----------------------------------------------------------


def _joined(ref: str, wasl: bool, words: list[tuple[int, int, int]]) -> dict:
    """A segment shaped as a shard writes it: ``[widx, start, end, letters, phones]``."""
    return {
        "ref": ref,
        "wasl": wasl,
        "words": [[widx, start, end, [], []] for widx, start, end in words],
    }


def test_a_bridge_tag_arriving_across_a_join_is_re_attribution():
    """The merger's other side is the previous segment's last word, which this
    scan cannot reach, so the join itself is what names the reason."""
    view = _view(current={"idgham_bi_ghunnah"}, joined=True)
    assert _families(view) == ["merger_attribution"]
    # ...and without the join there is nothing to explain it.
    assert _families(_view(current={"idgham_bi_ghunnah"})) == [None]


def test_the_wasl_boundary_may_move_when_the_pair_still_spans_the_same_time():
    """A head merger at a join holds its ghunnah on the word before, which moves
    the boundary between the two and nothing else."""
    before = [_joined("2:1", True, [(1, 0, 100)]), _joined("2:2", False, [(1, 100, 300)])]
    after = [_joined("2:1", True, [(1, 0, 180)]), _joined("2:2", False, [(1, 180, 300)])]
    rep = gate.Report()
    retimed = gate.retimed_joins(before, after, rep)
    assert retimed == {"2:1:1", "2:2:1"}
    assert rep.timing_moved == []


def test_a_join_that_moves_the_pair_s_span_is_still_a_failure():
    before = [_joined("2:1", True, [(1, 0, 100)]), _joined("2:2", False, [(1, 100, 300)])]
    after = [_joined("2:1", True, [(1, 0, 180)]), _joined("2:2", False, [(1, 180, 400)])]
    rep = gate.Report()
    assert gate.retimed_joins(before, after, rep) == frozenset()
    assert rep.timing_moved


@needs_producer
def test_wasl_refs_link_a_segment_to_the_word_across_the_join():
    segments = [
        _joined("2:1", True, [(1, 0, 100), (2, 100, 200)]),
        _joined("2:2", False, [(1, 200, 300)]),
    ]
    assert gate.wasl_refs(segments) == [(None, "2:2:1"), ("2:1:2", None)]


@needs_producer
def test_a_segment_that_does_not_continue_links_nothing():
    segments = [
        _joined("2:1", False, [(1, 0, 100)]),
        _joined("2:2", False, [(1, 200, 300)]),
    ]
    assert gate.wasl_refs(segments) == [(None, None), (None, None)]


# --- the corpus run ---------------------------------------------------------


@pytest.fixture(scope="module")
def corpus():
    """One replay of the whole corpus, shared by the four questions asked of
    it -- a scan re-phonemizes every shard and is minutes, not seconds."""
    return gate.scan(Path(_SHARDS))


@needs_producer
@needs_shards
def test_every_difference_over_the_frozen_corpus_has_a_family(corpus):
    assert corpus.words, "no shards read"
    assert not corpus.unclassified, [
        (d.kind, d.ref, d.text, d.detail) for d in corpus.unclassified[:20]
    ]


@needs_producer
@needs_shards
def test_word_timings_do_not_move_across_the_replay(corpus):
    assert corpus.timing_moved == []


@needs_producer
@needs_shards
def test_every_word_keeps_the_indexable_count_the_stamper_derives(corpus):
    assert corpus.count_moved == []
    assert corpus.runs_dropped == []


@needs_producer
@needs_shards
def test_family_counts_moved_in_no_undeclared_direction(corpus):
    assert gate.count_violations(corpus) == []
