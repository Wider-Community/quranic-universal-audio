<script lang="ts">
    /**
     * Project-overview modal ("About Qur'anic Universal Audio") — a single host
     * mounted in `App.svelte`, driven by the `infoModalOpen` store. Opened from
     * the dashboard ⓘ button AND the segments first-edit gate's Overview row, so
     * it looks identical in both places: a narrow `Modal` wrapping the shared
     * `OverviewContent`. `elevated` lets it stack above the segments guides gate.
     *
     * Opening it marks the `overview` onboarding guide as read — the same signal
     * the segments edit gate consumes — so a visitor who read it here isn't
     * re-gated on it. Mirrors AccordionGuideModal's record-on-open; `overview`
     * has no alias, so the raw key is the stored view key.
     */
    import { get } from 'svelte/store';

    import { i18n } from '$lib/i18n/locale.svelte';

    import { recordGuideViewed } from '../../api/guide-views';
    import { currentUser, markGuideReadLocally } from '../../stores/current-user';
    import { closeInfoModal, infoModalOpen } from '../../stores/info-modal';
    import Modal from '../Modal.svelte';
    import { getOverviewDoc } from './overview';
    import OverviewContent from './OverviewContent.svelte';

    const overviewDoc = $derived(getOverviewDoc(i18n.locale));

    $effect(() => {
        if ($infoModalOpen) void recordOverviewRead();
    });

    async function recordOverviewRead(): Promise<void> {
        const u = get(currentUser);
        if (u.hf_user_id === null || u.guides_read.includes('overview')) return;
        // Optimistic first (clears the gate signal instantly), then persist.
        markGuideReadLocally('overview');
        await recordGuideViewed('overview');
    }
</script>

<Modal open={$infoModalOpen} size="narrow" elevated title={overviewDoc.title} on:close={closeInfoModal}>
    <div slot="header" class="info-head">
        <h2 class="info-title">{overviewDoc.title}</h2>
    </div>
    <OverviewContent />
</Modal>

<style>
    .info-head {
        flex: 1;
        display: flex;
        justify-content: center;
        min-width: 0;
        /* Mirror the 32px close button on the right so the title centers across
         * the whole header, not just the space to its left. */
        padding-inline-start: 32px;
    }
    .info-title {
        margin: 0;
        font-size: var(--fs-h3);
        font-weight: 500;
        letter-spacing: 0.005em;
        color: var(--text-primary);
        text-align: center;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
</style>
