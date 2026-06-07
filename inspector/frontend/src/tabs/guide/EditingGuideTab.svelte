<script lang="ts">
    /**
     * EditingGuideTab — Renders all review guides as a list of non-collapsible step cards.
     * Clicking any card launches a premium modal with a sticky left sidebar steps navigation
     * and a scrollable content area on the right with example playback capabilities.
     */
    import { onDestroy, onMount } from 'svelte';
    import { get } from 'svelte/store';

    import { recordGuideViewed } from '../../lib/api/guide-views';
    import AudioElement from '../../lib/components/AudioElement.svelte';
    import { currentUser, loadCurrentUser, markGuideReadLocally } from '../../lib/stores/current-user';
    import { loadQuranRefs } from '../../lib/refs/quran-refs';
    import { getAccordionGuide, guideViewKey, isGuideRead, REQUIRED_GUIDE_KEYS } from '../segments/guides/registry';
    import { guideTitleFromBlocks, parseGuideSource } from '../segments/guides/parser';
    import { createPreviewPlaybackContext } from '../segments/utils/playback/preview';

    import type { HistoryBatch } from '../../lib/types/view-models';
    import { activeTab } from '../../lib/utils/active-tab';
    import { TAB_NAMES } from '../../lib/utils/constants';
    import OverviewContent from '../../lib/components/info/OverviewContent.svelte';
    import EditingGuideContent from '../segments/guides/editing/EditingGuideContent.svelte';
    import { getGuideExample } from '../segments/guides/examples';
    import type { GuideExample } from '../segments/guides/types';
    import {
        buildEditChains,
        type HistorySnapshot,
        snapToSeg,
    } from '../segments/stores/history';
    import { indexHistoryPeaksRecords } from '../segments/utils/waveform/utils';
    import EditChainRow from '../segments/components/history/EditChainRow.svelte';
    import HistoryOp from '../segments/components/history/HistoryOp.svelte';
    import SegmentRow from '../segments/components/list/SegmentRow.svelte';

    const GUIDE_COMPONENTS: Record<string, any> = {
        'editing-guide': EditingGuideContent,
        overview: OverviewContent,
    };

    // Pre-compute guide titles from their H1 block, fallback to key
    const GUIDE_TITLES: Record<string, string> = Object.fromEntries(
        REQUIRED_GUIDE_KEYS.map((key) => {
            const src = getAccordionGuide(key);
            return [key, src ? guideTitleFromBlocks(parseGuideSource(src), key) : key];
        }),
    );

    const previewCtx = createPreviewPlaybackContext({ persistPeaks: false });
    let audio: AudioElement;

    $: if (audio) {
        previewCtx.attachAudioEl(audio.element());
    }

    // Modal state
    let activeModalKey: string | null = null;
    let modalContentContainer: HTMLElement;

    // Track guides read in this session (does not persist across page refreshes)
    let readKeys = new Set<string>();

    $: items = REQUIRED_GUIDE_KEYS.map((key) => ({
        key,
        title: GUIDE_TITLES[key] || key,
        read: readKeys.has(guideViewKey(key)),
    }));

    $: readCount = items.filter((i) => i.read).length;

    // Cache parsed blocks for each guide key
    const parsedBlocksCache: Record<string, any[]> = {};
    function getBlocks(key: string) {
        if (!parsedBlocksCache[key]) {
            const src = getAccordionGuide(key);
            parsedBlocksCache[key] = src ? parseGuideSource(src) : [];
        }
        return parsedBlocksCache[key];
    }

    // Pause preview audio if the modal is closed or the tab is left/inactive.
    $: if (!activeModalKey || $activeTab !== TAB_NAMES.GUIDE) {
        audio?.pause();
    }

    function openModal(key: string) {
        activeModalKey = key;
    }

    function closeModal() {
        activeModalKey = null;
    }

    function selectStep(key: string) {
        activeModalKey = key;
        // Scroll the content area back to top when step changes
        if (modalContentContainer) {
            modalContentContainer.scrollTop = 0;
        }
    }

    let _recordedFor: string | null = null;
    $: if (activeModalKey && activeModalKey !== _recordedFor) {
        _recordedFor = activeModalKey;
        const vk = guideViewKey(activeModalKey);
        if (!readKeys.has(vk)) {
            readKeys = new Set([...readKeys, vk]);
        }
        void recordCategoryRead(activeModalKey);
    }

    async function recordCategoryRead(cat: string): Promise<void> {
        const u = get(currentUser);
        if (u.hf_user_id == null) return; // anonymous: nothing to persist
        if (isGuideRead(u.guides_read, cat)) return; // already read

        markGuideReadLocally(guideViewKey(cat));
        const ok = await recordGuideViewed(cat);
        if (!ok) void loadCurrentUser(); // fail -> fallback
    }

    // Warm up example waveforms when active step changes
    $: if (activeModalKey) {
        const blocks = getBlocks(activeModalKey);
        for (const block of blocks) {
            if (block.type !== 'example') continue;
            const ex = getGuideExample(block.id);
            if (ex) {
                indexHistoryPeaksRecords(ex.peaks);
                const clipUrl = ex.peaks?.[0]?.url;
                if (clipUrl && ex.clip_base_ms != null) {
                    previewCtx.setClipBase(clipUrl, ex.clip_base_ms);
                }
            }
        }
    }

    $: currentIndex = activeModalKey ? REQUIRED_GUIDE_KEYS.indexOf(activeModalKey) : -1;
    $: prevStepKey = currentIndex > 0 ? REQUIRED_GUIDE_KEYS[currentIndex - 1] : null;
    $: nextStepKey = currentIndex >= 0 && currentIndex < REQUIRED_GUIDE_KEYS.length - 1 ? REQUIRED_GUIDE_KEYS[currentIndex + 1] : null;

    function handleKeydown(e: KeyboardEvent) {
        if (activeModalKey) {
            if (e.key === 'Escape') {
                closeModal();
            } else if (e.key === 'ArrowLeft' && prevStepKey) {
                if (document.activeElement?.tagName !== 'INPUT' && document.activeElement?.tagName !== 'TEXTAREA') {
                    selectStep(prevStepKey);
                }
            } else if (e.key === 'ArrowRight' && nextStepKey) {
                if (document.activeElement?.tagName !== 'INPUT' && document.activeElement?.tagName !== 'TEXTAREA') {
                    selectStep(nextStepKey);
                }
            }
        }
    }

    function handleBackdropClick(e: MouseEvent) {
        if (e.target === e.currentTarget) {
            closeModal();
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
        void loadQuranRefs();
    });

    onDestroy(() => {
        previewCtx.dispose();
    });
</script>

<svelte:window on:keydown={handleKeydown} />

<div class="eg-tab-root">
    <div class="eg-tab-progress-section">
        <div class="eg-tab-progress-label">
            <h3>Guides review progress</h3>
            <span>{readCount} / {REQUIRED_GUIDE_KEYS.length} read</span>
        </div>
        <div class="eg-tab-progress-bar" aria-hidden="true">
            <div
                class="eg-tab-progress-bar-fill"
                style:width="{(readCount / REQUIRED_GUIDE_KEYS.length) * 100}%"
            ></div>
        </div>
    </div>

    <div class="eg-tab-list">
        {#each items as item, index (item.key)}
            <button
                type="button"
                class="eg-row-btn"
                class:read={item.read}
                on:click={() => openModal(item.key)}
            >
                <div class="eg-row-left">
                    <span class="eg-row-step">{(index + 1).toString().padStart(2, '0')}</span>
                    <span class="eg-row-mark" class:unread={!item.read} aria-hidden="true">
                        {item.read ? '✓' : '●'}
                    </span>
                    <span class="eg-row-title">{item.title}</span>
                </div>
                <div class="eg-row-right">
                    <span class="eg-row-action">{item.read ? 'Re-read' : 'Read guide'}</span>
                    <svg
                        class="eg-row-arrow"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                    >
                        <line x1="5" y1="12" x2="19" y2="12"></line>
                        <polyline points="12 5 19 12 12 19"></polyline>
                    </svg>
                </div>
            </button>
        {/each}

        <!-- Optional keyboard-shortcut reference -->
        <details class="guides-gate-shortcuts">
            <summary>Keyboard shortcuts <span class="guides-gate-optional">optional</span></summary>
            <div class="guides-gate-shortcuts-body">
                <div class="gs-col">
                    <h4>Playback</h4>
                    <dl>
                        <dt>Space</dt><dd>Play / pause</dd>
                        <dt>&larr; / &rarr;</dt><dd>Seek &plusmn;3 s</dd>
                        <dt>&uarr; / &darr;</dt><dd>Prev / next segment</dd>
                        <dt>, / .</dt><dd>Slower / faster playback</dd>
                        <dt>J</dt><dd>Scroll current segment into view</dd>
                    </dl>
                </div>
                <div class="gs-col">
                    <h4>Editing</h4>
                    <dl>
                        <dt>E</dt><dd>Edit reference of current segment</dd>
                        <dt>Enter</dt><dd>Confirm trim / split</dd>
                        <dt>Escape</dt><dd>Cancel trim / split</dd>
                        <dt>S</dt><dd>Save changes</dd>
                    </dl>
                </div>
            </div>
        </details>
    </div>

    <AudioElement bind:this={audio} />
</div>

{#if activeModalKey}
    {@const activeBlocks = getBlocks(activeModalKey)}
    {@const activeSource = getAccordionGuide(activeModalKey)}
    <div class="eg-modal-backdrop" role="presentation" on:click={handleBackdropClick}>
        <div
            class="eg-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="eg-modal-title"
            tabindex="-1"
        >
            <header class="eg-modal-header">
                <div class="eg-modal-header-left">
                    <h2 id="eg-modal-title">{GUIDE_TITLES[activeModalKey] || activeModalKey}</h2>
                </div>
                <div class="eg-modal-header-right">
                    <button
                        type="button"
                        class="eg-modal-close"
                        aria-label="Close"
                        on:click={closeModal}
                    >&times;</button>
                </div>
            </header>

            <div class="eg-modal-body">
                <!-- Scrollable Content Panel -->
                <main class="eg-modal-content" bind:this={modalContentContainer}>
                    <div class="accordion-guide-flow">
                        {#if !activeSource}
                            <p class="accordion-guide-muted">No guide yet.</p>
                        {:else}
                            {#each activeBlocks as block, i (`${block.type}:${i}`)}
                                {#if block.type === 'heading' && block.level === 1}
                                    <!-- H1 is used as modal title, do not duplicate in content -->
                                {:else if block.type === 'heading'}
                                    <h3 class="accordion-guide-heading">{block.text}</h3>
                                {:else if block.type === 'paragraph'}
                                    <p>{block.text}</p>
                                {:else if block.type === 'callout'}
                                    <div class="accordion-guide-callout" role="note">
                                        <span class="accordion-guide-callout-icon" aria-hidden="true">🎯</span>
                                        <div class="accordion-guide-callout-body">
                                            <div class="accordion-guide-callout-label">Goal</div>
                                            <p class="accordion-guide-callout-text">{block.text}</p>
                                        </div>
                                    </div>
                                {:else if block.type === 'component'}
                                    {#if GUIDE_COMPONENTS[block.name]}
                                        <svelte:component this={GUIDE_COMPONENTS[block.name]} />
                                    {:else}
                                        <p class="accordion-guide-error">Unknown guide component: {block.name}</p>
                                    {/if}
                                {:else}
                                    {#if block.type === 'missing'}
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
                                {/if}
                            {/each}
                        {/if}
                    </div>
                </main>
            </div>

            <footer class="eg-modal-footer">
                <div class="eg-modal-footer-nav">
                    {#if prevStepKey}
                        <button type="button" class="btn-prev" on:click={() => selectStep(prevStepKey)}>
                            &larr; Previous Step
                        </button>
                    {:else}
                        <div class="footer-spacer"></div>
                    {/if}
                    {#if nextStepKey}
                        <button type="button" class="btn-next-step" on:click={() => selectStep(nextStepKey)}>
                            Next Step &rarr;
                        </button>
                    {:else}
                        <button type="button" class="btn-finish" on:click={closeModal}>
                            Finish Review ✓
                        </button>
                    {/if}
                </div>
            </footer>
        </div>
    </div>
{/if}

<style>
    .eg-tab-root {
        max-width: 900px;
        margin: 0 auto;
        padding: 32px var(--gutter, 24px) 80px;
        box-sizing: border-box;
        display: flex;
        flex-direction: column;
        gap: 24px;
    }

    /* ---- Progress Section ---- */
    .eg-tab-progress-section {
        background: #101a33;
        border: 1px solid #243049;
        border-radius: 8px;
        padding: 16px 20px;
        box-sizing: border-box;
    }

    .eg-tab-progress-label {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        margin-bottom: 8px;
    }

    .eg-tab-progress-label h3 {
        margin: 0;
        font-size: 0.85rem;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: #8b97b4;
    }

    .eg-tab-progress-label span {
        font-size: 0.82rem;
        color: var(--accent, #4cc9f0);
        font-weight: 600;
    }

    .eg-tab-progress-bar {
        height: 6px;
        background: #1c2740;
        border-radius: 99px;
        overflow: hidden;
    }

    .eg-tab-progress-bar-fill {
        height: 100%;
        background: var(--accent, #4cc9f0);
        transition: width 0.25s ease;
    }

    /* ---- Compact List Rows ---- */
    .eg-tab-list {
        display: flex;
        flex-direction: column;
        gap: 8px;
        width: 100%;
    }

    .eg-row-btn {
        display: flex;
        align-items: center;
        justify-content: space-between;
        background: #101a33;
        border: 1px solid #243049;
        border-radius: 8px;
        padding: 12px 16px;
        color: #dfe6f5;
        cursor: pointer;
        width: 100%;
        text-align: left;
        box-sizing: border-box;
        transition: background 0.15s, border-color 0.15s, transform 0.15s;
    }

    .eg-row-btn:hover {
        background: #132040;
        border-color: var(--accent, #4cc9f0);
    }

    .eg-row-btn.read {
        background: #0b1122;
        border-color: #1a253d;
    }

    .eg-row-btn.read:hover {
        background: #101a33;
        border-color: #2b3b5c;
    }

    .eg-row-left {
        display: flex;
        align-items: center;
        gap: 12px;
        min-width: 0;
        flex: 1;
    }

    .eg-row-step {
        font-family: var(--font-mono, ui-monospace, monospace);
        font-size: 0.8rem;
        font-weight: 600;
        color: #4b556e;
        width: 20px;
    }

    .eg-row-btn.read .eg-row-step {
        color: #313a52;
    }

    .eg-row-mark {
        font-size: 0.85rem;
        color: var(--accent, #4cc9f0);
        font-weight: bold;
        width: 16px;
        text-align: center;
    }

    .eg-row-mark.unread {
        color: #ff9800;
        text-shadow: 0 0 4px rgba(255, 152, 0, 0.4);
        font-size: 0.7rem;
    }

    .eg-row-title {
        font-size: 0.95rem;
        font-weight: 500;
        color: #ffffff;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .eg-row-btn.read .eg-row-title {
        color: #9aa6c2;
    }

    .eg-row-right {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-shrink: 0;
    }

    .eg-row-action {
        font-size: 0.78rem;
        font-weight: 600;
        color: var(--accent, #4cc9f0);
    }

    .eg-row-btn.read .eg-row-action {
        color: #8b97b4;
    }

    .eg-row-arrow {
        width: 14px;
        height: 14px;
        color: var(--accent, #4cc9f0);
        transition: transform 0.15s;
    }

    .eg-row-btn:hover .eg-row-arrow {
        transform: translateX(3px);
    }

    .eg-row-btn.read .eg-row-arrow {
        color: #6b7796;
    }

    /* ---- Modal Styling ---- */
    .eg-modal-backdrop {
        position: fixed;
        inset: 0;
        z-index: 1000;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 24px;
        background: rgba(3, 6, 18, 0.72);
        backdrop-filter: blur(8px);
    }

    .eg-modal {
        width: min(1100px, calc(100vw - 32px));
        height: min(800px, calc(100vh - 32px));
        display: flex;
        flex-direction: column;
        border: 1px solid #243049;
        border-radius: 12px;
        background: #0a1020;
        box-shadow: 0 24px 80px rgba(0, 0, 0, 0.6);
        color: #e6e8f2;
        outline: none;
        overflow: hidden;
    }

    .eg-modal-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        padding: 16px 24px;
        border-bottom: 1px solid #1c2740;
        background: #0f172a;
    }

    .eg-modal-header-left {
        display: flex;
        flex-direction: column;
    }



    .eg-modal-header h2 {
        margin: 0;
        font-size: 1.15rem;
        font-weight: 600;
        color: #ffffff;
    }

    .eg-modal-header-right {
        display: flex;
        align-items: center;
        gap: 24px;
    }



    .eg-modal-close {
        width: 32px;
        height: 32px;
        border: 1px solid #243049;
        border-radius: 8px;
        background: #101a33;
        color: #d5daeb;
        cursor: pointer;
        font-size: 1.35rem;
        line-height: 1;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: background 0.15s, color 0.15s, border-color 0.15s;
    }

    .eg-modal-close:hover {
        background: #1b294d;
        color: #fff;
        border-color: #3b4d75;
    }

    .eg-modal-body {
        display: flex;
        flex-direction: column;
        flex: 1;
        min-height: 0;
        overflow: hidden;
    }

    /* ---- Content Area ---- */
    .eg-modal-content {
        flex: 1;
        overflow-y: auto;
        padding: 24px 32px 48px;
        background: #0a1020;
    }

    /* ---- Modal Footer ---- */
    .eg-modal-footer {
        padding: 16px 24px;
        border-top: 1px solid #1c2740;
        background: #0f172a;
    }

    .eg-modal-footer-nav {
        display: flex;
        justify-content: space-between;
        align-items: center;
    }

    .footer-spacer {
        width: 120px;
    }

    .btn-prev,
    .btn-next-step,
    .btn-finish {
        padding: 8px 18px;
        border-radius: 8px;
        font-size: 0.88rem;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.15s, border-color 0.15s, color 0.15s;
    }

    .btn-prev {
        background: #101a33;
        border: 1px solid #243049;
        color: #cdd6ee;
    }

    .btn-prev:hover {
        background: #162447;
        border-color: #3b4d75;
        color: #ffffff;
    }

    .btn-next-step {
        background: var(--accent, #4cc9f0);
        border: 1px solid transparent;
        color: #000;
    }

    .btn-next-step:hover {
        background: #73d5f4;
    }

    .btn-finish {
        background: #10b981;
        border: 1px solid transparent;
        color: #ffffff;
    }

    .btn-finish:hover {
        background: #059669;
    }

    /* ---- Guide Content Flow (copied from AccordionGuideModal) ---- */
    .accordion-guide-flow {
        color: #d8deef;
        line-height: 1.55;
    }

    .accordion-guide-flow > :global(p) {
        margin: 0 0 10px;
    }



    .accordion-guide-heading {
        margin: 22px 0 8px;
        color: #f0f3ff;
        font-size: 1.05rem;
        font-weight: 600;
    }

    .accordion-guide-callout {
        display: flex;
        gap: 12px;
        margin: 14px 0 16px;
        padding: 13px 15px;
        border: 1px solid rgba(52, 211, 153, 0.32);
        border-left: 3px solid #34d399;
        border-radius: 8px;
        background: linear-gradient(
            135deg,
            rgba(16, 185, 129, 0.12),
            rgba(16, 185, 129, 0.05)
        );
    }

    .accordion-guide-callout-icon {
        flex: none;
        font-size: 1.1rem;
        line-height: 1.4;
    }

    .accordion-guide-callout-body {
        min-width: 0;
    }

    .accordion-guide-callout-label {
        margin-bottom: 3px;
        color: #6ee7b7;
        font-size: 0.7rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.09em;
    }

    .accordion-guide-callout-text {
        margin: 0;
        color: #d9f5e8;
        font-size: 0.92rem;
        line-height: 1.5;
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

    /* Optional shortcuts reference — muted, clearly secondary to the guides. */
    .guides-gate-shortcuts {
        margin-top: 0;
        border: 1px solid #243049;
        border-radius: 8px;
        background: #101a33;
    }
    .guides-gate-shortcuts > summary {
        cursor: pointer;
        list-style: none;
        padding: 10px 12px;
        font-size: 0.85rem;
        color: #c2cce4;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .guides-gate-shortcuts > summary::-webkit-details-marker { display: none; }
    .guides-gate-shortcuts > summary::before {
        content: '▸';
        color: #6b7796;
        font-size: 0.8rem;
        transition: transform 0.15s ease;
    }
    .guides-gate-shortcuts[open] > summary::before { transform: rotate(90deg); }
    .guides-gate-optional {
        font-size: 0.68rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: #7f8bab;
        border: 1px solid #2c3a59;
        border-radius: 999px;
        padding: 1px 7px;
    }

    .guides-gate-shortcuts-body {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 12px 20px;
        padding: 4px 14px 14px;
    }
    .gs-col h4 {
        margin: 0 0 6px;
        font-size: 0.72rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: #8b97b4;
    }
    .gs-col dl {
        margin: 0;
        display: grid;
        grid-template-columns: auto 1fr;
        gap: 4px 10px;
        font-size: 0.82rem;
    }
    .gs-col dt {
        font-family: var(--font-mono, ui-monospace, monospace);
        color: var(--accent);
        white-space: nowrap;
    }
    .gs-col dd {
        margin: 0;
        color: #aeb9d4;
    }

    @media (max-width: 460px) {
        .guides-gate-shortcuts-body { grid-template-columns: 1fr; }
    }

    /* ---- Responsive Stepper Header for Mobile ---- */
    @media (max-width: 768px) {
        .eg-tab-root {
            padding: 16px 12px 60px;
            gap: 16px;
        }

        .eg-tab-progress-section {
            padding: 12px 14px;
        }

        .eg-modal-backdrop {
            padding: 8px;
        }

        .eg-modal {
            width: 100%;
            height: 100%;
            max-height: 100%;
            border-radius: 0;
            border: 0;
        }

        .eg-modal-body {
            flex-direction: column;
        }

        .eg-modal-content {
            padding: 16px 20px;
        }
        
        .eg-modal-header {
            padding: 12px 16px;
        }

        .eg-modal-header-right {
            gap: 12px;
        }
    }
</style>
