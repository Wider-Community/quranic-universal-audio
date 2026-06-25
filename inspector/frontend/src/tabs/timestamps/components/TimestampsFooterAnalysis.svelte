<script lang="ts">
    /**
     * Timestamps footer — analysis cluster, rendered in the BottomPlayer
     * `center-trail` slot (just right of the speed button) when the Timestamps
     * tab is active.
     *
     * A single flat row:  loop · letters · phonemes · translations(globe) · help
     * All operate on the shared player (dashPort) + timestamps display stores.
     * The help button opens the shortcuts/guide drop-up.
     */
    import { get } from 'svelte/store';

    import { clickOutside } from '../../../lib/actions/click-outside';
    import { dashPort } from '../../../lib/playback/dash-port';
    import { ControlIcon } from '../../../lib/recitation-animation';
    import { LS_KEYS } from '../../../lib/utils/constants';
    import { showLetters, showPhonemes } from '../stores/display';
    import { loopTarget } from '../stores/playback';
    import { loadedVerse } from '../stores/verse';
    import { findWordAt } from '../utils/loop-target';
    import TajweedSettingsPanel from './TajweedSettingsPanel.svelte';
    import TranslationGlobe from './TranslationGlobe.svelte';

    let guideOpen = $state(false);
    let tajweedOpen = $state(false);

    function persist(key: string, v: boolean): void {
        try { localStorage.setItem(key, String(v)); } catch { /* ignore */ }
    }
    function toggleLetters(): void {
        showLetters.update((v) => { persist(LS_KEYS.TS_SHOW_LETTERS, !v); return !v; });
    }
    function togglePhonemes(): void {
        showPhonemes.update((v) => { persist(LS_KEYS.TS_SHOW_PHONEMES, !v); return !v; });
    }
    function toggleLoop(): void {
        if (get(loopTarget)) { loopTarget.set(null); return; }
        const lv = get(loadedVerse);
        if (!lv) return;
        const t = dashPort.currentTimeMs() / 1000 - lv.tsSegOffset;
        const words = lv.data.words;
        const w = findWordAt(t, words, false) ?? words[0];
        if (!w) return;
        loopTarget.set({ kind: 'word', startSec: w.start, endSec: w.end, wordIndex: words.indexOf(w) });
    }

    type GuideRow = {
        icon?: 'letters' | 'phonemes' | 'globe';
        img?: string;
        key?: string;
        label: string;
    };
    const SHORTCUTS: { title: string; rows: GuideRow[] }[] = [
        { title: 'Playback', rows: [
            { key: 'Space', label: 'Play / pause' },
            { key: '← / →', label: 'Seek prev / next ayah' },
            { key: '↑ / ↓', label: 'Prev / next word' },
        ] },
        { title: 'Navigation', rows: [
            { key: '[ / ]', label: 'Prev / next ayah' },
            { key: 'R', label: 'Shuffle jump' },
            { key: 'J', label: 'Scroll active' },
        ] },
        { title: 'Display', rows: [
            { icon: 'letters', key: 'L', label: 'Letters' },
            { icon: 'phonemes', key: 'P', label: 'Phonemes' },
            { icon: 'globe', label: 'Translations' },
        ] },
        { title: 'Interactions', rows: [
            { key: 'Click', label: 'Seek to word' },
            { img: '/icons/loop.svg', key: 'Dbl-click', label: 'Loop word' },
            { key: 'Waveform', label: 'Click to seek' },
        ] },
    ];

    // Keep the drop-up on-screen: it's anchored to its button, but on a narrow
    // window the footer overflows and the button slides off the right edge,
    // dragging the popup with it. Shift it left so its right edge clears the
    // viewport, and only cap its width as a last resort.
    function keepInView(node: HTMLElement) {
        const margin = 8;
        const place = (): void => {
            node.style.right = '0px';
            node.style.maxWidth = '';
            const overflowRight = node.getBoundingClientRect().right - (window.innerWidth - margin);
            node.style.right = `${Math.max(0, overflowRight)}px`;
            if (node.getBoundingClientRect().left < margin) {
                node.style.maxWidth = `${window.innerWidth - margin * 2}px`;
            }
        };
        place();
        window.addEventListener('resize', place);
        return { destroy: () => window.removeEventListener('resize', place) };
    }
</script>

<div class="tfa" role="group" aria-label="Analysis tiers">
    <button
        type="button" class="icon-btn" class:on={$loopTarget !== null}
        aria-pressed={$loopTarget !== null} title="Loop current word" onclick={toggleLoop}
    ><img class="img-icon" src="/icons/loop.svg" alt="" aria-hidden="true" /></button>
    <button
        type="button" class="icon-btn" class:on={$showLetters}
        aria-pressed={$showLetters} title="Toggle letters" onclick={toggleLetters}
    ><ControlIcon name="letters" /></button>
    <button
        type="button" class="icon-btn" class:on={$showPhonemes}
        aria-pressed={$showPhonemes} title="Toggle phonemes" onclick={togglePhonemes}
    ><ControlIcon name="phonemes" /></button>

    <div class="guide-wrap" use:clickOutside={() => (tajweedOpen = false)}>
        <button
            type="button" class="icon-btn" class:on={tajweedOpen} title="Tajweed rules & colours"
            aria-haspopup="dialog" aria-expanded={tajweedOpen}
            onclick={() => (tajweedOpen = !tajweedOpen)}
        ><ControlIcon name="tajweed" /></button>
        {#if tajweedOpen}
            <div class="guide-pop" use:keepInView>
                <TajweedSettingsPanel />
            </div>
        {/if}
    </div>

    <TranslationGlobe />

    <div class="guide-wrap" use:clickOutside={() => (guideOpen = false)}>
        <button
            type="button" class="icon-btn" title="Shortcuts & guide"
            aria-haspopup="dialog" aria-expanded={guideOpen}
            onclick={() => (guideOpen = !guideOpen)}
        ><ControlIcon name="help" size={15} /></button>
        {#if guideOpen}
            <div class="guide-pop" use:keepInView>
                <div class="guide-shortcuts">
                    {#each SHORTCUTS as sec (sec.title)}
                        <div class="guide-sec">
                            <h4>{sec.title}</h4>
                            {#each sec.rows as r (r.label)}
                                <div class="guide-row">
                                    {#if r.icon}
                                        <span class="g-ic"><ControlIcon name={r.icon} size={14} /></span>
                                    {:else if r.img}
                                        <span class="g-ic"><img class="g-img" src={r.img} alt="" aria-hidden="true" /></span>
                                    {/if}
                                    {#if r.key}<kbd>{r.key}</kbd>{/if}
                                    <span class="g-label">{r.label}</span>
                                </div>
                            {/each}
                        </div>
                    {/each}
                </div>
            </div>
        {/if}
    </div>
</div>

<style>
    /* Single flat row: loop · letters · phonemes · globe · help. */
    .tfa {
        display: inline-flex;
        align-items: center;
        gap: 2px;
    }
    .icon-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 28px;
        height: 22px;
        color: var(--text-muted);
        background: transparent;
        border: 1px solid transparent;
        border-radius: var(--r-2);
        cursor: pointer;
        transition: color var(--t-fast), background var(--t-fast);
    }
    .icon-btn:hover:not(:disabled) { color: var(--text-primary); background: var(--panel-2); }
    .icon-btn.on { color: var(--accent); background: var(--accent-tint); }
    .icon-btn:disabled { opacity: 0.3; cursor: not-allowed; }
    .img-icon {
        width: 15px;
        height: 15px;
        opacity: 0.6;
        transition: opacity var(--t-fast);
    }
    .icon-btn:hover .img-icon { opacity: 0.9; }
    .icon-btn.on .img-icon { opacity: 1; }

    .guide-wrap { position: relative; display: inline-flex; }
    .guide-pop {
        position: absolute;
        bottom: calc(100% + var(--s-2));
        /* Anchored to the help button's right edge so the wider box grows
         * leftward instead of overflowing the viewport's right side. */
        right: 0;
        left: auto;
        display: flex;
        align-items: stretch;
        gap: var(--s-3);
        width: max-content;
        background: var(--panel);
        border: 1px solid var(--border-default);
        border-radius: var(--r-3);
        box-shadow: 0 16px 48px oklch(0 0 0 / 0.45);
        z-index: 50;
        padding: var(--s-3);
    }
    .guide-shortcuts {
        flex: 0 0 auto;
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: var(--s-3) var(--s-4);
        min-width: 360px;
    }
    .guide-sec h4 {
        margin: 0 0 4px;
        font-size: var(--fs-meta);
        color: var(--text-primary);
    }
    .guide-row {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        margin-bottom: 2px;
        font-size: var(--fs-meta);
        color: var(--text-secondary);
    }
    .g-ic {
        display: inline-flex;
        flex: 0 0 auto;
        color: var(--text-primary);
    }
    .g-img { width: 14px; height: 14px; opacity: 0.85; }
    .g-label { flex: 1 1 auto; }
    .guide-row kbd {
        flex: 0 0 auto;
        min-width: 42px;
        text-align: center;
        padding: 1px 5px;
        background: var(--panel-2);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-1);
        font-family: var(--font-mono);
        font-size: 10px;
        color: var(--text-faint);
    }
</style>
