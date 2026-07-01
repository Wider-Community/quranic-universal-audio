<script lang="ts">
    /**
     * GuideFlagButton — dev-only authoring affordance on each History card.
     *
     * Lets the maintainer flag an edit (with a note + target validation
     * category) so it can be turned into an accordion-guide example by the
     * offline builder. Self-gates on `$currentUser.dev_mode`, so it renders
     * nothing for real users and is absent on the deployed Space. The backing
     * endpoint 404s when dev mode is off. See
     * `docs/reference/accordion-guides.md`.
     *
     * The popover is portalled to <body> with fixed positioning anchored to the
     * button, so the scrolling/overflow-clipped History list can't chop it off.
     *
     * Svelte 5 runes (new component). Embedded in the legacy HistoryBatch /
     * EditChainRow parents — that's fine; the file itself is fully runes.
     */

    import { flagGuideExample, type GuideFlagPayload } from '../../../../lib/api/guide-flags';
    import { currentUser } from '../../../../lib/stores/current-user';
    import type { EditOp } from '../../../../lib/types/view-models';
    import { ALL_CATEGORIES, IssueRegistry } from '../../domain/registry';
    import { selectedReciter } from '../../stores/chapter';

    interface Props {
        chapter: number | null;
        batchId: string | null;
        group: EditOp[];
    }
    const { chapter, batchId, group }: Props = $props();

    let open = $state(false);
    let saving = $state(false);
    let saved = $state(false);
    let error = $state<string | null>(null);

    let category = $state('');
    let note = $state('');
    let exampleId = $state('');

    let btnEl = $state<HTMLButtonElement>();
    let popEl = $state<HTMLDivElement>();
    let popStyle = $state('');

    const POP_WIDTH = 300;

    const primary = $derived(group[0]);

    const defaultCategory = $derived(
        primary?.op_context_category && primary.op_context_category in IssueRegistry
            ? primary.op_context_category
            : 'low_confidence',
    );

    const render = $derived(primary?.op_type === 'split_segment' ? 'edit_chain' : 'history_op');

    const matchedRef = $derived(
        (primary?.targets_before?.[0]?.['matched_ref'] as string | undefined)
        ?? (primary?.targets_after?.[0]?.['matched_ref'] as string | undefined)
        ?? null,
    );

    /** Move the node to <body> so no overflow ancestor can clip it. */
    function portal(node: HTMLElement) {
        document.body.appendChild(node);
        return { destroy() { node.parentNode?.removeChild(node); } };
    }

    /** Anchor the fixed popover under the button, opening leftward, clamped
     *  to the viewport (flips above when there's no room below). */
    function place(): void {
        if (!btnEl) return;
        const r = btnEl.getBoundingClientRect();
        const h = popEl?.offsetHeight ?? 300;
        let left = Math.min(r.right - POP_WIDTH, window.innerWidth - POP_WIDTH - 8);
        left = Math.max(8, left);
        let top = r.bottom + 6;
        if (top + h > window.innerHeight - 8) top = Math.max(8, r.top - h - 6);
        popStyle = `top:${top}px; left:${left}px; width:${POP_WIDTH}px;`;
    }

    function toggle(): void {
        open = !open;
        if (open) {
            category = defaultCategory;
            error = null;
            saved = false;
        }
    }

    function onDocPointer(e: PointerEvent): void {
        const t = e.target as Node;
        if (btnEl?.contains(t) || popEl?.contains(t)) return;
        open = false;
    }
    function onKey(e: KeyboardEvent): void {
        if (e.key === 'Escape') open = false;
    }

    $effect(() => {
        if (!open) return;
        place();
        const reposition = () => place();
        window.addEventListener('scroll', reposition, true);
        window.addEventListener('resize', reposition);
        document.addEventListener('pointerdown', onDocPointer, true);
        document.addEventListener('keydown', onKey);
        return () => {
            window.removeEventListener('scroll', reposition, true);
            window.removeEventListener('resize', reposition);
            document.removeEventListener('pointerdown', onDocPointer, true);
            document.removeEventListener('keydown', onKey);
        };
    });

    async function submit(): Promise<void> {
        if (!$selectedReciter || !batchId || !category) return;
        saving = true;
        error = null;
        const payload: GuideFlagPayload = {
            reciter: $selectedReciter,
            chapter,
            batch_id: batchId,
            op_ids: group.map((o) => o.op_id),
            op_type: primary?.op_type ?? null,
            matched_ref: matchedRef,
            category,
            render,
            note: note.trim() || undefined,
            example_id: exampleId.trim() || undefined,
        };
        try {
            await flagGuideExample(payload);
            saved = true;
            open = false;
            note = '';
            exampleId = '';
        } catch (e) {
            error = e instanceof Error ? e.message : 'flag failed';
        } finally {
            saving = false;
        }
    }
</script>

{#if $currentUser.dev_mode && batchId && $selectedReciter}
    <button
        bind:this={btnEl}
        type="button"
        class="guide-flag-btn"
        class:saved
        onclick={toggle}
        title="Flag this edit for an accordion-guide example"
    >{saved ? '🚩 flagged' : '🚩 guide'}</button>

    {#if open}
        <div bind:this={popEl} use:portal class="guide-flag-pop" style={popStyle}>
            <div class="guide-flag-meta">
                {render === 'edit_chain' ? 'chain' : 'op'} · {group.length} op{group.length > 1 ? 's' : ''}
                {#if matchedRef}· {matchedRef}{/if}
            </div>
            <label>
                <span>Guide category</span>
                <select bind:value={category}>
                    {#each ALL_CATEGORIES as cat}
                        <option value={cat}>{IssueRegistry[cat]?.displayTitle ?? cat}</option>
                    {/each}
                </select>
            </label>
            <label>
                <span>Note — teaching point</span>
                <textarea
                    bind:value={note}
                    rows="3"
                    placeholder="What should the reader learn from this edit?"
                ></textarea>
            </label>
            <label>
                <span>Example id (optional)</span>
                <input bind:value={exampleId} placeholder="e.g. low_conf_trim_timing" />
            </label>
            {#if error}<p class="guide-flag-err">{error}</p>{/if}
            <div class="guide-flag-actions">
                <button type="button" onclick={() => (open = false)} disabled={saving}>Cancel</button>
                <button type="button" class="primary" onclick={submit} disabled={saving || !category}>
                    {saving ? 'Saving…' : 'Flag'}
                </button>
            </div>
        </div>
    {/if}
{/if}

<style>
    .guide-flag-btn {
        border: 1px dashed var(--border-strong);
        border-radius: 5px;
        background: var(--panel-2);
        color: var(--text-secondary);
        font-size: 0.72rem;
        padding: 1px 7px;
        cursor: pointer;
        line-height: 1.5;
    }

    .guide-flag-btn:hover {
        background: var(--elevated);
        color: var(--text-primary);
    }

    .guide-flag-btn.saved {
        border-style: solid;
        border-color: var(--ok-fg);
        color: var(--ok-fg);
    }

    /* Portalled to <body> — fixed so the scrolling History list can't clip it. */
    .guide-flag-pop {
        position: fixed;
        z-index: 2000;
        display: flex;
        flex-direction: column;
        gap: 8px;
        padding: 12px;
        border: 1px solid var(--border-default);
        border-radius: 8px;
        background: var(--popover-bg);
        box-shadow: var(--shadow-pop);
    }

    .guide-flag-meta {
        color: var(--text-muted);
        font-size: 0.72rem;
    }

    .guide-flag-pop label {
        display: flex;
        flex-direction: column;
        gap: 3px;
        color: var(--text-secondary);
        font-size: 0.74rem;
    }

    .guide-flag-pop select,
    .guide-flag-pop textarea,
    .guide-flag-pop input {
        width: 100%;
        box-sizing: border-box;
        border: 1px solid var(--border-default);
        border-radius: 5px;
        background: var(--input-bg);
        color: var(--text-primary);
        font-size: 0.78rem;
        padding: 5px 7px;
    }

    .guide-flag-pop textarea {
        resize: vertical;
        font-family: inherit;
    }

    .guide-flag-err {
        margin: 0;
        color: var(--bad-fg);
        font-size: 0.72rem;
    }

    .guide-flag-actions {
        display: flex;
        justify-content: flex-end;
        gap: 6px;
    }

    .guide-flag-actions button {
        border: 1px solid var(--border-default);
        border-radius: 5px;
        background: var(--panel);
        color: var(--text-secondary);
        font-size: 0.74rem;
        padding: 3px 10px;
        cursor: pointer;
    }

    .guide-flag-actions button.primary {
        background: var(--info-solid);
        border-color: var(--info-solid-hover);
        color: var(--ink-on-color);
    }

    .guide-flag-actions button:disabled {
        opacity: 0.5;
        cursor: default;
    }
</style>
