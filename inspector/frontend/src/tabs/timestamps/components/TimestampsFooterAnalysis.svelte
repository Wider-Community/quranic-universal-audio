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

    import { i18n } from '$lib/i18n/locale.svelte';
    import * as m from '$lib/paraglide/messages';
    import { clickOutside } from '../../../lib/actions/click-outside';
    import { dashPort } from '../../../lib/playback/dash-port';
    import { ControlIcon } from '../../../lib/recitation-animation';
    import { LS_KEYS } from '../../../lib/utils/constants';
    import { showLetters, showPhonemes } from '../stores/display';
    import { loopTarget } from '../stores/playback';
    import { loadedVerse } from '../stores/verse';
    import { findWordAt } from '../utils/loop-target';
    import TranslationGlobe from './TranslationGlobe.svelte';

    let guideOpen = $state(false);

    // Attribute labels gated on i18n.locale so they re-render on a locale switch.
    const groupAria = $derived((i18n.locale, m.ts_footer_analysis_group_aria_label()));
    const loopTitle = $derived((i18n.locale, m.ts_footer_loop_word_title()));
    const lettersTitle = $derived((i18n.locale, m.ts_footer_toggle_letters_title()));
    const phonemesTitle = $derived((i18n.locale, m.ts_footer_toggle_phonemes_title()));
    const guideTitle = $derived((i18n.locale, m.ts_footer_shortcuts_guide_title()));

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
    // Reading i18n.locale makes this $derived (and the inline title/aria-label
    // calls below) re-run when the locale switches.
    const SHORTCUTS = $derived<{ title: string; rows: GuideRow[] }[]>(
        (i18n.locale, [
            { title: m.ts_shortcuts_section_playback(), rows: [
                { key: 'Space', label: m.ts_shortcuts_label_play_pause() },
                { key: '← / →', label: m.ts_shortcuts_label_seek_prev_next_ayah() },
                { key: '↑ / ↓', label: m.ts_shortcuts_label_prev_next_word() },
            ] },
            { title: m.ts_shortcuts_section_navigation(), rows: [
                { key: '[ / ]', label: m.ts_shortcuts_label_prev_next_ayah() },
                { key: 'R', label: m.ts_shortcuts_label_shuffle_jump() },
                { key: 'J', label: m.ts_shortcuts_label_scroll_active() },
            ] },
            { title: m.ts_shortcuts_section_display(), rows: [
                { icon: 'letters', key: 'L', label: m.ts_shortcuts_label_letters() },
                { icon: 'phonemes', key: 'P', label: m.ts_shortcuts_label_phonemes() },
                { icon: 'globe', label: m.ts_shortcuts_label_translations() },
            ] },
            { title: m.ts_shortcuts_section_interactions(), rows: [
                { key: 'Click', label: m.ts_shortcuts_label_seek_to_word() },
                { img: '/icons/loop.svg', key: 'Dbl-click', label: m.ts_shortcuts_label_loop_word() },
                { key: 'Waveform', label: m.ts_shortcuts_label_click_to_seek() },
            ] },
        ]),
    );
</script>

<div class="tfa" role="group" aria-label={groupAria}>
    <button
        type="button" class="icon-btn" class:on={$loopTarget !== null}
        aria-pressed={$loopTarget !== null} title={loopTitle} onclick={toggleLoop}
    ><img class="img-icon" src="/icons/loop.svg" alt="" aria-hidden="true" /></button>
    <button
        type="button" class="icon-btn" class:on={$showLetters}
        aria-pressed={$showLetters} title={lettersTitle} onclick={toggleLetters}
    ><ControlIcon name="letters" /></button>
    <button
        type="button" class="icon-btn" class:on={$showPhonemes}
        aria-pressed={$showPhonemes} title={phonemesTitle} onclick={togglePhonemes}
    ><ControlIcon name="phonemes" /></button>
    <TranslationGlobe />

    <div class="guide-wrap" use:clickOutside={() => (guideOpen = false)}>
        <button
            type="button" class="icon-btn" title={guideTitle}
            aria-haspopup="dialog" aria-expanded={guideOpen}
            onclick={() => (guideOpen = !guideOpen)}
        ><ControlIcon name="help" size={15} /></button>
        {#if guideOpen}
            <div class="guide-pop">
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
        left: 50%;
        transform: translateX(-50%);
        width: min(460px, calc(100vw - var(--s-4) * 2));
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: var(--s-3);
        background: var(--panel);
        border: 1px solid var(--border-default);
        border-radius: var(--r-3);
        box-shadow: 0 16px 48px oklch(0 0 0 / 0.45);
        z-index: 50;
        padding: var(--s-3);
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
