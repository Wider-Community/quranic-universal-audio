<script lang="ts">
    /**
     * SegmentsList — the <div id="seg-list"> container + Navigation banner.
     *
     * Wave 5 interim: the actual row rendering stays IMPERATIVE via
     * `renderSegList(state.segDisplayedSegments)` from segments/rendering.ts
     * (legacy call site kept alive by edit / playback / validation modules
     * through Waves 6-10). Svelte owns only the container + banner — the
     * imperative list is appended as child DOM under #seg-list. Wave 6
     * converts this to `<SegmentRow>` rendering once playback highlighting
     * no longer needs imperative `classList` pokes.
     *
     * This design avoids the "Svelte {#each} vs imperative innerHTML fight"
     * problem: if Svelte renders rows AND edit/playback code mutates
     * state.segDisplayedSegments in place + calls renderSegList, the two
     * renderers collide. Letting imperative own it during interim preserves
     * Stage-1 behaviour bit-for-bit.
     *
     * Reactive side-effect: whenever $displayedSegments changes, invoke
     * imperative renderSegList so the DOM mirrors the current derivation.
     *
     * Back-banner position: `.seg-back-banner` uses `position: sticky`
     * scoped to #seg-list's scroll container, so it must live inside
     * #seg-list. renderSegList preserves the banner by walking children and
     * removing only non-banner children before appending fresh rows.
     */

    import { onMount } from 'svelte';

    import { displayedSegments } from '../../lib/stores/segments/filters';
    import { renderSegList } from '../../segments/rendering';
    import Navigation from './Navigation.svelte';

    export let onRestore: (() => void) | null = null;

    let listEl: HTMLDivElement | undefined;

    // Side-effect: re-render the imperative list whenever the derived
    // store changes (chapter load, verse filter, active-filter application,
    // edit/save/undo refreshes triggered via applyFiltersAndRender). The
    // imperative renderer attaches the IntersectionObserver and handles
    // missing-word tags from state.segValidation — no duplication here.
    let _prevRef: unknown = null;
    $: if (listEl && $displayedSegments !== _prevRef) {
        _prevRef = $displayedSegments;
        renderSegList($displayedSegments);
    }

    onMount(() => {
        // Trigger initial render (if any segments are already in the store).
        if (listEl) renderSegList($displayedSegments);
    });
</script>

<div id="seg-list" class="seg-list" bind:this={listEl}>
    <!-- Navigation banner stays inside #seg-list so `.seg-back-banner`'s
         `position: sticky` scopes to the list's scroll container. The
         imperative renderSegList call path preserves this element — it
         removes only non-banner children before appending fresh rows. -->
    <Navigation on:restore={() => onRestore && onRestore()} />
</div>
