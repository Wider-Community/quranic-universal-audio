<script lang="ts">
    /**
     * Per-user "My Notifications" rail — sits above Recent activity, under the
     * admin-dashboard button. Shows events that happened to the signed-in user
     * (request sent back / discarded, reciter ready, assigned, claim
     * force-released, segment-flag reply). Each notification is a mini-accordion
     * (collapsed: title + time; expanded: detail + a link to the reciter).
     *
     * Per-user, dismissable → archived (Active/Archive toggle in the header).
     * Polls every 30s while visible via the shared notifications store. Hidden
     * for anonymous users (they have no notifications).
     */
    import { onDestroy, onMount } from 'svelte';

    import type { UserNotification } from '../../../lib/api/notifications';
    import { currentUser, isSignedIn } from '../../../lib/stores/current-user';
    import { gotoSegments } from '../../../lib/utils/goto-segments';
    import { relativeTime } from '../../../lib/utils/relative-time';
    import { resolveDeliverySlug } from '../stores/catalog-data';
    import { openDetail } from '../stores/dashboard-state';
    import { notifications } from '../stores/notifications.svelte';

    const signedIn = $derived(isSignedIn($currentUser));

    onMount(() => notifications.start());
    onDestroy(() => notifications.stop());

    const list = $derived(
        notifications.view === 'active' ? notifications.active : notifications.archived,
    );

    function openReciter(n: UserNotification): void {
        if (!n.slug) return;
        const resolved = resolveDeliverySlug(n.slug);
        if (resolved) openDetail(resolved.reciter.reciter_id, n.slug);
    }

    /**
     * Where clicking a notification should take the user, with an explicit
     * label so the destination is transparent before they click:
     * - alignment-ready / assigned → open the reciter in the Segments tab
     *   (mirrors the post-claim redirect).
     * - flag reply → open it in Segments, open the Flagged accordion, and
     *   scroll to the flagged segment.
     * - everything else (request/intake rejections) → the dashboard detail
     *   modal, when the reciter is still in the catalog.
     */
    function navTarget(n: UserNotification): { label: string; go: () => void } | null {
        const slug = n.slug;
        if (!slug) return null;
        switch (n.event) {
            case 'reciter.alignment_completed':
            case 'reciter.claimed':
                return { label: 'Review in Segments →', go: () => gotoSegments(slug) };
            case 'flag.reply': {
                const uid =
                    typeof n.payload?.segment_uid === 'string' ? n.payload.segment_uid : undefined;
                return {
                    label: 'Open flagged segment →',
                    go: () => gotoSegments(slug, { openFlagged: true, focusFlaggedUid: uid }),
                };
            }
            default:
                return resolveDeliverySlug(slug)
                    ? { label: 'View reciter →', go: () => openReciter(n) }
                    : null;
        }
    }
</script>

{#if signedIn}
    <aside class="notifs" aria-label="My notifications">
        <header>
            <h2>My notifications</h2>
            {#if notifications.unread > 0 && notifications.view === 'active'}
                <span class="badge" aria-label="{notifications.unread} unread">{notifications.unread}</span>
            {/if}
            <div class="toggle" role="tablist" aria-label="Notifications view">
                <button
                    type="button"
                    role="tab"
                    aria-selected={notifications.view === 'active'}
                    class:on={notifications.view === 'active'}
                    onclick={() => notifications.setView('active')}>Active</button>
                <button
                    type="button"
                    role="tab"
                    aria-selected={notifications.view === 'archive'}
                    class:on={notifications.view === 'archive'}
                    onclick={() => notifications.setView('archive')}>Archive</button>
            </div>
        </header>

        {#if notifications.error}
            <div class="state error">{notifications.error}</div>
        {:else if notifications.view === 'active' && notifications.loading}
            <div class="state">Loading…</div>
        {:else if list.length === 0}
            <div class="state">
                {notifications.view === 'active' ? 'No notifications.' : 'Nothing archived.'}
            </div>
        {:else}
            <ol class="list">
                {#each list as n (n.id)}
                    {@const target = navTarget(n)}
                    <li class="item" class:unseen={notifications.view === 'active' && !n.seen_at}>
                        <details>
                            <summary>
                                <span class="title">{n.title}</span>
                                <time class="time" datetime={n.created_at}>{relativeTime(n.created_at)}</time>
                            </summary>
                            {#if n.body}
                                <p class="body">{n.body}</p>
                            {/if}
                            {#if target}
                                <button type="button" class="link" onclick={target.go}>
                                    {target.label}
                                </button>
                            {/if}
                        </details>
                        {#if notifications.view === 'active'}
                            <button
                                class="act"
                                type="button"
                                aria-label="Dismiss"
                                title="Dismiss to archive"
                                onclick={() => notifications.dismiss(n.id)}>✕</button>
                        {:else}
                            <button
                                class="act"
                                type="button"
                                aria-label="Restore"
                                title="Restore to active"
                                onclick={() => notifications.restore(n.id)}>↩</button>
                        {/if}
                    </li>
                {/each}
            </ol>
        {/if}
    </aside>
{/if}

<style>
    .notifs {
        padding: var(--s-5) var(--s-5);
        border-left: 1px solid var(--border-quiet);
        border-bottom: 1px solid var(--border-quiet);
    }
    header {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        margin-bottom: var(--s-4);
    }
    header h2 {
        font-size: var(--fs-h3);
        color: var(--text-primary);
        font-weight: 500;
        margin: 0;
    }
    .badge {
        font-size: 10px;
        font-weight: 600;
        line-height: 1;
        padding: 2px 6px;
        border-radius: 999px;
        background: var(--state-requested-fg);
        color: var(--surface-base, #fff);
    }
    .toggle {
        margin-left: auto;
        display: inline-flex;
        gap: 2px;
    }
    .toggle button {
        background: transparent;
        border: 0;
        font-size: var(--fs-meta);
        color: var(--text-muted);
        padding: 2px 6px;
        cursor: pointer;
        border-radius: var(--radius-sm, 4px);
    }
    .toggle button.on {
        color: var(--text-primary);
        background: var(--surface-raised, var(--border-quiet));
    }
    .state {
        padding: var(--s-6) 0;
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
        grid-template-columns: 1fr 24px;
        gap: var(--s-2);
        padding: var(--s-3) 0;
        border-bottom: 1px solid var(--border-quiet);
        align-items: start;
    }
    .item:last-child { border-bottom: none; }
    .item.unseen .title { font-weight: 600; color: var(--text-primary); }

    details { min-width: 0; }
    summary {
        cursor: pointer;
        list-style: none;
        display: flex;
        flex-direction: column;
        gap: 2px;
    }
    summary::-webkit-details-marker { display: none; }
    .title {
        font-size: var(--fs-body);
        color: var(--text-secondary);
        line-height: var(--lh-normal);
    }
    .time {
        font-size: 10.5px;
        color: var(--text-faint);
        font-variant-numeric: tabular-nums;
    }
    .body {
        margin: var(--s-2) 0 0;
        font-size: var(--fs-meta);
        color: var(--text-muted);
        line-height: var(--lh-normal);
        white-space: pre-wrap;
    }
    .link {
        margin-top: var(--s-2);
        background: transparent;
        border: 0;
        padding: 0;
        font-size: var(--fs-meta);
        color: var(--accent-fg, var(--state-under-review-fg));
        cursor: pointer;
    }
    .link:hover { text-decoration: underline; }
    .act {
        background: transparent;
        border: 0;
        color: var(--text-muted);
        font-size: 13px;
        line-height: 1;
        padding: 0 2px;
        cursor: pointer;
        align-self: start;
        margin-top: 2px;
        transition: color var(--t-fast);
    }
    .act:hover { color: var(--text-primary); }
</style>
