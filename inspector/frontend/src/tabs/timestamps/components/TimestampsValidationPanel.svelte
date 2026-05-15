<script lang="ts">
    /**
     * TimestampsValidationPanel — accordion of issue categories surfaced by
     * `/api/ts/validate`. Each category renders an AccordionPanel + badge
     * and a list of jump buttons that move the verse dropdown via the
     * `onJump` callback prop.
     *
     * HF mode usually only carries pre-computed boundary_mismatches; the
     * other arrays come back empty and their panels self-hide. In local
     * mode the validator runs server-side and populates everything.
     */

    import AccordionPanel from '../../../lib/components/AccordionPanel.svelte';
    import ValidationBadge from '../../../lib/components/ValidationBadge.svelte';
    import type {
        TsBoundaryMismatch,
        TsLargeGap,
        TsMfaFailure,
        TsMissingVerse,
        TsMissingWords,
        TsVerseOverlap,
    } from '../../../lib/types/domain';
    import { validationData } from '../stores/verse';

    /** Parent-supplied handler: jump the verse dropdown to the clicked issue. */
    export let onJump: (_verseKey: string) => void;

    $: data = $validationData;
    $: mfa = data?.mfa_failures ?? [];
    $: missingVerses = data?.missing_verses ?? [];
    $: missing = data?.missing_words ?? [];
    $: overlaps = data?.verse_overlaps ?? [];
    $: boundary = data?.boundary_mismatches ?? [];
    $: gaps = data?.large_gaps ?? [];
    $: hasAny =
        mfa.length + missingVerses.length + missing.length +
        overlaps.length + boundary.length + gaps.length > 0;

    function mfaTitle(i: TsMfaFailure): string {
        return i.error || '';
    }
    function missingTitle(i: TsMissingWords): string {
        return `missing indices: ${(i.missing || []).join(', ')}`;
    }
    function overlapTitle(i: TsVerseOverlap): string {
        return `overlaps with ${i.prev_verse_key} by ${i.overlap_ms}ms`;
    }
    function boundaryTitle(i: TsBoundaryMismatch): string {
        return `${i.side} boundary drift: ${i.diff_ms}ms`;
    }
    function gapTitle(i: TsLargeGap): string {
        return `gap of ${(i.gap_ms / 1000).toFixed(1)}s after ${i.prev_verse_key}`;
    }
</script>

<div id="ts-validation" class="seg-validation" hidden={!hasAny}>
    {#if mfa.length > 0}
        <AccordionPanel label="Failed Alignments" category="ts-mfa" open={false}>
            <ValidationBadge label="Failed Alignments" count={mfa.length} tone="error" />
            <div class="val-items">
                {#each mfa as issue (issue.verse_key)}
                    <button
                        class="val-btn val-error"
                        title={mfaTitle(issue)}
                        on:click={() => onJump(issue.verse_key)}
                    >{issue.label}</button>
                {/each}
            </div>
        </AccordionPanel>
    {/if}
    {#if missingVerses.length > 0}
        <AccordionPanel label="Missing Verses" category="ts-missing-verses" open={false}>
            <ValidationBadge label="Missing Verses" count={missingVerses.length} tone="error" />
            <div class="val-items">
                {#each missingVerses as issue (issue.verse_key)}
                    <button
                        class="val-btn val-error"
                        title={`verse has no timestamp coverage`}
                        on:click={() => onJump(issue.verse_key)}
                    >{issue.label}</button>
                {/each}
            </div>
        </AccordionPanel>
    {/if}
    {#if missing.length > 0}
        <AccordionPanel label="Missing Words" category="ts-missing" open={false}>
            <ValidationBadge label="Missing Words" count={missing.length} tone="error" />
            <div class="val-items">
                {#each missing as issue (issue.verse_key)}
                    <button
                        class="val-btn val-error"
                        title={missingTitle(issue)}
                        on:click={() => onJump(issue.verse_key)}
                    >{issue.label}</button>
                {/each}
            </div>
        </AccordionPanel>
    {/if}
    {#if overlaps.length > 0}
        <AccordionPanel label="Verse Overlaps" category="ts-overlaps" open={false}>
            <ValidationBadge label="Verse Overlaps" count={overlaps.length} tone="error" />
            <div class="val-items">
                {#each overlaps as issue (issue.verse_key)}
                    <button
                        class="val-btn val-error"
                        title={overlapTitle(issue)}
                        on:click={() => onJump(issue.verse_key)}
                    >{issue.label}</button>
                {/each}
            </div>
        </AccordionPanel>
    {/if}
    {#if boundary.length > 0}
        <AccordionPanel label="Boundary Mismatches" category="ts-boundary" open={false}>
            <ValidationBadge label="Boundary Mismatches" count={boundary.length} tone="warning" />
            <div class="val-items">
                {#each boundary as issue, i (i)}
                    <button
                        class="val-btn val-warning"
                        title={boundaryTitle(issue)}
                        on:click={() => onJump(issue.verse_key)}
                    >{issue.label}</button>
                {/each}
            </div>
        </AccordionPanel>
    {/if}
    {#if gaps.length > 0}
        <AccordionPanel label="Large Gaps" category="ts-gaps" open={false}>
            <ValidationBadge label="Large Gaps" count={gaps.length} tone="warning" />
            <div class="val-items">
                {#each gaps as issue (issue.verse_key)}
                    <button
                        class="val-btn val-warning"
                        title={gapTitle(issue)}
                        on:click={() => onJump(issue.verse_key)}
                    >{issue.label}</button>
                {/each}
            </div>
        </AccordionPanel>
    {/if}
</div>
