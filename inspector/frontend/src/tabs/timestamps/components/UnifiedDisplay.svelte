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
    import type { PhonemeInterval, TsWord } from '../../../lib/types/ts-client';
    import { splitPhone } from '../utils/phoneme-columns';
    import { buildRendered, groupUnits } from '../utils/rendered-blocks';
    import {
        ruleHasLabel,
        tjKubraColor,
        tjRuleNames,
        tjShadow,
        type TjBadge,
    } from '../utils/tajweed-rules';
    import { isRuleEnabled, tajweedSettings, type TajweedSettings } from '../stores/tajweed-settings';
    import { waqfRenderStyle } from '../utils/waqf-render';
    import {
        highlightWipe,
        showLetters,
        showPhonemes,
        showTranslations,
        tsHoveredElement,
        tsWaveformHoverTime,
        verseTranslations,
    } from '../stores/display';
    import type { TsLoopTarget } from '../stores/playback';
    import { loopTarget } from '../stores/playback';
    import {
        focusCell,
        focusedCellKey,
        removeStaged,
        reportMode,
        type ReportMode,
        staged,
        upsertStaged,
    } from '../stores/report-mode';
    import { currentVerseReports } from '../stores/ts-reports';
    import type { TsReport } from '../../../lib/types/generated/schemas';
    import { cellTargetFromEl, elCellKey, gapKey, targetCellKey, timingLabel } from '../utils/report-target';
    import { focusWaslGroup, loadedVerse } from '../stores/verse';
    import { TS_CLICK_DELAY_MS } from '../utils/constants';
    import WordTranslation from './WordTranslation.svelte';

    // Container ref used for imperative highlight updates.
    let rootEl: HTMLDivElement;

    // When the focus verse is part of a cross-verse waṣl group, render the whole
    // merged group (junction tajweed renders across the boundary for free, since
    // the boundary words are now adjacent in the words array). The merged data is
    // anchored to the FOCUS verse start, so highlights / loop / seek use the same
    // `loadedVerse.tsSegOffset` unchanged; the other members render as read-only
    // context. Standalone focus → just the focus verse (the common case).
    $: displayData = $focusWaslGroup?.data ?? $loadedVerse?.data;
    /** The interactive verse ref within the merged group (loop/edit are scoped to
     *  it; other members render dimmed + non-loopable). */
    $: focusVerseRef = $focusWaslGroup?.focusRef ?? $loadedVerse?.data.verse_ref ?? '';

    // Reactive: rebuild rendered structure whenever the display data changes.
    // Bridges are baked into the shard (each merger phone carries a ``bridge``
    // rule), so there's nothing async to wait for — buildRendered just lifts the
    // tagged phones into gold bridge tiles (incl. the cross-verse junction).
    $: rendered = buildRendered(
        displayData?.words ?? [],
        displayData?.intervals ?? [],
    );

    /** "surah:ayah" of a word location ("surah:ayah:word"). */
    function verseOfLocation(location: string): string {
        const p = location.split(':');
        return `${p[0]}:${p[1]}`;
    }

    /** Seconds to add to a display-relative time to get chapter-absolute (and to
     *  subtract for the reverse). The displayed cells 0-anchor to the waṣl group
     *  start when in a group, else to the focus verse start. One offset drives
     *  highlights, click-seek, and loop bounds so they all share the render's
     *  coordinate base. */
    function displayOffsetSec(): number {
        const fg = get(focusWaslGroup);
        if (fg) return fg.span[0] / 1000;
        return get(loadedVerse)?.tsSegOffset ?? 0;
    }

    /** The currently-rendered verse data — the merged waṣl group when in one,
     *  else the focus verse. Read imperatively (matches the `{#each}` source) so
     *  the per-frame highlight loop indexes the SAME words/intervals the DOM has. */
    function displayDataNow() {
        return get(focusWaslGroup)?.data ?? get(loadedVerse)?.data ?? null;
    }

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
    // The active phoneme element (track mode sets its `--fill` per frame; phonemes
    // light by index diff, not in the timed-cell loop, so we hold a reference).
    let _trackPh: HTMLElement | null = null;
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
        // Strip report flags off reused keyed nodes so a verse switch starts clean.
        rootEl.querySelectorAll<HTMLElement>(
            '.report-flag-staged, .report-flag-public, .report-focused, .report-dim',
        ).forEach((c) => {
            c.classList.remove(
                'report-flag-staged',
                'report-flag-public',
                'report-focused',
                'report-dim',
                'report-inert',
            );
            if (c.dataset.reportTip) delete c.dataset.reportTip;
        });
    }

    // ---- Report mode: in-grid cell flagging (staged + persisted-public) ----
    // Reactive one-shot passes — deliberately NOT in the 60fps updateHighlights
    // loop. They toggle `report-*` classes on the cells whenever the mode, the
    // staged set, the focus, or the verse's reports change. Disjoint class names
    // from the imperative active-cell path, so the two never clobber.
    let _reportClickBound = false;
    $: $reportMode, $staged, $focusedCellKey, $currentVerseReports, rendered,
        untrack(() => void tick().then(() => { applyReportPasses(); reconcileSeededTajweedOptions(); }));

    function _publicByKey(): Map<string, TsReport[]> {
        const m = new Map<string, TsReport[]>();
        for (const r of get(currentVerseReports)) {
            if (r.status !== 'open') continue;
            const k = targetCellKey(r.target);
            const arr = m.get(k);
            if (arr) arr.push(r);
            else m.set(k, [r]);
        }
        return m;
    }
    function _composeReportTip(reps: TsReport[]): string {
        return reps
            .map((r) => {
                const sub =
                    r.category === 'timing'
                        ? ` · ${timingLabel(r.onset ?? null, r.offset ?? null)}`
                        : r.subtype
                          ? ` · ${r.subtype.replace(/_/g, ' ')}`
                          : '';
                const rule = r.selected_rule_tags?.length ? ` (${r.selected_rule_tags.join(', ')})` : '';
                const c = r.comment ? `: ${r.comment}` : '';
                return `⚑ ${r.category}${sub}${rule}${c}`;
            })
            .join('\n');
    }
    function applyReportPasses(): void {
        if (!rootEl) return;
        const mode = get(reportMode);
        const active = mode.kind !== 'inactive';
        rootEl.classList.toggle('report-mode', active);
        // Mode-scoped so CSS (e.g. the un-grey of rule-bearing silent cells) applies
        // only where it should — never to silent letters in a timing session.
        rootEl.classList.toggle('report-timing', mode.kind === 'timing');
        rootEl.classList.toggle('report-tajweed', mode.kind === 'tajweed');
        rootEl.classList.toggle('report-phonemes', mode.kind === 'phonemes');
        // Silence targets the inter-word gaps: existing pause tiles (boundary / waṣl)
        // or inserted missed-pause slots (missed). The root class reveals the slots.
        const silenceMissed = mode.kind === 'silence' && mode.subtype === 'pause_missed';
        const silenceExisting =
            mode.kind === 'silence' && (mode.subtype === 'pause_boundary' || mode.subtype === 'pause_wasl');
        rootEl.classList.toggle('report-silence', mode.kind === 'silence');
        rootEl.classList.toggle('report-missed', silenceMissed);
        rootEl.classList.toggle('report-existing', silenceExisting);
        const stagedMap = get(staged);
        const focused = get(focusedCellKey);
        const pub = _publicByKey();
        const dimWrong = mode.kind === 'tajweed' && mode.subtype === 'wrong_rule';
        const timing = mode.kind === 'timing';
        const phonemes = mode.kind === 'phonemes';
        const silence = mode.kind === 'silence';
        const els = rootEl.querySelectorAll<HTMLElement>(
            '[data-cell-index], .mega-phoneme, .mega-block, .pause-bridge, .missed-slot',
        );
        els.forEach((el) => {
            const key = elCellKey(el);
            // wrong_rule spotlights rule-bearing cells: dim + inert every cell/phoneme
            // that carries no rule (letters + phonemes expose data-has-tj; blocks
            // have none). Dimming is tajweed-only — in timing the silent letters keep
            // their native greyed style and are merely made inert (no opacity change).
            const noTj = dimWrong && el.hasAttribute('data-has-tj') && el.getAttribute('data-has-tj') !== '1';
            // A silent letter has no duration to call too-long/short, so it can't be a
            // timing target — inert it (keep its look) so only timed letters are live.
            const noTiming = timing && el.hasAttribute('data-cell-index') && el.dataset.cellTimed !== '1';
            // Phonemes mode targets phoneme spans only — inert the letter/diacritic
            // cells (NOT the block, which contains the phoneme spans).
            const noPhoneme = phonemes && el.hasAttribute('data-cell-index');
            // Silence: only the active gap type stays live; everything else is dimmed +
            // inert. Dim the words (.mega-block) + off-type gap tiles, not nested cells
            // (their word already dims — no compounded opacity).
            const isPauseBridge = el.classList.contains('pause-bridge');
            const isMissedSlot = el.classList.contains('missed-slot');
            const isSilenceTarget =
                (silenceExisting && isPauseBridge) || (silenceMissed && isMissedSlot);
            const silenceInert = silence && !isSilenceTarget;
            const silenceDim = silenceInert && (el.classList.contains('mega-block') || isPauseBridge || isMissedSlot);
            el.classList.toggle('report-dim', noTj || silenceDim);
            el.classList.toggle('report-inert', noTj || noTiming || noPhoneme || silenceInert);
            // For .mega-block: flag ring + reportTip go on the .mega-word child so the
            // outline sits on the hover target (onWordEnter fires on .mega-word) and the
            // tooltip is reachable. dim/inert stay on the block itself.
            const flagEl = el.classList.contains('mega-block')
                ? (el.querySelector<HTMLElement>('.mega-word') ?? el)
                : el;
            flagEl.classList.toggle('report-flag-staged', active && !!key && stagedMap.has(key));
            flagEl.classList.toggle('report-focused', active && !!key && key === focused);
            const reps = key ? pub.get(key) : undefined;
            flagEl.classList.toggle('report-flag-public', !!reps?.length);
            if (reps?.length) flagEl.dataset.reportTip = _composeReportTip(reps);
            else if (flagEl.dataset.reportTip) delete flagEl.dataset.reportTip;
            // A missed-slot has no hover/duration plumbing, so surface its public
            // flag via a native title instead of the custom cell tooltip.
            if (isMissedSlot) {
                if (reps?.length) el.title = 'Reported missing pause';
                else el.removeAttribute('title');
            }
        });
    }

    /** Reconcile seeded tajweed entries against the live DOM so re-entering a
     *  session shows the cell's full rule set, not just the previously-picked tags. */
    function reconcileSeededTajweedOptions(): void {
        if (!rootEl) return;
        if (get(reportMode).kind !== 'tajweed') return;
        const stagedMap = get(staged);
        const els = rootEl.querySelectorAll<HTMLElement>('[data-cell-index], .mega-phoneme');
        stagedMap.forEach((a, cellKey) => {
            if (a.kind !== 'tajweed' || !a.originalId) return;
            for (const el of Array.from(els)) {
                if (elCellKey(el) !== cellKey) continue;
                const tags = (el.getAttribute('data-tj-tags') || '')
                    .split(',')
                    .filter(Boolean)
                    .filter(ruleHasLabel);
                if (tags.length > a.ruleOptions.length) {
                    upsertStaged({ ...a, ruleOptions: tags });
                }
                break;
            }
        });
    }

    // Delegated capture-phase click: in report mode a cell/word click STAGES (and,
    // for timing, loops the cell) instead of seeking. stopPropagation blocks the
    // normal letter/word handlers from also firing.
    function _onReportClickCapture(e: MouseEvent): void {
        const mode = get(reportMode);
        if (mode.kind === 'inactive') return;
        const tgt = e.target as HTMLElement;
        // Silence targets the inter-word gap tiles only — a pause bridge (existing)
        // or a missed-pause slot (missed). Swallow every other in-grid click.
        if (mode.kind === 'silence') {
            const gapEl = tgt.closest<HTMLElement>('.pause-bridge, .missed-slot');
            if (gapEl && rootEl.contains(gapEl) && !gapEl.classList.contains('report-inert')) {
                e.stopPropagation();
                e.preventDefault();
                _reportSelectGap(gapEl, mode);
            } else {
                e.stopPropagation();
                e.preventDefault();
            }
            return;
        }
        const cellEl = tgt.closest<HTMLElement>('[data-cell-index]');
        if (cellEl && rootEl.contains(cellEl) && !cellEl.classList.contains('report-inert')) {
            e.stopPropagation();
            e.preventDefault();
            _reportSelectCell(cellEl, mode);
            return;
        }
        // A phoneme span (no cell index) is also a selectable target (timing,
        // tajweed, and the dedicated phonemes mode).
        const phEl = tgt.closest<HTMLElement>('.mega-phoneme');
        if (phEl && rootEl.contains(phEl) && !phEl.classList.contains('report-inert')) {
            e.stopPropagation();
            e.preventDefault();
            _reportSelectCell(phEl, mode);
            return;
        }
        if (mode.kind === 'timing') {
            const blockEl = tgt.closest<HTMLElement>('.mega-block');
            if (blockEl && rootEl.contains(blockEl)) {
                e.stopPropagation();
                e.preventDefault();
                _reportSelectWord(blockEl);
            }
            return;
        }
        // tajweed/phonemes: targets only — swallow any other in-grid click so it
        // can't fall through to the normal seek/select-word handler.
        e.stopPropagation();
        e.preventDefault();
    }
    function _num(v: string | undefined): number | null {
        if (v == null || v === '') return null;
        const n = parseFloat(v);
        return Number.isNaN(n) ? null : n;
    }
    function _reportSelectCell(el: HTMLElement, mode: ReportMode): void {
        const key = elCellKey(el);
        const target = cellTargetFromEl(el);
        if (!key || !target) return;
        if (mode.kind === 'phonemes') {
            // Multi-select toggle: re-clicking a flagged phoneme removes it. No loop.
            if (get(staged).has(key)) {
                removeStaged(key);
                return;
            }
            if (target.kind !== 'phoneme') return; // letters/diacritics aren't phoneme targets
            const glyph = (el.querySelector('.ph-base')?.textContent ?? '').trim();
            upsertStaged({
                kind: 'phonemes',
                cellKey: key,
                target,
                wordIndex: target.word_index ?? -1,
                glyph,
            });
            focusCell(key);
            return;
        }
        if (!get(staged).has(key)) {
            if (mode.kind === 'timing') {
                upsertStaged({ kind: 'timing', cellKey: key, target, wordIndex: target.word_index ?? -1, onset: null, offset: null, comment: '' });
            } else if (mode.kind === 'tajweed') {
                // Only real, labelable rules are pickable — drop sentinels like
                // `silent_unclassified` so the picker never shows a raw tag id.
                const opts = (el.getAttribute('data-tj-tags') || '')
                    .split(',')
                    .filter(Boolean)
                    .filter(ruleHasLabel);
                upsertStaged({
                    kind: 'tajweed',
                    cellKey: key,
                    target,
                    subtype: mode.subtype,
                    ruleOptions: opts,
                    selectedRuleTags: opts.length === 1 ? opts : [],
                    comment: '',
                });
            }
        }
        focusCell(key); // auto-discards a previously focused incomplete cell
        // Only timing loops the selected cell (audio reference). Tajweed keeps the
        // current play/pause state + the whole-verse loop untouched — a tajweed
        // judgement doesn't need the cell isolated on a loop.
        if (mode.kind !== 'timing') return;
        // A letter/diacritic cell loops on its letter span; silent cells with no
        // timing skip (handled below).
        const lv = get(loadedVerse);
        if (!lv) return;
        const wi = parseInt(el.dataset.wordIndex ?? '-1', 10);
        const isPhoneme = el.dataset.phonemeFlatIndex != null;
        const s = isPhoneme
            ? _num(el.dataset.cellStart)
            : (_num(el.dataset.letterStart) ?? _num(el.dataset.cellStart));
        const en = isPhoneme
            ? _num(el.dataset.cellEnd)
            : (_num(el.dataset.letterEnd) ?? _num(el.dataset.cellEnd));
        if (s == null || en == null) return; // silent cell with no own timing — no loop
        // Set the loop directly so playback stays pinned to this verse (it must
        // not run on and advance the focus verse out of the session).
        if (isPhoneme) {
            const childIndex = parseInt(el.dataset.index ?? '-1', 10);
            loopTarget.set({ kind: 'phoneme', startSec: s, endSec: en, wordIndex: wi, childIndex });
        } else {
            const ci = parseInt(el.dataset.cellIndex ?? '-1', 10);
            loopTarget.set({ kind: 'letter', startSec: s, endSec: en, wordIndex: wi, childIndex: ci });
        }
        if (dashPort.element) {
            const targetMs = (s + lv.tsSegOffset) * 1000;
            ensureDashCovering(targetMs);
            dashPort.seek(targetMs);
            if (dashPort.paused) dashPort.play();
        }
    }
    function _reportSelectWord(el: HTMLElement): void {
        const wi = parseInt(el.dataset.wordIndex ?? '-1', 10);
        if (wi < 0) return;
        const key = `w${wi}`;
        if (!get(staged).has(key)) {
            upsertStaged({
                kind: 'timing',
                cellKey: key,
                target: { kind: 'word', word_index: wi, source_letter_index: null, cell_index: null, phoneme_flat_index: null, share_group: null },
                wordIndex: wi,
                onset: null,
                offset: null,
                comment: '',
            });
        }
        focusCell(key); // auto-discards a previously focused incomplete cell
        // Loop the whole word for audio reference (same span as onWordClick).
        const lv = get(loadedVerse);
        const word = lv?.data.words[wi];
        if (!lv || !word) return;
        loopTarget.set({ kind: 'word', startSec: word.start, endSec: word.end, wordIndex: wi });
        if (dashPort.element) {
            const targetMs = (word.start + lv.tsSegOffset) * 1000;
            ensureDashCovering(targetMs);
            dashPort.seek(targetMs);
            if (dashPort.paused) dashPort.play();
        }
    }
    /** Loop the two words straddling a gap (audio reference for a pause report). */
    function _loopGap(wi: number): void {
        const lv = get(loadedVerse);
        const prev = lv?.data.words[wi];
        const next = lv?.data.words[wi + 1];
        if (!lv || !prev || !next) return;
        loopTarget.set({ kind: 'word', startSec: prev.start, endSec: next.end, wordIndex: wi });
        if (dashPort.element) {
            const targetMs = (prev.start + lv.tsSegOffset) * 1000;
            ensureDashCovering(targetMs);
            dashPort.seek(targetMs);
            if (dashPort.paused) dashPort.play();
        }
    }
    function _reportSelectGap(el: HTMLElement, mode: ReportMode): void {
        if (mode.kind !== 'silence') return;
        const wi = parseInt(el.dataset.gapWordIndex ?? '-1', 10);
        if (wi < 0) return;
        const key = gapKey(wi);
        // The binary subtypes toggle (re-click removes); pause_boundary stays staged
        // and is completed via the strip's Start/End axes.
        if (mode.subtype !== 'pause_boundary' && get(staged).has(key)) {
            removeStaged(key);
            return;
        }
        if (!get(staged).has(key)) {
            const target = cellTargetFromEl(el);
            if (!target) return;
            upsertStaged({
                kind: 'silence',
                cellKey: key,
                target,
                gapWordIndex: wi,
                subtype: mode.subtype,
                onset: null,
                offset: null,
            });
        }
        focusCell(key);
        _loopGap(wi);
    }
    $: if (rootEl && !_reportClickBound) {
        rootEl.addEventListener('click', _onReportClickCapture, true);
        _reportClickBound = true;
    }
    onDestroy(() => {
        if (rootEl) rootEl.removeEventListener('click', _onReportClickCapture, true);
    });

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

    // Continuous-highlight mode is a root class the cell CSS reads; the per-frame
    // `--fill` is written in `updateHighlights` only while this is on.
    $: if (rootEl) rootEl.classList.toggle('hl-track', $highlightWipe);




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
        const dd = displayDataNow();
        if (!dd) return;
        const time = getSegRelTime(displayOffsetSec());

        const intervals = dd.intervals;
        const words = dd.words;
        const portReady = !!dashPort.element;
        const portPaused = dashPort.paused;
        const hoverTime = get(tsWaveformHoverTime);

        // Continuous karaoke wipe across the active cell (vs the discrete fill).
        const trackOn = get(highlightWipe);
        const leadSec = 0;

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
            _trackPh = null;
            hc.phonemes.forEach((ph) => {
                const on = parseInt(ph.dataset.index ?? '-1') === currentIndex;
                ph.classList.toggle('active', on);
                if (on) _trackPh = ph;
                else ph.style.removeProperty('--fill');
            });
            _prevActivePhonemeIdx = currentIndex;
        }
        if (trackOn && _trackPh && currentIndex >= 0) {
            const iv = intervals[currentIndex];
            if (iv) {
                const d = iv.end - iv.start;
                const f = d > 0 ? (time + leadSec - iv.start) / d : 0;
                _trackPh.style.setProperty('--fill', String(f < 0 ? 0 : f > 1 ? 1 : f));
            }
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
            const isActive = time >= s && time < e;
            el.classList.toggle('active', isActive);
            el.classList.toggle(
                'hover-preview',
                hoverTime != null && wi === hoverWordIndex && hoverTime >= s && hoverTime < e,
            );
            if (trackOn) {
                if (isActive) {
                    const d = e - s;
                    const f = d > 0 ? (time + leadSec - s) / d : 0;
                    el.style.setProperty('--fill', String(f < 0 ? 0 : f > 1 ? 1 : f));
                } else if (el.style.getPropertyValue('--fill')) {
                    el.style.removeProperty('--fill');
                }
            }
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
        // End-of-verse waqf: the trailing silence after the last recited word (a
        // real stop at the verse / waṣl-group end) dims the row exactly like an
        // inter-word pause. A bridged inner boundary has no trailing silence, so
        // this only fires at the group's final stop.
        if (!inPauseGap && words.length) {
            const lastEnd = words[words.length - 1]!.end;
            if (time >= lastEnd) inPauseGap = true;
        }
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
                word.start + displayOffsetSec(),
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
                iv.start + displayOffsetSec(),
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
        seekToTime(target.startSec + displayOffsetSec());
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
                startSec + displayOffsetSec(),
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
        seekToTime(startSec + displayOffsetSec());
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
            if (target) _swapLoopOrSeek(target, target.startSec + displayOffsetSec());
            else if (startSec != null) seekToTime(startSec + displayOffsetSec());
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
        const report = el.dataset.reportTip;
        if (report) lines.push(report);
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
        {#if unit.gapWordIndex != null}
            <!-- Missing-pause slot: a between-words tile at a contiguous boundary. A
                 direct row child so the row column-gap applies symmetrically on both
                 sides (matching normal word spacing). Hidden at rest; revealed
                 (spotlit) in the missed-pause report mode, or shown with a red ring +
                 tooltip when publicly flagged. -->
            <div class="missed-slot" data-gap-word-index={unit.gapWordIndex} role="group">
                {#if unit.missedMark}
                    <span class="pause-waqf" style={waqfRenderStyle(unit.missedMark)}>{unit.missedMark}</span>
                {:else}
                    <span class="pause-icon" aria-hidden="true"></span>
                {/if}
            </div>
        {/if}
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
                    {@const parts = splitPhone(ph.interval.phone)}
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
                data-gap-word-index={pb.fromWordIndex}
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
            {@const isContext = verseOfLocation(block.word.location) !== focusVerseRef}
        <div
            class="mega-block"
            class:context={isContext}
            data-word-index={block.wordIndex}
            on:click={() => onWordClick(block.word, block.wordIndex)}
            on:dblclick={() => { if (!isContext) onWordDblClick(block.word, block.wordIndex); }}
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
                                            data-cell-index={f.cellIndex}
                                            data-has-tj={f.ruleTags.length || f.tjBadges.length || f.silentRules.length ? '1' : '0'}
                                            data-tj-tags={f.ruleTags.join(',')}
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
                                            data-word-index={block.wordIndex}
                                            data-cell-index={f.cellIndex}
                                            data-source-letter-index={f.letterIndex}
                                            data-share-group={f.shareGroup}
                                            data-has-tj={f.ruleTags.length || f.tjBadges.length || f.silentRules.length ? '1' : '0'}
                                            data-tj-tags={f.ruleTags.join(',')}
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
                                            class:dia-replaced={f.status === 'replaced'}
                                            class:dia-timed={f.cellStart != null && (!f.silent || f.shareGroup != null)}
                                            style="grid-column:{ci + 1}; justify-self:stretch"
                                            data-cell-timed={f.cellStart != null && (!f.silent || f.shareGroup != null) ? '1' : undefined}
                                            data-cell-start={f.cellStart}
                                            data-cell-end={f.cellEnd}
                                            data-letter-start={f.letterStart}
                                            data-letter-end={f.letterEnd}
                                            data-word-index={block.wordIndex}
                                            data-letter-index={f.letterIndex}
                                            data-cell-index={f.cellIndex}
                                            data-source-letter-index={f.letterIndex}
                                            data-share-group={f.shareGroup}
                                            data-has-tj={f.ruleTags.length || f.tjBadges.length || f.silentRules.length ? '1' : '0'}
                                            data-tj-tags={f.ruleTags.join(',')}
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
                                            data-cell-index={c.cellIndex}
                                            data-share-group={c.shareGroup}
                                            data-has-tj={c.ruleTags.length || c.tjBadges.length || c.silentRules.length ? '1' : '0'}
                                            data-tj-tags={c.ruleTags.join(',')}
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
                                        {@const parts = splitPhone(ph.interval.phone)}
                                        <span
                                            class="mega-phoneme"
                                            class:silence={!ph.interval.phone ||
                                                ph.interval.phone === 'sil' ||
                                                ph.interval.phone === 'sp'}
                                            class:geminate={ph.interval.geminate_start}
                                            data-index={ph.index}
                                            data-word-index={block.wordIndex}
                                            data-phoneme-flat-index={ph.wordLocalIndex}
                                            data-cell-start={ph.interval.start}
                                            data-cell-end={ph.interval.end}
                                            data-has-tj={ph.tjBadges.length ? '1' : '0'}
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
                        {@const parts = splitPhone(ph.interval.phone)}
                        <span
                            class="mega-phoneme"
                            class:silence={!ph.interval.phone ||
                                ph.interval.phone === 'sil' ||
                                ph.interval.phone === 'sp'}
                            class:geminate={ph.interval.geminate_start}
                            data-index={ph.index}
                            data-word-index={block.wordIndex}
                            data-phoneme-flat-index={ph.wordLocalIndex}
                            data-cell-start={ph.interval.start}
                            data-cell-end={ph.interval.end}
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

