<script lang="ts">
    /** Users compartment: fetches the list once, renders the people/traffic
     * ribbon + toolbar + master table, and orchestrates the detail drawer. */
    import {
        fetchAdminUsers,
        fetchVisitorStats,
        setUserRole,
    } from '../../../../lib/api/admin-users';
    import {
        currentUser,
        isOwner,
        loadCurrentUser,
    } from '../../../../lib/stores/current-user';
    import type {
        AdminUserRow,
        AdminUsersResponse,
        AdminVisitorStats,
    } from '../../../../lib/types/generated/schemas';
    import type { UsersSortKey } from '../../stores/admin-dashboard.svelte';
    import UserDetailDrawer from './UserDetailDrawer.svelte';
    import UsersTable from './UsersTable.svelte';

    type RoleFilter = 'all' | 'owner' | 'maintainer' | 'contributor';
    type AssignableRole = 'contributor' | 'maintainer' | 'owner';

    let resp = $state<AdminUsersResponse | null>(null);
    let visitor = $state<AdminVisitorStats | null>(null);
    let loading = $state(true);
    let error = $state<string | null>(null);

    let search = $state('');
    let roleFilter = $state<RoleFilter>('all');
    let selectedId = $state<string | null>(null);
    let sortKey = $state<UsersSortKey>('reviews');
    let sortDir = $state<'asc' | 'desc'>('desc');

    // Inline role editing (owner only).
    let roleBusyId = $state<string | null>(null);
    let roleError = $state<string | null>(null);

    async function changeRole(hfUserId: string, role: AssignableRole): Promise<void> {
        const users = resp?.users;
        if (!users) return;
        const idx = users.findIndex((u) => u.hf_user_id === hfUserId);
        const target = users[idx];
        if (!target) return;
        const prev = target.role;
        if (prev === role) return;
        const login = target.login ?? null;

        target.role = role; // optimistic
        roleBusyId = hfUserId;
        roleError = null;
        try {
            await setUserRole(hfUserId, role, login);
            // Refresh our own session if we just changed ourselves (owner UI gating).
            if (hfUserId === $currentUser.hf_user_id) await loadCurrentUser();
            // Reconcile cascaded/derived fields (counts, active_claim) authoritatively.
            resp = await fetchAdminUsers();
        } catch (e) {
            target.role = prev; // revert
            roleError = (e as Error).message ?? 'Failed to change role';
        } finally {
            roleBusyId = null;
        }
    }

    function handleSort(key: UsersSortKey): void {
        if (sortKey === key) {
            sortDir = sortDir === 'asc' ? 'desc' : 'asc';
        } else {
            sortKey = key;
            sortDir = 'desc'; // new column starts "most interesting first"
        }
    }

    const ROLE_RANK: Record<string, number> = { owner: 3, maintainer: 2, contributor: 1 };

    function dateNum(iso?: string | null): number {
        if (!iso) return -Infinity;
        const t = Date.parse(iso);
        return Number.isNaN(t) ? -Infinity : t;
    }
    function claimVal(r: AdminUserRow): number {
        if (!r.active_claim) return 0;
        return r.active_claim.marked_ready ? 2 : 1;
    }
    function compareRows(a: AdminUserRow, b: AdminUserRow, key: UsersSortKey): number {
        switch (key) {
            case 'role':
                return (ROLE_RANK[roleOf(a)] ?? 0) - (ROLE_RANK[roleOf(b)] ?? 0);
            case 'requests':
                return (a.requests ?? 0) - (b.requests ?? 0);
            case 'reviews':
                return (a.reviews ?? 0) - (b.reviews ?? 0);
            case 'active_claim':
                return claimVal(a) - claimVal(b);
            case 'joined':
                return dateNum(a.joined) - dateNum(b.joined);
            case 'last_activity':
                return dateNum(a.last_activity) - dateNum(b.last_activity);
            default:
                return 0;
        }
    }

    $effect(() => {
        const ac = new AbortController();
        loading = true;
        error = null;
        Promise.all([
            fetchAdminUsers(ac.signal),
            fetchVisitorStats(ac.signal).catch(() => null),
        ])
            .then(([r, v]) => {
                if (ac.signal.aborted) return;
                resp = r;
                visitor = v;
                loading = false;
            })
            .catch((e) => {
                if (ac.signal.aborted) return;
                error = (e as Error).message ?? 'Failed to load users';
                loading = false;
            });
        return () => ac.abort();
    });

    const rows = $derived(resp?.users ?? []);
    const roleOf = (r: { role?: string | null }) => r.role ?? 'contributor';

    const counts = $derived({
        all: rows.length,
        owner: rows.filter((r) => roleOf(r) === 'owner').length,
        maintainer: rows.filter((r) => roleOf(r) === 'maintainer').length,
        contributor: rows.filter((r) => roleOf(r) === 'contributor').length,
    });

    const filtered = $derived.by(() => {
        let out = rows;
        if (roleFilter !== 'all') out = out.filter((r) => roleOf(r) === roleFilter);
        const q = search.trim().toLowerCase();
        if (q) {
            out = out.filter(
                (r) =>
                    (r.login ?? '').toLowerCase().includes(q) ||
                    r.hf_user_id.toLowerCase().includes(q),
            );
        }
        const dir = sortDir === 'asc' ? 1 : -1;
        return [...out].sort((a, b) => {
            const c = compareRows(a, b, sortKey);
            if (c !== 0) return c * dir;
            // stable tiebreak: login asc
            return (a.login ?? a.hf_user_id).localeCompare(b.login ?? b.hf_user_id);
        });
    });

    const today = $derived(visitor?.today ?? null);
    const selectedRow = $derived(rows.find((r) => r.hf_user_id === selectedId) ?? null);
</script>

<div class="users">
    {#if loading}
        <div class="state">Loading…</div>
    {:else if error}
        <div class="state error">{error}</div>
    {:else}
        <div class="users-summary">
            <div class="sum-group">
                <span class="sum-label">People</span>
                <span class="sum-item"><span class="n">{resp?.summary?.registered ?? 0}</span><span class="t">registered</span></span>
                <span class="sum-item"><span class="n">{resp?.summary?.active_this_week ?? 0}</span><span class="t">active this week</span></span>
            </div>
            {#if today}
                <span class="sum-sep"></span>
                <div class="sum-group">
                    <span class="sum-label">Traffic · today</span>
                    <span class="sum-item"><span class="n">{today.signed_in_hits ?? 0}</span><span class="t">signed-in</span></span>
                    <span class="sum-item"><span class="n">{today.anon_hits ?? 0}</span><span class="t">anonymous</span></span>
                    <span class="sum-item"><span class="n approx">~{today.unique_anon ?? 0}</span><span class="t">unique visitors</span></span>
                </div>
            {/if}
        </div>

        <div class="users-toolbar">
            <span class="search">
                <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true">
                    <circle cx="7" cy="7" r="5" /><line x1="11" y1="11" x2="14.5" y2="14.5" />
                </svg>
                <input type="text" placeholder="Search login or HF id…" bind:value={search} />
            </span>
            <div class="role-filters">
                <button class="chip" class:active={roleFilter === 'all'} onclick={() => (roleFilter = 'all')}>All <span class="c-count">{counts.all}</span></button>
                <button class="chip" class:active={roleFilter === 'owner'} class:empty={!counts.owner} onclick={() => (roleFilter = 'owner')}>Owners <span class="c-count">{counts.owner}</span></button>
                <button class="chip" class:active={roleFilter === 'maintainer'} class:empty={!counts.maintainer} onclick={() => (roleFilter = 'maintainer')}>Maintainers <span class="c-count">{counts.maintainer}</span></button>
                <button class="chip" class:active={roleFilter === 'contributor'} class:empty={!counts.contributor} onclick={() => (roleFilter = 'contributor')}>Contributors <span class="c-count">{counts.contributor}</span></button>
            </div>
        </div>

        {#if roleError}
            <div class="role-error" role="alert">
                <span>{roleError}</span>
                <button type="button" aria-label="Dismiss" onclick={() => (roleError = null)}>✕</button>
            </div>
        {/if}

        {#if filtered.length === 0}
            <div class="state empty">
                <div class="glyph">⌕</div>
                <h4>No users match</h4>
                <p>Clear the search or pick a different role.</p>
            </div>
        {:else}
            <UsersTable
                rows={filtered}
                {selectedId}
                {sortKey}
                {sortDir}
                onselect={(id) => (selectedId = id)}
                onsort={handleSort}
                canEditRoles={$isOwner}
                {roleBusyId}
                onrolechange={changeRole}
            />
        {/if}

        {#if selectedId}
            <div
                class="drawer-scrim"
                role="presentation"
                onclick={() => (selectedId = null)}
            ></div>
            <UserDetailDrawer
                hfUserId={selectedId}
                onclose={() => (selectedId = null)}
                canEditRole={$isOwner}
                roleBusy={roleBusyId === selectedId}
                roleOverride={selectedRow?.role}
                onrolechange={(r) => selectedId && changeRole(selectedId, r)}
            />
        {/if}
    {/if}
</div>

<style>
    .users { position: relative; display: flex; flex-direction: column; height: 100%; }

    .state { padding: var(--s-12) 0; text-align: center; color: var(--text-muted); font-size: var(--fs-meta); }
    .state.error { color: var(--state-error-fg); }
    .state.empty { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--s-2); }
    .state.empty .glyph { font-size: 26px; opacity: 0.5; }
    .state.empty h4 { margin: 0; font-size: var(--fs-row); font-weight: 500; color: var(--text-secondary); }
    .state.empty p { margin: 0; font-size: var(--fs-meta); color: var(--text-faint); }

    .role-error {
        display: flex; align-items: center; justify-content: space-between; gap: var(--s-3);
        margin: var(--s-3) var(--s-5) 0;
        padding: var(--s-2) var(--s-3);
        background: var(--state-error-bg, oklch(0.5 0.16 25 / 0.14));
        border: 1px solid var(--state-error-fg);
        border-radius: var(--r-2);
        color: var(--state-error-fg);
        font-size: var(--fs-meta);
    }
    .role-error button {
        background: transparent; border: 0; color: inherit; cursor: pointer;
        font-size: 12px; line-height: 1; padding: 2px 4px;
    }

    .users-summary {
        display: flex; align-items: center; gap: var(--s-5); flex-wrap: wrap;
        padding: var(--s-3) var(--s-5);
        background: var(--panel);
        border-bottom: 1px solid var(--border-quiet);
        flex-shrink: 0;
    }
    .sum-group { display: inline-flex; align-items: baseline; gap: var(--s-4); }
    .sum-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-faint); }
    .sum-item { display: inline-flex; align-items: baseline; gap: 5px; }
    .sum-item .n { font-family: var(--font-mono); font-variant-numeric: tabular-nums; color: var(--text-primary); font-size: 15px; line-height: 1; }
    .sum-item .n.approx { color: var(--text-secondary); }
    .sum-item .t { font-size: var(--fs-meta); color: var(--text-muted); }
    .sum-sep { width: 1px; align-self: stretch; background: var(--border-quiet); margin: 2px 0; }

    .users-toolbar {
        display: flex; align-items: center; gap: var(--s-4);
        padding: var(--s-4) var(--s-5);
        border-bottom: 1px solid var(--border-quiet);
        flex-shrink: 0;
    }
    .search {
        display: inline-flex; align-items: center; gap: var(--s-2);
        height: 32px; padding: 0 var(--s-3); min-width: 240px;
        background: var(--canvas-inset); border: 1px solid var(--border-quiet);
        border-radius: var(--r-2); color: var(--text-muted); font-size: var(--fs-meta);
    }
    .search:focus-within { border-color: var(--accent); }
    .search svg { width: 14px; height: 14px; flex-shrink: 0; }
    .search input { flex: 1; background: transparent; border: 0; outline: none; color: var(--text-primary); font-size: var(--fs-body); }
    .search input::placeholder { color: var(--text-faint); }

    .role-filters { display: inline-flex; gap: var(--s-2); }
    .chip {
        display: inline-flex; align-items: center; gap: var(--s-2);
        height: 28px; padding: 0 var(--s-3);
        background: transparent; border: 1px solid var(--border-quiet);
        border-radius: 999px; color: var(--text-secondary); font-size: var(--fs-meta);
        cursor: pointer;
        transition: border-color var(--t-fast), color var(--t-fast), background var(--t-fast);
    }
    .chip:hover { border-color: var(--border-strong); color: var(--text-primary); }
    .chip .c-count { font-family: var(--font-mono); font-size: 10.5px; font-variant-numeric: tabular-nums; color: var(--text-faint); }
    .chip.active { background: var(--accent-tint); border-color: var(--accent); color: var(--accent); }
    .chip.active .c-count { color: var(--accent); }
    .chip.empty { opacity: 0.45; }

    .drawer-scrim { position: absolute; inset: 0; background: oklch(0.06 0.005 268 / 0.45); z-index: 4; }
</style>
