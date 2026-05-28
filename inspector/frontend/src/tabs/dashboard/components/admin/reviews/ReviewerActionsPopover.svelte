<script lang="ts">
    /**
     * Owner-only popover on the current-reviewer chip in the General drawer.
     *
     * Three modes:
     *   - ``menu``   — initial: choose Change or Remove
     *   - ``change`` — pick from registered users (typeahead-filtered list,
     *                  no free-text HF lookup — only people who've signed
     *                  into Inspector can actually act on a claim) + optional
     *                  reason + Reassign
     *   - ``remove`` — optional reason + Force-release
     *
     * Toggle behaviour mirrors ``RolePicker.svelte``: click-outside (capture-
     * phase document listener) + Escape close. The popover positions itself
     * absolute-below the trigger; the parent owns the trigger button + the
     * ``.rp-wrap``-style relative container.
     *
     * Mounted only when ``$isOwner`` (the parent gates the trigger).
     */
    import { onMount, onDestroy } from 'svelte';

    import {
        forceReleaseClaim,
        reassignClaim,
    } from '../../../../../lib/api/admin-reviews';
    import { fetchAdminUsers } from '../../../../../lib/api/admin-users';
    import { refreshReciterTask } from '../../../../../lib/api/reciter-task';
    import { loadCurrentUser } from '../../../../../lib/stores/current-user';
    import type { AdminUserRow } from '../../../../../lib/types/generated/schemas';
    import { loadCatalog } from '../../../stores/catalog-data';

    let {
        slug,
        currentLogin,
        onclose,
        onaction,
    }: {
        slug: string;
        currentLogin: string | null;
        /** Close the popover (also fired on success). */
        onclose: () => void;
        /** Fired after a successful Reassign or Remove — drawer refetches. */
        onaction?: () => void;
    } = $props();

    type Mode = 'menu' | 'change' | 'remove';
    let mode = $state<Mode>('menu');

    // ---- Change-mode state ----
    /** All registered Inspector users — fetched once on entering 'change'. */
    let users = $state<AdminUserRow[]>([]);
    let usersLoading = $state(false);
    let usersErr = $state<string | null>(null);
    let usersAC: AbortController | null = null;
    /** Client-side typeahead filter (login OR hf_user_id substring). */
    let filterQ = $state('');
    /** The picked user → confirm reassign. */
    let resolved = $state<AdminUserRow | null>(null);
    let changeReason = $state('');
    let changeErr = $state<string | null>(null);
    let reassigning = $state(false);

    async function loadUsersOnce(): Promise<void> {
        if (users.length > 0 || usersLoading) return;
        usersLoading = true;
        usersErr = null;
        usersAC?.abort();
        const ac = new AbortController();
        usersAC = ac;
        try {
            const resp = await fetchAdminUsers(ac.signal);
            if (!ac.signal.aborted) users = resp.users ?? [];
        } catch (e) {
            if (!ac.signal.aborted) usersErr = (e as Error).message ?? 'Failed to load users';
        } finally {
            if (!ac.signal.aborted) usersLoading = false;
        }
    }

    /** Filtered + sorted user list — current reviewer excluded (would be a
     * no-op reassign). Maintainers + owners surface first, then contributors;
     * inside each tier sort alphabetically by login. */
    const filteredUsers = $derived.by(() => {
        const q = filterQ.trim().toLowerCase();
        const cur = (currentLogin ?? '').toLowerCase();
        const rolePriority: Record<string, number> = {
            owner: 0,
            maintainer: 1,
            contributor: 2,
        };
        return users
            .filter((u) => {
                const login = (u.login ?? '').toLowerCase();
                if (login && login === cur) return false;
                if (!q) return true;
                return login.includes(q) || u.hf_user_id.toLowerCase().includes(q);
            })
            .sort((a, b) => {
                const pa = rolePriority[a.role ?? 'contributor'] ?? 3;
                const pb = rolePriority[b.role ?? 'contributor'] ?? 3;
                if (pa !== pb) return pa - pb;
                return (a.login ?? '').localeCompare(b.login ?? '');
            });
    });

    const canReassign = $derived(resolved !== null && !reassigning);

    /**
     * Push the new state to every surface that might be displaying this slug
     * without waiting for its natural refresh cadence. Mirrors the
     * SegmentsTab's ``_refreshTask`` trio so the Segments-tab footer + claim
     * affordance flip in lockstep with the admin drawer.
     */
    async function _propagateStateChange(): Promise<void> {
        await Promise.allSettled([
            refreshReciterTask(slug),
            loadCurrentUser(),
            loadCatalog(true),
        ]);
    }

    async function confirmReassign(): Promise<void> {
        if (!canReassign || !resolved) return;
        const login = resolved.login;
        if (!login) {
            changeErr = 'Selected user has no login';
            return;
        }
        reassigning = true;
        changeErr = null;
        try {
            await reassignClaim(slug, login, changeReason.trim());
            await _propagateStateChange();
            onaction?.();
            onclose();
        } catch (e) {
            changeErr = (e as Error).message ?? 'Reassign failed';
        } finally {
            reassigning = false;
        }
    }

    // ---- Remove-mode state ----
    let removeReason = $state('');
    let removeErr = $state<string | null>(null);
    let removing = $state(false);

    const canRemove = $derived(!removing);

    async function confirmRemove(): Promise<void> {
        if (!canRemove) return;
        removing = true;
        removeErr = null;
        try {
            await forceReleaseClaim(slug, removeReason.trim());
            await _propagateStateChange();
            onaction?.();
            onclose();
        } catch (e) {
            removeErr = (e as Error).message ?? 'Remove failed';
        } finally {
            removing = false;
        }
    }

    // ---- Mode switching ----
    function pickChange(): void {
        mode = 'change';
        void loadUsersOnce();
    }
    function pickRemove(): void {
        mode = 'remove';
    }
    function backToMenu(): void {
        mode = 'menu';
        changeErr = null;
        removeErr = null;
    }

    function pickUser(u: AdminUserRow): void {
        resolved = u;
    }
    function clearPicked(): void {
        resolved = null;
    }

    // ---- Dismissal — Escape + click-outside (mirrors RolePicker) ----
    let rootEl: HTMLDivElement | null = null;

    function onDocClick(e: MouseEvent): void {
        if (!rootEl) return;
        const t = e.target as Node | null;
        if (t && !rootEl.contains(t)) {
            onclose();
        }
    }

    function onKey(e: KeyboardEvent): void {
        if (e.key === 'Escape') {
            e.stopPropagation();
            onclose();
        }
    }

    onMount(() => {
        document.addEventListener('click', onDocClick, true);
        document.addEventListener('keydown', onKey);
    });

    onDestroy(() => {
        document.removeEventListener('click', onDocClick, true);
        document.removeEventListener('keydown', onKey);
        usersAC?.abort();
    });

    function avatarInitials(s: string | null | undefined): string {
        const trimmed = (s ?? '').trim();
        if (!trimmed) return '?';
        const chars = trimmed.replace(/[^a-z0-9]/gi, '').slice(0, 2).toUpperCase();
        return chars || trimmed.slice(0, 2).toUpperCase();
    }
</script>

<div class="popover" bind:this={rootEl} role="dialog" aria-label="Reassign or remove reviewer">
    {#if mode === 'menu'}
        <div class="menu">
            <button class="menu-item change" type="button" onclick={pickChange}>
                <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true">
                    <path d="M4 4 L12 4 M4 8 L10 8 M4 12 L8 12" />
                    <path d="M11 11 L14 14 M14 11 L11 14" />
                </svg>
                <div class="menu-text">
                    <div class="menu-title">Change reviewer</div>
                    <div class="menu-sub">Hand off to a different registered user</div>
                </div>
            </button>
            <button class="menu-item remove" type="button" onclick={pickRemove}>
                <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true">
                    <circle cx="8" cy="6" r="2.5" />
                    <path d="M3 13.5 C3 11 5 9.5 8 9.5 C11 9.5 13 11 13 13.5" />
                    <path d="M11 4 L15 4" />
                </svg>
                <div class="menu-text">
                    <div class="menu-title">Remove reviewer</div>
                    <div class="menu-sub">Force-release · back to available</div>
                </div>
            </button>
        </div>
    {:else if mode === 'change'}
        <div class="form">
            <button class="back" type="button" onclick={backToMenu}>← back</button>
            <div class="form-title">Change reviewer</div>

            {#if resolved}
                <!-- Picked user — confirm step -->
                <div class="user-card picked">
                    {#if resolved.avatar_url}
                        <!-- eslint-disable-next-line svelte/no-at-html-tags -->
                        <img class="ucard-avatar" src={resolved.avatar_url as string} alt="" />
                    {:else}
                        <span class="ucard-avatar fallback">{avatarInitials(resolved.login)}</span>
                    {/if}
                    <div class="ucard-meta">
                        <div class="ucard-login">{resolved.login ?? resolved.hf_user_id}</div>
                        {#if resolved.role}
                            <div class="ucard-role">{resolved.role}</div>
                        {/if}
                    </div>
                    <button class="link-btn" type="button" onclick={clearPicked} disabled={reassigning}>
                        change
                    </button>
                </div>

                <label class="field">
                    <span>Reason (optional)</span>
                    <textarea
                        bind:value={changeReason}
                        placeholder="Why is the claim being reassigned?"
                        rows="2"
                        disabled={reassigning}
                    ></textarea>
                </label>

                {#if changeErr}
                    <div class="status error" role="alert">{changeErr}</div>
                {/if}

                <div class="actions">
                    <button
                        class="btn-primary"
                        type="button"
                        onclick={confirmReassign}
                        disabled={!canReassign}
                    >{reassigning ? 'Reassigning…' : 'Reassign'}</button>
                    <button class="btn-cancel" type="button" onclick={onclose} disabled={reassigning}>
                        Cancel
                    </button>
                </div>
            {:else}
                <!-- User picker — typeahead-filtered list -->
                <label class="field">
                    <span>Pick a registered user</span>
                    <div class="search">
                        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true">
                            <circle cx="7" cy="7" r="5" /><line x1="11" y1="11" x2="14.5" y2="14.5" />
                        </svg>
                        <input
                            type="text"
                            bind:value={filterQ}
                            placeholder="Filter by login…"
                            autocomplete="off"
                            spellcheck="false"
                        />
                    </div>
                </label>

                {#if usersLoading}
                    <div class="status muted">Loading users…</div>
                {:else if usersErr}
                    <div class="status error" role="alert">{usersErr}</div>
                {:else if filteredUsers.length === 0}
                    <div class="status muted">No matching users.</div>
                {:else}
                    <ul class="user-list">
                        {#each filteredUsers as u (u.hf_user_id)}
                            <li>
                                <button class="user-row" type="button" onclick={() => pickUser(u)}>
                                    {#if u.avatar_url}
                                        <!-- eslint-disable-next-line svelte/no-at-html-tags -->
                                        <img class="ucard-avatar" src={u.avatar_url as string} alt="" />
                                    {:else}
                                        <span class="ucard-avatar fallback">{avatarInitials(u.login)}</span>
                                    {/if}
                                    <div class="ucard-meta">
                                        <div class="ucard-login">{u.login ?? u.hf_user_id}</div>
                                        {#if u.role}
                                            <div class="ucard-role">{u.role}</div>
                                        {/if}
                                    </div>
                                    {#if u.active_claim}
                                        <span class="busy-pill" title="Already has an active claim">claimed</span>
                                    {/if}
                                </button>
                            </li>
                        {/each}
                    </ul>
                {/if}
            {/if}
        </div>
    {:else if mode === 'remove'}
        <div class="form">
            <button class="back" type="button" onclick={backToMenu}>← back</button>
            <div class="form-title danger">Remove reviewer</div>
            <div class="form-q">
                Force-release this claim? The reviewer is removed and the recitation
                returns to <em>Available for review</em>.
            </div>

            <label class="field">
                <span>Reason (optional)</span>
                <textarea
                    bind:value={removeReason}
                    placeholder="Why is the claim being removed?"
                    rows="2"
                    disabled={removing}
                ></textarea>
            </label>

            {#if removeErr}
                <div class="status error" role="alert">{removeErr}</div>
            {/if}

            <div class="actions">
                <button
                    class="btn-danger"
                    type="button"
                    onclick={confirmRemove}
                    disabled={!canRemove}
                >{removing ? 'Removing…' : 'Force-release'}</button>
                <button class="btn-cancel" type="button" onclick={onclose} disabled={removing}>
                    Cancel
                </button>
            </div>
        </div>
    {/if}
</div>

<style>
    .popover {
        position: absolute;
        top: calc(100% + 6px);
        left: 0;
        z-index: 50;
        min-width: 300px;
        max-width: 360px;
        background: var(--canvas-inset, var(--panel));
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        box-shadow: 0 8px 24px oklch(0.06 0.005 268 / 0.5);
        padding: var(--s-2);
    }

    /* ---- menu mode ---- */
    .menu { display: flex; flex-direction: column; gap: 2px; }
    .menu-item {
        display: flex;
        align-items: center;
        gap: var(--s-3);
        padding: var(--s-2) var(--s-3);
        background: transparent;
        border: 0;
        border-radius: var(--r-1);
        color: var(--text-primary);
        font: inherit;
        font-size: var(--fs-body);
        cursor: pointer;
        text-align: left;
        transition: background var(--t-fast);
    }
    .menu-item:hover { background: var(--panel); }
    .menu-item svg {
        width: 18px; height: 18px;
        color: var(--text-muted);
        flex-shrink: 0;
    }
    .menu-item.remove svg { color: var(--state-error-fg, var(--text-muted)); }
    .menu-text { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
    .menu-title { font-weight: 500; }
    .menu-sub { font-size: var(--fs-meta); color: var(--text-faint); }

    /* ---- form mode ---- */
    .form {
        display: flex;
        flex-direction: column;
        gap: var(--s-3);
        padding: var(--s-2) var(--s-2) var(--s-1);
    }
    .back {
        align-self: flex-start;
        background: transparent;
        border: 0;
        color: var(--text-muted);
        font: inherit;
        font-size: var(--fs-meta);
        cursor: pointer;
        padding: 0;
    }
    .back:hover { color: var(--text-primary); }
    .form-title {
        font-size: var(--fs-row);
        font-weight: 500;
        color: var(--text-primary);
    }
    .form-title.danger { color: var(--state-error-fg, var(--text-primary)); }
    .form-q {
        font-size: var(--fs-meta);
        color: var(--text-secondary);
        line-height: 1.45;
    }
    .form-q em { color: var(--text-primary); font-style: normal; font-weight: 500; }

    .field { display: flex; flex-direction: column; gap: 4px; }
    .field > span {
        font-size: 10.5px;
        font-family: var(--font-mono);
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: var(--text-faint);
    }
    .field textarea {
        background: var(--panel-2);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-1);
        color: var(--text-primary);
        font: inherit;
        font-size: var(--fs-body);
        padding: var(--s-2);
        resize: vertical;
        min-height: 48px;
        outline: 0;
    }
    .field textarea:focus { border-color: var(--accent-tint); box-shadow: 0 0 0 2px var(--accent-tint-soft); }

    .search {
        display: flex;
        align-items: center;
        gap: 6px;
        background: var(--panel-2);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-1);
        padding: 0 var(--s-2);
        height: 30px;
        color: var(--text-muted);
    }
    .search svg { width: 14px; height: 14px; flex-shrink: 0; }
    .search input {
        flex: 1;
        background: transparent;
        border: 0;
        color: var(--text-primary);
        font: inherit;
        font-size: var(--fs-body);
        outline: 0;
        min-width: 0;
    }
    .search input::placeholder { color: var(--text-faint); }
    .search:focus-within { border-color: var(--accent-tint); box-shadow: 0 0 0 2px var(--accent-tint-soft); }

    /* ---- user list ---- */
    .user-list {
        list-style: none;
        padding: 0;
        margin: 0;
        display: flex;
        flex-direction: column;
        gap: 2px;
        max-height: 260px;
        overflow-y: auto;
        background: var(--panel-2);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-1);
        padding: 4px;
    }
    .user-row {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        width: 100%;
        padding: 5px var(--s-2);
        background: transparent;
        border: 0;
        border-radius: var(--r-1);
        color: var(--text-primary);
        font: inherit;
        font-size: var(--fs-body);
        cursor: pointer;
        text-align: left;
        transition: background var(--t-fast);
    }
    .user-row:hover { background: var(--panel); }
    .user-row:focus-visible {
        outline: 0;
        background: var(--panel);
        box-shadow: inset 0 0 0 1px var(--accent-tint);
    }

    /* ---- picked / list user card chrome ---- */
    .user-card {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        padding: var(--s-2);
        background: var(--panel);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-1);
    }
    .user-card.picked { border-color: var(--accent-tint); }
    .ucard-avatar {
        width: 26px;
        height: 26px;
        border-radius: 50%;
        flex-shrink: 0;
    }
    .ucard-avatar.fallback {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        background: var(--accent-tint);
        color: var(--accent-strong);
        font-size: 10px;
        font-weight: 600;
    }
    .ucard-meta { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
    .ucard-login { color: var(--text-primary); font-size: var(--fs-body); }
    .ucard-role {
        color: var(--text-muted);
        font-size: 10.5px;
        font-family: var(--font-mono);
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }
    .busy-pill {
        font-size: 10px;
        font-family: var(--font-mono);
        color: var(--text-muted);
        background: var(--panel-2);
        border: 1px solid var(--border-quiet);
        border-radius: 999px;
        padding: 1px 6px;
        flex-shrink: 0;
    }
    .link-btn {
        background: transparent;
        border: 0;
        color: var(--accent);
        font: inherit;
        font-size: var(--fs-meta);
        cursor: pointer;
        padding: 0 4px;
    }
    .link-btn:hover:not(:disabled) { color: var(--accent-strong); text-decoration: underline; }
    .link-btn:disabled { opacity: 0.5; cursor: not-allowed; }

    /* ---- status banners ---- */
    .status { font-size: var(--fs-meta); padding: 2px 4px; }
    .status.muted { color: var(--text-muted); }
    .status.error { color: var(--state-error-fg); }

    /* ---- action buttons ---- */
    .actions { display: flex; gap: var(--s-2); margin-top: 2px; }
    .actions button {
        flex: 0 0 auto;
        font: inherit;
        font-size: var(--fs-meta);
        padding: 5px 12px;
        border-radius: var(--r-1);
        cursor: pointer;
        transition: background var(--t-fast), border-color var(--t-fast), color var(--t-fast);
    }
    .actions button:disabled { cursor: not-allowed; opacity: 0.5; }
    .btn-primary {
        background: var(--accent);
        border: 1px solid var(--accent);
        color: var(--accent-fg);
    }
    .btn-primary:hover:not(:disabled) { background: var(--accent-strong); }
    .btn-danger {
        background: transparent;
        border: 1px solid var(--state-error-fg, var(--border-default));
        color: var(--state-error-fg, var(--text-primary));
    }
    .btn-danger:hover:not(:disabled) {
        background: var(--state-error-bg, var(--panel));
    }
    .btn-cancel {
        background: transparent;
        border: 1px solid var(--border-quiet);
        color: var(--text-muted);
    }
    .btn-cancel:hover:not(:disabled) { color: var(--text-primary); border-color: var(--border-default); }
</style>
