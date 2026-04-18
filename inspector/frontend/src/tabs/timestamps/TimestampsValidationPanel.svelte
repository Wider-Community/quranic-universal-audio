<script lang="ts">
    /**
     * TimestampsValidationPanel — 3-category accordion for /api/ts/validate.
     *
     * Port of Stage-1 timestamps/validation.ts. Three categories (Failed
     * Alignments, Missing Words, Boundary Mismatches) each render an
     * AccordionPanel with a ValidationBadge and a list of issue buttons that
     * jump to the offending verse via the `onJump` callback prop.
     */

    import AccordionPanel from '../../lib/components/AccordionPanel.svelte';
    import ValidationBadge from '../../lib/components/ValidationBadge.svelte';
    import { validationData } from '../../lib/stores/timestamps/verse';
    import type {
        TsBoundaryMismatch,
        TsMfaFailure,
        TsMissingWords,
    } from '../../lib/types/domain';

    /** Parent-supplied handler: jump the verse dropdown to the clicked issue. */
    export let onJump: (verseKey: string) => void;

    $: data = $validationData;
    $: mfa = data?.mfa_failures ?? [];
    $: missing = data?.missing_words ?? [];
    $: boundary = data?.boundary_mismatches ?? [];
    $: hasAny = mfa.length + missing.length + boundary.length > 0;

    function mfaTitle(i: TsMfaFailure): string {
        return i.error || '';
    }
    function missingTitle(i: TsMissingWords): string {
        return `missing indices: ${(i.missing || []).join(', ')}`;
    }
    function boundaryTitle(i: TsBoundaryMismatch): string {
        return `${i.side} boundary drift: ${i.diff_ms}ms`;
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
</div>
