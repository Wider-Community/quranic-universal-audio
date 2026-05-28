<script lang="ts">
    /**
     * Owner-only popover on the current-reviewer chip in the General drawer.
     *
     * Three modes:
     *   - ``menu``   — initial: choose Change or Remove
     *   - ``change`` — HF login search (debounced lookup) + reason + Reassign
     *   - ``remove`` — reason + Force-release
     *
     * Toggle behaviour mirrors ``RolePicker.svelte``: click-outside (capture-
     * phase document listener) + Escape close. The popover positions itself
     * absolute-below the trigger; the parent owns the trigger button + the
     * ``.rp-wrap``-style relative container.
     *
     * Mounted only when ``$isOwner`` (the parent gates the trigger). Each
     * mode keeps its own scratch state so backing out of one mode doesn't
     * leak input into the other.
     */
    import { onMount, onDestroy } from 'svelte';

    import {
        forceReleaseClaim,
        lookupUser,
        reassignClaim,
        type UserCard,
    } from '../../../../../lib/api/admin-reviews';

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
    let loginInput = $state('');
    let resolved = $state<UserCard | null>(null);
    let lookupErr = $state<string | null>(null);
    let lookingUp = $state(false);
    let changeReason = $state('');
    let changeErr = $state<string | null>(null);
    let reassigning = $state(false);

    // Debounced lookup — 300ms is the sweet spot per the existing
    // SearchInput pattern (cheap HF round-trip, but not while still typing).
    let debounceId: ReturnType<typeof setTimeout> | null = null;
    let lookupAC: AbortController | null = null;

    function scheduleLookup(): void {
        if (debounceId !== null) {
            clearTimeout(debounceId);
            debounceId = null;
        }
        lookupAC?.abort();
        lookupAC = null;
        const q = loginInput.trim();
        // Clear stale result the moment the input changes so the user never
        // sees a card that doesn't match what they typed.
        resolved = null;
        lookupErr = null;
        if (q.length === 0) {
            lookingUp = false;
            return;
        }
        lookingUp = true;
        debounceId = setTimeout(() => {
            debounceId = null;
            const ac = new AbortController();
            lookupAC = ac;
            lookupUser(q, ac.signal)
                .then((card) => {
                    if (ac.signal.aborted) return;
                    resolved = card;
                    lookupErr = card === null ? 'Not a known HF user' : null;
                })
                .catch((e: unknown) => {
                    if (ac.signal.aborted) return;
                    lookupErr = (e as Error).message ?? 'Lookup failed';
                })
                .finally(() => {
                    if (!ac.signal.aborted) lookingUp = false;
                });
        }, 300);
    }

    const isSelfReassign = $derived(
        resolved !== null
        && currentLogin !== null
        && resolved.login.toLowerCase() === currentLogin.toLowerCase(),
    );
    const canReassign = $derived(
        resolved !== null
        && !isSelfReassign
        && changeReason.trim().length >= 10
        && !reassigning,
    );

    async function confirmReassign(): Promise<void> {
        if (!canReassign || !resolved) return;
        reassigning = true;
        changeErr = null;
        try {
            await reassignClaim(slug, resolved.login, changeReason.trim());
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

    const canRemove = $derived(removeReason.trim().length >= 10 && !removing);

    async function confirmRemove(): Promise<void> {
        if (!canRemove) return;
        removing = true;
        removeErr = null;
        try {
            await forceReleaseClaim(slug, removeReason.trim());
            onaction?.();
            onclose();
        } catch (e) {
            removeErr = (e as Error).message ?? 'Remove failed';
        } finally {
            removing = false;
        }
    }

    // ---- Mode switching ----
    function backToMenu(): void {
        // Don't wipe inputs — let the user back-and-forth without retyping.
        // (The popover unmount on success / dismiss is what resets them.)
        mode = 'menu';
        changeErr = null;
        removeErr = null;
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
        if (debounceId !== null) clearTimeout(debounceId);
        lookupAC?.abort();
    });

    function avatarInitials(login: string): string {
        const trimmed = login.trim();
        if (!trimmed) return '?';
        const chars = trimmed.replace(/[^a-z0-9]/gi, '').slice(0, 2).toUpperCase();
        return chars || trimmed.slice(0, 2).toUpperCase();
    }
</script>

<div class="popover" bind:this={rootEl} role="dialog" aria-label="Reassign or remove reviewer">
    {#if mode === 'menu'}
        <div class="menu">
            <button class="menu-item change" type="button" onclick={() => (mode = 'change')}>
                <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true">
                    <path d="M4 4 L12 4 M4 8 L10 8 M4 12 L8 12" />
                    <path d="M11 11 L14 14 M14 11 L11 14" />
                </svg>
                <div class="menu-text">
                    <div class="menu-title">Change reviewer</div>
                    <div class="menu-sub">Hand off to a different HF user</div>
                </div>
            </button>
            <button class="menu-item remove" type="button" onclick={() => (mode = 'remove')}>
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

            <label class="field">
                <span>HF login</span>
                <div class="search">
                    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true">
                        <circle cx="7" cy="7" r="5" /><line x1="11" y1="11" x2="14.5" y2="14.5" />
                    </svg>
                    <input
                        type="text"
                        bind:value={loginInput}
                        oninput={scheduleLookup}
                        placeholder="e.g. ahmed-bahy"
                        disabled={reassigning}
                        autocomplete="off"
                        spellcheck="false"
                    />
                </div>
            </label>

            {#if lookingUp}
                <div class="status muted">Looking up…</div>
            {:else if resolved}
                <div class="user-card" class:self={isSelfReassign}>
                    {#if resolved.avatar_url}
                        <img class="ucard-avatar" src={resolved.avatar_url} alt="" />
                    {:else}
                        <span class="ucard-avatar fallback">{avatarInitials(resolved.login)}</span>
                    {/if}
                    <div class="ucard-meta">
                        <div class="ucard-login">{resolved.login}</div>
                        {#if resolved.fullname}
                            <div class="ucard-fullname">{resolved.fullname}</div>
                        {/if}
                    </div>
                    {#if isSelfReassign}
                        <span class="self-pill" title="This is the current reviewer">current</span>
                    {/if}
                </div>
            {:else if lookupErr}
                <div class="status error" role="alert">{lookupErr}</div>
            {/if}

            <label class="field">
                <span>Reason</span>
                <textarea
                    bind:value={changeReason}
                    placeholder="Why is the claim being reassigned? (≥10 chars)"
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
                    title={isSelfReassign ? 'Already the current reviewer' : ''}
                >{reassigning ? 'Reassigning…' : 'Reassign'}</button>
                <button class="btn-cancel" type="button" onclick={onclose} disabled={reassigning}>
                    Cancel
                </button>
            </div>
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
                <span>Reason</span>
                <textarea
                    bind:value={removeReason}
                    placeholder="Why is the claim being removed? (≥10 chars)"
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
    /* Absolute-below the trigger; matches RolePicker chrome (canvas-inset
     * bg, quiet border, drop shadow). The parent provides the .rp-wrap-style
     * relative container so this positions naturally. */
    .popover {
        position: absolute;
        top: calc(100% + 6px);
        left: 0;
        z-index: 50;
        min-width: 280px;
        max-width: 340px;
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

    /* ---- resolved user card ---- */
    .user-card {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        padding: var(--s-2);
        background: var(--panel);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-1);
    }
    .user-card.self { border-color: var(--accent-tint); }
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
    .ucard-fullname { color: var(--text-muted); font-size: var(--fs-meta); }
    .self-pill {
        font-size: 10px;
        font-family: var(--font-mono);
        color: var(--accent-strong);
        background: var(--accent-tint-soft);
        border-radius: 999px;
        padding: 1px 6px;
        flex-shrink: 0;
    }

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
