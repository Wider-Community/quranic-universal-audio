<script lang="ts">
    /**
     * Vertical activity rail rendered on the right column of the
     * Dashboard list view. Polls every 30 seconds while the tab is
     * visible (Page Visibility API via visible-poll); discards
     * in-flight responses that resolve after the tab hides.
     *
     * Capability-gated affordances (default owner-only, but owner-toggleable
     * via the Permissions tab):
     * - Actor login (``@alice · 2h ago``) — ``identity.see_actor``.
     * - Trash icon to permanently delete a card from the public feed
     *   (writes a tombstone; reason ≥10 chars required) — ``activity.delete``.
     */
    import { onDestroy, onMount } from 'svelte';

    import {
        fetchPublicActivity,
        type PublicActivityCard,
        type PublicEventKind,
    } from '../../../lib/api/public-activity';
    import { deletePublicActivity } from '../../../lib/api/public-activity-admin';
    import { can } from '../../../lib/stores/capabilities';
    import { titleCaseSlug } from '../../../lib/utils/delivery-label';
    import { relativeTime } from '../../../lib/utils/relative-time';
    import { visiblePoll } from '../../../lib/utils/visible-poll';
    import AdminDashboardButton from './admin/AdminDashboardButton.svelte';

    // Capability-gated affordances (both default owner-only, so this matches
    // the prior `$isOwner` behavior — but now reflects an owner's toggle).
    const canDelete = can('activity.delete');
    const canSeeActor = can('identity.see_actor');

    let cards: PublicActivityCard[] = [];
    let loading = true;
    let error: string | null = null;
    let teardown: (() => void) | null = null;

    onMount(() => {
        teardown = visiblePoll<{ cards: PublicActivityCard[] }>({
            intervalMs: 30_000,
            fetcher: (signal) => fetchPublicActivity({ limit: 50, signal }),
            onResult: (page) => {
                cards = page.cards;
                loading = false;
                error = null;
            },
            onError: (e) => {
                loading = false;
                error = (e as Error).message ?? 'Failed to load activity';
            },
        });
    });

    onDestroy(() => teardown?.());

    function dotClass(kind: PublicActivityCard['kind']): string {
        return `marker marker-${kind.replace(/_/g, '-')}`;
    }

    const ACTION: Record<PublicEventKind, string> = {
        added: 'added to catalog',
        requested: 'has been requested',
        available_review: 'is now available for review',
        under_review: 'is now under review',
        published: 'is now published',
    };

    function formatLine(card: PublicActivityCard): string {
        if (card.riwayah && card.style) {
            return `${card.name} (${titleCaseSlug(card.riwayah)}) (${titleCaseSlug(card.style)}) ${ACTION[card.kind]}`;
        }
        return card.text;
    }

    async function onDelete(card: PublicActivityCard): Promise<void> {
        if (!card.audit_id) return;
        const reason = window.prompt(
            'Delete this card from Recent Activity for everyone?\n\n' +
                'Reason (≥10 characters; recorded in the audit log):',
            '',
        );
        if (reason === null) return; // cancelled
        const trimmed = reason.trim();
        if (trimmed.length < 10) {
            window.alert('Reason must be at least 10 characters.');
            return;
        }
        const idx = cards.findIndex((c) => c.audit_id === card.audit_id);
        const removed = cards[idx];
        if (idx === -1 || removed === undefined) return;
        cards = [...cards.slice(0, idx), ...cards.slice(idx + 1)];
        try {
            await deletePublicActivity(card.audit_id, trimmed);
        } catch (e) {
            cards = [...cards.slice(0, idx), removed, ...cards.slice(idx)];
            error = (e as Error).message ?? 'Failed to delete';
        }
    }
</script>

<div class="rail-wrap">
    <AdminDashboardButton />

    <aside class="activity" aria-label="Recent activity">
        <header>
            <h2>Recent activity</h2>
            <span class="sub">Last {cards.length} events</span>
        </header>

        {#if loading}
            <div class="state">Loading…</div>
        {:else if error}
            <div class="state error">{error}</div>
        {:else if cards.length === 0}
            <div class="state">No activity yet.</div>
        {:else}
            <ol class="list">
                {#each cards as card (card.audit_id ?? card.ts + card.kind + card.name)}
                    <li class="item" class:has-delete={$canDelete && card.audit_id}>
                        <span class={dotClass(card.kind)} aria-hidden="true"></span>
                        <div class="body">
                            <p class="text">{formatLine(card)}</p>
                            <time class="time" datetime={card.ts}>
                                {#if $canSeeActor && card.actor_login}
                                    <span class="actor">@{card.actor_login}</span>
                                    <span class="time-sep">·</span>
                                {/if}
                                {relativeTime(card.ts)}
                            </time>
                        </div>
                        {#if $canDelete && card.audit_id}
                            <button
                                class="delete"
                                type="button"
                                aria-label="Delete from public feed"
                                title="Delete permanently from the public feed"
                                on:click={() => onDelete(card)}
                            >
                                🗑
                            </button>
                        {/if}
                    </li>
                {/each}
            </ol>
        {/if}
    </aside>
</div>

<style>
    .rail-wrap {
        position: sticky;
        top: 0;
        align-self: start;
        max-height: 100vh;
        overflow-y: auto;
    }
    .activity {
        padding: var(--s-5) var(--s-5);
        border-left: 1px solid var(--border-quiet);
    }
    header {
        display: flex;
        align-items: baseline;
        gap: var(--s-2);
        margin-bottom: var(--s-4);
    }
    header h2 {
        font-size: var(--fs-h3);
        color: var(--text-primary);
        font-weight: 500;
        margin: 0;
    }
    .sub {
        font-size: var(--fs-meta);
        color: var(--text-muted);
    }
    .state {
        padding: var(--s-8) 0;
        text-align: center;
        color: var(--text-muted);
        font-size: var(--fs-meta);
    }
    .state.error { color: var(--state-error-fg); }

    .list {
        list-style: none;
        padding: 0;
        margin: 0;
        display: flex;
        flex-direction: column;
    }
    .item {
        display: grid;
        grid-template-columns: 14px 1fr;
        gap: var(--s-3);
        padding: var(--s-3) 0;
        border-bottom: 1px solid var(--border-quiet);
    }
    .item.has-delete {
        grid-template-columns: 14px 1fr 24px;
    }
    .item:last-child { border-bottom: none; }
    .marker {
        width: 8px; height: 8px;
        border-radius: 50%;
        margin-top: 6px;
        background: var(--border-strong);
    }
    .marker-added             { background: var(--state-available-request-fg); }
    .marker-requested         { background: var(--state-requested-fg); }
    .marker-available-review  { background: var(--state-available-fg); }
    .marker-under-review      { background: var(--state-under-review-fg); }
    .marker-published         { background: var(--state-published-fg); }

    .body { min-width: 0; }
    .text {
        margin: 0;
        font-size: var(--fs-body);
        color: var(--text-secondary);
        line-height: var(--lh-normal);
    }
    .time {
        display: block;
        margin-top: 2px;
        font-size: 10.5px;
        color: var(--text-faint);
        font-variant-numeric: tabular-nums;
    }
    .actor {
        color: var(--text-muted);
        font-weight: 500;
    }
    .time-sep {
        margin: 0 4px;
        color: var(--text-faint);
    }
    .delete {
        background: transparent;
        border: 0;
        color: var(--text-muted);
        font-size: 14px;
        line-height: 1;
        padding: 0 2px;
        cursor: pointer;
        opacity: 0;
        transition: opacity var(--t-fast), color var(--t-fast);
        align-self: start;
        margin-top: 4px;
    }
    .item:hover .delete { opacity: 1; }
    .delete:hover { color: var(--state-error-fg); }
</style>
