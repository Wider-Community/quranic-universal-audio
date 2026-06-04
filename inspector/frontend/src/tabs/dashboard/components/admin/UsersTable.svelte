<script lang="ts">
    import Avatar from '../../../../lib/components/Avatar.svelte';
    import RolePicker from '../../../../lib/components/RolePicker.svelte';
    import type { AdminUserRow } from '../../../../lib/types/generated/schemas';
    import { compactAgo, daysSince, fmtDate } from '../../../../lib/utils/admin-format';
    import type { UsersSortKey as SortKey } from '../../stores/admin-dashboard.svelte';

    type AssignableRole = 'contributor' | 'maintainer' | 'owner';

    interface Props {
        rows: AdminUserRow[];
        selectedId?: string | null;
        sortKey: SortKey;
        sortDir: 'asc' | 'desc';
        onselect: (_hfUserId: string) => void;
        onsort: (_key: SortKey) => void;
        /** Owners may edit roles inline; others see a static pill. */
        canEditRoles?: boolean;
        /** hf_user_id whose role change is in flight (disables its picker). */
        roleBusyId?: string | null;
        onrolechange?: (_hfUserId: string, _role: AssignableRole) => void;
    }
    let {
        rows,
        selectedId = null,
        sortKey,
        sortDir,
        onselect,
        onsort,
        canEditRoles = false,
        roleBusyId = null,
        onrolechange = () => {},
    }: Props = $props();

    const STALL_DAYS = 7;

    const COLUMNS: { key: SortKey; label: string; num?: boolean }[] = [
        { key: 'role', label: 'Role' },
        { key: 'joined', label: 'Joined' },
        { key: 'last_activity', label: 'Last activity' },
        { key: 'requests', label: 'Requests', num: true },
        { key: 'reviews', label: 'Reviews', num: true },
        { key: 'active_claim', label: 'Active claim' },
    ];
    const ariaSort = (k: SortKey) =>
        sortKey === k ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none';

    function isStalled(row: AdminUserRow): boolean {
        if (!row.active_claim) return false;
        const d = daysSince(row.last_activity);
        return d != null && d >= STALL_DAYS;
    }
</script>

<div class="users-scroll">
    <table class="users-table">
        <thead>
            <tr>
                <th>User</th>
                {#each COLUMNS as col (col.key)}
                    <th class:num={col.num} aria-sort={ariaSort(col.key)}>
                        <button
                            class="th-sort"
                            class:active={sortKey === col.key}
                            type="button"
                            onclick={() => onsort(col.key)}
                        >
                            {col.label}
                            <span class="sort" aria-hidden="true"
                                >{sortKey === col.key ? (sortDir === 'asc' ? '▲' : '▼') : ''}</span
                            >
                        </button>
                    </th>
                {/each}
            </tr>
        </thead>
        <tbody>
            {#each rows as row (row.hf_user_id)}
                <tr
                    class:selected={row.hf_user_id === selectedId}
                    onclick={() => onselect(row.hf_user_id)}
                >
                    <td>
                        <div class="u-cell">
                            <Avatar login={row.login} role={row.role} />
                            <span class="u-names">
                                <span class="u-login">@{row.login ?? row.hf_user_id}</span>
                                <span class="u-id">{row.hf_user_id}</span>
                            </span>
                        </div>
                    </td>
                    <td onclick={(e) => { if (canEditRoles) e.stopPropagation(); }}>
                        <RolePicker
                            role={row.role ?? 'contributor'}
                            editable={canEditRoles}
                            busy={roleBusyId === row.hf_user_id}
                            onchange={(r) => onrolechange(row.hf_user_id, r)}
                        />
                    </td>
                    <td class="ago">{fmtDate(row.joined)}</td>
                    <td>
                        <span class="ago" class:stale={isStalled(row)}>{compactAgo(row.last_activity)}</span>
                    </td>
                    <td class="num" class:zero={!row.requests}>{row.requests ?? 0}</td>
                    <td class="num" class:zero={!row.reviews}>{row.reviews ?? 0}</td>
                    <td>
                        {#if row.active_claim}
                            <span class="claim-slug">{row.active_claim.slug}</span>
                            {#if row.active_claim.marked_ready}
                                <span class="pill ready">Marked ready</span>
                            {:else}
                                <span class="pill under-review">Under review</span>
                            {/if}
                        {:else}
                            <span class="dash">—</span>
                        {/if}
                    </td>
                </tr>
            {/each}
        </tbody>
    </table>
</div>

<style>
    .users-scroll { flex: 1; min-height: 0; overflow: auto; }
    .users-table { width: 100%; border-collapse: collapse; font-size: var(--fs-meta); }
    .users-table thead th {
        position: sticky; top: 0; z-index: 1;
        text-align: left; font-weight: 500;
        color: var(--text-muted);
        text-transform: uppercase; letter-spacing: 0.08em;
        font-size: 10.5px;
        padding: var(--s-3) var(--s-4);
        background: var(--panel);
        border-bottom: 1px solid var(--border-quiet);
        white-space: nowrap;
    }
    .users-table thead th.num, .users-table td.num { text-align: right; font-variant-numeric: tabular-nums; }
    .th-sort {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        width: 100%;
        background: transparent;
        border: 0;
        padding: 0;
        margin: 0;
        font: inherit;
        color: inherit;
        letter-spacing: inherit;
        text-transform: inherit;
        cursor: pointer;
        transition: color var(--t-fast);
    }
    .th-sort:hover { color: var(--text-secondary); }
    .th-sort.active { color: var(--text-primary); }
    .users-table thead th.num .th-sort { justify-content: flex-end; }
    .th-sort .sort { color: var(--accent); font-size: 9px; min-width: 8px; }
    .users-table tbody td {
        padding: var(--s-3) var(--s-4);
        color: var(--text-secondary);
        border-bottom: 1px solid var(--border-quiet);
        vertical-align: middle;
        white-space: nowrap;
    }
    .users-table tbody tr { cursor: pointer; transition: background var(--t-fast); }
    .users-table tbody tr:hover td { background: var(--panel); }
    .users-table tbody tr.selected td { background: var(--accent-tint-soft); }
    .users-table td.num { font-family: var(--font-mono); color: var(--text-primary); }
    .users-table td.num.zero { color: var(--text-faint); }

    .u-cell { display: flex; align-items: center; gap: var(--s-3); }
    .u-names { display: flex; flex-direction: column; min-width: 0; }
    .u-login { color: var(--text-primary); font-size: var(--fs-body); line-height: 1.2; }
    .u-id { color: var(--text-faint); font-family: var(--font-mono); font-size: 10px; line-height: 1.3; }

    .ago { color: var(--text-muted); font-variant-numeric: tabular-nums; }
    .ago.stale { color: var(--state-error-fg); }
    .ago.stale::after { content: ' ⚠'; font-size: 10px; }

    .pill {
        display: inline-flex; align-items: center; gap: 6px;
        padding: 2px 8px; border-radius: 999px;
        font-size: 11px; font-weight: 500;
    }
    .pill::before { content: ''; width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
    .pill.under-review { color: var(--state-under-review-fg); background: var(--state-under-review-bg); }
    .pill.ready { color: var(--state-published-fg); background: var(--state-published-bg); }
    .claim-slug { font-family: var(--font-mono); color: var(--text-secondary); font-size: 11px; }
    .dash { color: var(--text-faint); }
</style>
