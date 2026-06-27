# Plan — Waṣl-bridge frontend feature (inspector)

## Context

The waṣl backend campaign is complete: schema **v10** shards (per-occurrence `wasl: true` flag on a segment that continues into the next verse without a stop) are **live in the prod bucket for 22 reciters**, with junction phones + per-character cells already stored in waṣl-correct form. The FE has never consumed the flag — it currently **drops `wasl`** at the type boundary (`SegmentEntry`), so every recitation surface still renders cross-verse continuations as if they were two unrelated stopped verses.

This plan wires the flag through the FE data layer and lands four user-facing waṣl behaviours across the two recitation surfaces. The pipeline already did the hard part (timing/phonemes); the FE only has to **group + render** the bridge — no re-timing.

**Surface topology (mapped):** one shared player `lib/components/player/NowReciting.svelte` (mounted app-wide) composes the **filmstrip** (`recitation-animation/AyahFilmstrip.svelte`) + **teleprompter** (`recitation-animation/LineAnimation.svelte`), shown on both Dashboard and Timestamps tabs. The Timestamps tab additionally renders the **analysis cells** (`tabs/timestamps/components/UnifiedDisplay.svelte`) and **waveform** (`tabs/timestamps/components/TimestampsWaveform.svelte`).

**Design methodology:** built with the repo's `impeccable` skill (run `node .claude/skills/impeccable/scripts/context.mjs` once, then `impeccable craft`/`animate` for the filmstrip motion); in-browser verified with Playwright on real waṣl reciters.

### Decisions locked (from user)
- **Filmstrip merge = dynamic geometry.** Cells animate apart/together **synced to the takes**, paced to the **continuous-glide cursor velocity** (riding the existing repeat-back "back in time" transport). A full **static-vs-dynamic edge-case table** (below) is the spec; statically-merged boundaries never animate apart, dynamic ones do.
- **Analysis cells = display-only context merge.** The bridged verse's cells render as read-only context (so junction tajweed shows across the boundary); editing/loop/validation stay scoped to the focused verse.
- **Waveform = auto-span the whole bridge** — including **peak computation fetched directly over the group span**, and the **random-ayah prewarmer accounting for a cross-verse-group target**.
- **Naming guard:** "bridge" is already taken for cross-word idgham (`PhonemeInterval.bridge`, `RenderedBridge`, `.pause-bridge`, …). All new identifiers use **`wasl` / `waslJunction`**, never `bridge`.
- **Closeout:** `/pr` (audio-repo skill) → 2 Opus review agents post PR comments (concise praise, detailed on bugs/improvements).

---

## Edge-case spec — static vs dynamic (grounded in the 22-reciter v10 corpus)

Corpus reality: **601 static** boundaries vs **2 dynamic**. Static = the ordered pair (verse N adjacent to N+1) bridges in *every* take that crosses it ⇒ render permanently merged, no animation. Dynamic = the pair has *both* a bridging take and a stopping take ⇒ animate join/break, paced to glide.

| # | Case | Class | Filmstrip behaviour | Real example(s) |
|---|------|-------|---------------------|-----------------|
| 1 | Single-take CV (verse recited once, bridges) | **Static** | Permanent gapless mega-cell + always-on connector | `ghraio_2025` 101:6»101:7; `husary_mujawwad` 56:66»56:67 |
| 2 | Multi-verse chain 2+ (3–4 verses) | **Static** | Contiguous mega-group; every internal edge gapless | `abdulwadood` 20:25»26»27»28 (4); 26:46»47»48 (3) |
| 3 | Trailing-partial bridge (leaving take starts mid-verse, `lo>1`) | **Static** | Merged; leading cell width is the partial take | `ghraio` 30:4[10-12]»30:5; `abdulwadood` 2:219[20-26]»2:220; `ghraio` 17:107[16-18]»17:108 |
| 4 | Leading verse repeated, a full take bridges | **Static** | Boundary always bridges → merged; leading cell still holds its repeats (one cell) | `abdulwadood` 20:106»107 (2 takes); 30:4»30:5; 37:34»35 |
| 5 | Lookback then bridge (reciter steps back, strip glides "back in time") | **Dynamic** | Merge re-forms as the bridging take replays; gap eased at glide velocity | `ayman_swed` ch14 (14:2 → back to 14:1[13-16]»14:2); `abdulwadood` ch30 (30:5 → 30:4»30:5) |
| 6 | Same pair bridges in one take, **stops** in another (the showcase) | **Dynamic** | Cells animate together on the bridging take, apart on the stop take | `ayman_swed` ch14 14:1↔14:2; ch8 8:62↔8:63 — *the only 2 in the corpus* |
| 7 | Overlapping consecutive (chain pivot is both `toRef` and `fromRef`) | **Static** | Pivot cell shares both inner edges → one continuous capsule | `abdulwadood` 20:26 & 20:27 (in 25»26»27»28); 26:47 — 118 pivots total |
| 8 | Chain changing count across takes (3 → 2) | **Dynamic** (theoretical) | Per-take chain length is independent; merge reflects the active take's reach | none in corpus — mechanism must handle gracefully |
| 9 | Chapter-edge / no next / unrecited neighbour | n/a | No merge (guarded: you cannot waṣl into an unrecited verse) | last verse of any chapter |
| 10 | v9 shard (no `wasl`) | n/a | Feature no-ops; renders exactly as today | any non-migrated reciter |

**Implementation rule:** the model precomputes, per cell-boundary, `waslNext` (bridges in ≥1 take) and `waslDynamic` (also stops in ≥1 take). Static (`waslNext && !waslDynamic`) ⇒ gap pinned to 0, mega-cell + connector always on, zero per-frame cost. Dynamic ⇒ gap is an animated value in `[0, G]` driven by the live take, eased with the scroll controller's Hermite glide so a join/break travels at the same px/sec as the strip.

---

## A. Data foundation (shared; no UI) — enables all four features

1. **`SegmentEntry.wasl`** — add `wasl?: boolean` to `lib/types/ts-client.ts` (~223). The shard is parsed as raw JSON objects (only `words` rows are positionally decoded), so this single type field is the *entire* decode; absent on v9 ⇒ `undefined` ⇒ no-op (case 10).
2. **`occasions.ts` → `bridgesOutTo`** — add `bridgesOutTo: string | null` to `ChapterOccasion`; one-line back-stamp in the existing loop (a cross-verse waṣl is, by construction, an occasion's last segment continuing into the next occasion). Also compute `waslDynamic` per boundary (a stop-adjacency for the same ordered pair exists in the stream).
3. **New `lib/recitation-data/wasl.ts`** — the reusable `isWaslBridge`/`groupItems` walk from `WASL_FE.md`, pure and shard-level: `chapterWaslJunctions(occasions)` → `WaslJunction[]` ({fromRef, toRef, fromWords, toWords, leaveMs, enterMs}), `isPartialTake(words, verseWordCount)`, and `waslGroupSpan(focusOcc)` → `[startMs, endMs, refs[]]` (the maximal `bridgesOutTo` run containing the focus). `verseWordCount` from the existing `quranRefs.verse_word_counts` store (do not add a third word-count source). Memoize per shard via a `_junctionsByShard` WeakMap (mirror `_occasionsByShard`).
4. **`chapter-words.ts` → `TimeSpan.waslTo`** — thread `bridgesOutTo` through `AssembledVerse` into the LAST word's pushed occurrence as `waslTo?: string` (the target ayahKey); preserve it through the collapse-by-location merge so only the bridging *occurrence* carries it (per-take, case 6).
5. **`recitation-active.ts`** — surface `waslTo` on `SortedInterval` + `ActiveHit` (both `findActiveAt` paths), so the filmstrip and teleprompter read the per-take flag with no per-frame matching.

Tests: `occasions` (`bridgesOutTo` + `waslDynamic` on a `14:1↔14:2` fixture and a v9 no-op fixture), `wasl.ts` (junction walk, partiality, group span), `chapter-words` (`waslTo` on the right occurrence after collapse), `recitation-active` (surfaced both paths).

## B. Filmstrip dynamic merge (`filmstrip-model.ts`, `AyahFilmstrip.svelte`, reuse `filmstrip-scroll.svelte.ts`)

- **Model:** add `waslNext`/`waslDynamic` to `VerseCell` (false on placeholders; target verse is always a present successor since you can't waṣl into an unrecited verse).
- **Static path:** in the `cells` derived, `gapAfter = 0` for `waslNext && !waslDynamic`; render mega-cell capsule (square the touching inner corners, round the outer, drop the shared border, low-alpha wash via `::before` on the left member, kept under `.active`'s tint) + an always-on hairline connector glyph at the boundary. Each cell stays its own `(ayah)`-keyed entity ⇒ repeat-backs, click-seek, needle tracking, next/random-ayah, auto-center untouched.
- **Dynamic path:** `gapAfter` is an animated `gapNow ∈ [0, G]`. Drive it from the live take: track `liveWaslIdx` from `ActiveHit.waslTo` (set in `recitationAt`/`drivePlayback`); when the active take across the boundary is bridging, ease `gapNow→0` (join); when on a stopping take (incl. lookback to it), ease `gapNow→G` (break). **Reuse the scroll Hermite easing** (`filmstrip-scroll.svelte.ts`) so the gap animation velocity matches the glide ruler (`filmstripPxPerSec`) — the merge/break visibly travels with the "back in time" scroll. Connector intensifies (`--border-default`→`--accent` + soft glow) only while the live take bridges.
- **Freeze coexistence:** the waqf-freeze path is silence-driven (`drivePlayback` → `scrollThroughGap`); a waṣl take has no inter-verse silence ⇒ freeze never engages ⇒ continuous flow. A waqf take (incl. the stop take of a dynamic pair) keeps the existing freeze/grey-needle unchanged.
- **Motion/a11y:** all eases honour `prefers-reduced-motion` (instant snap, no travel); the file already computes `reducedMotion`.

Tests/visual: `AyahFilmstrip.wasl.test.ts` (static gapless geometry; connector present; dynamic gap animates; waqf take of a dynamic pair still freezes). Playwright: `abdulwadood` ch20 (4-chain static capsule), `ayman_swed` ch14 (dynamic join/break on lookback).

## C. Teleprompter chaining + marker coloring (`LineAnimation.svelte`)

- **Chain across a live waṣl boundary:** add `pageEndAyahKey` so `ayahEndIdx` can extend to the next verse; in `tick()`, when `hit.waslTo` is set, extend `pageEndAyahKey` + force a re-measure (`pageCount = null`) so verse N+1's words flow onto the same line (overflow then re-pages as today). Suppress the `clearOnAyahEnd` re-page when the crossing equals the waṣl we just chained (track `lastWaslTo`); advance `pageAyahKey` so 3+ chains keep extending. Reading order already places N's words before N+1's.
- **Marker stays static + un-highlighted:** the `۝`+numeral is a `.ra-ayah-marker` span (not `.ra-word`/`.ra-char`), so the sweep flows past it untouched (confirm with a test). When the page spans N and N+1, the marker renders inline between them automatically.
- **(4a) Silence-color the marker on waqf:** mirror the waqf stop-sign mechanism (`sweepDecorators` + `.ra-decorator--waqf`/`waqf-active`). Stamp `data-after-word={i}` on the marker; in `sweepDecorators`, toggle `.marker-pause` when a pause holds on that word (`hit===null && after===lastActive`) — which only happens on a waqf stop (a waṣl crossing has no pause and is already chained past). CSS: `.ra-ayah-marker.marker-pause { color: var(--ra-highlight) }`, transition killed under reduced-motion.

Tests: `LineAnimation.wasl.test.ts` (no clear at a waṣl boundary; marker rendered + un-highlighted; `marker-pause` lights on a waqf pause; 3-chain keeps extending).

## D. Analysis context-merge + waveform auto-span (`UnifiedDisplay.svelte`, `TimestampsWaveform.svelte`, `tabs/timestamps/stores/verse.ts`, `TimestampsTab.svelte`)

- **`assembleWaslGroup` (`ts-source.ts`):** a multi-occasion generalization of `assembleOccasion` over the focus occasion's `bridgesOutTo` chain — one running `share_group` base, concatenated `intervals[]`, words with `phoneme_indices` into the flat list, single span rebased by one `offsetSec`. Each `TsWord.location` keeps its true `"surah:ayah:word"`, so every cell knows its owning verse.
- **Display-only context merge:** keep `loadedVerse` = focus occasion (editing model untouched). Add a parallel `focusWaslGroup: Writable<TsVerseData|null>` (set in the focus-load path when the occasion is part of a chain). `UnifiedDisplay` renders from `focusWaslGroup ?? loadedVerse.data`, tagging blocks whose verse ≠ focus with a dimmed `context` class (click still seeks; loop/validation/cell-edit gated to focus-verse blocks). The merged `words` feed the *existing* idgham bridge lift, so junction tajweed renders across the boundary for free.
- **Waveform auto-span + direct peaks:** when the focus verse is in a waṣl group, set the waveform window to `waslGroupSpan` and **fetch peaks over the whole group span directly** (one `ensureSegmentPeaks`/`ensureChapterPeaks` call over `[groupStart, groupEnd]`, not per-verse). Playhead/zoom math already keys off the window bounds.
- **Random-ayah prewarmer:** where the shuffle/random-ayah target is resolved (`TimestampsFooterLeft.svelte` + the focus-load path) and where the filmstrip prewarms (`onHoverPrewarm`), if the target verse is part of a waṣl group, prewarm/cover the **group span** (via `waslGroupSpan`) so the merged waveform + analysis are ready on land.
- **(4b) End-of-verse dimming on waqf:** waṣl junctions are **gapless** (no pause), so 4b is purely the **waqf** case and is decoupled from the merge. Just **reuse the existing `.in-pause` 0.7 dim**: when the end-of-verse waqf silence plays, dim the analysis view exactly as the existing inter-word pause-dim already does. The only gap today is that pause detection covers *between-word* silences; extend it to the trailing end-of-verse silence so the same effect fires. No new scoped/cross-verse-tagged variant, no merged-words coupling.

Tests: `assembleWaslGroup` (concatenated intervals, share-group offset, rebased span); `UnifiedDisplay.wasl.test.ts` (context blocks dimmed + non-editable; junction tajweed present; end-of-verse waqf silence reuses the existing `.in-pause` dim).

## E. Sequencing, validation, closeout

Build in the order **A → B → C → D**, each independently testable and each a no-op on v9 shards (case 10 is the safety net — "lots of changes at once," so every layer degrades gracefully). After each layer: `npm run build` (`tsc --noEmit && vite build`) + `npm test` (vitest) + lint (`--max-warnings 0`) green.

**In-browser (Playwright + impeccable):** drive both surfaces on `ayman_swed_muallim_tvquran` ch14 (`14:1»14:2`, the dynamic showcase + lookback) and `abdulwadood_haneef_mp3quran` ch20 (4-chain static capsule, ch26 chain-with-retake). Screenshot: the merged mega-cell capsule, the dynamic join/break across a lookback, the chained teleprompter line crossing `۝`, the junction tajweed tile, the auto-spanned waveform, and a waqf pair still freezing the strip + silence-coloring the marker.

**Closeout:** run `/pr` (audio-repo skill) to open the PR off the new worktree (branched from `origin/main`). Then spawn **2 Opus review agents** on the PR diff, each from a distinct angle — (1) data-layer correctness + edge-case/table coverage + graceful v9 degradation + naming-guard (no `bridge` collision); (2) UI/UX/animation craft + glide-pacing fidelity + a11y/reduced-motion + per-frame perf — posting `gh pr comment` reviews: concise for positive feedback, detailed for bugs/code improvements. (Do NOT merge — user reviews.)

---

## Critical files
- **Data:** `lib/types/ts-client.ts` (`SegmentEntry.wasl`); `lib/recitation-data/occasions.ts` (`bridgesOutTo`/`waslDynamic`); new `lib/recitation-data/wasl.ts`; `lib/recitation-data/ts-source.ts` (`assembleWaslGroup`, junction memo); `lib/recitation-animation/chapter-words.ts` + `recitation-active.ts` (`waslTo` thread).
- **Filmstrip:** `lib/recitation-animation/filmstrip-model.ts`, `AyahFilmstrip.svelte`, `filmstrip-scroll.svelte.ts` (reuse easing).
- **Teleprompter:** `lib/recitation-animation/LineAnimation.svelte`.
- **Analysis/waveform:** `tabs/timestamps/components/UnifiedDisplay.svelte`, `TimestampsWaveform.svelte`, `tabs/timestamps/stores/verse.ts`, `tabs/timestamps/TimestampsTab.svelte`, `tabs/timestamps/components/TimestampsFooterLeft.svelte` (prewarmer).

## Out of scope (deferred)
- Full editable analysis merge (Option B) — `assembleWaslGroup` is factored so it's a contained follow-up.
- The `set_is_wasl` materialization fix in the inspector save path; the 12 no-waṣl / legacy-unannotated reciters; model A/B (psil vs qalqala-v2).
