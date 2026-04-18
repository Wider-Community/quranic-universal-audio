<script lang="ts">
    /**
     * AnimationDisplay — reveal-mode animation view for the Timestamps tab.
     *
     * Port of Stage-1 timestamps/animation.ts. Like UnifiedDisplay.svelte,
     * structure is rendered declaratively via `{#each}` and per-frame highlight
     * updates are applied imperatively via `updateHighlights()` called from the
     * parent's animation loop. The cross-word group-ID merging happens in the
     * pure-function data builder (not a post-render DOM walk).
     */

    import { afterUpdate } from 'svelte';
    import { get } from 'svelte/store';

    import { granularity } from '../../lib/stores/timestamps/display';
    import { loadedVerse } from '../../lib/stores/timestamps/verse';
    import {
        charsMatch,
        DAGGER_ALEF,
        isCombiningMark,
        splitIntoCharGroups,
        ZWSP,
    } from '../../lib/utils/arabic-text';
    import type { TsWord } from '../../lib/types/domain';

    // ---- Data model (produced by buildStructure) ----

    interface AnimChar {
        text: string;
        start: number;
        end: number;
        groupId: string;
    }

    interface AnimWord {
        word: TsWord;
        wordIndex: number;
        start: number;
        end: number;
        /** Characters split for character-granularity animation. */
        chars: AnimChar[];
        /** Whether the word has any char groups (empty display_text → render text directly). */
        hasChars: boolean;
    }

    let rootEl: HTMLDivElement;

    // Reactive structural data
    $: structure = buildStructure($loadedVerse?.data.words ?? []);

    // Reset animation cache / state on structure change
    $: structure, (_lastWordIdx = -1);
    $: structure, (_lastCharIdx = -1);
    $: structure, (_charsReindexed = false);

    // ---- Pure data builder ----

    function buildStructure(words: TsWord[]): AnimWord[] {
        if (!words.length) return [];

        let groupIdCounter = 0;
        const out: AnimWord[] = [];

        words.forEach((word, wi) => {
            const displayText = word.display_text || word.text;
            const charGroups = splitIntoCharGroups(displayText);
            const letters = word.letters || [];

            // Assign initial group IDs
            const chars: Array<{ text: string; start: number; end: number; groupId: string }> =
                charGroups.map((group) => ({
                    text: group.startsWith(DAGGER_ALEF) ? ZWSP + group : group,
                    start: word.start,
                    end: word.end,
                    groupId: `g${groupIdCounter++}`,
                }));

            // Fuzzy two-pointer: walk display chars + MFA letters simultaneously
            let mfaIdx = 0;
            const stamped = new Set<number>();
            for (let di = 0; di < chars.length; di++) {
                if (stamped.has(di)) continue;
                const span = chars[di];
                if (!span) continue;
                const displayChar = span.text.replace(/^\u200B/, ''); // strip ZWSP for matching
                if (mfaIdx < letters.length) {
                    const lt = letters[mfaIdx];
                    if (!lt) {
                        mfaIdx++;
                        continue;
                    }
                    const mfaChar = lt.char || '';
                    if (charsMatch(mfaChar, displayChar)) {
                        const startSec = lt.start != null ? lt.start : word.start;
                        const endSec = lt.end != null ? lt.end : word.end;
                        span.start = startSec;
                        span.end = endSec;

                        // Peek ahead: combining-mark-only groups that belong to same MFA letter
                        const mfaNfd = mfaChar.normalize('NFD');
                        let peek = di + 1;
                        while (peek < chars.length) {
                            const peekSpan = chars[peek];
                            if (!peekSpan) break;
                            const peekText = peekSpan.text.replace(/\u0640/g, '');
                            if (
                                !peekText ||
                                ![...peekText].every((c) => {
                                    const cp = c.codePointAt(0);
                                    return cp !== undefined && isCombiningMark(cp);
                                })
                            ) {
                                break;
                            }
                            if (![...peekText].some((c) => mfaNfd.includes(c))) break;
                            peekSpan.start = startSec;
                            peekSpan.end = endSec;
                            stamped.add(peek);
                            peek++;
                        }
                        mfaIdx++;
                    }
                    // else: no-match path keeps word-level timing (already set above)
                }
                // else: exhausted MFA letters → word timing (already set)
            }

            out.push({
                word,
                wordIndex: wi,
                start: word.start,
                end: word.end,
                chars,
                hasChars: chars.length > 0,
            });
        });

        // Cross-word group-ID merge: any two chars with identical (start, end)
        // share a group. This ensures that when the same timing applies across
        // word boundaries (e.g. idgham ghunna), a single group highlights together.
        const timingMap: Record<string, string> = {};
        for (const w of out) {
            for (const ch of w.chars) {
                const key = `${ch.start}|${ch.end}`;
                const existing = timingMap[key];
                if (existing) ch.groupId = existing;
                else timingMap[key] = ch.groupId;
            }
        }
        return out;
    }

    // ---- Per-frame imperative updates (called from parent animation loop) ----

    interface CacheItem {
        el: HTMLElement;
        start: number;
        end: number;
        groupId: string;
    }
    interface Cache {
        items: CacheItem[];
        groupIndex: Record<string, number[]>;
    }

    let _wordCache: Cache | null = null;
    let _charCache: Cache | null = null;
    let _lastWordIdx = -1;
    let _lastCharIdx = -1;
    let _charsReindexed = false;

    // Rebuild caches once the DOM reflects the latest structure
    afterUpdate(() => {
        if (!rootEl) return;
        _wordCache = indexCache(rootEl, '.anim-word');
        _charCache = indexCache(rootEl, '.anim-char');
        _lastWordIdx = -1;
        _lastCharIdx = -1;
        _charsReindexed = true;
    });

    function indexCache(container: HTMLElement, selector: string): Cache {
        const items: CacheItem[] = [];
        const groupIndex: Record<string, number[]> = {};
        container.querySelectorAll<HTMLElement>(selector).forEach((el, i) => {
            const start = parseFloat(el.dataset.start ?? '0');
            const end = parseFloat(el.dataset.end ?? '0');
            const groupId = el.dataset.groupId || '';
            items.push({ el, start, end, groupId });
            if (groupId) {
                if (!groupIndex[groupId]) groupIndex[groupId] = [];
                groupIndex[groupId].push(i);
            }
        });
        return { items, groupIndex };
    }

    function applyClass(cache: Cache, idx: number, className: string, add: boolean): void {
        const item = cache.items[idx];
        if (!item) return;
        if (add) item.el.classList.add(className);
        else item.el.classList.remove(className);
        const members = item.groupId ? cache.groupIndex[item.groupId] : undefined;
        if (!members) return;
        for (const mi of members) {
            if (mi === idx) continue;
            const other = cache.items[mi];
            if (!other) continue;
            if (add) other.el.classList.add(className);
            else other.el.classList.remove(className);
        }
    }

    function applyOpacity(cache: Cache, idx: number, opacity: string | null): void {
        const item = cache.items[idx];
        if (!item) return;
        if (opacity === null) item.el.style.removeProperty('opacity');
        else item.el.style.opacity = opacity;
        const members = item.groupId ? cache.groupIndex[item.groupId] : undefined;
        if (!members) return;
        for (const mi of members) {
            if (mi === idx) continue;
            const other = cache.items[mi];
            if (!other) continue;
            if (opacity === null) other.el.style.removeProperty('opacity');
            else other.el.style.opacity = opacity;
        }
    }

    function applyRevealOpacity(cache: Cache, newIdx: number, prevIdx: number): void {
        if (cache.items.length === 0) return;

        // Fast path: advancing by 1
        if (prevIdx >= 0 && newIdx === prevIdx + 1) {
            applyOpacity(cache, prevIdx, '1');
            applyOpacity(cache, newIdx, null);
            return;
        }

        for (let i = 0; i < cache.items.length; i++) {
            if (i < newIdx) applyOpacity(cache, i, '1');
            else if (i === newIdx) applyOpacity(cache, i, null);
            else applyOpacity(cache, i, '0');
        }

        // Reconcile group opacities
        for (const gid of Object.keys(cache.groupIndex)) {
            const members = cache.groupIndex[gid];
            if (!members || members.length <= 1) continue;
            let anyActive = false;
            let maxOp = -1;
            for (const mi of members) {
                const m = cache.items[mi];
                if (!m) continue;
                if (m.el.classList.contains('active')) {
                    anyActive = true;
                    break;
                }
                const op = m.el.style.opacity;
                if (op !== '') {
                    const val = parseFloat(op);
                    if (!isNaN(val) && val > maxOp) maxOp = val;
                }
            }
            if (anyActive) {
                for (const mi of members) {
                    const m = cache.items[mi];
                    if (m) m.el.style.opacity = '1';
                }
            } else if (maxOp > 0) {
                const s = String(maxOp);
                for (const mi of members) {
                    const m = cache.items[mi];
                    if (m) m.el.style.opacity = s;
                }
            }
        }
    }

    /**
     * Called once per animation frame from the parent's loop.
     * No-op when the tab isn't the animation view; caller is responsible
     * for that gating (we don't want a store read per frame).
     */
    export function updateHighlights(): void {
        if (!rootEl) return;
        const lv = get(loadedVerse);
        if (!lv) return;
        const audio = document.getElementById('audio-player') as HTMLAudioElement | null;
        if (!audio) return;
        const time = audio.currentTime - lv.tsSegOffset;

        const gran = get(granularity);
        const cache = gran === 'characters' ? _charCache : _wordCache;
        if (!cache || cache.items.length === 0) return;

        const items = cache.items;
        const lastIdx = gran === 'characters' ? _lastCharIdx : _lastWordIdx;

        // Fast-path tick: check current → next → full scan
        let newIdx = -1;
        const lastItem = lastIdx >= 0 && lastIdx < items.length ? items[lastIdx] : undefined;
        const nextItem = lastIdx + 1 < items.length ? items[lastIdx + 1] : undefined;
        if (lastItem && time >= lastItem.start && time < lastItem.end) {
            newIdx = lastIdx;
        } else if (nextItem && time >= nextItem.start && time < nextItem.end) {
            newIdx = lastIdx + 1;
        } else {
            for (let i = 0; i < items.length; i++) {
                const it = items[i];
                if (!it) continue;
                if (time >= it.start && time < it.end) {
                    newIdx = i;
                    break;
                }
            }
            const tail = items[items.length - 1];
            if (newIdx === -1 && items.length > 0 && tail && time >= tail.start) {
                newIdx = items.length - 1;
            }
        }

        if (newIdx !== lastIdx) {
            if (lastIdx >= 0 && lastIdx < items.length) {
                applyClass(cache, lastIdx, 'active', false);
                applyClass(cache, lastIdx, 'reached', true);
            }
            if (newIdx >= 0) {
                applyClass(cache, newIdx, 'active', true);
                if (lastIdx === -1) {
                    for (let j = 0; j < newIdx; j++) applyClass(cache, j, 'reached', true);
                }
                applyRevealOpacity(cache, newIdx, lastIdx);
                const item = items[newIdx];
                if (item) item.el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }
            if (gran === 'characters') _lastCharIdx = newIdx;
            else _lastWordIdx = newIdx;
        }
    }

    /** Scroll the currently-active item into view (keyboard `J`). */
    export function scrollActiveIntoView(): void {
        const gran = get(granularity);
        const cache = gran === 'characters' ? _charCache : _wordCache;
        const idx = gran === 'characters' ? _lastCharIdx : _lastWordIdx;
        if (!cache || idx < 0) return;
        const item = cache.items[idx];
        if (item) item.el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    // Granularity-change housekeeping: clear highlights + opacity when mode
    // switches. Reactive statement guards re-entry during initial build.
    $: if (_charsReindexed && rootEl) {
        rootEl
            .querySelectorAll<HTMLElement>('.anim-word, .anim-char')
            .forEach((el) => {
                el.classList.remove('active', 'reached');
                el.style.removeProperty('opacity');
            });
        _lastWordIdx = -1;
        _lastCharIdx = -1;
        // Pick up new position
        updateHighlights();
        _charsReindexed = false;
    }

    // Also watch granularity toggles while the cache is stable (no rebuild)
    let _prevGranularity = get(granularity);
    $: {
        if ($granularity !== _prevGranularity) {
            _prevGranularity = $granularity;
            if (rootEl) {
                rootEl
                    .querySelectorAll<HTMLElement>('.anim-word, .anim-char')
                    .forEach((el) => {
                        el.classList.remove('active', 'reached');
                        el.style.removeProperty('opacity');
                    });
                _lastWordIdx = -1;
                _lastCharIdx = -1;
                updateHighlights();
            }
        }
    }

    // Click to seek
    function onWordClick(word: TsWord): void {
        const lv = get(loadedVerse);
        if (!lv) return;
        const audio = document.getElementById('audio-player') as HTMLAudioElement | null;
        if (!audio) return;
        audio.currentTime = word.start + lv.tsSegOffset;
        updateHighlights();
    }
</script>

<div
    bind:this={rootEl}
    id="animation-display"
    class="anim-window"
    class:anim-chars={$granularity === 'characters'}
>
    {#each structure as w, wi (w.wordIndex)}
        {#if wi > 0}{' '}{/if}
        <span
            class="anim-word"
            data-start={w.start}
            data-end={w.end}
            data-pos={w.word.location}
            on:click={() => onWordClick(w.word)}
            on:keydown={() => {}}
            role="button"
            tabindex="-1"
        >{#if w.hasChars}{#each w.chars as ch, ci (ci)}<span
                    class="anim-char"
                    data-start={ch.start}
                    data-end={ch.end}
                    data-group-id={ch.groupId}
                >{ch.text}</span>{/each}{:else}{w.word.display_text ||
                w.word.text}{/if}</span>
    {/each}
</div>
