<script lang="ts">
    /**
     * "My Notifications" rail — sits above Recent activity, under the
     * admin-dashboard button. Two sources, rendered as one list:
     *
     * - Global announcements (public; shown to everyone incl. anonymous) — an
     *   owner broadcast. Dismiss is client-side (localStorage); no archive.
     * - Per-user notifications (signed-in only) — events that happened to the
     *   user (request sent back / discarded, reciter ready, assigned, claim
     *   force-released, segment-flag reply). Dismissable → archived.
     *
     * In the Active view both sources merge, newest-first, styled identically.
     * The Active/Archive toggle + archive list are signed-in-only (announcements
     * never archive). The whole rail shows for anonymous users whenever at least
     * one announcement is active. Polls every 30s while visible.
     */
    import { onDestroy, onMount } from 'svelte';

    import type { UserNotification } from '../../../lib/api/notifications';
    import { currentUser, isSignedIn } from '../../../lib/stores/current-user';
    import { gotoSegments } from '../../../lib/utils/goto-segments';
    import { relativeTime } from '../../../lib/utils/relative-time';
    import { announcements } from '../stores/announcements.svelte';
    import { resolveDeliverySlug } from '../stores/catalog-data';
    import { openDetail } from '../stores/dashboard-state';
    import { notifications } from '../stores/notifications.svelte';

    const signedIn = $derived(isSignedIn($currentUser));
    const visible = $derived(signedIn || announcements.active.length > 0);

    onMount(() => {
        announcements.start();
        if (signedIn) notifications.start();
    });
    onDestroy(() => {
        announcements.stop();
        if (signedIn) notifications.stop();
    });

    /** Unified card shape so announcements + notifications render identically. */
    interface RailCard {
        key: string;
        title: string;
        body: string | null;
        created_at: string;
        unseen: boolean;
        nav: { label: string; go: () => void } | null;
        dismiss: () => void;
    }

    function openReciter(n: UserNotification): void {
        if (!n.slug) return;
        const resolved = resolveDeliverySlug(n.slug);
        if (resolved) openDetail(resolved.reciter.reciter_id, n.slug);
    }

    /**
     * Where clicking a notification should take the user, with an explicit
     * label so the destination is transparent before they click.
     */
    function navTarget(n: UserNotification): { label: string; go: () => void } | null {
        const slug = n.slug;
        if (!slug) return null;
        switch (n.event) {
            case 'reciter.alignment_completed':
            case 'reciter.claimed':
                return { label: 'Review in Segments', go: () => gotoSegments(slug) };
            case 'flag.reply': {
                const uid =
                    typeof n.payload?.segment_uid === 'string' ? n.payload.segment_uid : undefined;
                return {
                    label: 'Open flagged segment',
                    go: () => gotoSegments(slug, { openFlagged: true, focusFlaggedUid: uid }),
                };
            }
            default:
                return resolveDeliverySlug(slug)
                    ? { label: 'View reciter', go: () => openReciter(n) }
                    : null;
        }
    }

    /** Active view: announcements + personal notifications merged, newest-first. */
    const activeCards = $derived<RailCard[]>(
        [
            ...announcements.active.map(
                (a): RailCard => ({
                    key: `ann-${a.id}`,
                    title: a.title,
                    body: a.body ?? null,
                    created_at: a.created_at,
                    unseen: announcements.isNew(a.id),
                    nav: null,
                    dismiss: () => announcements.dismiss(a.id),
                }),
            ),
            ...notifications.active.map(
                (n): RailCard => ({
                    key: `notif-${n.id}`,
                    title: n.title,
                    body: n.body,
                    created_at: n.created_at,
                    unseen: !n.seen_at,
                    nav: navTarget(n),
                    dismiss: () => notifications.dismiss(n.id),
                }),
            ),
        ].sort((a, b) => (a.created_at < b.created_at ? 1 : -1)),
    );

    const badge = $derived(announcements.unread + notifications.unread);
</script>

{#if visible}
    <aside class="notifs" aria-label="My notifications">
        <header>
            <h2>My notifications</h2>
            {#if badge > 0 && notifications.view === 'active'}
                <span class="badge" aria-label="{badge} unread">{badge}</span>
            {/if}
            {#if signedIn}
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
            {/if}
        </header>

        {#if notifications.view === 'archive'}
            {#if notifications.error}
                <div class="state error">{notifications.error}</div>
            {:else if notifications.archived.length === 0}
                <div class="state">Nothing archived.</div>
            {:else}
                <ol class="list">
                    {#each notifications.archived as n (n.id)}
                        {@const target = navTarget(n)}
                        <li class="item">
                            <div class="body-wrap">
                                <p class="title">{n.title}</p>
                                {#if n.body}
                                    <p class="body">{n.body}</p>
                                {/if}
                                <time class="time" datetime={n.created_at}
                                    >{relativeTime(n.created_at)}</time>
                            </div>
                            <div class="actions">
                                {#if target}
                                    <button
                                        class="act"
                                        type="button"
                                        aria-label={target.label}
                                        title={target.label}
                                        onclick={target.go}>↗</button>
                                {/if}
                                <button
                                    class="act"
                                    type="button"
                                    aria-label="Restore"
                                    title="Restore to active"
                                    onclick={() => notifications.restore(n.id)}>↩</button>
                            </div>
                        </li>
                    {/each}
                </ol>
            {/if}
        {:else if notifications.error}
            <div class="state error">{notifications.error}</div>
        {:else if signedIn && notifications.loading && activeCards.length === 0}
            <div class="state">Loading…</div>
        {:else if activeCards.length === 0}
            <div class="state">No notifications.</div>
        {:else}
            <ol class="list">
                {#each activeCards as c (c.key)}
                    <li class="item" class:unseen={c.unseen}>
                        <div class="body-wrap">
                            <p class="title">{c.title}</p>
                            {#if c.body}
                                <p class="body">{c.body}</p>
                            {/if}
                            <time class="time" datetime={c.created_at}>{relativeTime(c.created_at)}</time>
                        </div>
                        <div class="actions">
                            {#if c.nav}
                                <button
                                    class="act"
                                    type="button"
                                    aria-label={c.nav.label}
                                    title={c.nav.label}
                                    onclick={c.nav.go}>↗</button>
                            {/if}
                            <button
                                class="act"
                                type="button"
                                aria-label="Dismiss"
                                title="Dismiss"
                                onclick={c.dismiss}>✕</button>
                        </div>
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
        grid-template-columns: 1fr auto;
        gap: var(--s-2);
        padding: var(--s-3) 0;
        border-bottom: 1px solid var(--border-quiet);
        align-items: start;
    }
    .item:last-child { border-bottom: none; }
    .item.unseen .title { font-weight: 600; color: var(--text-primary); }

    .body-wrap {
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: 2px;
    }
    .title {
        margin: 0;
        font-size: var(--fs-body);
        color: var(--text-secondary);
        line-height: var(--lh-normal);
    }
    .body {
        margin: 0;
        font-size: var(--fs-meta);
        color: var(--text-muted);
        line-height: var(--lh-normal);
        white-space: pre-wrap;
    }
    .time {
        font-size: 10.5px;
        color: var(--text-faint);
        font-variant-numeric: tabular-nums;
    }
    .actions {
        display: flex;
        align-items: center;
        gap: 2px;
    }
    .act {
        background: transparent;
        border: 0;
        color: var(--text-muted);
        font-size: 13px;
        line-height: 1;
        padding: 2px 3px;
        cursor: pointer;
        border-radius: var(--radius-sm, 4px);
        transition: color var(--t-fast), background var(--t-fast);
    }
    .act:hover {
        color: var(--text-primary);
        background: var(--surface-raised, var(--border-quiet));
    }
</style>
