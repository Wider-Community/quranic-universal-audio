<script lang="ts">
    /**
     * Timestamps footer — "Report" button + category drop-up (BottomPlayer
     * `loc-lead` slot, just left of the surah picker). Files a categorized issue
     * against the verse currently playing; visible to everyone holding
     * `timestamps.report` (anonymous-eligible). Disabled until a verse loads.
     *
     * The verse + reciter are SNAPSHOTTED when the drop-up opens, so the report
     * targets what the user was hearing even if playback advances. The drop-up
     * shows the category taxonomy (ReportMenu); audio/other expand a comment
     * composer INLINE in their row; the grid-target categories enter report mode.
     * The button (and each reported category) lights amber when the playing
     * verse already carries open reports.
     */
    import { clickOutside } from '../../../lib/actions/click-outside';
    import { can } from '../../../lib/stores/capabilities';
    import { playerContext } from '../../../lib/stores/player-context';
    import type { TsReport } from '../../../lib/types/generated/schemas';
    import { getVerseReports } from '../services/reports-client';
    import { enterTajweed, enterTiming, type TajweedSubtype } from '../stores/report-mode';
    import { loadReciterReports, openReportedVerseKeys } from '../stores/ts-reports';
    import { selectedVerse } from '../stores/verse';
    import ReportIcon from './report/ReportIcon.svelte';
    import ReportMenu from './report/ReportMenu.svelte';

    const canReport = can('timestamps.report');

    let open = $state(false);
    let snapSlug = $state('');
    let snapVerse = $state('');
    let verseReports = $state<TsReport[]>([]);

    const curSlug = $derived($playerContext.delivery?.slug ?? '');
    const curVerse = $derived($selectedVerse);
    const disabled = $derived(!curSlug || !curVerse);
    const isReported = $derived(!!curVerse && $openReportedVerseKeys.has(curVerse));

    // Keep the reciter-level reported-verse counts (button highlight) in sync
    // with the playing reciter.
    let lastSlug = '';
    $effect(() => {
        const slug = curSlug;
        if (slug !== lastSlug) {
            lastSlug = slug;
            void loadReciterReports(slug);
        }
    });

    async function loadVerse(): Promise<void> {
        if (!snapSlug || !snapVerse) return;
        try {
            const doc = await getVerseReports(snapSlug, snapVerse);
            verseReports = doc.reports ?? [];
        } catch {
            verseReports = [];
        }
    }

    function toggle(): void {
        if (open) {
            open = false;
            return;
        }
        if (disabled) return;
        snapSlug = curSlug;
        snapVerse = curVerse;
        verseReports = [];
        open = true;
        void loadVerse();
    }

    function onChanged(): void {
        void loadVerse();
        void loadReciterReports(snapSlug);
    }

    function onEnterMode(mode: 'timing' | 'tajweed', subtype?: TajweedSubtype): void {
        open = false;
        if (!snapSlug || !snapVerse) return;
        if (mode === 'timing') enterTiming(snapSlug, snapVerse);
        else enterTajweed(snapSlug, snapVerse, subtype ?? 'wrong_rule');
    }

    // Shift a left-anchored drop-up back on-screen if it overflows the right
    // edge on a narrow window.
    function keepInView(node: HTMLElement) {
        const margin = 8;
        const place = (): void => {
            node.style.left = '0px';
            node.style.maxWidth = '';
            const overflow = node.getBoundingClientRect().right - (window.innerWidth - margin);
            if (overflow > 0) node.style.left = `${-overflow}px`;
            node.style.maxWidth = `${window.innerWidth - margin * 2}px`;
        };
        place();
        window.addEventListener('resize', place);
        return { destroy: () => window.removeEventListener('resize', place) };
    }
</script>

{#if $canReport}
    <div class="report-wrap" use:clickOutside={() => (open = false)}>
        <button
            type="button"
            class="report-btn"
            class:reported={isReported}
            class:on={open}
            {disabled}
            onclick={toggle}
            aria-haspopup="menu"
            aria-expanded={open}
            aria-label={`Report a timestamps issue${curVerse ? ` on verse ${curVerse}` : ''}`}
            title="Report a timestamps issue"
        >
            <ReportIcon name="flag" size={14} />
            <span>Report</span>
        </button>

        {#if open}
            <div class="report-pop" use:keepInView>
                <ReportMenu
                    slug={snapSlug}
                    verseKey={snapVerse}
                    {verseReports}
                    onchanged={onChanged}
                    onenterMode={onEnterMode}
                />
            </div>
        {/if}
    </div>
{/if}

<style>
    .report-wrap {
        position: relative;
        display: inline-flex;
        flex: 0 0 auto;
        align-self: center;
    }
    .report-btn {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        padding: 4px var(--s-2);
        line-height: 1.2;
        color: var(--text-muted);
        background: var(--panel-2);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        cursor: pointer;
        font: inherit;
        font-size: var(--fs-meta);
        white-space: nowrap;
        transition: color var(--t-fast), background var(--t-fast), border-color var(--t-fast);
    }
    .report-btn:hover:not(:disabled) {
        color: var(--text-primary);
        border-color: var(--border-strong);
        background: var(--panel);
    }
    .report-btn.on {
        color: var(--text-primary);
        border-color: var(--border-strong);
        background: var(--panel);
    }
    .report-btn:disabled { opacity: 0.5; cursor: default; }
    /* Amber "reported" highlight (the one warning voice). */
    .report-btn.reported {
        color: var(--state-warn-fg);
        border-color: var(--state-warn-border);
        background: var(--state-warn-bg);
    }
    .report-btn.reported:hover:not(:disabled) {
        background: color-mix(in oklab, var(--state-warn-bg), var(--state-warn-fg) 8%);
    }

    .report-pop {
        position: absolute;
        bottom: calc(100% + var(--s-2));
        left: 0;
        width: max-content;
        max-width: min(380px, calc(100vw - 16px));
        max-height: min(640px, 70vh);
        overflow-y: auto;
        background: var(--panel);
        border: 1px solid var(--border-default);
        border-radius: var(--r-3);
        box-shadow: 0 16px 48px oklch(0 0 0 / 0.45);
        z-index: 50;
        padding: var(--s-3);
    }
</style>
