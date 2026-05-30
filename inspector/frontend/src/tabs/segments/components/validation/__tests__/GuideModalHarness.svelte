<!--
    Test harness mirroring SegmentsTab's composition: the ValidationPanel `?`
    sets the `guideModal` store, and a single AccordionGuideModal host renders
    whatever is set. Lets the modal integration test exercise the real
    store-driven open path without standing up the whole tab.
-->
<script lang="ts">
    import { closeGuideModal, guideModal } from '../../../stores/guides';
    import AccordionGuideModal from '../AccordionGuideModal.svelte';
    import ValidationPanel from '../ValidationPanel.svelte';
</script>

<ValidationPanel />

{#if $guideModal}
    <AccordionGuideModal
        category={$guideModal.category}
        opener={$guideModal.opener}
        on:close={closeGuideModal}
    />
{/if}
