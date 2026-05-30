<script lang="ts">
    /**
     * First-edit onboarding gate + browsable guide index.
     *
     * Driven by the `guidesGate` store. Two ways in:
     *   - `gate`   — the `editGate` action opened it because the user tried to
     *                edit before reading every guide. Blocking framing.
     *   - `browse` — opened voluntarily from a "Guides" entry point.
     *
     * Lists every required guide with read/unread state. "Read" opens the real
     * `AccordionGuideModal` (via the `guideModal` store) stacked on top; opening
     * a guide records the view, so the checklist fills in live and — in gate
     * mode — the edit gate lifts the moment the last guide is read (SegmentsTab
     * recomputes editingMode on `currentUser.guides_read`).
     *
     * This is the edge-case fix: guides open directly here, independent of
     * whether the current reciter surfaces that category's accordion at all.
     */
    import { currentUser } from '../../../../lib/stores/current-user';
    import { closeGuidesGate, guidesGate } from '../../../../lib/stores/guides-gate';
    import { guideTitleFromBlocks, parseGuideSource } from '../../guides/parser';
    import {
        allGuidesRead,
        getAccordionGuide,
        isGuideRead,
        REQUIRED_GUIDE_KEYS,
    } from '../../guides/registry';
    import { openGuideModal } from '../../stores/guides';

    // Guide display titles derived from each guide's own H1 — computed once
    // (sources are static module imports). Falls back to the raw key.
    const GUIDE_TITLES: Record<string, string> = Object.fromEntries(
        REQUIRED_GUIDE_KEYS.map((key) => {
            const src = getAccordionGuide(key);
            return [key, src ? guideTitleFromBlocks(parseGuideSource(src), key) : key];
        }),
    );

    const open = $derived($guidesGate.open);
    const mode = $derived($guidesGate.mode);

    const items = $derived(
        REQUIRED_GUIDE_KEYS.map((key) => ({
            key,
            title: GUIDE_TITLES[key],
            read: isGuideRead($currentUser.guides_read, key),
        })),
    );
    const done = $derived(allGuidesRead($currentUser.guides_read));
    const readCount = $derived(items.filter((i) => i.read).length);

    function read(key: string, ev: MouseEvent): void {
        openGuideModal(key, ev.currentTarget as HTMLElement);
    }

    function onKeydown(ev: KeyboardEvent): void {
        if (!$guidesGate.open) return;
        if (ev.key === 'Escape') {
            ev.preventDefault();
            closeGuidesGate();
        }
    }

    function onBackdropClick(ev: MouseEvent): void {
        if (ev.target === ev.currentTarget) closeGuidesGate();
    }
</script>

<svelte:window onkeydown={onKeydown} />

{#if open}
    <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
    <div class="guides-gate-backdrop" role="presentation" onclick={onBackdropClick}>
        <div
            class="guides-gate-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="guides-gate-title"
            tabindex="-1"
        >
            <header class="guides-gate-header">
                <div>
                    <div class="guides-gate-kicker">
                        {mode === 'gate' ? 'Before you edit' : 'Review guides'}
                    </div>
                    <h2 id="guides-gate-title">
                        {mode === 'gate' ? 'Read the review guides first' : 'Review guides'}
                    </h2>
                </div>
                <button
                    type="button"
                    class="guides-gate-close"
                    aria-label="Close"
                    onclick={closeGuidesGate}
                >&times;</button>
            </header>

            <div class="guides-gate-body">
                <p class="guides-gate-intro">
                    {#if mode === 'gate'}
                        Editing unlocks once you've read all {REQUIRED_GUIDE_KEYS.length}
                        guides — a one-time step. They explain what each validation
                        flag means and what's expected by the end of a review.
                    {:else}
                        A quick reference for every validation category. Open any
                        guide to see real examples.
                    {/if}
                </p>

                <div class="guides-gate-progress" aria-hidden="true">
                    <div
                        class="guides-gate-progress-fill"
                        style:width="{(readCount / REQUIRED_GUIDE_KEYS.length) * 100}%"
                    ></div>
                </div>
                <div class="guides-gate-progress-label">
                    {readCount} / {REQUIRED_GUIDE_KEYS.length} read
                </div>

                <ul class="guides-gate-list">
                    {#each items as item (item.key)}
                        <li class="guides-gate-row" class:read={item.read}>
                            <span class="guides-gate-mark" aria-hidden="true">
                                {item.read ? '✓' : ''}
                            </span>
                            <span class="guides-gate-title">{item.title}</span>
                            <button
                                type="button"
                                class="guides-gate-open"
                                class:primary={!item.read}
                                onclick={(e) => read(item.key, e)}
                            >
                                {item.read ? 'Re-read' : 'Read'}
                            </button>
                        </li>
                    {/each}
                </ul>
            </div>

            <footer class="guides-gate-footer">
                {#if done}
                    <span class="guides-gate-done">
                        {mode === 'gate' ? "You're all set — editing is unlocked." : 'All guides read.'}
                    </span>
                {/if}
                <button
                    type="button"
                    class="guides-gate-dismiss"
                    class:primary={done}
                    onclick={closeGuidesGate}
                >
                    {done && mode === 'gate' ? 'Start editing' : 'Close'}
                </button>
            </footer>
        </div>
    </div>
{/if}

<style>
    .guides-gate-backdrop {
        position: fixed;
        inset: 0;
        /* Below the AccordionGuideModal (z-index 1000) so an opened guide
           stacks on top of this checklist. */
        z-index: 950;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 24px;
        background: rgba(4, 8, 18, 0.62);
        backdrop-filter: blur(2px);
    }

    .guides-gate-modal {
        width: min(560px, 100%);
        max-height: min(84vh, 720px);
        display: flex;
        flex-direction: column;
        background: #131a2c;
        border: 1px solid #28344f;
        border-radius: 12px;
        box-shadow: 0 18px 48px rgba(0, 0, 0, 0.5);
        color: #dfe6f5;
        overflow: hidden;
    }

    .guides-gate-header {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 12px;
        padding: 16px 18px;
        border-bottom: 1px solid #232f49;
    }

    .guides-gate-kicker {
        font-size: 0.7rem;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--accent);
        margin-bottom: 2px;
    }

    .guides-gate-header h2 {
        margin: 0;
        font-size: 1.05rem;
        color: #f2f5fc;
    }

    .guides-gate-close {
        flex: 0 0 auto;
        width: 30px;
        height: 30px;
        border: none;
        border-radius: 8px;
        background: transparent;
        color: #97a2bd;
        font-size: 1.3rem;
        line-height: 1;
        cursor: pointer;
    }
    .guides-gate-close:hover { background: #1d2740; color: #fff; }

    .guides-gate-body {
        padding: 16px 18px;
        overflow-y: auto;
    }

    .guides-gate-intro {
        margin: 0 0 14px;
        font-size: 0.88rem;
        line-height: 1.5;
        color: #aeb9d4;
    }

    .guides-gate-progress {
        height: 6px;
        border-radius: 999px;
        background: #1c2740;
        overflow: hidden;
    }
    .guides-gate-progress-fill {
        height: 100%;
        background: var(--accent);
        transition: width 0.25s ease;
    }
    .guides-gate-progress-label {
        margin: 6px 0 14px;
        font-size: 0.74rem;
        color: #8b97b4;
    }

    .guides-gate-list {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: 6px;
    }

    .guides-gate-row {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 8px 10px;
        border: 1px solid #243049;
        border-radius: 8px;
        background: #101829;
    }
    .guides-gate-row.read {
        border-color: #21364a;
        background: #0e1726;
    }

    .guides-gate-mark {
        flex: 0 0 18px;
        width: 18px;
        text-align: center;
        color: var(--accent);
        font-weight: 700;
        font-size: 0.85rem;
    }

    .guides-gate-title {
        flex: 1;
        min-width: 0;
        font-size: 0.9rem;
    }
    .guides-gate-row.read .guides-gate-title { color: #9aa6c2; }

    .guides-gate-open {
        flex: 0 0 auto;
        padding: 5px 12px;
        border: 1px solid #36456a;
        border-radius: 6px;
        background: #16203a;
        color: #cdd6ee;
        font-size: 0.8rem;
        cursor: pointer;
    }
    .guides-gate-open:hover { background: #1d2b4c; }
    .guides-gate-open.primary {
        border-color: var(--accent);
        color: var(--accent);
        box-shadow: 0 0 0 1px var(--accent-tint);
    }

    .guides-gate-footer {
        display: flex;
        align-items: center;
        justify-content: flex-end;
        gap: 12px;
        padding: 14px 18px;
        border-top: 1px solid #232f49;
    }

    .guides-gate-done {
        margin-right: auto;
        font-size: 0.82rem;
        color: var(--accent);
    }

    .guides-gate-dismiss {
        padding: 7px 16px;
        border: 1px solid #36456a;
        border-radius: 7px;
        background: #16203a;
        color: #cdd6ee;
        font-size: 0.85rem;
        cursor: pointer;
    }
    .guides-gate-dismiss.primary {
        border-color: var(--accent);
        background: var(--accent);
        color: var(--accent-fg);
        font-weight: 600;
    }
</style>
