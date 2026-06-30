<script lang="ts">
    /**
     * Announcements compartment (capability: announcements.send; owner-only by
     * default). Compose a global announcement (title + optional body) that shows
     * in every user's "My Notifications" rail — including signed-out visitors —
     * until revoked. Below the form, the management list of past announcements
     * (active + revoked) with a per-row Revoke action.
     */
    import { onMount } from 'svelte';

    import {
        type AnnouncementAdmin,
        createAnnouncement,
        listAnnouncements,
        revokeAnnouncement,
    } from '../../../../lib/api/announcements';
    import { relativeTime } from '../../../../lib/utils/relative-time';

    const TITLE_MAX = 200;
    const BODY_MAX = 2000;

    let rows = $state<AnnouncementAdmin[]>([]);
    let loading = $state(true);
    let error = $state<string | null>(null);

    let title = $state('');
    let body = $state('');
    let sending = $state(false);
    let sendError = $state<string | null>(null);

    const canSend = $derived(title.trim().length > 0 && !sending);

    onMount(load);

    async function load(): Promise<void> {
        loading = true;
        error = null;
        try {
            rows = await listAnnouncements();
        } catch (e) {
            error = (e as Error).message ?? 'Failed to load announcements';
        } finally {
            loading = false;
        }
    }

    async function send(): Promise<void> {
        const t = title.trim();
        if (!t || sending) return;
        sending = true;
        sendError = null;
        try {
            const created = await createAnnouncement(t, body.trim() || null);
            rows = [created, ...rows];
            title = '';
            body = '';
        } catch (e) {
            sendError = (e as Error).message ?? 'Failed to send announcement';
        } finally {
            sending = false;
        }
    }

    async function revoke(row: AnnouncementAdmin): Promise<void> {
        if (row.revoked_at) return;
        if (!window.confirm('Revoke this announcement? It will disappear from everyone’s rail.'))
            return;
        const prev = row.revoked_at;
        row.revoked_at = new Date().toISOString(); // optimistic
        try {
            await revokeAnnouncement(row.id);
        } catch (e) {
            row.revoked_at = prev; // revert
            error = (e as Error).message ?? 'Failed to revoke';
        }
    }
</script>

<div class="ann">
    <section class="compose">
        <label class="field">
            <span class="lbl">Title</span>
            <input
                type="text"
                bind:value={title}
                maxlength={TITLE_MAX}
                placeholder="Short headline shown to everyone"
            />
        </label>
        <label class="field">
            <span class="lbl">Body <span class="opt">(optional)</span></span>
            <textarea
                bind:value={body}
                maxlength={BODY_MAX}
                rows="3"
                placeholder="Optional detail"
            ></textarea>
        </label>
        <div class="actions">
            {#if sendError}<span class="err">{sendError}</span>{/if}
            <button class="send" type="button" disabled={!canSend} onclick={send}>
                {sending ? 'Sending…' : 'Send announcement'}
            </button>
        </div>
    </section>

    <section class="history">
        <h3>Announcements</h3>
        {#if loading}
            <div class="state">Loading…</div>
        {:else if error}
            <div class="state err">{error}</div>
        {:else if rows.length === 0}
            <div class="state">No announcements yet.</div>
        {:else}
            <ol class="list">
                {#each rows as row (row.id)}
                    <li class="item" class:revoked={!!row.revoked_at}>
                        <div class="meta">
                            <p class="title">{row.title}</p>
                            {#if row.body}<p class="body">{row.body}</p>{/if}
                            <span class="sub">
                                {#if row.author_login}@{row.author_login} · {/if}
                                {relativeTime(row.created_at)}
                                {#if row.revoked_at}· <span class="rv">revoked</span>{/if}
                            </span>
                        </div>
                        {#if !row.revoked_at}
                            <button class="revoke" type="button" onclick={() => revoke(row)}>
                                Revoke
                            </button>
                        {/if}
                    </li>
                {/each}
            </ol>
        {/if}
    </section>
</div>

<style>
    .ann {
        display: flex;
        flex-direction: column;
        gap: var(--s-6);
        padding: var(--s-2) 0;
    }
    .compose {
        display: flex;
        flex-direction: column;
        gap: var(--s-3);
    }
    .field {
        display: flex;
        flex-direction: column;
        gap: var(--s-1);
    }
    .lbl {
        font-size: var(--fs-meta);
        color: var(--text-muted);
    }
    .opt {
        color: var(--text-faint);
    }
    input,
    textarea {
        width: 100%;
        padding: var(--s-2) var(--s-3);
        background: var(--surface-base);
        border: 1px solid var(--border-quiet);
        border-radius: var(--radius-sm, 4px);
        color: var(--text-primary);
        font-size: var(--fs-body);
        font-family: inherit;
        resize: vertical;
    }
    input:focus,
    textarea:focus {
        outline: none;
        border-color: var(--accent);
    }
    .actions {
        display: flex;
        align-items: center;
        justify-content: flex-end;
        gap: var(--s-3);
    }
    .send {
        padding: var(--s-2) var(--s-4);
        background: var(--accent);
        color: var(--ink-on-color);
        border: 0;
        border-radius: var(--radius-sm, 4px);
        font-size: var(--fs-body);
        cursor: pointer;
    }
    .send:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
    .err {
        color: var(--state-error-fg);
        font-size: var(--fs-meta);
    }

    .history h3 {
        font-size: var(--fs-body);
        font-weight: 500;
        color: var(--text-primary);
        margin: 0 0 var(--s-3);
    }
    .state {
        padding: var(--s-5) 0;
        text-align: center;
        color: var(--text-muted);
        font-size: var(--fs-meta);
    }
    .state.err {
        color: var(--state-error-fg);
    }
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
        gap: var(--s-3);
        padding: var(--s-3) 0;
        border-bottom: 1px solid var(--border-quiet);
        align-items: start;
    }
    .item:last-child {
        border-bottom: none;
    }
    .item.revoked {
        opacity: 0.55;
    }
    .meta {
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: 2px;
    }
    .title {
        margin: 0;
        font-size: var(--fs-body);
        color: var(--text-primary);
    }
    .item.revoked .title {
        text-decoration: line-through;
    }
    .body {
        margin: 0;
        font-size: var(--fs-meta);
        color: var(--text-muted);
        white-space: pre-wrap;
    }
    .sub {
        font-size: 10.5px;
        color: var(--text-faint);
    }
    .rv {
        color: var(--state-error-fg);
    }
    .revoke {
        background: transparent;
        border: 1px solid var(--border-quiet);
        color: var(--text-muted);
        font-size: var(--fs-meta);
        padding: 2px var(--s-2);
        border-radius: var(--radius-sm, 4px);
        cursor: pointer;
    }
    .revoke:hover {
        color: var(--state-error-fg);
        border-color: var(--state-error-fg);
    }
</style>
