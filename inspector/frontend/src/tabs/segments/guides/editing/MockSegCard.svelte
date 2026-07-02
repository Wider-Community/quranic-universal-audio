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
    import { i18n } from '../../../../lib/i18n/locale.svelte';
    import * as m from '../../../../lib/paraglide/messages';
    import type { PeakBucket } from '../../../../lib/types/peaks-transport';

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
        /** Depict the segment as already flagged (warm flag button fill). */
        flagged?: boolean;
        /** Render a mock flag comment thread below the card. */
        showFlagComment?: boolean;
        /** Comment text shown in the mock thread (when `showFlagComment`). */
        flagComment?: string;
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
        flagged = false,
        showFlagComment = false,
        flagComment = '',
    }: Props = $props();

    // Locale-reactive labels. The six action buttons + "Go to" reuse the REAL
    // editor's message keys so the illustration stays in lockstep with the live
    // SegmentRow; reading i18n.locale re-runs each on a switch.
    const L = $derived.by(() => {
        void i18n.locale;
        return {
            goto: m.segments_row_goto_button(),
            adjust: m.segments_row_adjust_button(),
            mergeUp: m.segments_row_merge_up_button(),
            del: m.segments_row_delete_button(),
            split: m.segments_row_split_button(),
            mergeDown: m.segments_row_merge_down_button(),
            editRef: m.segments_row_edit_ref_button(),
            cancel: m.segments_eg_mock_cancel(),
            apply: m.segments_eg_mock_apply(),
            splitConfirm: m.segments_eg_mock_split_confirm(),
            flagAria: m.segments_eg_mock_flag_aria(),
            timeAnatomy: m.segments_eg_mock_anatomy_time(),
            flagAuthorContributor: m.segments_eg_mock_flag_author_contributor(),
            flagAuthorMaintainer: m.segments_eg_mock_flag_author_maintainer(),
            flagTimeHours: m.segments_eg_mock_flag_time_hours(),
            flagTimeMinutes: m.segments_eg_mock_flag_time_minutes(),
            flagReplyBody: m.segments_eg_mock_flag_reply_body(),
            flagReplyPlaceholder: m.segments_eg_mock_flag_reply_placeholder(),
            flagReplySend: m.segments_eg_mock_flag_reply_send(),
        };
    });

    // In placeholder (anatomy) mode each slot shows its own name.
    const dIndex = $derived(placeholder ? (i18n.locale, m.segments_eg_mock_anatomy_index()) : index);
    const dRef = $derived(placeholder ? (i18n.locale, m.segments_eg_mock_anatomy_ref()) : refText);
    const dConf = $derived(placeholder ? (i18n.locale, m.segments_eg_mock_anatomy_conf()) : conf);
    const dArabic = $derived(placeholder ? (i18n.locale, m.segments_eg_mock_anatomy_text()) : arabic);
    const dFlagComment = $derived(flagComment || (i18n.locale, m.segments_eg_mock_flag_default_comment()));

    const hasEmph = $derived(emphasize.length > 0);

    /** Emphasis class for a labelled part: spotlight it, or dim it when some
     *  *other* part is being spotlighted. No-op when nothing is emphasized. */
    function ec(key: string): string {
        if (!hasEmph) return '';
        return emphasize.includes(key) ? 'is-emph' : 'is-dim';
    }
</script>

<!-- dir="ltr": the mock faithfully mirrors the real (LTR) editor card even inside
     an RTL guide, so its waveform/controls keep the live editor's geometry. -->
<div class="eg-mock-wrap" dir="ltr" class:eg-mock-flagged={showFlagComment}>
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
                    <button type="button" tabindex="-1" class="btn btn-sm btn-cancel">{L.cancel}</button>
                    <div class="seg-nudge-pair seg-nudge-start">
                        <button type="button" tabindex="-1" class="seg-nudge">&lsaquo;</button>
                        <button type="button" tabindex="-1" class="seg-nudge">&rsaquo;</button>
                    </div>
                    <span class="seg-replay" aria-hidden="true">&#8635;</span>
                    <div class="seg-nudge-pair seg-nudge-end">
                        <button type="button" tabindex="-1" class="seg-nudge">&lsaquo;</button>
                        <button type="button" tabindex="-1" class="seg-nudge">&rsaquo;</button>
                    </div>
                    <button type="button" tabindex="-1" class="btn btn-sm btn-confirm">{L.apply}</button>
                </div>
            </div>
        {:else if mode === 'split'}
            <div class="seg-edit-inline">
                <div class="seg-edit-buttons">
                    <button type="button" tabindex="-1" class="btn btn-sm btn-cancel">{L.cancel}</button>
                    <button type="button" tabindex="-1" class="seg-side-pick">L</button>
                    <div class="seg-nudge-pair seg-nudge-split">
                        <button type="button" tabindex="-1" class="seg-nudge">&lsaquo;</button>
                        <button type="button" tabindex="-1" class="seg-nudge">&rsaquo;</button>
                    </div>
                    <button type="button" tabindex="-1" class="seg-side-pick active">R</button>
                    <button type="button" tabindex="-1" class="btn btn-sm btn-confirm">{L.splitConfirm}</button>
                </div>
            </div>
        {:else}
            <div class="seg-row-controls">
                <div class="seg-row-play-actions {ec('play')}">
                    <button type="button" tabindex="-1" class="btn btn-sm seg-card-play-btn">&#9654;</button>
                    <button type="button" tabindex="-1" class="btn btn-sm seg-card-goto-btn">{L.goto}</button>
                    <button
                        type="button"
                        tabindex="-1"
                        aria-label={L.flagAria}
                        class="btn btn-sm seg-flag-btn eg-flag-btn {ec('flag')}"
                        class:is-flagged={flagged}
                    >
                        <svg class="seg-flag-icon" viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
                            <path d="M3.5 1.5v13" />
                            <path d="M3.5 2.2h8.2l-1.7 2.6 1.7 2.6H3.5z" />
                        </svg>
                    </button>
                </div>
                <div class="seg-actions">
                    <button type="button" tabindex="-1" class="btn btn-sm btn-adjust {ec('adjust')}">{L.adjust}</button>
                    <button type="button" tabindex="-1" class="btn btn-sm btn-merge-prev {ec('merge-prev')}">{L.mergeUp}</button>
                    <button type="button" tabindex="-1" class="btn btn-sm btn-delete {ec('delete')}">{L.del}</button>
                    <button type="button" tabindex="-1" class="btn btn-sm btn-split {ec('split')}">{L.split}</button>
                    <button type="button" tabindex="-1" class="btn btn-sm btn-merge-next {ec('merge-next')}">{L.mergeDown}</button>
                    <button type="button" tabindex="-1" class="btn btn-sm btn-edit-ref {ec('editref')}">{L.editRef}</button>
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
                        <span class="seg-text-duration eg-ph">{L.timeAnatomy}</span>
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

{#if showFlagComment}
    <div class="eg-flag-thread">
        <div class="eg-flag-comment">
            <div class="eg-flag-comment-head">
                <span class="eg-flag-author">{L.flagAuthorContributor}</span>
                <span class="eg-flag-time">{L.flagTimeHours}</span>
            </div>
            <div class="eg-flag-body">{dFlagComment}</div>
        </div>
        <div class="eg-flag-comment eg-flag-reply-comment">
            <div class="eg-flag-comment-head">
                <span class="eg-flag-author eg-flag-author-reply">{L.flagAuthorMaintainer}</span>
                <span class="eg-flag-time">{L.flagTimeMinutes}</span>
            </div>
            <div class="eg-flag-body">{L.flagReplyBody}</div>
        </div>
        <div class="eg-flag-reply">
            <span class="eg-flag-reply-input">{L.flagReplyPlaceholder}</span>
            <span class="eg-flag-reply-send">{L.flagReplySend}</span>
        </div>
    </div>
{/if}
</div>
