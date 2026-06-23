<script lang="ts">
    /**
     * UnifiedDisplay — the analysis-mode view for the Timestamps tab.
     *
     * Structure is rendered declaratively via `{#each}` from the `$loadedVerse`
     * store. Per-frame highlights (current word / phoneme / letter) are applied
     * imperatively via `updateHighlights()` — the caller invokes this from the
     * per-frame animation loop, avoiding a reactive re-render at 60fps.
     *
     * Hybrid pattern: Svelte `{#each}` owns structure (words, letter rows,
     * phoneme rows); `bind:this` gives us the container; `querySelectorAll`
     * pulls elements to apply `.active` / `.past` classList imperatively.
     * Scoped styles use `:global()` selectors for the dynamic classes.
     */

    import { onDestroy, tick, untrack } from 'svelte';
    import { get } from 'svelte/store';

    import { ensureDashCovering } from '../../../lib/playback/dash-covering';
    import { dashPort } from '../../../lib/playback/dash-port';
    import type { PhonemeInterval, TsCell, TsWord } from '../../../lib/types/ts-client';
    import { splitWaqf } from '../../../lib/utils/waqf';
    import { harakaRenderStyle } from '../utils/haraka-render';
    import {
        ALEF_MAKSURA,
        cellGlyph,
        cellSlot,
        DAGGER,
        DAMMA,
        FATHA,
        firstMark,
        implicitMaddGlyph,
        IQLAB_FORM,
        KASRA,
        OPEN_TANWEEN,
        OPEN_TANWEEN_TAGS,
        SUKUN,
    } from '../utils/tajweed-script';
    import { waqfRenderStyle } from '../utils/waqf-render';
    import {
        showLetters,
        showPhonemes,
        showTranslations,
        tsHoveredElement,
        tsWaveformHoverTime,
        verseTranslations,
    } from '../stores/display';
    import type { TsLoopTarget } from '../stores/playback';
    import { loopTarget } from '../stores/playback';
    import { loadedVerse } from '../stores/verse';
    import { TS_CLICK_DELAY_MS } from '../utils/constants';
    import WordTranslation from './WordTranslation.svelte';

    /** Rub-el-hizb (۞ U+06DE) and place-of-sajdah (۩ U+06E9) — section markers,
     *  not recited; stripped from the analysis word box so the cell shows only the
     *  recited text. */
    const NON_RECITED_SIGNS = /[\u06de\u06e9]/g;

    // ---- Local structural state (derived declaratively from loadedVerse) ----

    /** A FULL letter-sized cell in the letter row — a `base` consonant/carrier or
     *  an implicit `madd` (Allah dagger-alef / madd-ʿiwaḍ alef). A base cell is
     *  the interactive "letter" element: it carries the LETTER's full [start,end]
     *  (for click/dblclick/hover/loop) AND its own phoneme-interval [cellStart,
     *  cellEnd] (for per-frame highlight — the base lights on its consonant). */
    interface RenderedFull {
        glyph: string;
        silent: boolean;
        status: string;
        tag: string | null;
        /** Implicit madd (chars==='') — rendered with the inserted/replaced glow. */
        implicit: boolean;
        /** True for a `base` cell (the interactive letter target). */
        isBase: boolean;
        /** Highlight interval from the cell's own phoneme indices (+share union). */
        cellStart: number | null;
        cellEnd: number | null;
        /** The LETTER's full [start,end] for click/dblclick/hover/loop. */
        letterStart: number | null;
        letterEnd: number | null;
        /** Untimed letter (no per-letter timing) → never highlighted, inert. */
        isNull: boolean;
        /** Rendered-letter index this base cell maps to (loop-highlight identity). */
        letterIndex: number;
        shareGroup: number | null;
    }

    /** A SMALL diacritic cell — haraka / tanween (incl. iqlab fused mini-meem,
     *  inserted graphemeless vowels). Pins top or bottom of the group's letter
     *  row. Sukūn cells are filtered out upstream and never become one of these. */
    interface RenderedSmall {
        /** The combining mark(s) to render — a single haraka/tanwīn, or for iqlab
         *  the single short-vowel + its mini-meem composed in one DK glyph. */
        glyph: string;
        slot: 'top' | 'bottom';
        status: string;
        tag: string | null;
        cellStart: number | null;
        cellEnd: number | null;
        shareGroup: number | null;
        /** Per-glyph centring style string (`--haraka-*`). */
        renderStyle: string;
        /** inserted graphemeless vowel (hamza-waṣl / iltiqaa) — affordance only. */
        inserted: boolean;
    }

    /** A rendered cell-group. `kind` drives the in-row order:
     *  - `base`  : a consonant (+ its short haraka/tanwīn) → full THEN small.
     *  - `vowel` : a long-vowel unit [diacritic + carrier] (base lives in its own
     *    separate group) or a standalone/implicit madd → small THEN full, so the
     *    diacritic precedes the vowel grapheme it pairs with.
     *  Gap 0 within a group, non-zero between groups. */
    interface RenderedGroup {
        kind: 'base' | 'vowel';
        full: RenderedFull[];
        small: RenderedSmall[];
        shareGroup: number | null;
    }

    /** The folded letter view of `word.letters` — one entry per rendered letter
     *  (the ىٰ fold collapses two source letters into one), each carrying the
     *  glyph + per-letter timing + silent flag a `base` cell reads from. */
    interface FoldedLetter {
        glyph: string;
        silent: boolean;
        start: number | null;
        end: number | null;
        isNull: boolean;
        srcIndices: number[];
    }

    interface RenderedPhoneme {
        interval: PhonemeInterval;
        /** Flat interval index (for highlight matching + click seek). */
        index: number;
    }

    interface RenderedBridge {
        phonemes: RenderedPhoneme[];
        /** iltiqaa connecting-kasra letter cell — the kasra char lifted onto the
         *  letter row of a borderless bridge; null for an idgham merger (which
         *  bridges only the phoneme row). */
        letter: {
            glyph: string;
            style: string;
            cellStart: number | null;
            cellEnd: number | null;
            wordIndex: number;
        } | null;
    }

    /** A detected silence between this block and the previous one. Sits as a small
     *  cell between the two words; carries the previous word's lifted-out waqf
     *  (stop) mark, or null → the neutral pause icon. Lights while its silence
     *  plays; dims the rest of the row to 70%. */
    interface RenderedPauseBridge {
        mark: string | null;
        startSec: number;
        endSec: number;
    }

    interface RenderedBlock {
        word: TsWord;
        wordIndex: number;
        /** Word text to render — the previous-word's waqf mark is stripped here
         *  when a following pause surfaces it into the pause bridge. */
        displayText: string;
        /** Ordered cell-groups (base + its trailing diacritics) — the single
         *  source for the analysis letter row. */
        groups: RenderedGroup[];
        phonemes: RenderedPhoneme[];
        /** Optional cross-word (idgham) bridge to render before this block. */
        bridge: RenderedBridge | null;
        /** Optional pause bridge to render before this block. */
        pauseBridge: RenderedPauseBridge | null;
    }

    // Container ref used for imperative highlight updates.
    let rootEl: HTMLDivElement;

    // Reactive: rebuild rendered structure whenever loadedVerse changes. Bridges
    // are baked into the shard (each merger phone carries a ``bridge`` rule), so
    // there's nothing async to wait for — buildRendered just lifts the tagged
    // phones into gold bridge tiles.
    $: rendered = buildRendered(
        $loadedVerse?.data.words ?? [],
        $loadedVerse?.data.intervals ?? [],
    );

    // Reset previous-index cache when structure changes (new verse, etc.)
    $: rendered, (_prevActiveWordIdx = -1);
    $: rendered, (_prevActivePhonemeIdx = -1);
    // Clear stale highlight classes on verse change. The keyed `{#each}` reuses
    // DOM nodes whose `block.wordIndex` matches across verses (typically 0,1,2…),
    // so without this the prior verse's `.active`/`.past` classes survive on
    // reused nodes until the next rAF tick. Between auto-next pause-and-flush
    // and the new audio's `play` event the rAF loop is stopped, so the user
    // sees the stale highlight pinned on the old word until playback resumes.
    $: rendered, _resetHighlightClasses();
    // Measure a real full letter cell after each structural render so the small
    // diacritic cells (sized as a factor of --letter-cell-w/h) track the actual
    // letter box at the current zoom. tick() waits for the DOM to flush.
    $: rendered, untrack(() => void tick().then(() => { _measureLetterCell(); _rebuildHighlightCache(); }));
    function _measureLetterCell(): void {
        if (!rootEl) return;
        const sample =
            rootEl.querySelector<HTMLElement>('.mega-letter:not(.implicit):not(.null-ts)')
            ?? rootEl.querySelector<HTMLElement>('.mega-letter');
        if (!sample) return;
        const r = sample.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) {
            rootEl.style.setProperty('--letter-cell-w', `${r.width.toFixed(2)}px`);
            rootEl.style.setProperty('--letter-cell-h', `${r.height.toFixed(2)}px`);
        }
    }

    // Per-frame highlight node cache. `updateHighlights` runs at 60fps and must
    // NOT re-query the (now much larger) cell DOM each frame — that regressed the
    // animation to a laggy, trailing smear. We snapshot the node lists once per
    // structural render (the only time the DOM changes) and iterate the arrays.
    interface HiCache {
        blocks: HTMLElement[];
        phonemes: HTMLElement[];
        timedCells: HTMLElement[];
        letters: HTMLElement[];
        pauseBridges: HTMLElement[];
    }
    let _hc: HiCache | null = null;
    function _rebuildHighlightCache(): void {
        if (!rootEl) { _hc = null; return; }
        const q = (s: string): HTMLElement[] => Array.from(rootEl.querySelectorAll<HTMLElement>(s));
        _hc = {
            blocks: q('.mega-block'),
            phonemes: q('.mega-phoneme'),
            timedCells: q('[data-cell-timed]'),
            letters: q('.mega-letter:not(.null-ts)'),
            pauseBridges: q('.pause-bridge'),
        };
    }
    function _resetHighlightClasses(): void {
        if (!rootEl) return;
        rootEl.classList.remove('in-pause');
        rootEl.querySelectorAll<HTMLElement>('.pause-bridge').forEach((b) => {
            b.classList.remove('active', 'hover-preview');
        });
        rootEl.querySelectorAll<HTMLElement>('.mega-block').forEach((b) => {
            b.classList.remove('active', 'past', 'hover-preview');
        });
        rootEl.querySelectorAll<HTMLElement>('.mega-phoneme').forEach((p) => {
            p.classList.remove('active', 'hover-preview');
        });
        rootEl.querySelectorAll<HTMLElement>('.mega-letter:not(.null-ts)').forEach((l) => {
            l.classList.remove('active', 'hover-preview');
        });
        rootEl.querySelectorAll<HTMLElement>('.haraka-cell').forEach((c) => {
            c.classList.remove('active', 'hover-preview');
        });
        rootEl.querySelectorAll<HTMLElement>('.bridge-letter').forEach((c) => {
            c.classList.remove('active', 'hover-preview');
        });
    }

    // Waveform hover → re-run highlights. The rAF loop is stopped while paused,
    // so without this reactive trigger hover-driven previews wouldn't repaint.
    // Loop target changes also retrigger so `.loop` classes update.
    //
    // `untrack` is critical here: `updateHighlights()` mutates `_prevActiveWordIdx`
    // / `_prevActivePhonemeIdx` (top-level `let`s, which Svelte 5 legacy mode
    // treats as reactive state). Without `untrack` the imperative reads of
    // those fields inside `updateHighlights` would become dependencies of THIS
    // effect, and the subsequent writes inside the same function would re-fire
    // the effect — Svelte 5 raises `effect_update_depth_exceeded` after ~200
    // such re-runs, which broke first-load reactivity wholesale.
    $: ($tsWaveformHoverTime, $loopTarget, untrack(() => updateHighlights()));

    // ---- Pure helpers (state-free) ----

    // Alef-maksura (ى U+0649) + dagger alef (ٰ U+0670) is one long-vowel unit
    // (علىٰ, موسىٰ, إلىٰ). The aligner splits the dagger into its own shard letter,
    // but the two render as a single cell. Folding by char is safe — an alef-
    // maksura never carries an independent dagger. Every other grapheme stays its
    // own cell: a carrier waw keeps its (silent) waw + dagger split, a consonant's
    // dagger stays independent.
    /** A sukūn cell — never rendered (cell exists with empty phonemeIndices). */
    function _isSukunCell(c: TsCell): boolean {
        return c.role === 'haraka' && firstMark(c.chars) === SUKUN;
    }

    function _cellTiming(
        indices: number[],
        intervals: PhonemeInterval[],
        shareIv: [number, number] | null,
    ): { start: number | null; end: number | null } {
        let s = Infinity;
        let e = -Infinity;
        for (const i of indices) {
            const iv = intervals[i];
            if (!iv) continue;
            s = Math.min(s, iv.start);
            e = Math.max(e, iv.end);
        }
        if (shareIv) {
            // A sounded share-group member extends to (and a silent one borrows)
            // the group's interval union so co-lit cells light together.
            s = Math.min(s, shareIv[0]);
            e = Math.max(e, shareIv[1]);
        }
        return s === Infinity ? { start: null, end: null } : { start: s, end: e };
    }

    /** Per-word share-group interval unions: cells sharing one non-null shareGroup
     *  co-highlight, so each resolves its span to the union of all members. */
    function _shareUnions(
        cells: TsCell[],
        intervals: PhonemeInterval[],
    ): Map<number, [number, number]> {
        const unions = new Map<number, [number, number]>();
        for (const c of cells) {
            if (c.shareGroup == null) continue;
            for (const i of c.phonemeIndices) {
                const iv = intervals[i];
                if (!iv) continue;
                const cur = unions.get(c.shareGroup);
                if (!cur) unions.set(c.shareGroup, [iv.start, iv.end]);
                else {
                    cur[0] = Math.min(cur[0], iv.start);
                    cur[1] = Math.max(cur[1], iv.end);
                }
            }
        }
        return unions;
    }

    /** The folded letter view of `word.letters` (the ىٰ fold collapses two source
     *  letters into one). Used both for the synthetic-base fallback and to resolve
     *  a `base` cell's glyph / letter-timing by its `sourceLetterIndex`. */
    function foldedLettersFor(word: TsWord): {
        folded: FoldedLetter[];
        srcToFold: Map<number, number>;
    } {
        const folded: FoldedLetter[] = [];
        const srcToFold = new Map<number, number>();
        let origIdx = 0;
        for (const letter of word.letters || []) {
            const prev = folded[folded.length - 1];
            if (prev && letter.char.startsWith(DAGGER) && prev.glyph.endsWith(ALEF_MAKSURA)) {
                // Fold the dagger onto the maksura cell: one combined unit spanning
                // both timings, sounding unless both graphemes are silent.
                prev.glyph += letter.char;
                if (letter.end != null) prev.end = letter.end;
                prev.silent = prev.silent && letter.silent === true;
                prev.isNull = prev.isNull || letter.start == null || letter.end == null;
                prev.srcIndices.push(origIdx);
                srcToFold.set(origIdx, folded.length - 1);
                origIdx++;
                continue;
            }
            folded.push({
                glyph: letter.char,
                silent: letter.silent === true,
                start: letter.start,
                end: letter.end,
                isNull: letter.start == null || letter.end == null,
                srcIndices: [origIdx],
            });
            srcToFold.set(origIdx, folded.length - 1);
            origIdx++;
        }
        return { folded, srcToFold };
    }

    /**
     * Build the ordered cell-group model — the single source for the letter row.
     *
     * GROUPING (respects allocation): a SHORT vowel stays with its base
     * (`[base, haraka]`, kind `base`); a LONG vowel is its own unit
     * `[diacritic, carrier]` (kind `vowel`) whose base is rendered SEPARATELY in
     * its own base group. A long-vowel unit is a `madd` carrier that shares a
     * phoneme (shareGroup) with a haraka. Implicit / standalone madds get their
     * own `vowel` group too. Full cells (`base` + `madd` carriers, real or
     * implicit) render letter-sized; haraka/tanwīn render as small pinned cells.
     * Sukūn is filtered. A base/carrier glyph comes from
     * `word.letters[sourceLetterIndex]` (folded), with ◌ّ composed on when the
     * consonant is geminated (the aligner's letter char carries no shaddah).
     *
     * When a word carries no `base` cells (lightweight test fixtures), synthesize
     * one base per folded letter so the row matches the letters.
     */
    function cellGroupsFor(
        word: TsWord,
        intervals: PhonemeInterval[],
        shareUnions: Map<number, [number, number]>,
        liftIltiqaa = false,
    ): RenderedGroup[] {
        const { folded, srcToFold } = foldedLettersFor(word);
        // The iltiqaa-kasra cell is lifted into a cross-word bridge — drop it from
        // the word's own letter row so it renders only between the two words.
        const cells = (word.cells ?? []).filter(
            (c) => !(liftIltiqaa && c.tag === 'iltiqaa_kasra'),
        );
        const hasBase = cells.some((c) => c.role === 'base');
        const groups: RenderedGroup[] = [];

        // Share-groups that contain a madd carrier = long-vowel units (the haraka
        // pairs with the carrier after it; its base renders separately).
        const longVowelSG = new Set<number>();
        for (const c of cells) {
            if (c.role === 'madd' && c.shareGroup != null) longVowelSG.add(c.shareGroup);
        }
        // Folded letters already emitted as a full cell (the ىٰ maksura+dagger fold).
        const consumedFold = new Set<number>();

        // --- Carried-vowel resolution: a haraka/tanwīn the phonemizer marks
        //     `dropped` (empty indices) because its vowel is realized on an
        //     ADJACENT carrier must co-light + group with that carrier, not grey
        //     out. Three carriers: the madd-ʿiwaḍ alef, the Allah dagger-alef, and
        //     (idgham shafawi / noon) the merged base that absorbed the vowel. ---
        const iwadAlef = cells.find((c) => c.role === 'madd' && c.tag === 'madd_iwad');
        const _iwadIv = iwadAlef
            ? _cellTiming(iwadAlef.phonemeIndices, intervals, null)
            : { start: null, end: null };
        const iwadIv: [number, number] | null = _iwadIv.start != null ? [_iwadIv.start, _iwadIv.end!] : null;
        const daggerBySrc = new Map<number, { group: RenderedGroup; iv: [number, number] }>();
        let iwadGroup: RenderedGroup | null = null;

        const newGroup = (kind: 'base' | 'vowel'): RenderedGroup => {
            const g: RenderedGroup = { kind, full: [], small: [], shareGroup: null };
            groups.push(g);
            return g;
        };
        const noteShare = (g: RenderedGroup, c: TsCell): void => {
            if (c.shareGroup != null && g.shareGroup == null) g.shareGroup = c.shareGroup;
        };

        const pushSmall = (
            g: RenderedGroup,
            c: TsCell,
            opts: { coLightIv?: [number, number]; glyphOverride?: string } = {},
        ): void => {
            const phone = c.phonemeIndices.length ? intervals[c.phonemeIndices[0]!]?.phone : undefined;
            const shareIv = c.shareGroup != null ? shareUnions.get(c.shareGroup) ?? null : null;
            let { start, end } = _cellTiming(c.phonemeIndices, intervals, shareIv);
            if (opts.coLightIv) [start, end] = opts.coLightIv; // co-light on the carrier's interval
            const mark = firstMark(c.chars);
            const iqlab = c.tag === 'iqlab_tanween' ? IQLAB_FORM[mark] : undefined;
            let glyph: string;
            let slot: 'top' | 'bottom';
            let sizeGlyph: string;
            let extraShift = 0;
            // iqlab composites carry their OWN calibration (the mini-meem shifts
            // the ink), via a named key — not the bare haraka's.
            let calibKey: string | undefined;
            if (opts.glyphOverride) {
                glyph = opts.glyphOverride;
                slot = cellSlot(glyph);
                sizeGlyph = glyph;
            } else if (iqlab) {
                // SINGLE short vowel + a mini-meem composed in ONE DK glyph (never a
                // doubled tanwīn); calibrated by its own iqlab key.
                glyph = iqlab.haraka + iqlab.meem;
                slot = iqlab.haraka === KASRA ? 'bottom' : 'top';
                sizeGlyph = iqlab.haraka;
                calibKey = iqlab.haraka === FATHA ? 'iqlab_fatha'
                    : iqlab.haraka === DAMMA ? 'iqlab_damma' : 'iqlab_kasra';
            } else if (c.role === 'tanween' && OPEN_TANWEEN[mark] && OPEN_TANWEEN_TAGS.has(c.tag ?? '')) {
                // Assimilated tanwīn (idgham / ikhfaa) renders OPEN (DK encodes it
                // as a distinct codepoint); iẓhar (tagless) keeps the stacked form.
                // Slot follows the canonical mark (kasratan below, others above).
                glyph = OPEN_TANWEEN[mark]!;
                slot = cellSlot(mark);
                sizeGlyph = glyph;
            } else {
                glyph = cellGlyph(c.chars, c.tag, phone);
                slot = cellSlot(glyph);
                sizeGlyph = glyph;
            }
            g.small.push({
                glyph,
                slot,
                // a carried-vowel cell sounds (co-lit) — render timed, not greyed.
                status: opts.coLightIv ? 'present' : c.status,
                tag: c.tag,
                cellStart: start,
                cellEnd: end,
                shareGroup: c.shareGroup,
                renderStyle: harakaRenderStyle(sizeGlyph, extraShift, calibKey),
                inserted: c.chars === '' && c.status === 'inserted',
            });
            noteShare(g, c);
        };

        // A FULL letter-sized cell from a `base` or real `madd` carrier. The glyph
        // is the cell's OWN canonical char (the phonemizer composes ◌ّ onto a
        // geminated consonant) — NOT looked up in word.letters: the phonemizer's
        // source_letter_index folds a dagger-alef ٰ into its base letter, while the
        // aligner keeps it a separate `word.letters` entry, so the two indexings
        // diverge and a word.letters lookup mis-glyphs / drops carriers. `isBase`
        // marks the interactive letter element.
        const pushFullGrapheme = (g: RenderedGroup, c: TsCell, isBase: boolean): void => {
            const shareIv = c.shareGroup != null ? shareUnions.get(c.shareGroup) ?? null : null;
            const { start, end } = _cellTiming(c.phonemeIndices, intervals, shareIv);
            let glyph: string;
            let silent: boolean;
            let lStart: number | null;
            let lEnd: number | null;
            let isNull: boolean;
            let letterIndex: number;
            if (c.chars) {
                glyph = c.chars; // canonical text, shaddah already composed by the phonemizer
                // A dropped consonant that CO-LIGHTS through a merger — the idgham-noon
                // source noon: silent on its own (the merged sound is on the receiving
                // letter) but lit together with it — renders as a NORMAL cell, not greyed,
                // so both letters highlight as one. A genuinely silent letter (no share
                // group) still greys.
                silent = c.status === 'dropped' && c.shareGroup == null;
                lStart = start;
                lEnd = end;
                isNull = start == null;
                letterIndex = c.sourceLetterIndex;
            } else {
                // Graphemeless base cell (lightweight test fixtures): fall back to
                // the folded word.letters glyph + timing.
                const foldIdx = srcToFold.get(c.sourceLetterIndex);
                const fl = foldIdx != null ? folded[foldIdx] : undefined;
                glyph = fl?.glyph ?? '';
                silent = (fl?.silent ?? c.status === 'dropped') && c.shareGroup == null;
                lStart = fl?.start ?? null;
                lEnd = fl?.end ?? null;
                isNull = fl?.isNull ?? (start == null);
                letterIndex = foldIdx ?? -1;
                if (foldIdx != null) consumedFold.add(foldIdx);
            }
            g.full.push({
                glyph,
                silent,
                status: c.status,
                tag: c.tag,
                implicit: false,
                isBase,
                cellStart: start,
                cellEnd: end,
                letterStart: lStart,
                letterEnd: lEnd,
                isNull,
                letterIndex,
                shareGroup: c.shareGroup,
            });
            noteShare(g, c);
        };

        const pushFullImplicit = (g: RenderedGroup, c: TsCell): void => {
            const shareIv = c.shareGroup != null ? shareUnions.get(c.shareGroup) ?? null : null;
            const { start, end } = _cellTiming(c.phonemeIndices, intervals, shareIv);
            g.full.push({
                glyph: implicitMaddGlyph(c.tag),
                silent: c.status === 'dropped',
                status: c.status,
                tag: c.tag,
                implicit: true,
                isBase: false,
                cellStart: start,
                cellEnd: end,
                letterStart: null,
                letterEnd: null,
                isNull: true,
                letterIndex: -1,
                shareGroup: c.shareGroup,
            });
            noteShare(g, c);
        };

        if (hasBase) {
            let curBase: RenderedGroup | null = null;
            const vowelGroups = new Map<number, RenderedGroup>();
            const vowelGroupFor = (sg: number): RenderedGroup => {
                let g = vowelGroups.get(sg);
                if (!g) {
                    g = newGroup('vowel');
                    vowelGroups.set(sg, g);
                }
                return g;
            };
            const ownIv = (c: TsCell): [number, number] | null => {
                const t = _cellTiming(c.phonemeIndices, intervals, null);
                return t.start != null ? [t.start, t.end!] : null;
            };
            for (const c of cells) {
                if (_isSukunCell(c)) continue; // sukūn never rendered
                const foldIdx = srcToFold.get(c.sourceLetterIndex);
                if (c.role === 'base') {
                    if (foldIdx != null && consumedFold.has(foldIdx)) continue; // maksura+dagger half
                    curBase = newGroup('base');
                    pushFullGrapheme(curBase, c, true);
                } else if (c.role === 'madd') {
                    if (c.chars !== '' && foldIdx != null && consumedFold.has(foldIdx)) continue; // fold half
                    if (c.tag === 'madd_iwad') {
                        // the substituted (written) or inserted (implicit — word ends in
                        // hamza, مَآءً) iwaḍ alef joins the [fatḥa, alef] vowel group
                        iwadGroup = iwadGroup ?? newGroup('vowel');
                        if (c.chars === '') pushFullImplicit(iwadGroup, c);
                        else pushFullGrapheme(iwadGroup, c, false);
                    } else if (c.chars === '') {
                        const g = c.shareGroup != null && longVowelSG.has(c.shareGroup)
                            ? vowelGroupFor(c.shareGroup) : newGroup('vowel');
                        pushFullImplicit(g, c);
                        if (c.tag === 'allah_dagger_alef') {
                            const iv = ownIv(c);
                            if (iv) daggerBySrc.set(c.sourceLetterIndex, { group: g, iv });
                        }
                    } else {
                        const lv = c.shareGroup != null && longVowelSG.has(c.shareGroup);
                        pushFullGrapheme(lv ? vowelGroupFor(c.shareGroup!) : newGroup('vowel'), c, false);
                    }
                } else {
                    // haraka / tanwīn
                    const dropped = c.phonemeIndices.length === 0;
                    if (c.shareGroup != null && longVowelSG.has(c.shareGroup)) {
                        pushSmall(vowelGroupFor(c.shareGroup), c); // long vowel — leaves its base
                    } else if (dropped && c.tag === 'madd_iwad' && iwadIv) {
                        // dropped tanwīn at waqf → a fatḥa grouped + co-lit with the iwaḍ alef
                        iwadGroup = iwadGroup ?? newGroup('vowel');
                        pushSmall(iwadGroup, c, { coLightIv: iwadIv, glyphOverride: FATHA });
                    } else if (dropped && daggerBySrc.has(c.sourceLetterIndex)) {
                        const d = daggerBySrc.get(c.sourceLetterIndex)!;
                        pushSmall(d.group, c, { coLightIv: d.iv }); // Allah: fatḥa joins the dagger ā
                    } else {
                        // short vowel / true waqf drop. (An idgham-shafawi haraka
                        // whose vowel the merged base absorbed arrives `present` +
                        // share-grouped from the phonemizer, so it co-lights here via
                        // its share union — no phone inspection.)
                        pushSmall(curBase ?? (curBase = newGroup('base')), c);
                    }
                }
            }
            return groups;
        }

        // --- Synthetic-base fallback: no base cells (test fixtures). One group
        //     per folded letter, with the word's diacritic cells attached. ---
        const groupByFold: RenderedGroup[] = folded.map((fl, i) => {
            const g = newGroup('base');
            g.full.push({
                glyph: fl.glyph,
                silent: fl.silent,
                status: 'present',
                tag: null,
                implicit: false,
                isBase: true,
                cellStart: fl.start,
                cellEnd: fl.end,
                letterStart: fl.start,
                letterEnd: fl.end,
                isNull: fl.isNull,
                letterIndex: i,
                shareGroup: null,
            });
            return g;
        });
        for (const c of cells) {
            if (_isSukunCell(c)) continue;
            if (c.role === 'madd' && c.chars !== '') continue; // real carrier — already a folded letter
            const foldIdx = srcToFold.get(c.sourceLetterIndex);
            const g = (foldIdx != null ? groupByFold[foldIdx] : undefined) ?? groupByFold[groupByFold.length - 1];
            if (!g) continue;
            if (c.role === 'madd' && c.chars === '') pushFullImplicit(g, c);
            else pushSmall(g, c);
        }
        return groups;
    }

    /** Split a phone string into base character(s) and trailing IPA modifiers
     *  (length ː, emphatic ˤ, ghunnah tilde ̃). The modifier is rendered as a
     *  superscript so the base stays visually centred in the cell. */
    // Only length marks (ː / ASCII :) are detached modifiers; ˤ is integral to
    // the consonant symbol (rˤ, aˤ) and must stay in the base.
    const PHONE_MOD_RE = /([ː:]+)$/u;
    function splitPhone(phone: string | undefined): { base: string; mod: string } {
        if (!phone || phone === 'sil' || phone === 'sp') return { base: phone ?? '', mod: '' };
        const m = PHONE_MOD_RE.exec(phone);
        return m ? { base: phone.slice(0, -m[0].length), mod: m[0] } : { base: phone, mod: '' };
    }

    /** Parse the trailing word number from a ``surah:ayah:word`` location.
     *  Returns 0 when the location is malformed — caller filters those out. */
    function buildRendered(
        words: TsWord[],
        intervals: PhonemeInterval[],
    ): RenderedBlock[] {
        if (!words.length) return [];

        // Cross-word bridges are baked into the shard at generation: a phoneme
        // carrying a ``bridge`` rule is the idgham merger that fuses two words.
        // Lift it out of its inline row into the gold tile at the boundary — no
        // scanning, no side inference. A merger at a word's head renders before
        // that block; one in a word's tail (idgham shafawi) bridges into the
        // next block. The generator placed the tag on the exact merger interval,
        // so there's nothing to disambiguate here.
        const bridgeBeforeBlock = new Map<number, RenderedBridge>();
        const excluded = new Set<number>();
        // Words whose inserted iltiqaa-kasra cell was lifted into a bridge — its
        // small cell is then suppressed in the word's own letter row.
        const liftedIltiqaa = new Set<number>();
        for (let wi = 0; wi < words.length; wi++) {
            const word = words[wi];
            const indices = word?.phoneme_indices ?? [];
            for (let k = 0; k < indices.length; k++) {
                const pi = indices[k]!;
                if (!intervals[pi]?.bridge) continue;
                const target = k === 0 ? wi : wi + 1;
                if (target < words.length) {
                    bridgeBeforeBlock.set(target, {
                        phonemes: [{ interval: intervals[pi]!, index: pi }],
                        letter: null,
                    });
                    excluded.add(pi);
                }
            }
            // iltiqaa kasra: tanwīn meeting the next word's hamza-waṣl inserts a
            // connecting kasra (i). Lift its cell out of word N into a borderless
            // bridge before word N+1 — the kasra char on the letter row + the i
            // phoneme on the phoneme row, between the two words. The silent alef of
            // a fatḥatan+alef word (خَيْرًا) stays in word N, so the bridge naturally
            // sits after it; the lifted i is the word's last phoneme.
            const kasra = (word?.cells ?? []).find((c) => c.tag === 'iltiqaa_kasra');
            const kpi = kasra?.phonemeIndices[0];
            if (kasra && kpi != null && intervals[kpi] && wi + 1 < words.length
                && !bridgeBeforeBlock.has(wi + 1)) {
                const iv = intervals[kpi];
                const glyph = cellGlyph(kasra.chars, kasra.tag, iv.phone);
                bridgeBeforeBlock.set(wi + 1, {
                    phonemes: [{ interval: iv, index: kpi }],
                    letter: {
                        glyph,
                        style: harakaRenderStyle(glyph),
                        cellStart: iv.start,
                        cellEnd: iv.end,
                        wordIndex: wi,
                    },
                });
                excluded.add(kpi);
                liftedIltiqaa.add(wi);
            }
        }

        // Share-group interval unions computed VERSE-WIDE (across all words' cells):
        // a cross-word idgham tanwīn shares a group with the receiving word's base,
        // so its highlight must span the haraka + the ghunnah/merger in the next
        // word — a per-word union would miss the other side.
        const shareUnions = _shareUnions(words.flatMap((w) => w.cells ?? []), intervals);

        const blocks: RenderedBlock[] = [];
        for (let wi = 0; wi < words.length; wi++) {
            const word = words[wi];
            if (!word) continue;

            const bridge: RenderedBridge | null = bridgeBeforeBlock.get(wi) ?? null;

            const phonemes: RenderedPhoneme[] = [];
            for (const pi of word.phoneme_indices ?? []) {
                if (excluded.has(pi)) continue;
                const iv = intervals[pi];
                if (iv && !iv.geminate_end) phonemes.push({ interval: iv, index: pi });
            }

            blocks.push({
                word,
                wordIndex: wi,
                displayText: (word.display_text || word.text).replace(NON_RECITED_SIGNS, ''),
                groups: cellGroupsFor(word, intervals, shareUnions, liftedIltiqaa.has(wi)),
                phonemes,
                bridge,
                pauseBridge: null,
            });
        }

        // Detected inter-word silences: a positive gap between consecutive words
        // (their end/start are ms-quantized, so contiguous words share a boundary
        // and only a real pause leaves a gap). Each gap gets a pause bridge before
        // the later block; a surfaced waqf mark on the earlier word is lifted out
        // of its box into the bridge.
        for (let bi = 0; bi < blocks.length - 1; bi++) {
            const a = blocks[bi]!;
            const b = blocks[bi + 1]!;
            const startSec = a.word.end;
            const endSec = b.word.start;
            if (endSec <= startSec) continue;
            const { clean, mark } = splitWaqf(a.displayText);
            if (mark) a.displayText = clean;
            b.pauseBridge = { mark, startSec, endSec };
        }
        return blocks;
    }

    // ---- Per-frame imperative highlight update (called from animation loop) ----

    let _prevActiveWordIdx = -1;
    let _prevActivePhonemeIdx = -1;

    /**
     * Apply current-time-based highlights imperatively. Called from the
     * animation loop via bind:this; does NOT go through Svelte reactivity
     * so we stay at 60fps with minimal GC pressure.
     */
    export function updateHighlights(): void {
        if (!rootEl) return;
        const lv = get(loadedVerse);
        if (!lv) return;
        const time = getSegRelTime(lv.tsSegOffset);

        const intervals = lv.data.intervals;
        const words = lv.data.words;
        const portReady = !!dashPort.element;
        const portPaused = dashPort.paused;
        const hoverTime = get(tsWaveformHoverTime);

        // Cached node lists (rebuilt only on structural render) — never query the
        // DOM per frame; that regressed the animation to a laggy, trailing smear.
        if (!_hc) _rebuildHighlightCache();
        const hc = _hc;
        if (!hc) return;

        // Current phoneme (skip geminate_end)
        let currentIndex = -1;
        for (let i = 0; i < intervals.length; i++) {
            const iv = intervals[i];
            if (!iv) continue;
            if (time >= iv.start && time < iv.end) {
                currentIndex = iv.geminate_end ? i - 1 : i;
                break;
            }
        }

        // Current word
        let currentWordIndex = -1;
        for (let i = 0; i < words.length; i++) {
            const w = words[i];
            if (!w) continue;
            if (time >= w.start && time < w.end) {
                currentWordIndex = i;
                break;
            }
        }

        // Block highlights (.active / .past) — diff-only.
        // Suppress scrollIntoView when the update is driven by waveform hover
        // (user is actively scrubbing; auto-scrolling would fight the pointer).
        let hoverWordIndex = -1;
        let hoverPhonemeIndex = -1;
        const showWaveformPreview = hoverTime != null && portReady && !portPaused;
        if (showWaveformPreview) {
            for (let i = 0; i < words.length; i++) {
                const w = words[i];
                if (!w) continue;
                if (hoverTime >= w.start && hoverTime < w.end) {
                    hoverWordIndex = i;
                    break;
                }
            }
            if (hoverWordIndex === currentWordIndex) {
                hoverWordIndex = -1;
            } else {
                for (let i = 0; i < intervals.length; i++) {
                    const iv = intervals[i];
                    if (!iv) continue;
                    if (hoverTime >= iv.start && hoverTime < iv.end) {
                        hoverPhonemeIndex = iv.geminate_end ? i - 1 : i;
                        break;
                    }
                }
            }
        }
        const isHoverDriven = hoverTime != null && portReady && portPaused;
        if (currentWordIndex !== _prevActiveWordIdx) {
            hc.blocks.forEach((block) => {
                const wi = parseInt(block.dataset.wordIndex ?? '-1');
                block.classList.remove('active', 'past');
                if (wi === currentWordIndex) {
                    block.classList.add('active');
                    if (!isHoverDriven) block.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                } else if (currentWordIndex >= 0 && wi < currentWordIndex) {
                    block.classList.add('past');
                }
            });
            _prevActiveWordIdx = currentWordIndex;
        }
        hc.blocks.forEach((block) => {
            const wi = parseInt(block.dataset.wordIndex ?? '-1');
            block.classList.toggle('hover-preview', wi === hoverWordIndex);
        });

        // Phoneme highlights — diff-only
        if (currentIndex !== _prevActivePhonemeIdx) {
            hc.phonemes.forEach((ph) => {
                ph.classList.toggle('active', parseInt(ph.dataset.index ?? '-1') === currentIndex);
            });
            _prevActivePhonemeIdx = currentIndex;
        }
        hc.phonemes.forEach((ph) => {
            ph.classList.toggle('hover-preview', parseInt(ph.dataset.index ?? '-1') === hoverPhonemeIndex);
        });

        // Cell highlights — ONE loop over EVERY timed cell (full base + small
        // diacritic). Each lights on ITS OWN phoneme interval (data-cell-start/
        // end): a base lights on its consonant; a haraka on the vowel; a long-
        // vowel haraka + carrier share an index (and share-group union) and
        // co-light. This tiles cleanly with no flash/gap. Untimed cells (sukūn,
        // dropped, null-ts) carry no `data-cell-timed` and are skipped.
        hc.timedCells.forEach((el) => {
            const s = parseFloat(el.dataset.cellStart ?? 'NaN');
            const e = parseFloat(el.dataset.cellEnd ?? 'NaN');
            const wi = parseInt(el.dataset.wordIndex ?? '-1');
            el.classList.toggle('active', time >= s && time < e);
            el.classList.toggle(
                'hover-preview',
                hoverTime != null && wi === hoverWordIndex && hoverTime >= s && hoverTime < e,
            );
        });

        // Loop perma-highlight — outline the looped element on its tier.
        const lp = get(loopTarget);
        hc.blocks.forEach((block) => {
            const wi = parseInt(block.dataset.wordIndex ?? '-1');
            block.classList.toggle(
                'loop',
                lp?.kind === 'word' && lp.wordIndex === wi,
            );
        });
        hc.letters.forEach((el) => {
            const wi = parseInt(el.dataset.wordIndex ?? '-1');
            const li = parseInt(el.dataset.letterIndex ?? '-1');
            el.classList.toggle(
                'loop',
                lp?.kind === 'letter' && lp.wordIndex === wi && lp.childIndex === li,
            );
        });
        hc.phonemes.forEach((el) => {
            const idx = parseInt(el.dataset.index ?? '-1');
            el.classList.toggle(
                'loop',
                lp?.kind === 'phoneme' && lp.childIndex === idx,
            );
        });

        // Pause bridges: the bridge whose silence span contains the playhead lights
        // (`.active`) and the rest of the row dims to 70% (`.in-pause` on the
        // container). Waveform hover over a silence span previews its bridge.
        let inPauseGap = false;
        hc.pauseBridges.forEach((b) => {
            const s = parseFloat(b.dataset.pauseStart ?? 'NaN');
            const e = parseFloat(b.dataset.pauseEnd ?? 'NaN');
            const playing = time >= s && time < e;
            if (playing) inPauseGap = true;
            b.classList.toggle('active', playing);
            b.classList.toggle(
                'hover-preview',
                hoverTime != null && hoverTime >= s && hoverTime < e,
            );
        });
        rootEl.classList.toggle('in-pause', inPauseGap);
    }

    function getSegRelTime(segOffset: number): number {
        if (!dashPort.element) return 0;
        // While paused, waveform hover drives a preview: treat the hovered
        // slice-relative time as the "current" time so block highlights
        // (active word / letter / phoneme) follow the pointer.
        const hoverT = get(tsWaveformHoverTime);
        if (hoverT != null && dashPort.paused) return hoverT;
        return dashPort.currentTimeMs() / 1000 - segOffset;
    }

    /** Scroll the active mega-block into view (keyboard `J`). */
    export function scrollActiveIntoView(): void {
        if (!rootEl) return;
        const active = rootEl.querySelector<HTMLElement>('.mega-block.active');
        if (active) active.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    // ---- Click handlers: seek audio on click ----

    function seekToTime(absTime: number): void {
        if (!dashPort.element) return;
        const targetMs = absTime * 1000;
        ensureDashCovering(targetMs);
        dashPort.seek(targetMs);
        // Clicking a block always starts playback — resumes if paused.
        if (dashPort.paused) dashPort.play();
        // Force a repaint immediately after user seek (not waiting on timeupdate)
        updateHighlights();
    }

    // Single-click handlers are DEFERRED by `TS_CLICK_DELAY_MS` to
    // disambiguate from double-click. The DOM fires `click` before
    // `dblclick`, so without this defer the sequence for a user double-
    // clicking word B while looped on word A would be:
    //   click#1 → swap loop A → B → zoom animates to B
    //   click#2 → no-op (already on B)
    //   dblclick → toggleLoopOn(B) sees sameTarget → clears loop → zoom
    //              resets to full view. Net effect: "dblclick on B
    //              destroyed my loop". Deferring click and cancelling it
    //              on dblclick gives dblclick exclusive say over loop
    //              toggling.
    //
    // When in loop mode and the click lands on a DIFFERENT word (or tier
    // target), the committed click swaps the loop target — matching the
    // waveform and Animation-view click surfaces so all three behave
    // identically.
    let _pendingClick: number | null = null;

    function _cancelPendingClick(): void {
        if (_pendingClick !== null) {
            clearTimeout(_pendingClick);
            _pendingClick = null;
        }
    }

    function _deferClick(fn: () => void): void {
        _cancelPendingClick();
        _pendingClick = window.setTimeout(() => {
            _pendingClick = null;
            fn();
        }, TS_CLICK_DELAY_MS);
    }

    function _swapLoopOrSeek(target: TsLoopTarget, absSeek: number): void {
        const cur = get(loopTarget);
        if (cur) {
            const same =
                cur.kind === target.kind
                && cur.wordIndex === target.wordIndex
                && cur.childIndex === target.childIndex;
            if (same) return;
            loopTarget.set(target);
            if (dashPort.element) {
                const targetMs = absSeek * 1000;
                ensureDashCovering(targetMs);
                dashPort.seek(targetMs);
                if (dashPort.paused) dashPort.play();
            }
            updateHighlights();
            return;
        }
        // No loop active → pure seek.
        if (!dashPort.element) return;
        const targetMs = absSeek * 1000;
        ensureDashCovering(targetMs);
        dashPort.seek(targetMs);
        if (dashPort.paused) dashPort.play();
        updateHighlights();
    }

    function onWordClick(word: TsWord, wordIndex: number): void {
        _deferClick(() => {
            const lv = get(loadedVerse);
            if (!lv) return;
            _swapLoopOrSeek(
                { kind: 'word', startSec: word.start, endSec: word.end, wordIndex },
                word.start + lv.tsSegOffset,
            );
        });
    }

    function onPhonemeClick(
        e: MouseEvent,
        iv: PhonemeInterval,
        phonemeIndex: number,
        wordIndex: number,
    ): void {
        e.stopPropagation();
        _deferClick(() => {
            const lv = get(loadedVerse);
            if (!lv) return;
            _swapLoopOrSeek(
                {
                    kind: 'phoneme',
                    startSec: iv.start,
                    endSec: iv.end,
                    wordIndex,
                    childIndex: phonemeIndex,
                },
                iv.start + lv.tsSegOffset,
            );
        });
    }

    // ---- Double-click handlers: toggle loop on the clicked token ----

    /**
     * Toggle loop on the given token. If it's already the looped target,
     * exit loop mode; otherwise engage loop + seek to its start.
     */
    function toggleLoopOn(target: TsLoopTarget): void {
        const lv = get(loadedVerse);
        if (!lv) return;
        const cur = get(loopTarget);
        const sameTarget =
            cur?.kind === target.kind
            && cur.wordIndex === target.wordIndex
            && cur.childIndex === target.childIndex;
        if (sameTarget) {
            loopTarget.set(null);
            return;
        }
        loopTarget.set(target);
        seekToTime(target.startSec + lv.tsSegOffset);
        // Zoom/pan is handled by the centralized `loopTarget` subscription in
        // `utils/zoom.ts::setupZoomLifecycle` — no per-callsite hook needed.
    }

    function onWordDblClick(word: TsWord, wordIndex: number): void {
        _cancelPendingClick();
        toggleLoopOn({ kind: 'word', startSec: word.start, endSec: word.end, wordIndex });
    }

    function onLetterDblClick(
        e: MouseEvent,
        startSec: number,
        endSec: number,
        wordIndex: number,
        letterIndex: number,
    ): void {
        e.stopPropagation();
        _cancelPendingClick();
        toggleLoopOn({ kind: 'letter', startSec, endSec, wordIndex, childIndex: letterIndex });
    }

    function onPhonemeDblClick(
        e: MouseEvent,
        iv: PhonemeInterval,
        phonemeIndex: number,
        wordIndex: number,
    ): void {
        e.stopPropagation();
        _cancelPendingClick();
        toggleLoopOn({
            kind: 'phoneme',
            startSec: iv.start,
            endSec: iv.end,
            wordIndex,
            childIndex: phonemeIndex,
        });
    }

    function onLetterClick(
        e: MouseEvent,
        startSec: number,
        endSec: number,
        wordIndex: number,
        letterIndex: number,
    ): void {
        e.stopPropagation();
        _deferClick(() => {
            const lv = get(loadedVerse);
            if (!lv) return;
            _swapLoopOrSeek(
                { kind: 'letter', startSec, endSec, wordIndex, childIndex: letterIndex },
                startSec + lv.tsSegOffset,
            );
        });
    }

    // ---- Hover handlers: publish to tsHoveredElement for waveform sync, AND
    //      raise the per-cell duration tooltip (see the tooltip block below). ----

    function onWordEnter(e: MouseEvent, word: TsWord): void {
        tsHoveredElement.set({ kind: 'word', startSec: word.start, endSec: word.end });
        _tipEnter(e, word.start, word.end);
    }

    function onLetterEnter(e: MouseEvent, startSec: number | null, endSec: number | null): void {
        if (startSec == null || endSec == null) return;
        tsHoveredElement.set({ kind: 'letter', startSec, endSec });
        _tipEnter(e, startSec, endSec);
    }

    function onPhonemeEnter(e: MouseEvent, iv: PhonemeInterval): void {
        tsHoveredElement.set({ kind: 'phoneme', startSec: iv.start, endSec: iv.end });
        _tipEnter(e, iv.start, iv.end);
    }

    function onHoverLeave(): void {
        tsHoveredElement.set(null);
        _tipLeave();
    }

    // Diacritic cells (haraka/tanwīn small cells + implicit-madd full cells) and
    // the pause/stop cell: duration tooltip on hover, and — for diacritics —
    // click-to-seek. They deliberately do NOT publish tsHoveredElement, so the
    // waveform cursors stay exactly as they were (per requirement).
    function onCellEnter(e: MouseEvent, startSec: number | null, endSec: number | null): void {
        _tipEnter(e, startSec, endSec);
    }

    function onCellLeave(): void {
        _tipLeave();
    }

    function onCellClick(e: MouseEvent, startSec: number | null): void {
        e.stopPropagation();
        if (startSec == null) return;
        const lv = get(loadedVerse);
        if (!lv) return;
        seekToTime(startSec + lv.tsSegOffset);
    }

    // ---- Per-cell duration tooltip (warmup/cooldown) ----------------------
    // Shows a cell's recited duration (ms, rounded to the nearest 10) on hover.
    // The first (cold) hover warms up for TS_TIP_WARMUP_MS before showing; once
    // warm, moving to another cell shows near-instantly; warm decays back to
    // cold TS_TIP_COOLDOWN_MS after the pointer leaves a cell.
    const TS_TIP_WARMUP_MS = 500;
    const TS_TIP_COOLDOWN_MS = 2000;
    let tipText: string | null = null;
    let tipX = 0;
    let tipY = 0;
    let _tipWarm = false;
    let _tipShowTimer: number | null = null;
    let _tipCoolTimer: number | null = null;

    function _roundMs(startSec: number, endSec: number): number {
        return Math.round(((endSec - startSec) * 1000) / 10) * 10;
    }

    function _tipShowAt(el: HTMLElement, ms: number): void {
        if (!el.isConnected) return; // cell removed (verse change) before warmup fired
        const r = el.getBoundingClientRect();
        tipX = r.left + r.width / 2;
        tipY = r.top;
        tipText = `${ms} ms`;
        _tipWarm = true;
    }

    function _tipEnter(e: MouseEvent, startSec: number | null, endSec: number | null): void {
        const el = e.currentTarget as HTMLElement | null;
        if (!el || startSec == null || endSec == null) return;
        const ms = _roundMs(startSec, endSec);
        if (_tipCoolTimer !== null) { clearTimeout(_tipCoolTimer); _tipCoolTimer = null; }
        if (_tipShowTimer !== null) { clearTimeout(_tipShowTimer); _tipShowTimer = null; }
        if (_tipWarm) _tipShowAt(el, ms);
        else _tipShowTimer = window.setTimeout(() => { _tipShowTimer = null; _tipShowAt(el, ms); }, TS_TIP_WARMUP_MS);
    }

    function _tipLeave(): void {
        if (_tipShowTimer !== null) { clearTimeout(_tipShowTimer); _tipShowTimer = null; }
        tipText = null;
        if (_tipCoolTimer !== null) clearTimeout(_tipCoolTimer);
        _tipCoolTimer = window.setTimeout(() => { _tipCoolTimer = null; _tipWarm = false; }, TS_TIP_COOLDOWN_MS);
    }

    // Safety net: if the component unmounts while a hover is active (e.g. view
    // switch), clear the store so the waveform doesn't keep a stale band.
    // Also drop any pending deferred click / tooltip timer so neither fires
    // post-unmount.
    onDestroy(() => {
        tsHoveredElement.set(null);
        _cancelPendingClick();
        if (_tipShowTimer !== null) clearTimeout(_tipShowTimer);
        if (_tipCoolTimer !== null) clearTimeout(_tipCoolTimer);
    });

    // DEV-only highlight-transition perf A/B/C harness (remove before merge).
    // Sets `data-ts-perf` on <html>; the variants live in timestamps.css.
    const _perfModes: Array<[string, string]> = [
        ['baseline', 'baseline 0.1s'],
        ['drop', 'drop (none)'],
        ['fast', '30ms'],
        ['contain', 'contain:paint'],
    ];
    let _perfMode = 'baseline';
    function _setPerf(m: string): void {
        _perfMode = m;
        const el = document.documentElement;
        if (m === 'baseline') el.removeAttribute('data-ts-perf');
        else el.setAttribute('data-ts-perf', m);
    }
</script>

{#if import.meta.env.DEV}
    <div class="perf-ab" dir="ltr">
        <span class="perf-ab-label">highlight perf:</span>
        {#each _perfModes as [m, label] (m)}
            <button class="perf-ab-btn" class:on={_perfMode === m} on:click={() => _setPerf(m)}>{label}</button>
        {/each}
    </div>
{/if}

<div
    bind:this={rootEl}
    class="unified-display"
    dir="rtl"
    class:hidden={$loadedVerse === null}
>
    {#each rendered as block (block.wordIndex)}
        {#if block.bridge}
            {@const br = block.bridge}
            <div
                class="crossword-bridge"
                class:borderless={br.letter != null}
                class:hidden={br.letter != null ? !$showLetters && !$showPhonemes : !$showPhonemes}
            >
                {#if br.letter}
                    {@const lt = br.letter}
                    <!-- iltiqaa connecting kasra lifted onto the letter row, between
                         the two words; borderless, click-to-seek, lights on its i. -->
                    <span
                        class="bridge-letter dia-seekable"
                        class:hidden={!$showLetters}
                        data-cell-timed={lt.cellStart != null ? '1' : undefined}
                        data-cell-start={lt.cellStart}
                        data-cell-end={lt.cellEnd}
                        data-word-index={lt.wordIndex}
                        on:click={(e) => onCellClick(e, lt.cellStart)}
                        on:dblclick|stopPropagation
                        on:mouseenter={(e) => onCellEnter(e, lt.cellStart, lt.cellEnd)}
                        on:mouseleave={onCellLeave}
                        on:keydown={() => {}}
                        role="button"
                        tabindex="-1"
                    >
                        <span class="g" style={lt.style}>{lt.glyph}</span>
                    </span>
                {/if}
                {#each br.phonemes as ph (ph.index)}
                    {@const parts = splitPhone(ph.interval.phone)}
                    <span
                        class="mega-phoneme"
                        class:hidden={br.letter != null && !$showPhonemes}
                        class:silence={!ph.interval.phone ||
                            ph.interval.phone === 'sil' ||
                            ph.interval.phone === 'sp'}
                        class:geminate={ph.interval.geminate_start}
                        data-index={ph.index}
                        on:click={(e) => onPhonemeClick(e, ph.interval, ph.index, block.wordIndex)}
                        on:dblclick={(e) => onPhonemeDblClick(e, ph.interval, ph.index, block.wordIndex)}
                        on:mouseenter={(e) => onPhonemeEnter(e, ph.interval)}
                        on:mouseleave={onHoverLeave}
                        on:keydown={() => {}}
                        role="button"
                        tabindex="-1"
                    >
                        <span class="ph-base">{parts.base || '(sil)'}</span>{#if parts.mod}<sup class="ph-mod">{parts.mod}</sup>{/if}
                    </span>
                {/each}
            </div>
        {/if}
        {#if block.pauseBridge}
            {@const pb = block.pauseBridge}
            <div
                class="pause-bridge"
                data-pause-start={pb.startSec}
                data-pause-end={pb.endSec}
                role="group"
                on:mouseenter={(e) => onCellEnter(e, pb.startSec, pb.endSec)}
                on:mouseleave={onCellLeave}
            >
                {#if pb.mark}
                    <span class="pause-waqf" style={waqfRenderStyle(pb.mark)}
                    >{pb.mark}</span>
                {:else}
                    <span class="pause-icon" aria-hidden="true"></span>
                {/if}
            </div>
        {/if}
        <div
            class="mega-block"
            data-word-index={block.wordIndex}
            on:click={() => onWordClick(block.word, block.wordIndex)}
            on:dblclick={() => onWordDblClick(block.word, block.wordIndex)}
            on:keydown={() => {}}
            role="button"
            tabindex="-1"
        >
            {#if $showTranslations}
                <WordTranslation text={$verseTranslations[block.word.location] ?? ''} />
            {/if}
            <div
                class="mega-word"
                role="group"
                on:mouseenter={(e) => onWordEnter(e, block.word)}
                on:mouseleave={onHoverLeave}
            >{block.displayText}</div>
            {#if block.groups.length}
                <div class="mega-letters" class:hidden={!$showLetters} dir="rtl">
                    {#each block.groups as grp, gi (gi)}
                        <span class="cell-group" class:vowel={grp.kind === 'vowel'} class:share-group={grp.shareGroup != null}>
                            {#each grp.full as f}
                                {#if f.implicit}
                                    <!-- implicit madd (Allah dagger-alef / madd-ʿiwaḍ): a FULL cell,
                                         non-interactive, with the inserted/replaced affordance -->
                                    <span
                                        class="mega-letter implicit dia-{f.status}"
                                        class:dia-timed={f.status !== 'dropped' && f.cellStart != null}
                                        class:dia-seekable={f.cellStart != null}
                                        data-cell-timed={f.status !== 'dropped' && f.cellStart != null ? '1' : undefined}
                                        data-cell-start={f.cellStart}
                                        data-cell-end={f.cellEnd}
                                        data-word-index={block.wordIndex}
                                        on:click={(e) => onCellClick(e, f.cellStart)}
                                        on:dblclick|stopPropagation
                                        on:mouseenter={(e) => onCellEnter(e, f.cellStart, f.cellEnd)}
                                        on:mouseleave={onCellLeave}
                                        on:keydown={() => {}}
                                        role="button"
                                        tabindex="-1"
                                    >{f.glyph}</span>
                                {:else if f.isNull}
                                    <span
                                        class="mega-letter null-ts"
                                        class:silent={f.silent}
                                        on:click|stopPropagation
                                        on:keydown={() => {}}
                                        role="button"
                                        tabindex="-1"
                                    >{f.glyph}</span>
                                {:else}
                                    <!-- base consonant OR real madd carrier (ا و ي ٰ) — a FULL,
                                         interactive, timed letter cell -->
                                    <span
                                        class="mega-letter"
                                        class:silent={f.silent}
                                        class:dia-timed={f.cellStart != null && (!f.silent || f.shareGroup != null)}
                                        data-cell-timed={f.cellStart != null && (!f.silent || f.shareGroup != null) ? '1' : undefined}
                                        data-cell-start={f.cellStart}
                                        data-cell-end={f.cellEnd}
                                        data-letter-start={f.letterStart}
                                        data-letter-end={f.letterEnd}
                                        data-word-index={block.wordIndex}
                                        data-letter-index={f.letterIndex}
                                        on:click={(e) =>
                                            onLetterClick(e, f.letterStart ?? 0, f.letterEnd ?? 0, block.wordIndex, f.letterIndex)}
                                        on:dblclick={(e) =>
                                            onLetterDblClick(e, f.letterStart ?? 0, f.letterEnd ?? 0, block.wordIndex, f.letterIndex)}
                                        on:mouseenter={(e) => onLetterEnter(e, f.letterStart, f.letterEnd)}
                                        on:mouseleave={onHoverLeave}
                                        on:keydown={() => {}}
                                        role="button"
                                        tabindex="-1"
                                    >{f.glyph}</span>
                                {/if}
                            {/each}
                            {#each grp.small as c}
                                <span class="dia-track">
                                    <span
                                        class="haraka-cell pin-{c.slot} dia-{c.status}"
                                        class:dia-inserted={c.inserted}
                                        class:dia-timed={c.status !== 'dropped' && c.cellStart != null}
                                        class:dia-seekable={c.cellStart != null}
                                        data-cell-timed={c.status !== 'dropped' && c.cellStart != null ? '1' : undefined}
                                        data-cell-start={c.cellStart}
                                        data-cell-end={c.cellEnd}
                                        data-word-index={block.wordIndex}
                                        on:click={(e) => onCellClick(e, c.cellStart)}
                                        on:dblclick|stopPropagation
                                        on:mouseenter={(e) => onCellEnter(e, c.cellStart, c.cellEnd)}
                                        on:mouseleave={onCellLeave}
                                        on:keydown={() => {}}
                                        role="button"
                                        tabindex="-1"
                                    >
                                        <span class="g" style={c.renderStyle}>{c.glyph}</span>
                                    </span>
                                </span>
                            {/each}
                        </span>
                    {/each}
                </div>
            {/if}
            <div class="mega-phonemes" class:hidden={!$showPhonemes} dir="rtl">
                {#each block.phonemes as ph (ph.index)}
                    {@const parts = splitPhone(ph.interval.phone)}
                    <span
                        class="mega-phoneme"
                        class:silence={!ph.interval.phone ||
                            ph.interval.phone === 'sil' ||
                            ph.interval.phone === 'sp'}
                        class:geminate={ph.interval.geminate_start}
                        data-index={ph.index}
                        on:click={(e) => onPhonemeClick(e, ph.interval, ph.index, block.wordIndex)}
                        on:dblclick={(e) => onPhonemeDblClick(e, ph.interval, ph.index, block.wordIndex)}
                        on:mouseenter={(e) => onPhonemeEnter(e, ph.interval)}
                        on:mouseleave={onHoverLeave}
                        on:keydown={() => {}}
                        role="button"
                        tabindex="-1"
                    >
                        <span class="ph-base">{parts.base || '(sil)'}</span>{#if parts.mod}<sup class="ph-mod">{parts.mod}</sup>{/if}
                    </span>
                {/each}
            </div>
        </div>
    {/each}
    {#if tipText}
        <div class="cell-tip" dir="ltr" style="left:{tipX}px; top:{tipY}px;" aria-hidden="true">{tipText}</div>
    {/if}
</div>
