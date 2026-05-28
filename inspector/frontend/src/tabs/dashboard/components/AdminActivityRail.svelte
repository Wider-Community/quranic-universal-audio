<script lang="ts">
    /**
     * Admin/owner notification rail. Mounted above the public ActivityRail.
     *
     * - Visible only when `$isAdmin` (maintainer or owner).
     * - Each card shows event + reciter + relative time.
     * - Owner view additionally shows the actor login; maintainer view does not.
     * - `×` dismisses a card for the current user only (optimistic, persisted
     *   via /api/admin/activity/dismiss).
     * - A small arrow toggles a collapsed archive section listing dismissed
     *   cards (with an undismiss affordance).
     */
    import { onDestroy } from 'svelte';

    import {
        type AdminActivityCard,
        type AdminEventKind,
        dismissAdminActivity,
        fetchAdminActivity,
        undismissAdminActivity,
    } from '../../../lib/api/admin-activity';
    import { isAdmin, isOwner } from '../../../lib/stores/current-user';
    import { titleCaseSlug } from '../../../lib/utils/delivery-label';
    import { relativeTime } from '../../../lib/utils/relative-time';
    import { visiblePoll } from '../../../lib/utils/visible-poll';

    let live: AdminActivityCard[] = [];
    let archived: AdminActivityCard[] = [];
    let archivedExpanded = false;
    let archivedCount = 0;
    let loading = true;
    let error: string | null = null;
    let teardown: (() => void) | null = null;

    // Start the poll the first time the caller becomes admin. `onMount`
    // would be wrong here because this component is instantiated by its
    // parent before `loadCurrentUser()` resolves — the lifecycle hook would
    // fire when `$isAdmin` is still false. Reactive statement fires whenever
    // `$isAdmin` flips, and the `teardown === null` guard makes it idempotent
    // so the role-switcher flipping admin → contributor → admin doesn't
    // spawn duplicate pollers.
    $: if ($isAdmin && teardown === null) {
        teardown = visiblePoll<typeof live>({
            intervalMs: 30_000,
            fetcher: async (signal) => {
                const page = await fetchAdminActivity({ limit: 50, signal });
                archivedCount = page.archived_count;
                return page.cards;
            },
            onResult: (cards) => {
                live = cards;
                loading = false;
                error = null;
            },
            onError: (e) => {
                loading = false;
                error = (e as Error).message ?? 'Failed to load admin activity';
            },
        });
    }

    onDestroy(() => teardown?.());

    async function toggleArchive(): Promise<void> {
        archivedExpanded = !archivedExpanded;
        if (archivedExpanded && archived.length === 0) {
            try {
                const page = await fetchAdminActivity({ limit: 50, archived: true });
                archived = page.cards;
            } catch (e) {
                error = (e as Error).message ?? 'Failed to load archive';
            }
        }
    }

    async function onDismiss(card: AdminActivityCard): Promise<void> {
        const idx = live.findIndex((c) => c.audit_id === card.audit_id);
        const removed = live[idx];
        if (idx === -1 || removed === undefined) return;
        live = [...live.slice(0, idx), ...live.slice(idx + 1)];
        archived = [removed, ...archived];
        archivedCount += 1;
        try {
            await dismissAdminActivity(card.audit_id);
        } catch (e) {
            live = [...live.slice(0, idx), removed, ...live.slice(idx)];
            archived = archived.filter((c) => c.audit_id !== card.audit_id);
            archivedCount -= 1;
            error = (e as Error).message ?? 'Failed to dismiss';
        }
    }

    async function onUndismiss(card: AdminActivityCard): Promise<void> {
        const idx = archived.findIndex((c) => c.audit_id === card.audit_id);
        const removed = archived[idx];
        if (idx === -1 || removed === undefined) return;
        archived = [...archived.slice(0, idx), ...archived.slice(idx + 1)];
        live = [removed, ...live];
        archivedCount = Math.max(0, archivedCount - 1);
        try {
            await undismissAdminActivity(card.audit_id);
        } catch (e) {
            archived = [...archived.slice(0, idx), removed, ...archived.slice(idx)];
            live = live.filter((c) => c.audit_id !== card.audit_id);
            archivedCount += 1;
            error = (e as Error).message ?? 'Failed to restore';
        }
    }

    function dotClass(kind: AdminEventKind): string {
        return `marker marker-${kind.replace(/_/g, '-')}`;
    }

    const ACTION: Record<AdminEventKind, string> = {
        released: 'released claim on',
        marked_ready: 'marked ready',
        unmarked_ready: 'unmarked ready',
        merge_rejected: 'sent back',
        unpublished: 'unpublished',
        dataset_published: 'published to dataset',
        discarded: 'discarded',
        undiscarded: 'restored',
        force_released: 'force-released',
        reassigned: 'reassigned',
        unlocked_for_revision: 'unlocked for revision',
    };

    function formatLine(card: AdminActivityCard, owner: boolean): string {
        const combo =
            card.riwayah && card.style
                ? ` (${titleCaseSlug(card.riwayah)}) (${titleCaseSlug(card.style)})`
                : '';
        const verb = ACTION[card.kind] ?? card.kind;
        if (owner && card.actor_login) {
            return `@${card.actor_login} ${verb} ${card.name}${combo}`;
        }
        return `${card.name}${combo} — ${verb}`;
    }
</script>

{#if $isAdmin}
    <aside class="admin-rail" aria-label="Admin notifications">
        <header>
            <h2>Admin notifications</h2>
            <span class="sub">{live.length} live</span>
        </header>

        {#if loading}
            <div class="state">Loading…</div>
        {:else if error}
            <div class="state error">{error}</div>
        {:else if live.length === 0}
            <div class="state">No new admin notifications.</div>
        {:else}
            <ol class="list">
                {#each live as card (card.audit_id)}
                    <li class="item">
                        <span class={dotClass(card.kind)} aria-hidden="true"></span>
                        <div class="body">
                            <p class="text">{formatLine(card, $isOwner)}</p>
                            <time class="time" datetime={card.ts}
                                >{relativeTime(card.ts)}</time
                            >
                        </div>
                        <button
                            class="dismiss"
                            type="button"
                            aria-label="Dismiss notification"
                            title="Dismiss"
                            on:click={() => onDismiss(card)}
                        >
                            ×
                        </button>
                    </li>
                {/each}
            </ol>
        {/if}

        {#if archivedCount > 0 || archived.length > 0}
            <button class="archive-toggle" type="button" on:click={toggleArchive}>
                <span class="caret" class:open={archivedExpanded}>▸</span>
                {archivedExpanded ? 'Hide' : 'Show'} archive ({archivedCount})
            </button>
        {/if}

        {#if archivedExpanded && archived.length > 0}
            <ol class="list archive">
                {#each archived as card (card.audit_id)}
                    <li class="item archived">
                        <span class={dotClass(card.kind)} aria-hidden="true"></span>
                        <div class="body">
                            <p class="text">{formatLine(card, $isOwner)}</p>
                            <time class="time" datetime={card.ts}
                                >{relativeTime(card.ts)}</time
                            >
                        </div>
                        <button
                            class="dismiss"
                            type="button"
                            aria-label="Restore notification"
                            title="Restore"
                            on:click={() => onUndismiss(card)}
                        >
                            ↺
                        </button>
                    </li>
                {/each}
            </ol>
        {/if}
    </aside>
{/if}

<style>
    .admin-rail {
        padding: var(--s-5);
        border: 1px solid var(--accent-tint);
        border-radius: var(--r-2);
        background: var(--accent-tint-soft);
        margin-bottom: var(--s-4);
    }
    header {
        display: flex;
        align-items: baseline;
        gap: var(--s-2);
        margin-bottom: var(--s-3);
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
        padding: var(--s-4) 0;
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
        grid-template-columns: 14px 1fr 24px;
        gap: var(--s-3);
        align-items: start;
        padding: var(--s-3) 0;
        border-bottom: 1px solid var(--border-quiet);
    }
    .item:last-child { border-bottom: none; }
    .item.archived { opacity: 0.7; }
    .marker {
        width: 8px; height: 8px;
        border-radius: 50%;
        margin-top: 6px;
        background: var(--border-strong);
    }
    .marker-marked-ready,
    .marker-dataset-published   { background: var(--state-published-fg); }
    .marker-merge-rejected,
    .marker-unpublished,
    .marker-removed-from-dataset { background: var(--state-error-fg); }
    .marker-discarded,
    .marker-undiscarded         { background: var(--text-muted); }
    .marker-force-released,
    .marker-reassigned,
    .marker-unlocked-for-revision { background: var(--accent-strong); }
    .marker-released,
    .marker-unmarked-ready       { background: var(--state-available-fg); }

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
    .dismiss {
        background: transparent;
        border: 0;
        color: var(--text-muted);
        font-size: 16px;
        line-height: 1;
        padding: 0 2px;
        cursor: pointer;
        transition: color var(--t-fast);
        align-self: start;
        margin-top: 2px;
    }
    .dismiss:hover { color: var(--accent-strong); }

    .archive-toggle {
        background: transparent;
        border: 0;
        padding: var(--s-2) 0 0;
        color: var(--text-muted);
        font-size: var(--fs-meta);
        cursor: pointer;
        display: inline-flex;
        align-items: center;
        gap: var(--s-2);
    }
    .archive-toggle:hover { color: var(--text-primary); }
    .caret {
        display: inline-block;
        transition: transform var(--t-fast);
    }
    .caret.open { transform: rotate(90deg); }
</style>
