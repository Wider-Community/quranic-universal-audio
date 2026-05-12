<!--
    Reviewer banner. Surfaces when the current user is the assignee of an
    under_review row. Two states:

      - !marked_ready → "You're reviewing X. [Mark ready] [Unclaim]"
      - marked_ready  → "Awaiting publish. [Continue editing] [Unclaim]"

    Anonymous, non-assignee, or non-under_review states render nothing.

    "Unclaim" is the user-facing label; the underlying API event remains
    `reciter.released` for historical continuity with the state machine.
-->
<script lang="ts">
    import { markReady, release, unmarkReady } from '../api/claims-client';
    import type { ReciterTask } from '../api/reciter-task';
    import { currentUser } from '../stores/current-user';

    export let task: ReciterTask | null;
    export let onChanged: (() => void) | null = null;

    let busy: '' | 'mark' | 'unmark' | 'release' = '';

    $: row = task?.row ?? null;
    $: isAssignee = (
        row !== null
        && row.state === 'under_review'
        && $currentUser?.hf_user_id !== null
        && row.assignee_hf_id === $currentUser?.hf_user_id
    );
    $: visible = isAssignee;
    $: frozen = row !== null && row.marked_ready;

    async function _do(action: 'mark' | 'unmark' | 'release', slug: string) {
        if (busy) return;
        busy = action;
        try {
            if (action === 'mark') await markReady(slug);
            else if (action === 'unmark') await unmarkReady(slug);
            else await release(slug);
            onChanged?.();
        } catch {
            /* claims-client surfaced the toast */
        } finally {
            busy = '';
        }
    }
</script>

{#if visible && row}
    <div class="reviewer-banner" class:reviewer-banner--frozen={frozen}>
        {#if frozen}
            <span class="reviewer-banner__text">
                <strong>Awaiting publish.</strong> A maintainer will review and publish this reciter shortly.
            </span>
            <span class="reviewer-banner__actions">
                <button
                    type="button"
                    class="reviewer-banner__btn"
                    disabled={busy === 'unmark'}
                    on:click={() => _do('unmark', row.slug)}
                >
                    Continue editing
                </button>
                <button
                    type="button"
                    class="reviewer-banner__btn reviewer-banner__btn--danger"
                    disabled={busy === 'release'}
                    on:click={() => _do('release', row.slug)}
                >
                    Unclaim
                </button>
            </span>
        {:else}
            <span class="reviewer-banner__text">
                <strong>You're reviewing {row.name ?? row.slug}.</strong> When you're done, mark it ready for a maintainer to publish.
            </span>
            <span class="reviewer-banner__actions">
                <button
                    type="button"
                    class="reviewer-banner__btn"
                    disabled={busy === 'mark'}
                    on:click={() => _do('mark', row.slug)}
                >
                    Mark ready
                </button>
                <button
                    type="button"
                    class="reviewer-banner__btn reviewer-banner__btn--danger"
                    disabled={busy === 'release'}
                    on:click={() => _do('release', row.slug)}
                >
                    Unclaim
                </button>
            </span>
        {/if}
    </div>
{/if}

<style>
    .reviewer-banner {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        flex-wrap: wrap;
        margin: 0 0 10px;
        padding: 10px 14px;
        border-radius: 8px;
        /* In-review (warm): orange-tinted dark surface. */
        background: #3a2a10;
        border: 1px solid #8a5a00;
        color: #f5e6c2;
        font-size: 0.95rem;
        line-height: 1.4;
    }
    .reviewer-banner--frozen {
        /* Marked-ready (cool): blue-tinted dark surface. */
        background: #1a2a4e;
        border-color: #4361ee;
        color: #cfd9ff;
    }
    .reviewer-banner strong {
        color: #fff;
    }
    .reviewer-banner__actions {
        display: flex;
        gap: 8px;
    }
    .reviewer-banner__btn {
        border: 0;
        padding: 6px 12px;
        border-radius: 6px;
        font-weight: 600;
        cursor: pointer;
        background: #4361ee;
        color: #fff;
        font-size: 0.9rem;
        transition: background 0.2s;
    }
    .reviewer-banner__btn:hover:not(:disabled) {
        background: #3a56d4;
    }
    .reviewer-banner__btn:disabled {
        opacity: 0.5;
        cursor: progress;
    }
    .reviewer-banner__btn--danger {
        background: transparent;
        color: #ff9a9a;
        border: 1px solid #b71c1c;
    }
    .reviewer-banner__btn--danger:hover:not(:disabled) {
        background: rgba(183, 28, 28, 0.25);
        color: #ffcccc;
    }
</style>
