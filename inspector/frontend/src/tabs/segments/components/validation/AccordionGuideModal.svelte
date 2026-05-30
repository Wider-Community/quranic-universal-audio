<script lang="ts">
    import { createEventDispatcher, onDestroy, onMount, tick } from 'svelte';
    import { get } from 'svelte/store';

    import { recordGuideViewed } from '../../../../lib/api/guide-views';
    import AudioElement from '../../../../lib/components/AudioElement.svelte';
    import { currentUser, loadCurrentUser, markGuideReadLocally } from '../../../../lib/stores/current-user';
    import type { HistoryBatch } from '../../../../lib/types/domain';
    import { getGuideExample } from '../../guides/examples';
    import { guideTitleFromBlocks, parseGuideSource } from '../../guides/parser';
    import { getAccordionGuide, guideViewKey, isGuideRead } from '../../guides/registry';
    import type { GuideExample } from '../../guides/types';
    import {
        buildEditChains,
        type HistorySnapshot,
        snapToSeg,
    } from '../../stores/history';
    import { createPreviewPlaybackContext } from '../../utils/playback/preview';
    import { indexHistoryPeaksRecords } from '../../utils/waveform/utils';
    import EditChainRow from '../history/EditChainRow.svelte';
    import HistoryOp from '../history/HistoryOp.svelte';
    import SegmentRow from '../list/SegmentRow.svelte';

    export let category: string;
    export let opener: HTMLElement | null = null;

    const dispatch = createEventDispatcher<{ close: void }>();
    const previewCtx = createPreviewPlaybackContext({ persistPeaks: false });

    let audio: AudioElement;
    let dialogEl: HTMLElement;

    $: if (audio) {
        previewCtx.attachAudioEl(audio.element());
    }

    // Record-on-open: opening a guide marks it read (per the product rule
    // "once it's opened, it goes away"). The host reuses this instance across
    // categories (the gate modal opens guides back-to-back), so this tracks the
    // last category recorded rather than firing only on mount. Idempotent: the
    // server write is INSERT-OR-IGNORE and the local update dedups.
    let _recordedFor: string | null = null;
    $: if (category && category !== _recordedFor) {
        _recordedFor = category;
        void recordGuideRead(category);
    }

    async function recordGuideRead(cat: string): Promise<void> {
        const u = get(currentUser);
        if (u.hf_user_id == null) return;            // anonymous: nothing to persist
        if (isGuideRead(u.guides_read, cat)) return; // already read — skip the POST
        // Optimistic FIRST: clear the cyan badge (and lift the edit gate on the
        // last guide) instantly, instead of waiting on the POST — which blocks
        // on a full inspector.db → bucket sync inside durable_transaction.
        markGuideReadLocally(guideViewKey(cat));
        const ok = await recordGuideViewed(cat);     // background persist
        if (!ok) void loadCurrentUser();             // failure → resync truth from /api/me
    }

    $: guideSource = getAccordionGuide(category);
    $: blocks = guideSource ? parseGuideSource(guideSource) : [];
    $: title = guideTitleFromBlocks(blocks, category);
    $: {
        for (const block of blocks) {
            if (block.type !== 'example') continue;
            const ex = getGuideExample(block.id);
            indexHistoryPeaksRecords(ex?.peaks);
            // Register the clip's base offset so playback rebases into the
            // short same-origin clip while cards keep original timestamps.
            const clipUrl = ex?.peaks?.[0]?.url;
            if (clipUrl && ex?.clip_base_ms != null) {
                previewCtx.setClipBase(clipUrl, ex.clip_base_ms);
            }
        }
    }

    function close(): void {
        dispatch('close');
        void tick().then(() => opener?.focus());
    }

    function onKeydown(e: KeyboardEvent): void {
        if (e.key === 'Escape') {
            e.preventDefault();
            close();
        }
    }

    function onBackdropClick(e: MouseEvent): void {
        if (e.target === e.currentTarget) {
            close();
        }
    }

    function guideBatch(example: GuideExample): HistoryBatch {
        return {
            batch_id: null,
            batch_type: null,
            saved_at_utc: null,
            chapter: example.chapter,
            save_mode: null,
            is_revert: false,
            operations: example.operations,
        };
    }

    function guideChain(example: GuideExample) {
        const built = buildEditChains([guideBatch(example)]);
        return Array.from(built.chains.values())[0] ?? null;
    }

    function exampleFor(id: string): GuideExample | null {
        return getGuideExample(id);
    }

    onMount(() => {
        document.addEventListener('keydown', onKeydown);
        void tick().then(() => dialogEl?.focus());
    });

    onDestroy(() => {
        document.removeEventListener('keydown', onKeydown);
        previewCtx.dispose();
    });
</script>

<div class="accordion-guide-backdrop" role="presentation" on:click={onBackdropClick}>
    <div
        class="accordion-guide-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="accordion-guide-title"
        tabindex="-1"
        bind:this={dialogEl}
    >
        <header class="accordion-guide-header">
            <div>
                <div class="accordion-guide-kicker">Accordion guide</div>
                <h2 id="accordion-guide-title">{title}</h2>
            </div>
            <button
                type="button"
                class="accordion-guide-close"
                aria-label="Close accordion guide"
                on:click={close}
            >&times;</button>
        </header>

        <div class="accordion-guide-body">
            {#if !guideSource}
                <p class="accordion-guide-muted">No guide yet.</p>
            {:else}
                <div class="accordion-guide-flow">
                    {#each blocks as block, i (`${block.type}:${i}`)}
                        {#if block.type === 'heading' && block.level === 1}
                            <!-- The first H1 is already used as the modal title. -->
                        {:else if block.type === 'heading'}
                            <h3 class="accordion-guide-heading">{block.text}</h3>
                        {:else if block.type === 'paragraph'}
                            <p>{block.text}</p>
                        {:else if block.type === 'missing'}
                            <p class="accordion-guide-error">{block.message}</p>
                        {:else if block.type === 'example'}
                            {@const example = exampleFor(block.id)}
                            {#if !example}
                                <p class="accordion-guide-error">Missing guide example: {block.id}</p>
                            {:else}
                            <article class="accordion-guide-example">
                                <header class="accordion-guide-example-header">
                                    <h3>{example.title}</h3>
                                    {#if example.description}
                                        <p>{example.description}</p>
                                    {/if}
                                </header>

                                {#each (example.context ?? []).filter((c) => c.position === 'before') as ctx}
                                    <div class="accordion-guide-context">
                                        <div class="accordion-guide-context-label">{ctx.label}</div>
                                        {#each ctx.segments as snap}
                                            <SegmentRow
                                                seg={snapToSeg(snap as HistorySnapshot, example.chapter)}
                                                readOnly={true}
                                                showChapter={true}
                                                showPlayBtn={true}
                                                mode="history"
                                                instanceRole="history"
                                                {previewCtx}
                                            />
                                        {/each}
                                    </div>
                                {/each}

                                {#if example.render === 'edit_chain'}
                                    {@const chain = guideChain(example)}
                                    {#if chain}
                                        <EditChainRow {chain} {previewCtx} mode="preview" variant="guide" />
                                    {/if}
                                {:else}
                                    <HistoryOp
                                        group={example.operations}
                                        chapter={example.chapter}
                                        batchId={null}
                                        skipLabel={true}
                                        {previewCtx}
                                    />
                                {/if}

                                {#each (example.context ?? []).filter((c) => c.position === 'after') as ctx}
                                    <div class="accordion-guide-context">
                                        <div class="accordion-guide-context-label">{ctx.label}</div>
                                        {#each ctx.segments as snap}
                                            <SegmentRow
                                                seg={snapToSeg(snap as HistorySnapshot, example.chapter)}
                                                readOnly={true}
                                                showChapter={true}
                                                showPlayBtn={true}
                                                mode="history"
                                                instanceRole="history"
                                                {previewCtx}
                                            />
                                        {/each}
                                    </div>
                                {/each}
                            </article>
                            {/if}
                        {/if}
                    {/each}
                </div>
            {/if}
        </div>

        <AudioElement bind:this={audio} />
    </div>
</div>

<style>
    .accordion-guide-backdrop {
        position: fixed;
        inset: 0;
        z-index: 1000;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 24px;
        background: rgba(3, 6, 18, 0.72);
    }

    .accordion-guide-modal {
        width: min(980px, calc(100vw - 32px));
        max-height: min(840px, calc(100vh - 32px));
        display: flex;
        flex-direction: column;
        border: 1px solid #2a2a4a;
        border-radius: 8px;
        background: #0f172f;
        box-shadow: 0 24px 80px rgba(0, 0, 0, 0.45);
        color: #e6e8f2;
        outline: none;
    }

    .accordion-guide-header {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 16px;
        padding: 18px 20px 14px;
        border-bottom: 1px solid #27324f;
        background: #16213e;
    }

    .accordion-guide-kicker {
        margin-bottom: 4px;
        color: #9da9c7;
        font-size: 0.78rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }

    .accordion-guide-header h2 {
        margin: 0;
        font-size: 1.2rem;
        line-height: 1.25;
    }

    .accordion-guide-close {
        width: 32px;
        height: 32px;
        border: 1px solid #34405f;
        border-radius: 6px;
        background: #101a33;
        color: #d5daeb;
        cursor: pointer;
        font-size: 1.35rem;
        line-height: 1;
    }

    .accordion-guide-close:hover {
        background: #1b294d;
        color: #fff;
    }

    .accordion-guide-body {
        overflow: auto;
        padding: 18px 20px 22px;
    }

    .accordion-guide-flow {
        color: #d8deef;
        line-height: 1.55;
    }

    .accordion-guide-flow > p {
        margin: 0 0 10px;
    }

    .accordion-guide-heading {
        margin: 18px 0 8px;
        color: #f0f3ff;
        font-size: 1rem;
    }

    .accordion-guide-muted,
    .accordion-guide-error {
        margin: 0;
        color: #aeb8d4;
    }

    .accordion-guide-error {
        color: #ff9aa2;
    }

    .accordion-guide-example {
        margin: 14px 0 16px;
        padding-top: 14px;
        border-top: 1px solid #26314d;
    }

    .accordion-guide-example-header {
        margin-bottom: 10px;
    }

    .accordion-guide-example-header h3 {
        margin: 0 0 4px;
        font-size: 0.98rem;
        color: #f0f3ff;
    }

    .accordion-guide-example-header p {
        margin: 0;
        color: #aeb8d4;
        font-size: 0.88rem;
        line-height: 1.45;
    }

    .accordion-guide-context {
        margin: 8px 0;
        padding: 8px 10px;
        border: 1px dashed #2c3a5c;
        border-left: 3px solid #3a4a73;
        border-radius: 6px;
        background: #0d1428;
        opacity: 0.85;
    }

    .accordion-guide-context-label {
        margin-bottom: 6px;
        color: #9aa6c8;
        font-size: 0.74rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }

    @media (max-width: 720px) {
        .accordion-guide-backdrop {
            align-items: stretch;
            padding: 12px;
        }

        .accordion-guide-modal {
            width: 100%;
            max-height: calc(100vh - 24px);
        }

        .accordion-guide-header,
        .accordion-guide-body {
            padding-left: 14px;
            padding-right: 14px;
        }
    }
</style>
