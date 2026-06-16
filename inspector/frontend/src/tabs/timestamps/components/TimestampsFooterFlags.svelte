<script lang="ts">
    /**
     * Timestamps footer — "Report" button (BottomPlayer `loc-lead` slot, just
     * left of the surah picker). Flags the verse currently playing for a
     * timestamps issue. Visible to everyone holding `timestamps.flag` (open to
     * anonymous by default); disabled until a verse is loaded.
     *
     * The verse + reciter are SNAPSHOTTED at click time, so the report targets
     * what the user was hearing even if playback advances before they submit.
     * Opening the modal shows every comment on that verse and lets the caller
     * add/edit their own. The button lights up when the playing verse already
     * carries reports.
     */
    import { can } from '../../../lib/stores/capabilities';
    import { playerContext } from '../../../lib/stores/player-context';
    import { selectedVerse } from '../stores/verse';
    import { loadTsFlags, tsFlaggedVerses } from '../stores/ts-flags';
    import TsFlagModal from './TsFlagModal.svelte';

    const canFlag = can('timestamps.flag');

    let modalOpen = $state(false);
    let snapSlug = $state('');
    let snapVerse = $state('');

    const curSlug = $derived($playerContext.delivery?.slug ?? '');
    const curVerse = $derived($selectedVerse);
    const disabled = $derived(!curSlug || !curVerse);
    const flaggedVerseKeys = $derived(new Set($tsFlaggedVerses.map((f) => f.verse_key)));
    const isFlagged = $derived(!!curVerse && flaggedVerseKeys.has(curVerse));

    function openReport(): void {
        if (disabled) return;
        snapSlug = curSlug;
        snapVerse = curVerse;
        modalOpen = true;
    }

    function onClose(): void {
        modalOpen = false;
    }

    function onChanged(): void {
        if (snapSlug) void loadTsFlags(snapSlug);
    }
</script>

{#if $canFlag}
    <button
        type="button"
        class="report-btn"
        class:flagged={isFlagged}
        {disabled}
        onclick={openReport}
        aria-label={`Report a timestamps issue${curVerse ? ` on verse ${curVerse}` : ''}`}
        title="Report a timestamps issue"
    >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
                d="M5 21V4M5 4h11l-2 4 2 4H5"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
            />
        </svg>
        <span>Report</span>
    </button>

    {#if snapSlug && snapVerse}
        <TsFlagModal
            open={modalOpen}
            slug={snapSlug}
            verseKey={snapVerse}
            onclose={onClose}
            onchanged={onChanged}
        />
    {/if}
{/if}

<style>
    .report-btn {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        flex: 0 0 auto;
        height: 100%;
        align-self: stretch;
        padding: 0 var(--s-2);
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
    .report-btn:disabled { opacity: 0.5; cursor: default; }
    .report-btn.flagged {
        color: hsl(38 92% 52%);
        border-color: color-mix(in srgb, hsl(38 92% 52%) 55%, var(--border-quiet));
        background: color-mix(in srgb, hsl(38 92% 52%) 12%, var(--panel-2));
    }
    .report-btn svg { flex: 0 0 auto; }
</style>
