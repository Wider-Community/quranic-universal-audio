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

    import { recordGuideViewed } from '../../api/guide-views';
    import { currentUser, markGuideReadLocally } from '../../stores/current-user';
    import { closeInfoModal, infoModalOpen } from '../../stores/info-modal';
    import Modal from '../Modal.svelte';
    import { overviewDoc } from './overview';
    import OverviewContent from './OverviewContent.svelte';

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
    <OverviewContent />
</Modal>
