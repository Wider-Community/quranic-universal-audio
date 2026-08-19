# Timestamp shards

The reference for the per-chapter timestamp shard: `reciters/<slug>/timestamps/<chapter>.json.gz`.
One gzipped JSON document per chapter, written by the TS generation job and served as a byte
pass-through. This doc owns the **shard schema** and the four contracts around it (phonemizer, SDK,
MFA aligner, frontend). The job lifecycle, the consumer-side occasion dedup and the serve route live
in [timestamps-job.md](timestamps-job.md).

A shard is not a reading. The reading is the phonemizer's `PhonemizeResult`; a shard is that reading
**projected onto an aligner timeline** — every fact in it is either a timing the aligner measured or
a fact the producer read off the projection and stamped onto those timings.

---

## 1. The document

| Path | `reciters/<slug>/timestamps/<chapter>.json.gz` |
|---|---|
| Writer | `qua_shared/timestamps_shards.py::build_segment_shards` + `gzip_shard` (level 6, `mtime=0` — byte-stable) |
| Model | `qua_shared/schemas/bucket/ts_shard.py` (`TsShardDoc` / `TsShardSegment` / `TsShardWord` / `TsShardCell`) |
| Current version | `SEGMENT_SCHEMA_VERSION = 11` (`qua_shared/timestamps_shards.py`) |

```jsonc
{
  "_meta": { "schema_version": 11, "chapter": 1, "audio_category": "by_surah", /* provenance */ },
  "segments": [
    { "ref": "1:1", "t": [start_ms, end_ms], "words": [ <word tuple>, ... ], "wasl": true },
    ...
  ]
}
```

### `_meta` (`TsShardMeta`, `extra="allow"`)

| Field | Meaning |
|---|---|
| `schema_version` | `SEGMENT_SCHEMA_VERSION` at write time |
| `chapter` | Surah number |
| `audio_category` | `by_surah` / `by_ayah` (the pipeline's `_audio` suffix is stripped by `_normalize_audio_category`) |
| provenance | `padding`, `beam`, `method`, `aligner_model`, `shared_cmvn`, `audio_source`, `created_at`, `phonemizer_version` — copied through from the source `_meta` when present (`_SEGMENT_META_PROVENANCE`) |

Audio routing (`reciter`, `url_template`, `audio_urls`) is deliberately absent: the slug is the path
and the catalog + audio-manifest sidecar are ground truth. `_meta` is the one forward-compat surface
in the document: it is `extra="allow"`, so an unknown key rides through. Everything else is
`extra="forbid"`, and an unknown key at the top level is stripped with a WARNING before validation
(`strip_and_warn`, `TsShardDoc._surface_extras`).

### Segment entry (`TsShardSegment`)

| Slot | Type | Meaning |
|---|---|---|
| `ref` | `str` | Always a single verse `"surah:ayah"`. Cross-verse refs are rejected at build. |
| `t` | `[int, int]` | `[start_ms, end_ms]` of the occurrence |
| `words` | `TsShardWord[]` | The occurrence's words, ascending `word_idx` |
| `wasl` | `bool` | Emitted only when `true`: this occurrence continued into the next without a stop, so its junction word carries wasl (not waqf) phonemes. Absent = waqf. |

Segments are in recitation order (sorted by `t[0]`, tie-broken on `seg_index`). A verse recurs once
per accepted occurrence — every take is kept verbatim.

### Word tuple (`TsShardWord`)

A flat positional tuple, 5 or 6 slots:

| # | Name | Type |
|---|---|---|
| 0 | `word_idx` | `int` (1-based within the verse) |
| 1 | `start_ms` | `int` |
| 2 | `end_ms` | `int` |
| 3 | `letters` | `LetterTiming[]` — the letter row |
| 4 | `phones` | `PhoneTiming[]` — the phone row |
| 5 | `cells` | `CellTiming[]` — the cell row (optional; absent on v3/v4 shards, and on any word the stamper declined) |

### Letter row — `LetterTiming`

`[char, start_ms|null, end_ms|null]` or `[char, start_ms|null, end_ms|null, silent]`.

| # | Name | Meaning |
|---|---|---|
| 0 | `char` | The aligner's own grapheme token, verbatim — the stamper writes only slot 3 |
| 1 | `start_ms` | `null` when the aligner could not place the letter |
| 2 | `end_ms` | `null` likewise |
| 3 | `silent` | `bool`, from schema v4. True when the grapheme produces no audible phoneme at its own position (elided hamzat wasl, the assimilated lam of a sun letter, the otiose tanween alef). A letter that merged into a **vowel** is not one of them — a vowel is nobody's letter, so the letter running into one is the writing of its length and keeps its sound (`_merged_away` in `cellrows.py`); only a letter merging into a consonant yields, that consonant being another letter's, doubled. Absent on v3 rows → `False`. |

Read via `qua_shared/ts_shard_letters.py::parse_letter` / `iter_letters`. Never unpack positionally:
a bare `for char, s, e in letters` broke every publish and cut the day the 4th slot landed.

### Phone row — `PhoneTiming`

`[phone, start_ms, end_ms, ...optional flags]` — heterogeneous and variable-length, so it is typed as
a loose `list`, not a fixed tuple.

| # | Name | Meaning |
|---|---|---|
| 0 | `phone` | The phoneme token **as a shard shows it** (see §6) |
| 1 | `start_ms` | Aligner interval start |
| 2 | `end_ms` | Aligner interval end |
| 3 | `geminate_start` | Aligner geminate-split flag; unused in the segment-array shard, padded `None` |
| 4 | `geminate_end` | Likewise |
| 5 | `bridge_rule` | The cross-word tajweed bridge rule this phone realizes, when it is a merger (`_BRIDGE_SLOT` in `qua_sdk/components/timing/lib/cells.py`) |

The bridge vocabulary is its own namespace (`qua_sdk.integrations.projection.BRIDGE_RULES`): eight
families, and it still splits each noon rule from its tanween twin (`idgham_ghunnah_noon` vs
`idgham_ghunnah_tanween`). The **cell** vocabulary does not. `idgham_mutajanisayn_naqis` is
deliberately not a bridge — it keeps both letters.

---

## 2. The cell row — schema v11

The 6th word slot. One row per written mark, in written order. Read via
`qua_shared/ts_shard_cells.py::parse_cell` / `iter_cells` / `word_cells`; the FE mirror is
`parseShardCell` in `inspector/frontend/src/lib/types/ts-client.ts`.

| # | Name | Type | Meaning |
|---|---|---|---|
| 0 | `chars` | `str` | The canonical source character(s) of this cell; `""` for a fully implicit cell. A shadda is composed into the letter it doubles (`رّ`). |
| 1 | `role` | `CellRole` | `base` / `haraka` / `tanween` / `madd` |
| 2 | `status` | `CellStatus` | `present` / `replaced` / `inserted` / `dropped` |
| 3 | `phoneme_indices` | `int[]` | Word-local indices over the word's **indexable** phones (§7). `[]` = this cell sounds nothing. |
| 4 | `source_letter_index` | `int` | Index into **this word's `letters` row**; `-1` for a fully implicit cell |
| 5 | `rules` | `str[]` | Every rule the producer fired on this grapheme, in the producer's order. Possibly empty. **There is no primary.** |
| 6 | `share_group` | `int \| null` | Cells presenting one sound carry one id, so they highlight together |
| 7 | `phoneme_rules` | `str[][] \| null` | Optional. One rule list per entry of `phoneme_indices`, in that order. Present **only** when the cell's phones do not all name the same thing. |

Slots 0–4 are required (`parse_cell` raises below 5). Slots 5–7 are read defensively and default to
`[]` / `None`. **A reader must ignore any slot past the 8th** — `parse_cell` and `parseShardCell`
both read only the positions they name, which is what keeps a future trailing slot from breaking a
consumer.

`phoneme_rules` exists because a letter can be read as a whole word. `عٓ` says four sounds and only
the hidden noon carries the ikhfaa; drawing `rules` across the cell would light all four. Every rule
in a per-phone list is **also** in `rules`, so a consumer that reads only slot 5 is never told less
than one that reads both (`cellrows.py`, after `_rules_per_phone`).

That union is what makes slot 5 safe to read alone, and what makes it wrong to **paint** alone: a
cell may colour whole only for the rules every one of its phones names, and anything narrower
belongs under the phone that names it. The tanween of `فِسْقًا` is heavy on its fatha and clear on its
noon, so a bar drawn over the glyph would claim both of each; the letters of a spelled-out opening
do the same with the rules of one sound inside their name. The frontend's `cellWideRules`
(`cell-model.ts`) is that intersection, and a cell with no per-phone list is unchanged by it — its
`rules` already are what all its phones name.

Real v11 rows (`10:1` word 1, `الٓر`, letters `ا` / `لٓ` / `ر`, phones
`ʔ a l i f l a: m rˤ aˤ:`):

```jsonc
["ا",  "base", "present", [0,1,2,3,4], 0, [],                             null]
["ل",  "base", "present", [5,6,7],     1, ["madd_lazim","izhar_shafawi"], 0,    [[], ["madd_lazim"], ["izhar_shafawi"]]]
["ٓ",  "madd", "present", [6],         1, ["madd_lazim"],                 0]
["ر",  "base", "present", [8,9],       2, ["madd_tabii","tafkheem"],      null, [["tafkheem"], ["madd_tabii","tafkheem"]]]
```

### `CellRole` (`qua_shared/schemas/bucket/cell_vocab.py`)

| Value | What the glyph is |
|---|---|
| `base` | A consonant, or a written letter that yields a consonant |
| `haraka` | A short vowel mark, or a sukun |
| `tanween` | A tanween mark |
| `madd` | A carrier of a vowel's length — a written madd letter, a dagger alef, a small vowel, a madd sign |

`base` vs `madd` is decided by what the letter yields, not by its script class: a written letter that
yields no consonant is carrying a vowel (`_base_or_madd`), so the yaa of `عَلَىٰ` is `madd`.

### `CellStatus` — what the reading did with the rasm

| Value | Meaning |
|---|---|
| `present` | The rasm wrote it and the reading keeps it |
| `replaced` | Written, and **shown as the letter the reading gives it** — the `أ`/`إ` a reader starting on `ٱ` says, an ibdal hamza, the alef a stop gives a tanween fath, a pausal taa marbuta. `chars` is then the *shown* letter, not the written one. |
| `inserted` | A cell of its own for what the rasm never wrote — an unwritten long vowel (the alef of `ٱللَّه`), the connecting kasra a meeting of two quiescent letters adds |
| `dropped` | Written, and said nothing |

Only `qua_sdk.integrations.vocabulary.REPLACEMENTS` makes a cell `replaced`: the three hamzat-wasl
vowel tags, `ibdal_hamza`, `madd_iwad`, `taa_marbuta_pausal`. Every other place the recited text
differs from the source is the same canonical letter in its canonical shape — a hamza seat written
bare, a maksura written as a yaa — and the shard keeps it as written.

The **letter row stays the rasm** even where the cell shows a different letter: a consumer matching
its own letters against `letters[]` would match nothing if it answered `أ` where it stored `ٱ`. Only
the `silent` flag on that row is the reading's to say.

### The tajweed vocabulary

`rules` and `phoneme_rules` carry the cell tag vocabulary — `TajweedRule` in
`qua_shared/schemas/bucket/tajweed_vocab.py`, 38 values across noon/meem/tanween, madd, heaviness and
qalqala, hamza, other articulations, and what a stop does to the written word. On the wire the
positional row keeps them as open-form `str` so an unknown tag rides through the byte pass-through;
the `TsShardCell` codegen vehicle types them as the enum so the FE registry compiles against it.

---

## 3. The previous schema — v10

A v10 cell row is **not readable as v11**: slot 5 changed type (one tag string → a rule list), so a
shard is re-stamped rather than migrated in place.

| # | Name | v10 type | v11 |
|---|---|---|---|
| 0–4 | `chars`, `role`, `status`, `phoneme_indices`, `source_letter_index` | same | same |
| 5 | `tag` | `str \| null` — the **one primary** rule the producer had to pick | `rules: str[]` |
| 6 | `share_group` | `int \| null` | same |
| 7 | `phoneme_rule_tags` | `list[str \| null] \| None` — one tag (or `None`) per phone, parallel to `phoneme_indices` | `phoneme_rules: str[][] \| None` |
| 8 | `secondary_tags` | `list[str]` — the colourable rules that co-occurred on the grapheme but **lost the single-tag pick** (in practice `["tafkheem"]` on a heavy madd/qalqala cell). Slot 7 is padded `None` when only slot 8 is present. | gone — every rule is in `rules` |

Slots 7 and 8 are what one tag could not carry. v11 deletes slot 8 outright — every rule is in
`rules` now — and keeps slot 7, retyped: one *list* per phone instead of one tag or `None`, and still
written only where the cell's phones do not all name the same thing. `ts_shard_cells._rules` still
reads a bare string at slot 5 as a one-element list, and `parseShardCell` does the same — reading it
as characters would be silent nonsense.

v10 `CellStatus` carried a fifth member, `shortened`, which is not a v11 value: such a cell now falls
to `present` or `dropped` by whether it sounds (`_status` in `cellrows.py`). The word tuple, letter
row, phone row and segment entry are **unchanged** between v10 and v11 (the `wasl` segment flag
itself arrived at v10).

Word/segment shapes a reader must still tolerate, independent of the cell row:

| Absent slot | Shards |
|---|---|
| word slot 5 (`cells`) | v3/v4 — `word_cells()` returns `[]` |
| letter slot 3 (`silent`) | v3 — `parse_letter` defaults `False` |
| segment `wasl` | v9 and earlier — absence means waqf |

---

## 4. Relation to the phonemizer API

The phonemizer (`quranic-phonemizer`, `docs/architecture.md` + `docs/public-api.md` in that repo)
owns **the reading**. It is the single source of truth for every non-timing fact in a shard. The
producer holds a `PhonemizeResult` and reads these surfaces off it:

| Surface | Kind | What the SDK takes from it |
|---|---|---|
| `res.words` | node array | Word identity and start/stop state; the per-word partition of everything below |
| `res.glyphs` | node array | The source script's characters and their `kind` — which decides whether a glyph opens a cell, rides one, or is dropped (§7) |
| `res.rendered` | node array | The recited spelling. A cell that shows a letter the rasm did not write takes its `char` from here (`_read_as`, `_added_glyphs`) rather than guessing one from a sound. |
| `res.units` | node array | Canonical letter positions + vowel state; `unit.word`, `unit.vowel.joined.quality` (which vowel a prosthetic hamza took) |
| `res.sounds` | node array | Performed sounds; `sound.token` is the phone string, `sound.long`, `sound.kind` |
| `res.rules` | node array | `RuleInstance` — `rule`, `source` unit, merger `host`. Mapped to shard tags by `qua_sdk.integrations.vocabulary`. |
| `res.spellings` | edge array | `Supplies` / `Witnesses` / `Decorates` / `Structural` — which unit(s) a glyph spells, which glyph writes a vowel's *length* rather than its quality, which mark decorates which unit |
| `res.attributions` | edge array | `Hosts` (the unit responsible for a sound — the whole word-local index space), `MergedInto` (where a merger sits), `Silent` |
| `res.modifiers` | edge array | `Recolours` / `SetsLength` / `Classifies` — which **sound** a rule names, which is what `phoneme_rules` is built from |
| `res.alignment(text="source", grouping="glyph")` | projection | The producer's main loop. Each pairing gives `glyphs`, `sounds` it owns, `shares`, `rules`, and `silent`. One pairing per source glyph, plus one glyphless pairing per sound no glyph writes — which is what a cell's `inserted` status is read off (`_status`). |
| `res.phonemes()` | projection | The flat token sequence, used to respell and to count stored phones |

The shard is a projection of that graph onto timings: `letters[]` is the source glyph sequence with
timings, `phones[]` is `sounds` with timings, `cells[]` is the alignment between them, and `rules` on
a cell is `res.rules` filtered to the ones this letter's own unit is the source of.

What the shard does **not** carry: the units, the edges, the recited-text alignment, the respelling
blocks, or teaching labels. A consumer needing those phonemizes the ref itself.

---

## 5. Relation to the SDK

Two stages, both in the pinned `qua_sdk` (`packages/sdk/src/qua_sdk/`).

### Producer — `integrations/cellrows.py`

`word_rows(res)` walks `res.alignment(text="source", grouping="glyph")` once and emits both rows per
word, because a cell names the letter it sits on by that letter's position in the letter row.

- `letter_rows(res)` → `[(char, silent), ...]` per word, over the written letters only.
- `cell_rows(res)` → the `CellRow` dataclass rows (the same eight fields as the shard row).
- `flat_map(res)` → `(letters, phonemes)` per sounding letter, for consumers that store a letter row.

`integrations/vocabulary.py` maps a producer rule to its shard tag: `RENAMED` (a noon rule loses its
tanween split, `ghunnah_mushaddadah` → `ghunnah`, `iwad` → `madd_iwad`, …), `DROPPED`
(`lam_qamariyyah`, `tarqeeq`, `fakk_idgham` — each is the *absence* of a rule, not a thing the reader
does), `WASL_START_BY_QUALITY` (one `wasl_start` becomes one of three tags by the vowel the
prosthetic hamza took), `IMPLIED` (`madd_iwad` also implies `madd_tabii`), and `SOURCE_ONLY` /
`CARRIER_ONLY` (which of the two letters a rule names).

### Stamper — `components/timing/lib/cells.py`

`annotate_ordered_segments(seq)` / `annotate_segment_words(...)` mutate a stored shard's word list in
place. Called from `qua_shared/timestamps_pipeline.py` via `annotate_v2_doc` before
`build_segment_shards` writes, and again by `scripts/backfills/backfill_cells.py` to re-stamp a
stored shard.

Five effects, in order:

| Effect | What it writes |
|---|---|
| Silent flags | Letter slot 3 only — the char is never rewritten (`_stamp_silent_flags`) |
| Phone spellings | Phone slot 0, respelt display-side (§6) (`_stamp_phone_tokens`) |
| Bridge tags | Phone slot 5 on each merger phone (`_apply_to_words`, before it re-slices) |
| Re-attribution | Same call: re-slices the segment's flat phones into words by the projection's per-word indexable counts, then recomputes word `start`/`end` |
| Cells | Word slot 5 (`_stamp_cells`) |

**What the stamper will not overwrite.** It never touches a timing the aligner measured. A folded
phone spans exactly the phones it replaces; a merger retime moves only the two boundary words'
`start`/`end`, never a phone interval; `_only_boundaries_move` refuses the whole re-slice unless every
word away from a merger boundary already holds the count it is about to be given. `_stamp_phone_tokens`
respells a phone **only** where the shard and the aligner's own projection already agree on it, so a
phone the producer genuinely disagrees about is left alone and reads as drift.

**When the projection and the stored shard disagree.** The stamper degrades rather than corrupts, and
never silently:

| Disagreement | Scope of the degrade | Log |
|---|---|---|
| Word count differs | The whole gap-bounded run renders without cells | `cell drift: … phonemizer has N word(s), shard has M` |
| A word's stored indexable-phone count differs | **That word alone** — its neighbours keep their cells | `cell drift: … word N stored X … produced Y` |
| The two letter rows cannot be reconciled | That word alone | `cell drift: … stores N letter(s) but the projection writes M` |
| Stored phone count differs from the projection's | The run keeps its stored phones, unrespelt | `phone drift: … kept its stored phones` |
| Letter rows unreconcilable at silence-stamp time | The run keeps whatever silent flags it had | `silence drift: … kept its stored silent flags` |
| Bridges detected but none applied | The segment's attribution is left alone | `bridge drift: … applied 0` |

**Letter-row reconciliation — `components/timing/lib/letter_cut.py`.** The two rows spell the same
word and do not always cut it the same way: the aligner writes a pausal alef and its mark as one
grapheme (`ا۠`) where the projection writes the mark on its own, and the aligner's letter tokens leave
out the annotation marks entirely (`UNWRITTEN` — saktah, the seen over a sad, imala, ishmam, tashil).
`recut(projected, stored)` returns the projected letter indices covered by each stored letter, or
`None` when the two genuinely disagree. `stored_of(cover)` inverts it, and a cell's
`source_letter_index` is remapped through that so it addresses the **shard's own** letter row. A
stored letter is `silent` only where every projected letter it covers is silent.

Segments are stamped over **gap-bounded runs** (`_gap_runs` — a break in `word_idx` or any timing gap,
because the shard is contiguous except at a waqf), so each run's last word is naturally stopping and
stop-sensitive cells (a dropped tanween, `madd_iwad`, `iltiqaa`) resolve at the real waqf. Where a
segment carries `wasl`, the boundary run is extended into the adjacent verse's junction word
(`_extend_ref`) so it phonemizes in continuation form and matches the stored wasl phones.
`share_group` ids are offset per run so they stay unique across a segment.

---

## 6. Relation to MFA

The aligner produces every timing in the shard, and its stored phone tier is in the token set its
**acoustic model was trained on**. A shard shows a richer set. Both are in
`qua_sdk/integrations/phonemizer.py`:

`get_phonemizer(display=…)` holds two lazily-built instances, differing only in the
`extra_phonemes` option set they were constructed with:

| Constant | Value | Surface |
|---|---|---|
| `MFA_EXTRA_PHONEMES` | `("emphatic_fatha",)` | The aligner's inventory. Its acoustic model was trained on labs built with this set and its lexicon is scanned off those labs, so a new symbol here needs retraining. |
| `DISPLAY_EXTRA_PHONEMES` | `MFA_EXTRA_PHONEMES` + `"emphatic_ikhfaa"`, `"tashil"`, `"imala"` | What a shard shows |
| `DISPLAY_ONLY_TOKENS` | `ŋˤ→ŋ`, `ʔ̞→ʔ`, `e:→i:`, `eː→iː` | The tokens those three extras add, and what each collapses back to |

Each display extra is a **pure token substitution of the same length**. The two surfaces are the same
length, phone for phone, so **a phoneme index means the same thing on either** and nothing downstream
is re-indexed: a cell's `phoneme_indices`, a bridge's flat index, and a report's
`phoneme_flat_index` are all in one coordinate space regardless of which surface produced the token.

`components/timing/lib/transforms.py::transform_phonemes` is the one reduction from what a shard shows
to what the aligner was trained on, applied to every phoneme before it reaches a `.lab` file: drop
`Q` (unless the loaded model keeps it — `keep_q_enabled`, model-driven via the `_keep_q` ContextVar or
`QUA_KEEP_Q=1`), apply `DISPLAY_ONLY_TOKENS`, strip the emphatics the model has no phone for
(`rˤ→r`, `aˤ→a`, `lˤ→l`), then split geminates into two identical halves. A display-only colouring
collapses here rather than reaching the lexicon — a collapse is free, retraining is not.
`normalize_phonemes` is the step before it (ASCII `:` → IPA `ː`).

`phonemizer.collapse_to_simple` is a separate, further collapse onto the ASR training-target set (used
for training labs, not for shards).

---

## 7. Tokenization of cells

A word is cut into cells by walking the source alignment one glyph pairing at a time. **A cell is one
written mark**, with the shadda composed into the letter it doubles. The tables are in
`qua_sdk/integrations/cellrows.py`.

| Glyph `kind` | Behaviour | Role taken |
|---|---|---|
| `base`, `vowel_letter` | Opens a cell **and** takes a place in the letter row | `base` (or `madd` when it yields no consonant) |
| `small_vowel` | Opens a cell and takes a place in the letter row | `madd` |
| `haraka`, `sukun` | Opens a cell | `haraka` |
| `tanween` | Opens a cell | `tanween` |
| `madd_sign` | Opens a cell, and is written onto the previous letter's row entry | `madd` |
| `shadda` | **Rides** the cell before it — its chars join that cell, the letter row does not show it separately (a shadda doubles a letter rather than decorating it) | — |
| `silence_sign`, `tajweed_mark` | Ride the cell before them, and are written onto the previous letter's row entry | — |
| `tatweel`, `structural`, `stop_sign` | **Dropped** — a shard writes nothing for the stretch, the word gap, or the sign advising a stop | — |

A riding mark goes to the cell **presenting the sound it evidences** (`_ridden`), not blindly to the
last cell: `وَٱلطُّورِ` writes the damma before the shadda, and the shadda is the taa's. A mark that
evidences no sound at all rides the last cell. A folded mark hands its host the rules naming a sound
that host actually makes, plus any rule naming no sound at all — that one is about the writing, which
is what the mark is (`_borne`).

Two cells exist that no glyph opened:

- `_stretch_unwritten` — a long vowel no letter stretches gets a `madd` cell showing it (the alef of
  `ٱللَّه`, the iwad alef of `مَآءً`). Where the reading put that length on a letter the rasm did write,
  that cell takes the sound instead.
- `_speak_unwritten` — a sound the reading writes a mark for gets a cell of its own (the connecting
  kasra of an `iltiqaa`), and the seat it was taken from loses that index and any rule about it.

### `phoneme_indices`

Word-local indices over the word's **indexable** phones. `qua_sdk/integrations/tokens.py::is_indexable`
defines it: everything except `RENDER_ONLY = {"Q"}`, the qalqala echo. A render-only marker carries no
grapheme, appears in no cell, and takes no place in the index — the shard's phones are grouped into
units (one indexable phone plus any markers trailing it) so the marker rides along with its anchor
through re-attribution. The producer numbers its cells in the projection's own sound space; the
stamper re-expresses them into the shard's indexable space (`idx_map` in `_stamp_cells`), dropping
any index a render-only marker held and taking its per-phone rule entry out with it, so the two lists
stay the same length. The FE mirrors the set as `RENDER_ONLY_PHONES` in
`lib/recitation-data/ts-source.ts` and maps word-local → verse-flat there.

The same coordinate space carries the bridge index and the phone counts the re-slice guard uses. A
phone two cells present keeps one index in each (that is what `share_group` is for).

**Resolving a cell's timing.** Walk the word's `phones`, skip every render-only marker, and take the
`phoneme_indices`-th entries of what is left; the interval is `[min(start), max(end)]` over them. A
cell with `[]` sounds nothing and has no timing of its own.

### `source_letter_index`

An index into **this word's shard letter row**, after the `letter_cut` remap (§5). `-1` on a cell the
rasm wrote nothing for and no letter anchors.

---

## 8. What the frontend derives on its own

Everything in this section is a **presentation choice made in the Inspector**. None of it is in the
shard, and none of it is modelled by the phonemizer — a future reader should not go looking for it in
the reading. Files are under `inspector/frontend/src/tabs/timestamps/utils/`.

### Folding a riding mark onto the letter it is written on

`foldRidingMarks` / `rides` — `cell-special-cases.ts`.

The producer gives a maddah a cell of its own; the letter row writes it on the letter it stretches, so
the FE folds it back. A folded mark's chars, phoneme indices and rules all join the host, and
`mergedPhonemeRules` recomputes the host's per-phone lists as the union per phone. `namedOnce` then
drops `orthographic_silence` from a fully silent folded cell that also carries a rule saying *why* it
is silent (`pausal_alif`), so it does not hover as two answers to one question.

| Case | Rule |
|---|---|
| The maddah `ٓ` (U+0653) | Always rides (`RIDING_MARKS`) |
| The pausal zero `۠` (U+06E0) | Always rides — written on its alef whether or not the reading sounds either |
| A dagger `ٰ` on a carrier | Rides only when it says nothing of its own AND the host is `madd` (`SILENT_MARKS` + `host.role === 'madd'`). A dagger on a bare consonant is not folded — its host is that letter's haraka and the two render side by side. |
| Soundless mark, other cases | A mark with no phoneme indices whose chars are all in `SILENT_MARKS` rides a `madd` host |
| Two carriers of one long vowel (`ىٰ`, `وٰ`) | Ride each other only when both are `madd`, share one non-null `share_group`, and index the same phones |

### Splitting an iqlab cell

`isIqlabCell` / `iqlabNoonSilentBase` / `iqlabTanweenVowel` / `iqlabMiniMeem` — `cell-special-cases.ts`.

The shard carries **one** cell for the converted noon or tanween and ships no mini-meem. The FE splits
it into a muted source grapheme and a synthesized meem that owns the nasal phone, the click/loop
target and the lone iqlab underline.

| Source | Result |
|---|---|
| `role === 'base'` (a quiescent noon) | The `ن` keeps its glyph, surrenders all its phones and its share group, and carries the FE-only tag `iqlab_silent_noon` (tooltip "Iqlab", no badge). The meem takes all the noon's phones and the `MEEM_HI` glyph. |
| `role === 'tanween'` with ≥2 phones | The tanween is reduced to the single haraka the mushaf writes (`FATHATAN→FATHA`, `DAMMATAN→DAMMA`, `KASRATAN→KASRA`) and keeps every phone but the last; the meem takes the last phone. |

Slot choice: the source mark picks `MEEM_HI` (U+06E2, fatha/damma → **above**) or `MEEM_LO` (U+06ED,
kasra → **below**) via `BELOW_MARKS`/`cellSlot`. `cellGlyph` then always **displays** the low-meem
glyph (cleaner than the isolated high one) while `pushSmall` slots and calibrates by the source mark.
The synthesized meem is `status: 'present'`, not `inserted` — the dashed border says "not what the
rasm wrote", which this is not.

### Lifting the iltiqaa-kasra cell into a cross-word bridge

`buildRendered` — `rendered-blocks.ts`; the suppression is the `liftIltiqaa` argument to
`cellGroupsFor`.

A tanween meeting the next word's hamzat wasl inserts a connecting kasra. The FE finds the cell
carrying `iltiqaa_kasra`, lifts it out of word N into a borderless bridge tile before word N+1 — the
kasra glyph on the letter row plus its `i` phoneme on the phoneme row — excludes that phoneme from
word N's inline row, and drops the cell from word N's own letter row. Only fires when the boundary is
not already claimed by a real shard bridge.

Two other bridge kinds are FE-side too. **Cross-verse wasl junctions**: the stamper phonemizes each
segment on its own, so the merger phone realized on the next verse's head carries no `bridge` tag even
though the source cell does. `_unifyWaslShareGroups` re-links the two share groups across the
junction, and `waslJunctions` synthesizes the bridge tile from the source tag. **Pause bridges**: a
positive gap between consecutive words becomes a pause tile carrying the earlier word's waqf mark
(lifted out of its text by `splitWaqf`), or the neutral `||`.

### Which rules colour a cell as a whole

`cellWideRules` — `cell-model.ts`.

```ts
const per = c.phonemeRules;
if (!per || per.length === 0) return c.rules;
return c.rules.filter((tag) => per.every((tags) => tags.includes(tag)));
```

A cell saying several sounds does not colour whole because one of them fires a rule — the tanween of
`فِسْقًا` is heavy on its fatha and clear on its noon, and a bar over the glyph would claim both of
each. Where a cell does not distinguish its phones, `rules` already is what they all name.

Per-phoneme badges are the other half, in `rendered-blocks.ts`: a tanween rule underlines only its
**last** phone (the nasal); a qalqala rule underlines the render-only `Q` echo, not the consonant,
which keeps only its other rules; a cross-word idgham source draws no inline badge because its merger
shows in the bridge tile. `badgesForTags` (`tajweed-rules.ts`) then resolves any tag list into at most
one `base` bar, one `merge` bar, `tafkheem` on top, and a full-cell `border` ring.

### Grouping cells, and what a share group does

`cellGroupsFor` — `cell-model.ts`. Two group kinds:

| Kind | Contents | In-row order |
|---|---|---|
| `base` | A consonant and its short vowel | full cell, then small |
| `vowel` | A long-vowel unit `[diacritic, carrier]`, or a standalone/implicit madd | small, then full — the diacritic precedes the grapheme it pairs with |

A **long-vowel unit is detected by the share group**: `longVowelSG` collects every non-null
`share_group` containing a `madd` carrier, and a haraka in one of those groups leaves its base and
joins the carrier's vowel group (`vowelGroupFor`). So the share group is not only a highlight cue —
it is the structural signal that splits `[base][haraka]` into `[base]` + `[haraka, carrier]`. Its
other jobs: `_shareUnions` gives every member the union interval so co-lit cells light together,
`_nasalUnions` points a merger receiver's own click/loop span at the ghunnah nasal, `idghamGroupTags`
propagates a silent source's idgham underline to its receiver, and `shareGroupRuleTags` makes a
rule-less co-lit partner reportable as the shared rule.

Special group placements, all FE-side: a `madd_iwad` haraka is rendered as a dashed `FATHA` in the
alef's vowel group; a dropped waqf carrier's own fatha rejoins the carrier's group after it instead of
landing on the preceding base; a dropped silah carrier (`هُۥ`/`هِۦ` at waqf) opens a shared silent
vowel group at its haraka. A sukun cell is filtered out and never rendered.

### The phoneme column layout, and `splitPhone`

`_buildColumns` / `splitPhone` — `phoneme-columns.ts`.

Each group is laid out as ordered `GraphemeColumn`s (row 1), and every phoneme is assigned to the
column(s) that sound it (row 2), then packed into clusters spanning those columns:

| Shape | Layout |
|---|---|
| 1 grapheme : 1 sound | Its own column |
| many graphemes : 1 sound (a long vowel, a share group) | The cluster spans the unit's columns and centres across them |
| 1 grapheme : many sounds | Stays in the single column, which widens |
| A silent grapheme | Indexes nothing → empty slot |
| A render-only `Q` no cell indexes | Rides the preceding phoneme's columns |

A vowel group's per-column clusters are then collapsed into one cluster spanning the group, minus any
trailing silent drop, so a normal madd, a madd-iwad, the Allah dagger-alef and an inserted iwad alef
all take the same width for the same sound.

`splitPhone` splits a phone into base + trailing IPA modifier for rendering, and the split is narrow
by design: **only the length marks `ː`/`:` are detached** (rendered as a superscript). The emphatic
`ˤ` is integral to the consonant symbol (`rˤ`, `dˤ`, `sˤ`, `tˤ`, `ðˤ`) and stays in the base.

### Greying

A cell greys when it **sounds nothing and shares nothing**:

```ts
silent = c.phonemeIndices.length === 0 && c.shareGroup == null;   // pushFullGrapheme, cell-model.ts
```

Keyed on the indices, not on a status, so every soundless carrier greys uniformly — the otiose alef,
the carrier a shortening silenced, an elided hamzat wasl, an assimilated sun lam. A merger source with
no phones of its own but a share group is co-lit and stays a normal cell; a silent-but-tagged source
(mutaqaribayn, mutajanisayn) stays grey and still draws its underline and tooltip. The bounded gate
counts the same predicate aggregated per letter — `greyed_letters` (`ts_bounded_equivalence.py`)
greys `source_letter_index` N when *every* cell on it sounds nothing and shares nothing — which is
what lets a greying regression be caught as its own family.

### Everything else the FE owns

Script and visual detail is the renderer's, by design — the producer emits canonical domain only.
`tajweed-script.ts` holds the diacritic codepoints, the open-tanween forms (`U+08F0`–`U+08F2`, chosen
when a `tanween` cell carries `idgham_bi_ghunnah` / `idgham_bila_ghunnah` / `ikhfaa` — izhar keeps the
stacked form), the mini-meem glyphs, and `insertedLengthGlyph` (an inserted alef draws dagger-sized
unless its seat is `replaced`). `tajweed-rules.ts` holds the whole palette, the legend, the silent-rule
tooltip set, and the badge stack order. The qalqala echo's `[start,end]` is folded into its
consonant's cell and letter spans by `_qalqalaEchoIv` so click, loop and tooltip run the consonant and
its bounce as one unit.

---

## 9. How a shard change is policed

`scripts/diagnostics/ts_bounded_equivalence.py` + `scripts/diagnostics/ts_bounded_vocab.py`, driven by
`qua_shared/tests/test_bounded_equivalence.py` (reads its corpus from `QUA_FROZEN_SHARDS`; skips
without it).

**The frozen shards are the oracle.** The gate replays a read-only directory of frozen shards through
the live producer — the same `annotate_ordered_segments` the pipeline runs — and sorts every
difference into a **declared family**. Anything it cannot name exits 1. The producer's vocabulary
changed on purpose, so byte parity is the wrong question; the right one is *is every change one we
named in advance?*

Difference kinds, per word: `tag` (a rule one side names and the other does not), `bucket` (a phone
the re-attribution moved between words), `token` (a stored phone the producer no longer produces),
`silence` (a letter whose `silent` flag moved), plus four cell-row comparisons — `owner` (which letter
each sound is drawn under), `greyed`, `share` (how the share groups partition the word) and `cut`
(what each cell shows).

| Family | Names |
|---|---|
| `rename` | One legacy tag, one new tag, mechanically mapped (`RENAMED_TAGS`) |
| `collapse` | A noon/tanween pair folded onto one cell tag (`COLLAPSED_TAGS`) |
| `new_rule` | An allowlisted tag legacy had no name for (`NEW_RULE_TAGS`) |
| `dropped` | A producer rule the shard vocabulary carries no tag for (`DROPPED_RULES`) |
| `merger_attribution` | A merged sound hosted on the word whose letter carries it |
| `fix` | A listed correction — the ref, what moved, and why the new reading is right (`FIX_REFS`) |
| `residue` | A listed exception with its reason (`RESIDUE_REFS`) |
| `cell_owner` / `cell_greyed` / `cell_share` / `cell_cut` | The four cell-row counts |

Two assertions ride on top and belong to no family (`Report.hard_failures` — `timing_moved`,
`count_moved`, `runs_dropped`); any of them non-empty fails the run outright:

1. **Word timings do not move** — `words[i][1]` / `words[i][2]` stay put for every word, including
   across a merger. This is the whole safety claim of the uniform merger attribution. The one
   exemption is a wasl junction, where the first word legitimately holds through the ghunnah of a
   merger starting the second: `retimed_joins` allows that pair's shared boundary to move only while
   the pair's **outer** span is unchanged and the two words still meet, and books it as
   `boundary_retimed`. Anything else at that join is a timing failure like any other.
2. **Every word's stored indexable-phone count equals the producer's**, so the stamper writes cells
   for each word instead of dropping a run (`count_moved` when it differs; `runs_dropped` when the
   producer returns no word at all). A ref listed in `FIX_REFS` under `count` moves instead to
   `count_fixed` — a correction that legitimately changes a word's phone count — which `DECLARED`
   bounds rather than forbids, alongside `cells_dropped` (words the stamper wrote no cells for).

`DECLARED` in `ts_bounded_vocab.py` keys each measured corpus by its `(shards, words)` shape and holds
each family to `exact` (a mechanical map over a frozen corpus has one right answer) or `at_most` (may
only fall, as a correction lands upstream). **Two reciters are measured**, because one corpus alone
cannot tell a producer change from a segmentation one: the same rule fires in a different waqf context
when runs are cut elsewhere, so a count that moves in one corpus and not the other is the segmentation
talking. A run over a shape not in `DECLARED` reports its counts and asserts nothing.

The rule that follows: **a legitimate producer change edits `ts_bounded_vocab.py` in the same commit
that makes it**, and the commit says which count moved and why. `test_cell_vocab_parity.py`
separately pins `CellRole` / `CellStatus` / `TajweedRule` against the live producer composed with the
SDK's rename map, so the codegen mirrors can never drift.

---

## Key files

| Concern | Files |
|---|---|
| Schema | `qua_shared/schemas/bucket/ts_shard.py`, `cell_vocab.py`, `tajweed_vocab.py` |
| Row accessors | `qua_shared/ts_shard_cells.py`, `qua_shared/ts_shard_letters.py` |
| Build / write | `qua_shared/timestamps_shards.py` (`build_segment_shards`, `gzip_shard`, `SEGMENT_SCHEMA_VERSION`) |
| Producer | `qua_sdk/integrations/{cellrows,vocabulary,tokens,phonemizer,projection}.py` |
| Stamper | `qua_sdk/components/timing/lib/{cells,letter_cut,transforms}.py` |
| Re-stamp | `scripts/backfills/backfill_cells.py`, `scripts/backfills/backfill_bridge_tags.py` |
| Gate | `scripts/diagnostics/ts_bounded_equivalence.py`, `ts_bounded_vocab.py`, `qua_shared/tests/test_bounded_equivalence.py`, `test_cell_vocab_parity.py` |
| FE read | `inspector/frontend/src/lib/types/ts-client.ts` (`parseShardCell`), `lib/recitation-data/ts-source.ts` |
| FE derive | `inspector/frontend/src/tabs/timestamps/utils/{cell-model,cell-special-cases,phoneme-columns,rendered-blocks,tajweed-script,tajweed-rules}.ts` |
| Job / serve / dedup | [timestamps-job.md](timestamps-job.md) |
