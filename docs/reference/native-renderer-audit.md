# Native renderer ownership audit

This is the retained evidence from the temporary native-to-v11 proof project. The proof code and generated logs were deleted after the findings were transferred here and into the v12 corpus audit.

## Corpus

- Nasser production evidence: 114 chapter shards.
- 13,450 recorded segment requests in their recorded join/stop context.
- 84,998 word occurrences.
- 659,073 historical Inspector cell rows.

## Ownership decision

The renderer may own only:

1. iqlab mini-meem glyph synthesis and dormant silencing; and
2. open versus closed/stacked tanween glyph selection.

The native phonemizer owns every other fold, carrier, group, sound placement, rule attribution, merger, and boundary relationship.

## Final native findings

| Finding | Count | Required owner |
| --- | ---: | --- |
| Sukun emitted as a satellite column | 0 | Producer |
| Started hamzat-wasl emitted as bare hamza | 0 | Producer |
| Long-vowel group reconstructed by a consumer | 0 | Producer |
| Long vowel missing an explicit native carrier/group | 0 | Producer |
| Iltiqa sound left inside a word | 0 | Producer boundary |
| Rule edge added from sound to columns by a consumer | 0 | Producer |
| Muanaqah paired by frontend text scan | 0 | Producer boundary |
| Explicit native groups | 375,125 | Producer |
| Explicit native vowel groups | 56,709 | Producer |
| Explicit native merger bridges | 5,844 | Producer |
| Explicit native qalqala echo sounds | 4,555 | Producer |
| Folded maddah columns | 5,917 | Producer |
| Folded pausal-zero columns | 72 | Producer |
| Allowed iqlab visual splits | 581 | Renderer |
| Allowed open-tanween choices | 4,848 | Renderer |

All 39 iltiqa sounds and inserted columns were boundary-owned. Every muanaqah sign encountered in replay had native exclusive-group membership.

## What the discarded adapter proof established

The former shadow adapter reached 99.984% field equality against v11 by reconstructing missing visual decisions before comparison. That was useful evidence that the analysis contained enough information, but it was not the acceptance criterion: raw native cells had to become renderer-ready without an adapter.

Differences that remained in the historical projection were accepted only when native behavior corrected it, including:

- both letters receiving a merger rule;
- native mini-seen/saad variant columns;
- true tashil sound/cell structure;
- correct pausal madd classification;
- native cross-verse merger ownership;
- native muqattaat per-sound attribution.

## Acceptance gate

The native projection was accepted only after:

- zero missing/fallback ownership findings across the full corpus;
- producer partition, rule-placement, and boundary tests passed;
- the package contained no rule-specific transform beyond the two approved visual policies;
- stable-layout geometry had zero known movers;
- the established hard references passed manual light/dark review.

The Inspector v12 migration relies on this stronger contract. It parses the native documents with `@quranic-phonemizer/cells`; it does not carry forward the proof adapter or its vocabulary.
