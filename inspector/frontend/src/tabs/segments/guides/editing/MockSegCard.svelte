<script lang="ts">
    /**
     * A static, inert replica of a real segment card (`SegmentRow`) for the
     * editing guide. It reuses the real global card classes (`.seg-row`,
     * `.seg-text*`, `.seg-actions`, `.btn-*`, the trim/split toolbar classes)
     * so it looks identical, but renders no audio/canvas-edit runtime — the
     * waveform is a synthetic `WaveformCanvas` and every control is a disabled,
     * non-focusable mock.
     *
     * `mode` picks which state to depict:
     *   - default   → play/go-to + the six action buttons
     *   - adjust    → the trim toolbar + green/red boundary cursors on the wave
     *   - split     → the split toolbar (L · ‹›· R) + a yellow split cursor
     *   - reference → default controls, but the ref shows as an active input
     *
     * `emphasize` lists part keys to spotlight (`.is-emph`); when non-empty,
     * every other labelled part dims (`.is-dim`). `compact` drops the text
     * column for the narrower follow-up cards.
     */
    import WaveformCanvas from '../../../../lib/components/WaveformCanvas.svelte';
    import type { PeakBucket } from '../../../../lib/types/domain';

    type Mode = 'default' | 'adjust' | 'split' | 'reference';

    interface Props {
        peaks: PeakBucket[];
        index?: string;
        refText?: string;
        conf?: string;
        confLevel?: 'high' | 'mid' | 'low' | 'fail';
        timeFrom?: string;
        timeTo?: string;
        duration?: string;
        arabic?: string;
        mode?: Mode;
        compact?: boolean;
        emphasize?: string[];
        /** Anatomy mode: show each slot's NAME ("Reference", "Confidence", …)
         *  in place of a value, so the card reads as a labelled diagram. */
        placeholder?: boolean;
    }

    let {
        peaks,
        index = '#664',
        // Reference and Arabic are kept in sync: 2:250:1-2:250:5 is exactly the
        // five words shown ("And when they went forth …", al-Baqarah 250).
        refText = '2:250:1-2:250:5',
        conf = '100.0%',
        confLevel = 'high',
        timeFrom = '01:21:22.337',
        timeTo = '01:21:27.200',
        duration = '4.9s',
        arabic = 'وَلَمَّا بَرَزُوا لِجَالُوتَ وَجُنُودِهِ قَالُوا',
        mode = 'default',
        compact = false,
        emphasize = [],
        placeholder = false,
    }: Props = $props();

    // In placeholder (anatomy) mode each slot shows its own name.
    const dIndex = $derived(placeholder ? 'Segment number' : index);
    const dRef = $derived(placeholder ? 'Reference' : refText);
    const dConf = $derived(placeholder ? 'Confidence' : conf);
    const dArabic = $derived(placeholder ? 'Quran reference text' : arabic);

    const hasEmph = $derived(emphasize.length > 0);

    /** Emphasis class for a labelled part: spotlight it, or dim it when some
     *  *other* part is being spotlighted. No-op when nothing is emphasized. */
    function ec(key: string): string {
        if (!hasEmph) return '';
        return emphasize.includes(key) ? 'is-emph' : 'is-dim';
    }
</script>

<div class="seg-row eg-static" class:eg-compact={compact} aria-hidden="true">
    <div class="seg-left">
        <div class="eg-wave {ec('peak')}">
            <WaveformCanvas {peaks} width={360} height={60} />
            {#if mode === 'adjust'}
                <div class="eg-dim-region" style="left:0;width:11%"></div>
                <div class="eg-cursor start" style="left:11%"></div>
                <div class="eg-cursor end" style="left:89%"></div>
                <div class="eg-dim-region" style="left:89%;right:0"></div>
            {:else if mode === 'split'}
                <div class="eg-cursor split" style="left:54%"></div>
            {/if}
        </div>

        {#if mode === 'adjust'}
            <div class="seg-edit-inline">
                <div class="seg-edit-buttons">
                    <button type="button" tabindex="-1" class="btn btn-sm btn-cancel">Cancel</button>
                    <div class="seg-nudge-pair seg-nudge-start">
                        <button type="button" tabindex="-1" class="seg-nudge">&lsaquo;</button>
                        <button type="button" tabindex="-1" class="seg-nudge">&rsaquo;</button>
                    </div>
                    <span class="seg-replay" aria-hidden="true">&#8635;</span>
                    <div class="seg-nudge-pair seg-nudge-end">
                        <button type="button" tabindex="-1" class="seg-nudge">&lsaquo;</button>
                        <button type="button" tabindex="-1" class="seg-nudge">&rsaquo;</button>
                    </div>
                    <button type="button" tabindex="-1" class="btn btn-sm btn-confirm">Apply</button>
                </div>
            </div>
        {:else if mode === 'split'}
            <div class="seg-edit-inline">
                <div class="seg-edit-buttons">
                    <button type="button" tabindex="-1" class="btn btn-sm btn-cancel">Cancel</button>
                    <button type="button" tabindex="-1" class="seg-side-pick">L</button>
                    <div class="seg-nudge-pair seg-nudge-split">
                        <button type="button" tabindex="-1" class="seg-nudge">&lsaquo;</button>
                        <button type="button" tabindex="-1" class="seg-nudge">&rsaquo;</button>
                    </div>
                    <button type="button" tabindex="-1" class="seg-side-pick active">R</button>
                    <button type="button" tabindex="-1" class="btn btn-sm btn-confirm">Split</button>
                </div>
            </div>
        {:else}
            <div class="seg-row-controls">
                <div class="seg-row-play-actions {ec('play')}">
                    <button type="button" tabindex="-1" class="btn btn-sm seg-card-play-btn">&#9654;</button>
                    <button type="button" tabindex="-1" class="btn btn-sm seg-card-goto-btn">Go to</button>
                </div>
                <div class="seg-actions">
                    <button type="button" tabindex="-1" class="btn btn-sm btn-adjust {ec('adjust')}">Adjust</button>
                    <button type="button" tabindex="-1" class="btn btn-sm btn-merge-prev {ec('merge-prev')}">Merge &uarr;</button>
                    <button type="button" tabindex="-1" class="btn btn-sm btn-delete {ec('delete')}">Delete</button>
                    <button type="button" tabindex="-1" class="btn btn-sm btn-split {ec('split')}">Split</button>
                    <button type="button" tabindex="-1" class="btn btn-sm btn-merge-next {ec('merge-next')}">Merge &darr;</button>
                    <button type="button" tabindex="-1" class="btn btn-sm btn-edit-ref {ec('editref')}">Edit Ref</button>
                </div>
            </div>
        {/if}
    </div>

    {#if !compact}
        <div class="seg-text conf-{confLevel}">
            <div class="seg-text-meta">
                <div class="seg-text-header">
                    <span class="seg-text-index {ec('index')}" class:eg-ph={placeholder}>{dIndex}</span>
                    <span class="seg-text-sep">|</span>
                    {#if mode === 'reference'}
                        <input class="seg-text-ref-input {ec('ref')}" value={dRef} readonly tabindex="-1" />
                    {:else}
                        <span class="seg-text-ref {ec('ref')}" class:eg-ph={placeholder}>{dRef}</span>
                    {/if}
                    <span class="seg-text-sep">|</span>
                    <span class="seg-text-conf conf-{confLevel} {ec('conf')}" class:eg-ph={placeholder}>{dConf}</span>
                </div>
                <div class="seg-text-times {ec('time')}" class:seg-text-time-editing={mode === 'adjust'}>
                    {#if placeholder}
                        <span class="seg-text-duration eg-ph">Time from - Time to | &amp; duration</span>
                    {:else}
                        <span class="seg-text-time-range">
                            <span class="seg-text-time">{timeFrom}</span>
                            <span class="seg-time-sep">&ndash;</span>
                            <span class="seg-text-time">{timeTo}</span>
                        </span>
                        <span class="seg-text-sep">|</span>
                        <span class="seg-text-duration">{duration}</span>
                    {/if}
                </div>
            </div>
            <div class="seg-text-body {ec('arabic')}" class:eg-ph-text={placeholder}>{dArabic}</div>
        </div>
    {/if}
</div>
