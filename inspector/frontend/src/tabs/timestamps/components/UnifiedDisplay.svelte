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

    import { onDestroy, onMount, tick, untrack } from 'svelte';
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
        FATHA,
        firstMark,
        implicitMaddGlyph,
        MEEM,
        MEEM_HI,
        MEEM_LO,
        NOON,
        OPEN_TANWEEN,
        OPEN_TANWEEN_TAGS,
        SHADDA,
        SUKUN,
    } from '../utils/tajweed-script';
    import {
        badgesForTags,
        isBridgeTag,
        silentTooltip,
        tagsForLegend,
        tjKubraColor,
        tjRuleNames,
        tjShadow,
        type TjBadge,
    } from '../utils/tajweed-rules';
    import { isRuleEnabled, tajweedSettings, type TajweedSettings } from '../stores/tajweed-settings';
    import {
        applyHamzaWaslMadd,
        iqlabNoonMiniMeem,
        iqlabNoonSilentBase,
        shedSilahMaddah,
        silahMaddahSources,
        wearSilahMaddah,
    } from '../utils/cell-special-cases';
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
        /** A written-but-"added" full cell (the madd-ʿiwaḍ alef substituted for the
         *  fatḥatan at waqf) — carries the muted dashed inserted border, like the
         *  implicit madd, without being implicit. */
        inserted: boolean;
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
        /** Flat interval indices this cell sounds — placed under its own column. */
        phoneIdx: number[];
        /** Ordered tajweed underline badges (bottom→top, tafkheem on top) — composed
         *  into a box-shadow at render, filtered by the live enable set. */
        tjBadges: TjBadge[];
        /** Silent-rule hover names (no underline) shown in the cell tooltip. */
        silentRules: string[];
    }

    /** A SMALL diacritic cell — haraka / tanween / an iqlab tanwīn's own mini-meem
     *  cell / inserted graphemeless vowels. Pins top or bottom of the group's
     *  letter row. Sukūn cells are filtered out upstream and never become one. */
    interface RenderedSmall {
        /** The combining mark to render — a single haraka/tanwīn or mini-meem. */
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
        /** Flat interval indices this cell sounds — placed under its own column. */
        phoneIdx: number[];
        /** Ordered tajweed underline badges (bottom→top, tafkheem on top). */
        tjBadges: TjBadge[];
        /** Silent-rule hover names (no underline) shown in the cell tooltip. */
        silentRules: string[];
    }

    /** A rendered cell-group. `kind` drives the in-row order:
     *  - `base`  : a consonant (+ its short haraka/tanwīn) → full THEN small.
     *  - `vowel` : a long-vowel unit [diacritic + carrier] (base lives in its own
     *    separate group) or a standalone/implicit madd → small THEN full, so the
     *    diacritic precedes the vowel grapheme it pairs with.
     *  Gap 0 within a group, non-zero between groups. */
    /** One grapheme's column within a group: the row-1 cell (a full letter OR a
     *  small diacritic) whose phonemes render directly beneath it in row 2. */
    interface GraphemeColumn {
        full: RenderedFull | null;
        small: RenderedSmall | null;
    }

    /** A row-2 phoneme placement: the phonemes sounding under column `colStart`,
     *  spanning `span` columns when adjacent graphemes share one sound. */
    interface PhonemeSpan {
        phonemes: RenderedPhoneme[];
        colStart: number;
        span: number;
    }

    interface RenderedGroup {
        kind: 'base' | 'vowel';
        full: RenderedFull[];
        small: RenderedSmall[];
        shareGroup: number | null;
        /** Ordered grapheme columns (reading order) — the group's row-1 cells. */
        cols: GraphemeColumn[];
        /** Row-2 phoneme placements, each aligned under its source grapheme so a
         *  silent grapheme leaves an empty slot and a vowel sits under its mark. */
        phonemeSpans: PhonemeSpan[];
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
        /** Ordered tajweed underline badges (bottom→top, tafkheem on top). */
        tjBadges: TjBadge[];
        /** DISPLAY-only phone override (the shard keeps `interval.phone`): a heavy
         *  ikhfaa nasal `ŋ` shown as `ŋˤ` before an istiʿlāʾ letter. Render sites
         *  prefer this over `interval.phone`; null/undefined → use the raw phone. */
        displayPhone?: string;
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
            /** Silent-rule hover names (the iltiqaa-sākinayn connecting kasra). */
            silentRules: string[];
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

    /** A justification line-unit: an unbreakable run of word block(s) — bridge-
     *  linked words stay together — plus an optional trailing pause cell, all
     *  rendered inside one `.word-unit`. The whole unit is the atom the row
     *  justifies between, so a bridged pair never splits across rows and a
     *  word+stop-cell stays glued with the stop cell as the flush anchor. */
    type RenderedUnitPart =
        | { kind: 'block'; block: RenderedBlock }
        | { kind: 'bridge'; bridge: RenderedBridge; wordIndex: number }
        | { kind: 'pause'; pause: RenderedPauseBridge };
    interface RenderedUnit {
        /** First block's wordIndex — the keyed-each identity. */
        key: number;
        parts: RenderedUnitPart[];
        /** Array index of the unit's last block (for bridge-join adjacency). */
        lastBlockIndex: number;
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

    // Group blocks into unbreakable `.word-unit`s (a bridge OR pause connector
    // pairs its two words into one unit). Centered rows share ONE uniform gap —
    // see `.word-unit` / `.unified-display` in timestamps.css and `recomputeRowGap`.
    $: units = groupUnits(rendered);

    // --- Uniform, capped inter-unit gap -------------------------------------
    // Centered rows with a flat gap leave wide edges on sparse rows. Instead size
    // ONE shared column-gap to flush the DENSEST wrapped row (the gap that exactly
    // fills the row with the least slack), clamped to [MIN, MAX]: dense rows fill
    // the width, sparser rows still center but with a smaller edge, and the gap
    // can never blow out. Re-measured on content/tier/size/font changes.
    const ROW_GAP_MIN = 16; // mirrors --mega-line-gap (base.css)
    const ROW_GAP_MAX = 40; // cap so a sparse row never opens an absurd gap
    const ROW_BUCKET_TOL = 1; // px — fold near-equal unit bottoms into one visual row
    let rowGapPx = ROW_GAP_MIN;

    function setRowGap(g: number): void {
        if (Math.abs(g - rowGapPx) > 0.5) rowGapPx = g;
    }

    /** Size the shared column-gap to the largest value that won't overflow any
     *  wrapped row, clamped to [MIN, MAX]. Units bottom-align (flex-end), so a row
     *  is the set of units sharing a rendered bottom edge. */
    function recomputeRowGap(): void {
        if (!rootEl || $loadedVerse === null) return;
        const unitEls = rootEl.querySelectorAll<HTMLElement>('.word-unit');
        if (unitEls.length < 2) {
            setRowGap(ROW_GAP_MIN);
            return;
        }
        const cs = getComputedStyle(rootEl);
        const innerW =
            rootEl.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
        const rows = new Map<number, { free: number; n: number }>();
        unitEls.forEach((u) => {
            const r = u.getBoundingClientRect();
            let key = Math.round(r.bottom);
            // snap to an existing row whose bottom is within a sub-pixel/zoom hair,
            // so one visual row never splits into two buckets (or vice-versa).
            for (const k of rows.keys()) {
                if (Math.abs(k - key) <= ROW_BUCKET_TOL) {
                    key = k;
                    break;
                }
            }
            const row = rows.get(key) ?? { free: innerW, n: 0 };
            row.free -= r.width;
            row.n += 1;
            rows.set(key, row);
        });
        let minFlush = Infinity;
        rows.forEach(({ free, n }) => {
            if (n > 1) minFlush = Math.min(minFlush, free / (n - 1));
        });
        setRowGap(
            Number.isFinite(minFlush)
                ? Math.max(ROW_GAP_MIN, Math.min(minFlush, ROW_GAP_MAX))
                : ROW_GAP_MIN,
        );
    }

    // Re-measure after the DOM reflects a content or tier-visibility change (the
    // leading refs are the tracked reactive deps); container resize / web-font swap
    // are caught by the ResizeObserver + fonts.ready below.
    function scheduleGapRecompute(): void {
        void tick().then(recomputeRowGap);
    }
    $: units, $showLetters, $showPhonemes, $showTranslations, scheduleGapRecompute();

    onMount(() => {
        if (typeof ResizeObserver === 'undefined') return;
        const ro = new ResizeObserver(() => recomputeRowGap());
        ro.observe(rootEl);
        if (document.fonts) void document.fonts.ready.then(() => recomputeRowGap());
        return () => ro.disconnect();
    });

    // Reset previous-index cache when structure changes (new verse, etc.)
    $: rendered, (_prevActiveWordIdx = -1);
    $: rendered, (_prevActivePhonemeIdx = -1);
    // Force the loop-highlight diff-gate to re-apply after a structural render
    // (reused keyed nodes can carry a stale `.loop` class).
    $: rendered, (_prevLoopKey = '\0');
    // Clear stale highlight classes on verse change. The keyed `{#each}` reuses
    // DOM nodes whose `block.wordIndex` matches across verses (typically 0,1,2…),
    // so without this the prior verse's `.active`/`.past` classes survive on
    // reused nodes until the next rAF tick. Between auto-next pause-and-flush
    // and the new audio's `play` event the rAF loop is stopped, so the user
    // sees the stale highlight pinned on the old word until playback resumes.
    $: rendered, _resetHighlightClasses();
    // Measure the natural-width sample cell after each structural render so the
    // small diacritic cells (sized as a factor of --letter-cell-w/h) track the
    // letter box at the current zoom. tick() waits for the DOM to flush.
    $: rendered, untrack(() => void tick().then(() => { _measureLetterCell(); _rebuildHighlightCache(); }));
    function _measureLetterCell(): void {
        if (!rootEl) return;
        // A dedicated natural-width sample, NOT a live letter cell — live cells
        // stretch to fill their column, which would inflate every dia-track.
        const sample = rootEl.querySelector<HTMLElement>('.letter-metrics');
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
        harakas: HTMLElement[];
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
            harakas: q('.haraka-cell[data-dia-loop-idx]'),
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
        rootEl.querySelectorAll<HTMLElement>('.group-hover').forEach((c) => c.classList.remove('group-hover'));
        rootEl.querySelectorAll<HTMLElement>('.mega-grid').forEach((g) => { g.dataset.hoverGi = ''; });
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

    /** Iẓhar — the phonemizer emits NO izhar tag, so it's synthesized here as the
     *  DEFAULT rule for a sounding, untagged, SAKIN noon/meem/tanwīn (the fallback
     *  when no assimilation/conversion rule fired). Two colours: ḥalqī (noon/tanwīn
     *  before a throat letter) vs shafawī (sakin meem). `voweledSrc` is the set of
     *  source-letter indices in the cell's word that carry a real (non-sukūn) vowel,
     *  used to decide a noon/meem is sakin. Returns the synthetic tag or null. */
    function _izharTag(c: TsCell, voweledSrc: Set<number>): 'izhar_halqi' | 'izhar_shafawi' | null {
        if (!c.phonemeIndices.length || c.tag != null || c.shareGroup != null) return null;
        // A tanwīn IS an inherent word-final nūn sound → ḥalqī when untagged.
        if (c.role === 'tanween') return 'izhar_halqi';
        if (c.role !== 'base') return null;
        const head = [...c.chars][0];
        if (c.chars.includes(SHADDA)) return null; // mushaddad → ghunnah, not izhar
        if (voweledSrc.has(c.sourceLetterIndex)) return null; // voweled → not sakin
        if (head === NOON) return 'izhar_halqi';
        if (head === MEEM) return 'izhar_shafawi';
        return null;
    }

    /** Source-letter indices in a word that carry a real (sounding, non-sukūn)
     *  haraka — a noon/meem on one of these is voweled, not sakin (so not iẓhar). A
     *  tanwīn also vowels its base letter (a meem with ḍammatan is مُ, never sākin), so
     *  count it too — else a tanwīn'd meem/noon falsely reads as a sākin iẓhar source. */
    function _voweledSrcSet(cells: TsCell[]): Set<number> {
        const s = new Set<number>();
        for (const c of cells) {
            if (c.phonemeIndices.length
                && ((c.role === 'haraka' && !_isSukunCell(c)) || c.role === 'tanween')) {
                s.add(c.sourceLetterIndex);
            }
        }
        return s;
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

    /** Qalqala cell tags (ṣughrā mid-word, kubrā at a stop) — derived from the
     *  registry so the tag keys live in one place. */
    const QALQALA_TAGS = tagsForLegend('qalqala');

    /** A qalqala consonant's render-only echo `Q` immediately follows its phoneme
     *  in `intervals[]` but is in NO cell's indexable `phonemeIndices` (excluded by
     *  design — making it indexable would shift the indexable/bridge index space and
     *  break shard byte-parity). For a qalqala cell, return the `[start,end]` of the
     *  `Q` directly after the cell's last own phoneme so its cell duration can include
     *  the echo; null when there's no such echo. */
    function _qalqalaEchoIv(
        indices: number[],
        intervals: PhonemeInterval[],
    ): [number, number] | null {
        if (!indices.length) return null;
        const after = Math.max(...indices) + 1;
        const iv = intervals[after];
        return iv && iv.phone === 'Q' ? [iv.start, iv.end] : null;
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

    /** Per-group interval of a cross-word merger's ghunnah nasal phone (m̃ ñ j̃ w̃).
     *  Only groups whose merged sound is a nasal appear. A receiving carrier in such
     *  a group sounds only that ghunnah, not the source tanwīn's haraka — so its OWN
     *  click/loop/tooltip span is THIS interval, while the highlight span keeps the
     *  full haraka+ghunnah union. Nasals are the only tilde-bearing phones. */
    function _nasalUnions(
        cells: TsCell[],
        intervals: PhonemeInterval[],
    ): Map<number, [number, number]> {
        const unions = new Map<number, [number, number]>();
        for (const c of cells) {
            if (c.shareGroup == null) continue;
            for (const i of c.phonemeIndices) {
                const iv = intervals[i];
                // U+0303 combining tilde marks every ghunnah nasal (m̃ ñ j̃ w̃).
                if (!iv || !iv.phone.normalize('NFD').includes('̃')) continue;
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
        nasalUnions: Map<number, [number, number]>,
        idghamGroupTags: Map<number, string>,
        izharCellTag: Map<TsCell, string>,
        liftIltiqaa = false,
    ): RenderedGroup[] {
        const { folded, srcToFold } = foldedLettersFor(word);
        // The iltiqaa-kasra cell is lifted into a cross-word bridge — drop it from
        // the word's own letter row so it renders only between the two words. The
        // hamza-waṣl ibtidaa madd (ٱئْتُونِى) re-pairs its kasra + dropped seat into a
        // shared vowel group — see cell-special-cases (no-op for other words).
        const cells = applyHamzaWaslMadd(
            (word.cells ?? []).filter((c) => !(liftIltiqaa && c.tag === 'iltiqaa_kasra')),
        );
        // A renderable anchor is a base cell OR a real madd carrier (chars != '').
        // Muqattaat whose letters are all spelled-out names (كٓهيعٓصٓ, عٓسٓقٓ, صٓ, قٓ …)
        // carry no base cell but ARE full graphemes — they render through the main
        // per-cell loop (carriers via pushFullGrapheme → madd underline + columns),
        // exactly like alif-led muqattaat (الٓمٓ). Only a truly anchor-less word
        // (diacritic-only fixtures) drops to the synthetic fallback below.
        const hasAnchor = cells.some(
            (c) => c.role === 'base' || (c.role === 'madd' && c.chars !== ''),
        );
        const groups: RenderedGroup[] = [];

        // A cell's underline stack: its own tag + secondary tafkheem + synthesized
        // iẓhar + the cross-word idgham tag propagated to a merger receiver (its
        // share group's source tag) + a heavy-ikhfaa tafkheem (the nasal before an
        // istiʿlāʾ letter, detected display-side). Resolved to ≤2 bars (base + tafkheem).
        const cellBadges = (c: TsCell): TjBadge[] => {
            const groupTag = c.shareGroup != null ? idghamGroupTags.get(c.shareGroup) : undefined;
            // A muqattaat letter's heaviness rides its own `secondaryTags` tafkhīm (set
            // on a heavy istiʿlāʾ / rāʾ name), NOT a buried ikhfaa nasal — so عَيْن's
            // heavy ŋˤ tafkhīm stays on the phoneme row, off the bare ع glyph.
            const isMuq = !!c.phonemeRuleTags?.length;
            const heavyIkhfaa = !isMuq && c.phonemeIndices.some(
                (fi) => _heavyIkhfaaDisplay(intervals[fi]?.phone, intervals[fi + 1]?.phone),
            );
            return badgesForTags([
                c.tag, ...(c.secondaryTags ?? []), izharCellTag.get(c), groupTag,
                heavyIkhfaa ? 'tafkheem' : undefined,
            ]);
        };
        // Context-derived silent-rule names (need the cell's neighbours): a trailing
        // dropped ḥaraka/tanwīn with nothing sounding after it is the word-final
        // vowel silenced at the stop → "Waqf"; the dropped fatḥatan whose
        // compensating madd moved onto the next ʾalif at waqf → "Madd 'Iwad" (the
        // ʾalif carries the bar); a silent alef/maqṣūra right after a tanwīn is the
        // otiose ʿiwaḍ alef at waṣl → "Madd 'Iwad Wasl".
        const extraSilent = new Map<TsCell, string>();
        {
            let lastSounding = -1;
            cells.forEach((c, i) => { if (c.phonemeIndices.length) lastSounding = i; });
            cells.forEach((c, i) => {
                if ((c.role === 'haraka' || c.role === 'tanween') && c.status === 'dropped'
                    && c.phonemeIndices.length === 0 && cells[i + 1]?.tag === 'madd_iwad') {
                    extraSilent.set(c, "Madd 'Iwad");
                } else if (c.role === 'madd' && c.tag === 'madd_iwad') {
                    // The sounding iwaḍ ʾalif names the rule on hover even when its madd
                    // underline (gated by the madd-ṭabīʿī toggle) is off — matching the fatḥa.
                    extraSilent.set(c, "Madd 'Iwad");
                } else if ((c.role === 'haraka' || c.role === 'tanween') && c.status === 'dropped'
                    && c.phonemeIndices.length === 0 && i > lastSounding) {
                    extraSilent.set(c, 'Waqf');
                } else if (c.role === 'base' && c.phonemeIndices.length === 0
                    && (c.chars === 'ا' || c.chars === 'ى') && cells[i - 1]?.role === 'tanween') {
                    extraSilent.set(c, "Madd 'Iwad Wasl");
                }
            });
        }
        // A cell's silent-rule hover names (lām shamsiyyah, hamzat-waṣl, iltiqaa, the
        // context cases above) — these draw no underline, only a tooltip line.
        const cellSilent = (c: TsCell): string[] => {
            const extra = extraSilent.get(c);
            if (extra) return [extra];
            const n = silentTooltip(c.tag);
            return n ? [n] : [];
        };

        // Share-groups that contain a madd carrier = long-vowel units (the haraka
        // pairs with the carrier after it; its base renders separately).
        const longVowelSG = new Set<number>();
        for (const c of cells) {
            if (c.role === 'madd' && c.shareGroup != null) longVowelSG.add(c.shareGroup);
        }
        // Source letters bearing a dropped ṣilah carrier (mini-waw/yaa at waqf, هُۥ/هِۦ):
        // its preceding ḥaraka folds into a shared SILENT vowel group with it, instead
        // of gluing onto the base — resolved in the haraka branch below.
        const droppedSilahSrc = new Set<number>();
        for (const c of cells) {
            if (c.role === 'madd' && c.status === 'dropped' && c.chars) {
                droppedSilahSrc.add(c.sourceLetterIndex);
            }
        }
        // Silah-madd carriers (see cell-special-cases): the maddah the phonemizer
        // merged onto the bearing letter is shed there + re-worn by its carrier.
        const silahMaddahSrc = silahMaddahSources(cells, droppedSilahSrc);
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
        // The dropped fatḥatan whose compensating madd moved onto the next ʾalif at waqf
        // — detected STRUCTURALLY (its own tag is cleared so it draws no underline; the
        // ʾalif carries the bar). The renderer transforms it into a dashed fatḥa co-lit
        // with the ʾalif (see the iwaḍ branch in the cell loop).
        const iwadFathatan = new Set<TsCell>();
        cells.forEach((c, i) => {
            if ((c.role === 'tanween' || c.role === 'haraka') && c.status === 'dropped'
                && c.phonemeIndices.length === 0 && cells[i + 1]?.tag === 'madd_iwad') {
                iwadFathatan.add(c);
            }
        });
        const daggerBySrc = new Map<number, { group: RenderedGroup; iv: [number, number] }>();
        // و/ى waqf carrier → its vowel group, so the carrier's own dropped fatḥa
        // rejoins it silently (a double-sided [haraka, carrier, dropped-fatḥa] unit)
        // instead of landing on the preceding base.
        const carrierGroupBySrc = new Map<number, RenderedGroup>();
        let iwadGroup: RenderedGroup | null = null;

        const newGroup = (kind: 'base' | 'vowel'): RenderedGroup => {
            const g: RenderedGroup = { kind, full: [], small: [], shareGroup: null, cols: [], phonemeSpans: [] };
            groups.push(g);
            return g;
        };
        // Carry a cell's share-group onto its group (the synchronized-highlight cue).
        const noteShare = (g: RenderedGroup, c: TsCell): void => {
            if (c.shareGroup != null && g.shareGroup == null) g.shareGroup = c.shareGroup;
        };

        const pushSmall = (
            g: RenderedGroup,
            c: TsCell,
            opts: { coLightIv?: [number, number]; glyphOverride?: string; inserted?: boolean } = {},
        ): void => {
            const phone = c.phonemeIndices.length ? intervals[c.phonemeIndices[0]!]?.phone : undefined;
            const shareIv = c.shareGroup != null ? shareUnions.get(c.shareGroup) ?? null : null;
            let { start, end } = _cellTiming(c.phonemeIndices, intervals, shareIv);
            if (opts.coLightIv) [start, end] = opts.coLightIv; // co-light on the carrier's interval
            const mark = firstMark(c.chars);
            let glyph: string;
            let slot: 'top' | 'bottom';
            let sizeGlyph: string;
            let extraShift = 0;
            if (opts.glyphOverride) {
                glyph = opts.glyphOverride;
                slot = cellSlot(glyph);
                sizeGlyph = glyph;
            } else if (c.role === 'tanween' && OPEN_TANWEEN[mark] && OPEN_TANWEEN_TAGS.has(c.tag ?? '')) {
                // Assimilated tanwīn (idgham / ikhfaa) renders OPEN (DK encodes it
                // as a distinct codepoint); iẓhar (tagless) keeps the stacked form.
                // Slot follows the canonical mark (kasratan below, others above).
                glyph = OPEN_TANWEEN[mark]!;
                slot = cellSlot(mark);
                sizeGlyph = glyph;
            } else {
                glyph = cellGlyph(c.chars, c.tag, phone);
                // Iqlab mini-meem: the displayed GLYPH is always the low-meem
                // (cellGlyph normalises it), but its SLOT + calibration follow the
                // SOURCE haraka the phonemizer stamped — MEEM_HI (ḍamma/fatḥa) sits
                // ABOVE, MEEM_LO (kasra) below — so a non-kasra iqlab meem is on top.
                const meemSrc = mark === MEEM_HI || mark === MEEM_LO;
                slot = meemSrc ? cellSlot(mark) : cellSlot(glyph);
                sizeGlyph = meemSrc ? mark : glyph;
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
                renderStyle: harakaRenderStyle(sizeGlyph, extraShift),
                inserted: opts.inserted ?? (c.chars === '' && c.status === 'inserted'),
                phoneIdx: c.phonemeIndices,
                // Diacritic cells underline from their OWN tag (tanwīn idgham/ikhfaa/
                // iqlab) or the synthesized iẓhar rule (an untagged sounding tanwīn);
                // a madd's haraka has no tag → no underline.
                tjBadges: cellBadges(c),
                silentRules: cellSilent(c),
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
        const pushFullGrapheme = (
            g: RenderedGroup,
            c: TsCell,
            isBase: boolean,
            opts: { glyphOverride?: string } = {},
        ): void => {
            const shareIv = c.shareGroup != null ? shareUnions.get(c.shareGroup) ?? null : null;
            const { start: ownStart, end: ownEnd } = _cellTiming(c.phonemeIndices, intervals, shareIv);
            // Qalqala: cover the render-only `Q` echo right after this consonant
            // (the echo is in intervals[] but no cell indexes it). BOTH the highlight
            // span (cellStart/cellEnd) AND the letter's own [start,end] grow to the
            // echo end, so click-seek, tooltip duration and loop all run the
            // consonant + its echo as one unit. Applied to the letter span below.
            let start = ownStart;
            let end = ownEnd;
            const qalqalaEcho =
                QALQALA_TAGS.has(c.tag ?? '') && ownEnd != null
                    ? _qalqalaEchoIv(c.phonemeIndices, intervals)
                    : null;
            if (qalqalaEcho) {
                start = start != null ? Math.min(start, qalqalaEcho[0]) : qalqalaEcho[0];
                end = Math.max(end!, qalqalaEcho[1]);
            }
            let glyph: string;
            let silent: boolean;
            let lStart: number | null;
            let lEnd: number | null;
            let isNull: boolean;
            let letterIndex: number;
            if (c.chars) {
                // canonical text (shaddah already composed by the phonemizer);
                // glyphOverride relocates a silah maddah off the bearing letter.
                glyph = opts.glyphOverride ?? c.chars;
                // Silent = sounds nothing (no own phoneme indices) AND isn't co-lit through
                // a merger (no share group). Keyed on the indices, NOT a specific status, so
                // every soundless carrier greys uniformly — a `dropped` otiose alef, a
                // `shortened` iltiqāʾ carrier, etc. (A merger-receiving idgham-noon source
                // noon has no own phones but a share group, so it stays a normal co-lit cell.)
                silent = c.phonemeIndices.length === 0 && c.shareGroup == null;
                lStart = ownStart;
                lEnd = ownEnd;
                isNull = ownStart == null;
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
            // A receiving carrier in a cross-word nasal merger (idgham / shafawi)
            // sounds only the ghunnah, not the source tanwīn's haraka. Point its OWN
            // click/loop/tooltip span at that nasal phone — the highlight span
            // (cellStart/cellEnd) keeps the full co-lit haraka+ghunnah union. Both
            // merged letters (e.g. the two shafawi meems) thus read the same nasal.
            const nasalIv = c.shareGroup != null ? nasalUnions.get(c.shareGroup) : undefined;
            if (nasalIv && lStart != null) {
                lStart = nasalIv[0];
                lEnd = nasalIv[1];
            }
            // Qalqala: the letter's click/loop/tooltip span runs through the echo too.
            if (qalqalaEcho && lEnd != null) {
                lStart = lStart != null ? Math.min(lStart, qalqalaEcho[0]) : qalqalaEcho[0];
                lEnd = Math.max(lEnd, qalqalaEcho[1]);
            }
            // Own tag + secondary tafkheem + synthesized iẓhar + the propagated
            // cross-word idgham (the receiving merged letter). Un-greying is driven
            // by co-light (a share group, folded into `silent` above), NOT by merely
            // carrying a badge: a co-lit merge source (mutamāthilayn, noon idgham)
            // reads visible + underlined, while a silent-but-tagged source
            // (mutaqāribayn / mutajānisayn) stays greyed yet still draws its
            // underline + tooltip.
            const badges = cellBadges(c);
            g.full.push({
                glyph,
                silent,
                status: c.status,
                tag: c.tag,
                implicit: false,
                // The written madd-ʿiwaḍ alef (substitutes the fatḥatan at waqf) is
                // "added, not in the rasm" → the muted dashed inserted border.
                inserted: c.tag === 'madd_iwad',
                isBase,
                cellStart: start,
                cellEnd: end,
                letterStart: lStart,
                letterEnd: lEnd,
                isNull,
                letterIndex,
                shareGroup: c.shareGroup,
                phoneIdx: c.phonemeIndices,
                tjBadges: badges,
                silentRules: cellSilent(c),
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
                inserted: false,
                isBase: false,
                cellStart: start,
                cellEnd: end,
                letterStart: null,
                letterEnd: null,
                isNull: true,
                letterIndex: -1,
                shareGroup: c.shareGroup,
                phoneIdx: c.phonemeIndices,
                // Implicit madd (dagger-alef of Allah / ʿiwaḍ alef) — both underline
                // with the madd-ṭabīʿī rule.
                tjBadges: cellBadges(c),
                silentRules: cellSilent(c),
            });
            noteShare(g, c);
        };

        if (hasAnchor) {
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
                    if (c.tag === 'iqlab_noon') {
                        // Iqlab noon → silent ن + a synthesized stacked mini-meem (see
                        // cell-special-cases): the meem owns the nasal + the iqlab underline.
                        pushFullGrapheme(curBase, iqlabNoonSilentBase(c), false);
                        pushSmall(curBase, iqlabNoonMiniMeem(c));
                    } else if (silahMaddahSrc.has(c.sourceLetterIndex)) {
                        pushFullGrapheme(curBase, c, true, { glyphOverride: shedSilahMaddah(c.chars) });
                    } else {
                        pushFullGrapheme(curBase, c, true);
                    }
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
                        // An implicit (chars='') non-iwaḍ madd is the Allah dagger-alef —
                        // tagged allah_dagger_alef (ṭabīʿī) or madd_arid_lissukun (ʿāriḍ at
                        // waqf). Co-light its dropped fatḥa with the dagger either way.
                        const iv = ownIv(c);
                        if (iv) daggerBySrc.set(c.sourceLetterIndex, { group: g, iv });
                    } else {
                        const lv = c.shareGroup != null && longVowelSG.has(c.shareGroup);
                        // A dropped ṣilah carrier reuses the vowel group its own ḥaraka
                        // already opened (the ḥaraka is emitted first); else a fresh one.
                        const cg = carrierGroupBySrc.get(c.sourceLetterIndex)
                            ?? (lv ? vowelGroupFor(c.shareGroup!) : newGroup('vowel'));
                        // A silah carrier bearing a madd wears the maddah shed by its
                        // bearing letter (هٓ → ه + ۥٓ) — see cell-special-cases.
                        pushFullGrapheme(
                            cg,
                            c,
                            false,
                            silahMaddahSrc.has(c.sourceLetterIndex) ? { glyphOverride: wearSilahMaddah(c.chars) } : {},
                        );
                        carrierGroupBySrc.set(c.sourceLetterIndex, cg);
                    }
                } else {
                    // haraka / tanwīn
                    const dropped = c.phonemeIndices.length === 0;
                    if (c.shareGroup != null && longVowelSG.has(c.shareGroup)) {
                        pushSmall(vowelGroupFor(c.shareGroup), c); // long vowel — leaves its base
                    } else if (dropped && iwadFathatan.has(c) && iwadIv) {
                        // dropped tanwīn at waqf → a fatḥa grouped + co-lit with the iwaḍ
                        // alef. The fatḥatan→fatḥa transform is "not in the rasm" — flag it
                        // inserted so the small fatḥa cell carries the muted dashed border.
                        // (Detected structurally — its tag is cleared so it draws no bar.)
                        iwadGroup = iwadGroup ?? newGroup('vowel');
                        pushSmall(iwadGroup, c, { coLightIv: iwadIv, glyphOverride: FATHA, inserted: true });
                    } else if (dropped && daggerBySrc.has(c.sourceLetterIndex)) {
                        const d = daggerBySrc.get(c.sourceLetterIndex)!;
                        pushSmall(d.group, c, { coLightIv: d.iv }); // Allah: fatḥa joins the dagger ā
                    } else if (dropped && carrierGroupBySrc.has(c.sourceLetterIndex)) {
                        // و/ى waqf: the carrier stole the haraka before it into a madd;
                        // its own fatḥa drops at the stop. Render it silent in the
                        // carrier's vowel group (after it), not on the preceding base.
                        pushSmall(carrierGroupBySrc.get(c.sourceLetterIndex)!, c);
                    } else if (dropped && droppedSilahSrc.has(c.sourceLetterIndex)) {
                        // Dropped ṣilah ḥaraka (هُۥ/هِۦ at waqf): OPEN the shared silent
                        // vowel group here so the ḍamma/kasra pairs with its mini-waw/yaa
                        // as one [ḥaraka, carrier] unit, instead of landing on the haa.
                        const cg = newGroup('vowel');
                        carrierGroupBySrc.set(c.sourceLetterIndex, cg);
                        pushSmall(cg, c);
                    } else {
                        // short vowel / true waqf drop — and the idgham-shafawi
                        // receiving meem's vowel, which the phonemizer now keeps on the
                        // haraka alone (own interval, no merger group), so it lights here
                        // on its own vowel without smearing across the merger.
                        pushSmall(curBase ?? (curBase = newGroup('base')), c);
                    }
                }
            }
            return groups;
        }

        // --- Synthetic-base fallback: no base AND no real carrier cells
        //     (diacritic-only fixtures). One group per folded letter, with the
        //     word's diacritic cells attached. ---
        const groupByFold: RenderedGroup[] = folded.map((fl, i) => {
            const g = newGroup('base');
            g.full.push({
                glyph: fl.glyph,
                silent: fl.silent,
                status: 'present',
                tag: null,
                implicit: false,
                inserted: false,
                isBase: true,
                cellStart: fl.start,
                cellEnd: fl.end,
                letterStart: fl.start,
                letterEnd: fl.end,
                isNull: fl.isNull,
                letterIndex: i,
                shareGroup: null,
                phoneIdx: [],
                tjBadges: [],
                silentRules: [],
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
    // the consonant symbol (rˤ, dˤ, sˤ, tˤ, ðˤ) and must stay in the base.
    const PHONE_MOD_RE = /([ː:]+)$/u;
    // Only the SHORT emphatic open vowel `aˤ` (heavy `a` after an istiʿlāʾ
    // consonant) DISPLAYS as a plain `a` — the emphasis is a vowel quality, not a
    // separate symbol like a consonant emphatic. The LONG emphatic `aˤ:` keeps its
    // ˤ (the emphasis stays on a held vowel). Display-only: the shard keeps `aˤ`.
    const EMPHATIC_A_RE = /^aˤ$/u;
    function splitPhone(phone: string | undefined): { base: string; mod: string } {
        if (!phone || phone === 'sil' || phone === 'sp') return { base: phone ?? '', mod: '' };
        if (EMPHATIC_A_RE.test(phone)) return { base: 'a', mod: '' };
        const m = PHONE_MOD_RE.exec(phone);
        return m ? { base: phone.slice(0, -m[0].length), mod: m[0] } : { base: phone, mod: '' };
    }

    /** The istiʿlāʾ (heavy) consonants among the 15 ikhfaa letters — ص ض ط ظ ق,
     *  whose base phones are `sˤ dˤ tˤ ðˤ q`. The ikhfaa nasal `ŋ` before one of
     *  these is articulated heavy (tafkhīm). */
    const HEAVY_IKHFAA_PHONES = new Set(['sˤ', 'dˤ', 'tˤ', 'ðˤ', 'q']);
    /** The emphatic long vowel `aˤ:` — a muqattaat heavy letter's vowel (ṣād's aˤ:,
     *  qāf's aˤ:, the heavy rāʾ's aˤ:). It stacks tafkhīm above its madd bar. */
    const HEAVY_VOWEL_PHONES = new Set(['aˤ:']);
    /** DISPLAY-only ikhfaa-heavy override: a plain ikhfaa nasal `ŋ` immediately
     *  before a heavy istiʿlāʾ consonant renders as `ŋˤ`. Returns the override
     *  phone, or undefined when no transform applies (the raw phone is used). The
     *  GATE skips a phone that is ALREADY `ŋˤ` so a future phonemizer-side heavy
     *  nasal wins unchanged. */
    function _heavyIkhfaaDisplay(phone: string | undefined, nextPhone: string | undefined): string | undefined {
        if (phone !== 'ŋ' || !nextPhone) return undefined;
        return HEAVY_IKHFAA_PHONES.has(nextPhone) ? 'ŋˤ' : undefined;
    }

    /** Assign each rendered phoneme to the grapheme COLUMN(s) that sound it, then
     *  pack the phonemes into row-2 clusters that SPAN those columns. So a phoneme
     *  sits beneath the grapheme(s) it belongs to:
     *   - 1 grapheme : 1 sound  → its own column (the cluster fills it; edges shared);
     *   - many graphemes : 1 sound (long vowel, share-group) → the cluster spans the
     *     unit's columns and centres across them (not pinned under one sub-column);
     *   - 1 grapheme : many sounds → the cluster stays in the single column, which
     *     widens to fit.
     *  A silent grapheme indexes nothing → empty slot. A render-only phone no cell
     *  indexes (qalqala echo `Q`) rides the preceding phoneme's columns. */
    function _buildColumns(groups: RenderedGroup[], phonemes: RenderedPhoneme[]): void {
        if (!groups.length) return;
        // phoneme index → owning group + the COLUMN SET that sounds it (a cell's own
        // columns, widened to every column sharing that cell's share-group so a long
        // vowel's lone phone spans both [diacritic, carrier] columns).
        const owner = new Map<number, { g: RenderedGroup; cols: Set<number> }>();
        for (const g of groups) {
            // Vowel group order: [live diacritic(s), carrier, …trailing silent drop].
            // A و/ى waqf carrier's OWN dropped fatḥa renders AFTER the carrier (its
            // glyph order in the word), outside the vowel sound — every other diacritic
            // precedes the carrier as usual. A FULLY-silent vowel group (dropped ṣilah at
            // waqf: ḍamma/kasra + mini-waw/yaa, both silent) is the exception: its
            // ḥaraka leads its carrier (orthographic هُ + ۥ), so the dropped diacritic
            // does NOT trail.
            const liveSmalls = g.small.filter((s) => s.status !== 'dropped');
            const droppedSmalls = g.small.filter((s) => s.status === 'dropped');
            const silentVowel = g.kind === 'vowel' && g.full.length > 0 && g.full.every((f) => f.silent);
            g.cols = g.kind !== 'vowel'
                ? [...g.full.map((f) => ({ full: f, small: null })), ...g.small.map((s) => ({ full: null, small: s }))]
                : silentVowel
                  ? [
                        ...g.small.map((s) => ({ full: null, small: s })),
                        ...g.full.map((f) => ({ full: f, small: null })),
                    ]
                  : [
                        ...liveSmalls.map((s) => ({ full: null, small: s })),
                        ...g.full.map((f) => ({ full: f, small: null })),
                        ...droppedSmalls.map((s) => ({ full: null, small: s })),
                    ];
            g.phonemeSpans = [];
            const sgCols = new Map<number, Set<number>>();
            g.cols.forEach((col, ci) => {
                const sg = col.full?.shareGroup ?? col.small?.shareGroup ?? null;
                if (sg == null) return;
                let s = sgCols.get(sg);
                if (!s) { s = new Set(); sgCols.set(sg, s); }
                s.add(ci);
            });
            g.cols.forEach((col, ci) => {
                const sg = col.full?.shareGroup ?? col.small?.shareGroup ?? null;
                const cols = sg != null ? sgCols.get(sg)! : new Set([ci]);
                for (const idx of col.full?.phoneIdx ?? col.small?.phoneIdx ?? []) {
                    if (!owner.has(idx)) owner.set(idx, { g, cols });
                }
            });
        }
        // Walk phonemes in reading order, merging into a cluster while the column
        // range overlaps the open one (1:many stays one cluster in one column; an
        // unowned phone rides the open cluster). A range change opens a new cluster.
        const acc = new Map<RenderedGroup, PhonemeSpan[]>();
        let cur: { g: RenderedGroup; lo: number; hi: number; span: PhonemeSpan } | null = null;
        for (const p of phonemes) {
            const found = owner.get(p.index);
            const g: RenderedGroup = found?.g ?? cur?.g ?? groups[0]!;
            const lo: number = found ? Math.min(...found.cols) : (cur?.lo ?? 0);
            const hi: number = found ? Math.max(...found.cols) : (cur?.hi ?? 0);
            if (cur && cur.g === g && lo <= cur.hi && hi >= cur.lo) {
                cur.span.phonemes.push(p);
                cur.lo = Math.min(cur.lo, lo);
                cur.hi = Math.max(cur.hi, hi);
                cur.span.colStart = cur.lo;
                cur.span.span = cur.hi - cur.lo + 1;
            } else {
                const span: PhonemeSpan = { phonemes: [p], colStart: lo, span: hi - lo + 1 };
                let spans = acc.get(g);
                if (!spans) acc.set(g, (spans = []));
                spans.push(span);
                cur = { g, lo, hi, span };
            }
        }
        for (const [g, spans] of acc) g.phonemeSpans = spans;

        // A vowel unit is one co-lit sound across its whole group ([diacritic,
        // carrier], implicit/ʿiwaḍ madd, dagger-Allah). Collapse its per-column
        // clusters into ONE cluster spanning every column, centred — so a normal
        // madd, madd-ʿiwaḍ, the Allah dagger-alef and the inserted ʿiwaḍ alef all
        // share the group's full width identically (same sound → same width),
        // regardless of whether they co-light via share-group or interval.
        for (const g of groups) {
            if (g.kind !== 'vowel' || g.phonemeSpans.length === 0) continue;
            const phonemes = g.phonemeSpans.flatMap((s) => s.phonemes);
            // The sound spans [diacritic, carrier] only; a trailing silent drop (a
            // و/ى waqf carrier's dropped fatḥa) sits past the carrier, outside the span.
            const silentTail = g.cols.filter((c) => c.small?.status === 'dropped').length;
            g.phonemeSpans = [{ phonemes, colStart: 0, span: g.cols.length - silentTail }];
        }
    }

    /** Build the per-word `RenderedBlock[]` for the analysis view: cross-word
     *  idgham / iltiqaa bridges lifted to between-word tiles, cell-groups whose
     *  phonemes are aligned per-grapheme to their source columns, and detected
     *  inter-word pause bridges. */
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
        // Share-group interval unions computed VERSE-WIDE (across all words' cells):
        // a cross-word idgham tanwīn shares a group with the receiving word's base,
        // so its highlight must span the haraka + the ghunnah/merger in the next
        // word — a per-word union would miss the other side.
        const allCells = words.flatMap((w) => w.cells ?? []);
        const shareUnions = _shareUnions(allCells, intervals);
        const nasalUnions = _nasalUnions(allCells, intervals);

        // Iẓhar (synthesized): the DEFAULT rule for an untagged sounding sakin
        // noon/meem/tanwīn. Resolved per-word (sakin-ness needs the word's voweling
        // context) into a cell→tag map, fed to BOTH the phoneme-badge map (below) and
        // the letter row (`cellGroupsFor`) so letter + phoneme underline together.
        const izharCellTag = new Map<TsCell, string>();
        for (const w of words) {
            const cells = w?.cells ?? [];
            const voweled = _voweledSrcSet(cells);
            for (const c of cells) {
                const t = _izharTag(c, voweled);
                if (t) izharCellTag.set(c, t);
            }
        }

        // Cross-word idgham SOURCE tag by share group, so a merger RECEIVER inherits
        // the idgham underline from its (silent) source across the group.
        const idghamGroupTags = new Map<number, string>();
        for (const c of allCells) {
            if (isBridgeTag(c.tag) && c.shareGroup != null) idghamGroupTags.set(c.shareGroup, c.tag!);
        }

        // Per-flat-index underline badges, built verse-wide — the single source for
        // BOTH inline phoneme boxes and the cross-word bridge tile (a merger phone is
        // the receiver's). A cell contributes its own tag + secondary tafkheem +
        // synthesized iẓhar + the propagated idgham (group) tag, resolved to the ≤2-bar
        // stack; a muqattaat cell colours each phoneme by its own per-phoneme rule; a
        // tanwīn rule underlines only its nasal (the last phone).
        // Idgham rules whose merger is realized as a separate bridge phone (every
        // cross-word merger). A source carrying one of these has its merger shown in the
        // bridge tile, so its OWN inline phonemes (a leftover tanwīn vowel, or the lifted
        // nasal) carry no badge. A within-word merger (mutajānisayn nāqiṣ) emits no bridge
        // phone, so its sounding source badges its own phoneme.
        const bridgeRules = new Set(
            intervals.map((iv) => iv.bridge).filter((r): r is string => !!r),
        );
        const phonemeBadges = new Map<number, TjBadge[]>();
        for (const c of allCells) {
            if (c.phonemeRuleTags) {
                c.phonemeIndices.forEach((fi, i) => {
                    const t = c.phonemeRuleTags![i];
                    // Qalqala on a muqattaat consonant rides its render-only Q echo
                    // (fi+1) — the echo has no shard slot, so the tag travels on the
                    // consonant and the renderer moves it here (regular-path parity).
                    if (QALQALA_TAGS.has(t ?? '') && intervals[fi + 1]?.phone === 'Q') {
                        const qb = badgesForTags([t]);
                        if (qb.length) phonemeBadges.set(fi + 1, qb);
                        return;
                    }
                    // A heavy long vowel (aˤ:) or a heavy ikhfaa nasal (ŋ before an
                    // istiʿlāʾ consonant, shown ŋˤ) stacks a tafkhīm bar above its own
                    // rule — the consonant's tafkhīm already rides its prt tag `t`.
                    const phone = intervals[fi]?.phone;
                    const heavy = HEAVY_VOWEL_PHONES.has(phone ?? '')
                        || !!_heavyIkhfaaDisplay(phone, intervals[fi + 1]?.phone);
                    const b = badgesForTags(heavy ? [t, 'tafkheem'] : [t]);
                    if (b.length) phonemeBadges.set(fi, b);
                });
                continue;
            }
            // A cross-word idgham source renders its merger as the bridge tile (and
            // colours its own letter via cellBadges) — its own inline phonemes carry no
            // badge: either it's dropped (no phoneme) or its merger is a separate bridge
            // phone. A within-word source (mutajānisayn nāqiṣ ط) has no bridge phone, so
            // it falls through and badges its own sounding phoneme (idgham + its tafkheem).
            if (isBridgeTag(c.tag) && (!c.phonemeIndices.length || bridgeRules.has(c.tag!))) continue;
            const groupTag = c.shareGroup != null ? idghamGroupTags.get(c.shareGroup) : undefined;
            // Qalqala underlines the render-only echo `Q` (the bounce), NOT the
            // consonant phoneme — its consonant keeps only its other rules (tafkheem).
            if (QALQALA_TAGS.has(c.tag ?? '') && c.phonemeIndices.length) {
                const echo = Math.max(...c.phonemeIndices) + 1;
                if (intervals[echo]?.phone === 'Q') {
                    const qb = badgesForTags([c.tag]);
                    if (qb.length) phonemeBadges.set(echo, qb);
                }
                const rest = badgesForTags([...(c.secondaryTags ?? []), izharCellTag.get(c), groupTag]);
                if (rest.length) for (const fi of c.phonemeIndices) phonemeBadges.set(fi, rest);
                continue;
            }
            const baseTags = [c.tag, ...(c.secondaryTags ?? []), izharCellTag.get(c), groupTag];
            const badges = badgesForTags(baseTags);
            if (!badges.length) continue;
            const idxs = c.role === 'tanween' && c.phonemeIndices.length > 1
                ? c.phonemeIndices.slice(-1)
                : c.phonemeIndices;
            // A heavy ikhfaa nasal (ŋ before an istiʿlāʾ letter, shown ŋˤ) stacks a
            // tafkheem bar above its ikhfaa underline.
            for (const fi of idxs) {
                const heavy = !!_heavyIkhfaaDisplay(intervals[fi]?.phone, intervals[fi + 1]?.phone);
                phonemeBadges.set(fi, heavy ? badgesForTags([...baseTags, 'tafkheem']) : badges);
            }
        }

        // Cross-word bridges baked into the shard: a phoneme carrying a `bridge` rule
        // is the idgham merger fusing two words. Lift it into the gold tile at the
        // boundary — a merger at a word's head renders before that block; one in a
        // word's tail (idgham shafawi) bridges into the next block. The tile reuses the
        // merger phone's badges (the receiver's own stack — idgham + its tafkheem),
        // falling back to the raw bridge rule.
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
                        phonemes: [{
                            interval: intervals[pi]!, index: pi,
                            tjBadges: phonemeBadges.get(pi) ?? badgesForTags([intervals[pi]!.bridge]),
                        }],
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
                const sr = silentTooltip(kasra.tag);
                bridgeBeforeBlock.set(wi + 1, {
                    phonemes: [{ interval: iv, index: kpi, tjBadges: [] }],
                    letter: {
                        glyph,
                        style: harakaRenderStyle(glyph),
                        cellStart: iv.start,
                        cellEnd: iv.end,
                        wordIndex: wi,
                        silentRules: sr ? [sr] : [],
                    },
                });
                excluded.add(kpi);
                liftedIltiqaa.add(wi);
            }
        }

        const blocks: RenderedBlock[] = [];
        for (let wi = 0; wi < words.length; wi++) {
            const word = words[wi];
            if (!word) continue;

            const bridge: RenderedBridge | null = bridgeBeforeBlock.get(wi) ?? null;

            const phonemes: RenderedPhoneme[] = [];
            for (const pi of word.phoneme_indices ?? []) {
                if (excluded.has(pi)) continue;
                const iv = intervals[pi];
                if (iv && !iv.geminate_end) {
                    phonemes.push({
                        interval: iv,
                        index: pi,
                        tjBadges: phonemeBadges.get(pi) ?? [],
                        displayPhone: _heavyIkhfaaDisplay(iv.phone, intervals[pi + 1]?.phone),
                    });
                }
            }

            const groups = cellGroupsFor(word, intervals, shareUnions, nasalUnions, idghamGroupTags, izharCellTag, liftedIltiqaa.has(wi));
            _buildColumns(groups, phonemes);

            blocks.push({
                word,
                wordIndex: wi,
                displayText: (word.display_text || word.text).replace(NON_RECITED_SIGNS, ''),
                groups,
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

    /** Group the rendered blocks into unbreakable `.word-unit`s for centered,
     *  uniform-gap rows. A `block.bridge` (idgham / iltiqaa) and a `block.pauseBridge`
     *  (inter-word silence) are both CONNECTORS linking the block to its
     *  predecessor: each pairs the two words into one unit with the connector tile
     *  between them, so neither a bridged pair/chain nor a word+stop-cell splits
     *  across rows. Bridge and pause are mutually exclusive at a boundary (a merger
     *  is contiguous, a pause is a gap); a bridge wins if both ever appear. */
    function groupUnits(blocks: RenderedBlock[]): RenderedUnit[] {
        const units: RenderedUnit[] = [];
        let cur: RenderedUnit | null = null;
        for (let i = 0; i < blocks.length; i++) {
            const block = blocks[i]!;
            const connector: RenderedUnitPart | null = block.bridge
                ? { kind: 'bridge', bridge: block.bridge, wordIndex: block.wordIndex }
                : block.pauseBridge
                  ? { kind: 'pause', pause: block.pauseBridge }
                  : null;
            const joins = connector != null && cur != null && cur.lastBlockIndex === i - 1;
            if (joins) {
                cur!.parts.push(connector!, { kind: 'block', block });
                cur!.lastBlockIndex = i;
            } else {
                cur = { key: block.wordIndex, parts: [], lastBlockIndex: i };
                // Defensive: a connector with no joinable predecessor still renders.
                if (connector) cur.parts.push(connector);
                cur.parts.push({ kind: 'block', block });
                units.push(cur);
            }
        }
        return units;
    }

    // ---- Per-frame imperative highlight update (called from animation loop) ----

    let _prevActiveWordIdx = -1;
    let _prevActivePhonemeIdx = -1;
    // Loop-highlight is a function of the loop target ALONE (not the playhead), so
    // its four full-tier passes only need to run when the target changes — diff-gate
    // them so the steady (no-loop) frame skips ~4×N classList writes.
    let _prevLoopKey = '\0';

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

        // Loop perma-highlight — outline the looped element on its tier. Only re-run
        // the four tier passes when the loop target changes (a clear runs once to
        // strip the classes); the steady frame skips them entirely.
        const lp = get(loopTarget);
        const loopKey = lp ? `${lp.kind}:${lp.wordIndex ?? ''}:${lp.childIndex ?? ''}` : '';
        if (loopKey !== _prevLoopKey) {
            _prevLoopKey = loopKey;
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
            hc.harakas.forEach((el) => {
                const wi = parseInt(el.dataset.wordIndex ?? '-1');
                const idx = parseInt(el.dataset.diaLoopIdx ?? '-1');
                el.classList.toggle(
                    'loop',
                    lp?.kind === 'diacritic' && lp.wordIndex === wi && lp.childIndex === idx,
                );
            });
        }

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
        // A silent letter (no timing) still raises its rule tooltip — but never
        // publishes a waveform band.
        if (startSec != null && endSec != null) tsHoveredElement.set({ kind: 'letter', startSec, endSec });
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

    /** A diacritic (haraka / tanwīn) loop target spanning the cell's [cellStart,
     *  cellEnd) — already the UNION of the cell's phoneme(s) (a tanwīn covers both
     *  its short-vowel + nasal, a plain haraka its one). Identity is the cell's
     *  first sounded interval index; null when the cell carries no timing. */
    function _diacriticTarget(
        startSec: number | null,
        endSec: number | null,
        wordIndex: number,
        firstPhoneIdx: number | undefined,
    ): TsLoopTarget | null {
        if (startSec == null || endSec == null || firstPhoneIdx == null) return null;
        return { kind: 'diacritic', startSec, endSec, wordIndex, childIndex: firstPhoneIdx };
    }

    /** Single-click a diacritic cell: loop-aware (swap target while looping, else
     *  seek) — deferred to disambiguate from dblclick, matching letter/phoneme. */
    function onDiacriticClick(
        e: MouseEvent,
        startSec: number | null,
        endSec: number | null,
        wordIndex: number,
        firstPhoneIdx: number | undefined,
    ): void {
        e.stopPropagation();
        const target = _diacriticTarget(startSec, endSec, wordIndex, firstPhoneIdx);
        if (!target && startSec == null) return;
        _deferClick(() => {
            const lv = get(loadedVerse);
            if (!lv) return;
            // A co-lit dropped haraka has no phone of its own (no loop identity) but
            // is timed on the carrier's interval — seek there rather than no-op.
            if (target) _swapLoopOrSeek(target, target.startSec + lv.tsSegOffset);
            else if (startSec != null) seekToTime(startSec + lv.tsSegOffset);
        });
    }

    /** Double-click a diacritic cell: toggle loop on its span. */
    function onDiacriticDblClick(
        e: MouseEvent,
        startSec: number | null,
        endSec: number | null,
        wordIndex: number,
        firstPhoneIdx: number | undefined,
    ): void {
        e.stopPropagation();
        _cancelPendingClick();
        const target = _diacriticTarget(startSec, endSec, wordIndex, firstPhoneIdx);
        if (target) toggleLoopOn(target);
    }

    // ---- Group-hover spotlight ----
    // Hovering any cell softly tints its whole column (the cell-group + its
    // phoneme cluster, matched by `data-group-index`), so the letter↔phoneme
    // relationship reads on hover — not only when co-highlighted. A single
    // delegated listener per grid keeps this off the 60fps highlight path.
    function _applyColHover(grid: HTMLElement, gi: string | null): void {
        if (grid.dataset.hoverGi === (gi ?? '')) return;
        grid.dataset.hoverGi = gi ?? '';
        grid.querySelectorAll<HTMLElement>('[data-group-index]').forEach((el) => {
            el.classList.toggle('group-hover', gi != null && el.dataset.groupIndex === gi);
        });
    }
    function colHover(node: HTMLElement) {
        const over = (e: Event): void => {
            const t = (e.target as HTMLElement | null)?.closest<HTMLElement>('[data-group-index]');
            _applyColHover(node, t?.dataset.groupIndex ?? null);
        };
        const leave = (): void => _applyColHover(node, null);
        node.addEventListener('mouseover', over);
        node.addEventListener('mouseleave', leave);
        return {
            destroy(): void {
                node.removeEventListener('mouseover', over);
                node.removeEventListener('mouseleave', leave);
            },
        };
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

    /** Compose the tip text: the recited duration (when timed) plus the cell's
     *  enabled tajweed rule names (from `data-tj-rules`), each on its own line. A
     *  silent letter shows only its rule name(s). */
    function _tipTextFor(el: HTMLElement, ms: number | null): string | null {
        const lines: string[] = [];
        if (ms != null) lines.push(`${ms} ms`);
        const rules = el.dataset.tjRules;
        if (rules) lines.push(rules);
        return lines.length ? lines.join('\n') : null;
    }

    function _tipShowAt(el: HTMLElement, ms: number | null): void {
        if (!el.isConnected) return; // cell removed (verse change) before warmup fired
        const text = _tipTextFor(el, ms);
        if (!text) return;
        const r = el.getBoundingClientRect();
        tipX = r.left + r.width / 2;
        tipY = r.top;
        tipText = text;
        _tipWarm = true;
    }

    function _tipEnter(e: MouseEvent, startSec: number | null, endSec: number | null): void {
        const el = e.currentTarget as HTMLElement | null;
        if (!el) return;
        const ms = startSec != null && endSec != null ? _roundMs(startSec, endSec) : null;
        // Nothing to show — neither a duration nor a rule name on this cell.
        if (ms == null && !el.dataset.tjRules) return;
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

    // ---- Tajweed underline + tooltip (reactive on the rule settings) ----------
    // The cell box-shadow + tooltip rule names recompute when a rule's enable
    // toggle flips (passed `$tajweedSettings` so the template tracks the dep);
    // colour overrides apply via `--tj-*` CSS-var swaps with no re-render.
    function tjShadowFor(badges: TjBadge[], settings: TajweedSettings): string {
        return tjShadow(badges, (k) => isRuleEnabled(settings, k));
    }
    function tjTitleFor(badges: TjBadge[], silent: string[], settings: TajweedSettings): string {
        return tjRuleNames(badges, silent, (k) => isRuleEnabled(settings, k));
    }
    function tjKubraFor(badges: TjBadge[], settings: TajweedSettings): string {
        return tjKubraColor(badges, (k) => isRuleEnabled(settings, k));
    }
</script>

<div
    bind:this={rootEl}
    class="unified-display"
    dir="rtl"
    style="--mega-row-gap: {rowGapPx}px"
    class:hidden={$loadedVerse === null}
>
    <!-- natural-width reference for sizing the small diacritic cells (read by
         _measureLetterCell); shares the letter box metrics but is out of flow,
         not a .mega-letter, never highlighted or queried as a cell. -->
    <span class="letter-metrics" aria-hidden="true">ب</span>
    {#each units as unit (unit.key)}
        <div class="word-unit">
        {#each unit.parts as part}
        {#if part.kind === 'bridge'}
            {@const br = part.bridge}
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
                        data-tj-rules={lt.silentRules.join('\n') || null}
                        on:click={(e) => onCellClick(e, lt.cellStart)}
                        on:dblclick|stopPropagation
                        on:mouseenter={(e) => onCellEnter(e, lt.cellStart, lt.cellEnd)}
                        on:mouseleave={onCellLeave}
                        on:keydown={() => {}}
                        role="button"
                        tabindex="-1"
                    >
                        <span class="bg"><span class="g" style={lt.style}>{lt.glyph}</span></span>
                    </span>
                {/if}
                {#each br.phonemes as ph (ph.index)}
                    {@const parts = splitPhone(ph.displayPhone ?? ph.interval.phone)}
                    <span
                        class="mega-phoneme"
                        class:hidden={br.letter != null && !$showPhonemes}
                        class:silence={!ph.interval.phone ||
                            ph.interval.phone === 'sil' ||
                            ph.interval.phone === 'sp'}
                        class:geminate={ph.interval.geminate_start}
                        data-index={ph.index}
                        style:box-shadow={tjShadowFor(ph.tjBadges, $tajweedSettings)}
                        class:tj-kubra={!!tjKubraFor(ph.tjBadges, $tajweedSettings)}
                        style:--tj-kubra={tjKubraFor(ph.tjBadges, $tajweedSettings)}
                        data-tj-rules={tjTitleFor(ph.tjBadges, [], $tajweedSettings) || null}
                        on:click={(e) => onPhonemeClick(e, ph.interval, ph.index, part.wordIndex)}
                        on:dblclick={(e) => onPhonemeDblClick(e, ph.interval, ph.index, part.wordIndex)}
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
        {:else if part.kind === 'pause'}
            {@const pb = part.pause}
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
        {:else}
            {@const block = part.block}
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
                <div
                    class="mega-grid"
                    dir="rtl"
                    use:colHover
                    class:no-letters={!$showLetters}
                    class:no-phonemes={!$showPhonemes}
                >
                    {#each block.groups as grp, gi (gi)}
                        <div
                            class="cell-group"
                            class:vowel={grp.kind === 'vowel'}
                            class:share-group={grp.shareGroup != null}
                            data-group-index={gi}
                            style="--gcols:{grp.cols.length}"
                        >
                            {#each grp.cols as col, ci}
                                {#if col.full}
                                    {@const f = col.full}
                                    {#if f.implicit}
                                        <!-- implicit madd (Allah dagger-alef / madd-ʿiwaḍ): a FULL cell,
                                             non-interactive, with the inserted/replaced affordance -->
                                        <span
                                            class="mega-letter implicit dia-{f.status}"
                                            class:dia-timed={f.status !== 'dropped' && f.cellStart != null}
                                            class:dia-seekable={f.cellStart != null}
                                            style="grid-column:{ci + 1}; justify-self:stretch"
                                            data-cell-timed={f.status !== 'dropped' && f.cellStart != null ? '1' : undefined}
                                            data-cell-start={f.cellStart}
                                            data-cell-end={f.cellEnd}
                                            data-word-index={block.wordIndex}
                                            style:box-shadow={tjShadowFor(f.tjBadges, $tajweedSettings)}
                                            class:tj-kubra={!!tjKubraFor(f.tjBadges, $tajweedSettings)}
                                            style:--tj-kubra={tjKubraFor(f.tjBadges, $tajweedSettings)}
                                            data-tj-rules={tjTitleFor(f.tjBadges, f.silentRules, $tajweedSettings) || null}
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
                                            style="grid-column:{ci + 1}; justify-self:stretch"
                                            style:box-shadow={tjShadowFor(f.tjBadges, $tajweedSettings)}
                                            class:tj-kubra={!!tjKubraFor(f.tjBadges, $tajweedSettings)}
                                            style:--tj-kubra={tjKubraFor(f.tjBadges, $tajweedSettings)}
                                            data-tj-rules={tjTitleFor(f.tjBadges, f.silentRules, $tajweedSettings) || null}
                                            on:click|stopPropagation
                                            on:mouseenter={(e) => onCellEnter(e, null, null)}
                                            on:mouseleave={onCellLeave}
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
                                            class:dia-inserted={f.inserted}
                                            class:dia-timed={f.cellStart != null && (!f.silent || f.shareGroup != null)}
                                            style="grid-column:{ci + 1}; justify-self:stretch"
                                            data-cell-timed={f.cellStart != null && (!f.silent || f.shareGroup != null) ? '1' : undefined}
                                            data-cell-start={f.cellStart}
                                            data-cell-end={f.cellEnd}
                                            data-letter-start={f.letterStart}
                                            data-letter-end={f.letterEnd}
                                            data-word-index={block.wordIndex}
                                            data-letter-index={f.letterIndex}
                                            style:box-shadow={tjShadowFor(f.tjBadges, $tajweedSettings)}
                                            class:tj-kubra={!!tjKubraFor(f.tjBadges, $tajweedSettings)}
                                            style:--tj-kubra={tjKubraFor(f.tjBadges, $tajweedSettings)}
                                            data-tj-rules={tjTitleFor(f.tjBadges, f.silentRules, $tajweedSettings) || null}
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
                                {:else if col.small}
                                    {@const c = col.small}
                                    <span class="dia-track" style="grid-column:{ci + 1}">
                                        <span
                                            class="haraka-cell pin-{c.slot} dia-{c.status}"
                                            class:dia-inserted={c.inserted}
                                            class:dia-timed={c.status !== 'dropped' && c.cellStart != null}
                                            class:dia-seekable={c.cellStart != null}
                                            data-cell-timed={c.status !== 'dropped' && c.cellStart != null ? '1' : undefined}
                                            data-cell-start={c.cellStart}
                                            data-cell-end={c.cellEnd}
                                            data-word-index={block.wordIndex}
                                            data-dia-loop-idx={c.phoneIdx.length ? c.phoneIdx[0] : undefined}
                                            style:box-shadow={tjShadowFor(c.tjBadges, $tajweedSettings)}
                                            class:tj-kubra={!!tjKubraFor(c.tjBadges, $tajweedSettings)}
                                            style:--tj-kubra={tjKubraFor(c.tjBadges, $tajweedSettings)}
                                            data-tj-rules={tjTitleFor(c.tjBadges, c.silentRules, $tajweedSettings) || null}
                                            on:click={(e) => onDiacriticClick(e, c.cellStart, c.cellEnd, block.wordIndex, c.phoneIdx[0])}
                                            on:dblclick={(e) => onDiacriticDblClick(e, c.cellStart, c.cellEnd, block.wordIndex, c.phoneIdx[0])}
                                            on:mouseenter={(e) => onCellEnter(e, c.cellStart, c.cellEnd)}
                                            on:mouseleave={onCellLeave}
                                            on:keydown={() => {}}
                                            role="button"
                                            tabindex="-1"
                                        >
                                            <span class="g" style={c.renderStyle}>{c.glyph}</span>
                                        </span>
                                    </span>
                                {/if}
                            {/each}
                            {#each grp.phonemeSpans as ps}
                                <span
                                    class="phoneme-cluster"
                                    class:fill={ps.phonemes.length === 1}
                                    data-group-index={gi}
                                    style="grid-column:{ps.colStart + 1} / span {ps.span}"
                                >
                                    {#each ps.phonemes as ph (ph.index)}
                                        {@const parts = splitPhone(ph.displayPhone ?? ph.interval.phone)}
                                        <span
                                            class="mega-phoneme"
                                            class:silence={!ph.interval.phone ||
                                                ph.interval.phone === 'sil' ||
                                                ph.interval.phone === 'sp'}
                                            class:geminate={ph.interval.geminate_start}
                                            data-index={ph.index}
                                            style:box-shadow={tjShadowFor(ph.tjBadges, $tajweedSettings)}
                        class:tj-kubra={!!tjKubraFor(ph.tjBadges, $tajweedSettings)}
                        style:--tj-kubra={tjKubraFor(ph.tjBadges, $tajweedSettings)}
                                            data-tj-rules={tjTitleFor(ph.tjBadges, [], $tajweedSettings) || null}
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
                                </span>
                            {/each}
                        </div>
                    {/each}
                </div>
            {:else}
                <div class="mega-phonemes flat" class:hidden={!$showPhonemes} dir="rtl">
                    {#each block.phonemes as ph (ph.index)}
                        {@const parts = splitPhone(ph.displayPhone ?? ph.interval.phone)}
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
            {/if}
        </div>
        {/if}
        {/each}
        </div>
    {/each}
    {#if tipText}
        <div class="cell-tip" dir="ltr" style="left:{tipX}px; top:{tipY}px;" aria-hidden="true">
            {#each tipText.split('\n') as line (line)}
                <div class:tip-rule={!line.endsWith(' ms')}>{line}</div>
            {/each}
        </div>
    {/if}
</div>
