<script lang="ts">
    /**
     * Permissions compartment (owner-only). Renders the capability matrix
     * grouped by category; each capability row has an On/Off toggle per tier
     * (anonymous / contributor / maintainer) plus a static always-on Owner
     * indicator. Toggling is optimistic with revert-on-error; the change is
     * audited server-side and takes effect on the affected user's next request.
     *
     * Mirrors UsersCompartment's fetch-on-activate + optimistic-mutate pattern.
     */
    import {
        fetchAdminPermissions,
        type PermissionTier,
        resetCapabilityGrant,
        setCapabilityGrant,
    } from '../../../../lib/api/admin-permissions';
    import Toggle from '../../../../lib/components/Toggle.svelte';
    import type {
        AdminCapabilityRow,
        AdminCapabilityTierState,
        AdminPermissionsResponse,
    } from '../../../../lib/types/generated/schemas';

    let resp = $state<AdminPermissionsResponse | null>(null);
    let loading = $state(true);
    let error = $state<string | null>(null);
    let busyKey = $state<string | null>(null);
    let toggleError = $state<string | null>(null);

    const TIERS: { key: PermissionTier; label: string }[] = [
        { key: 'anonymous', label: 'Anonymous' },
        { key: 'contributor', label: 'Contributor' },
        { key: 'maintainer', label: 'Maintainer' },
    ];

    function cellOf(cap: AdminCapabilityRow, tier: PermissionTier): AdminCapabilityTierState {
        return (cap[tier] as AdminCapabilityTierState) ?? { applicable: false, allowed: null };
    }

    async function toggle(
        cap: AdminCapabilityRow,
        tier: PermissionTier,
        next: boolean,
    ): Promise<void> {
        if (cap.owner_only_fixed) return;
        const cell = cellOf(cap, tier);
        if (!cell.applicable) return;
        const prev = cell.allowed ?? false;
        const prevDefault = cell.is_default ?? true;
        if (prev === next) return;

        cell.allowed = next; // optimistic
        cell.is_default = false;
        busyKey = `${cap.id}:${tier}`;
        toggleError = null;
        try {
            await setCapabilityGrant(cap.id, tier, next);
        } catch (e) {
            cell.allowed = prev; // revert
            cell.is_default = prevDefault;
            toggleError = (e as Error).message ?? 'Failed to change permission';
        } finally {
            busyKey = null;
        }
    }

    async function reset(cap: AdminCapabilityRow, tier: PermissionTier): Promise<void> {
        if (cap.owner_only_fixed) return;
        const cell = cellOf(cap, tier);
        if (!cell.applicable || cell.is_default) return;
        const prev = cell.allowed ?? false;
        busyKey = `${cap.id}:${tier}`;
        toggleError = null;
        try {
            await resetCapabilityGrant(cap.id, tier);
            // Re-fetch to pick up the authoritative default value.
            resp = await fetchAdminPermissions();
        } catch (e) {
            cell.allowed = prev;
            toggleError = (e as Error).message ?? 'Failed to reset permission';
        } finally {
            busyKey = null;
        }
    }

    $effect(() => {
        const ac = new AbortController();
        loading = true;
        error = null;
        fetchAdminPermissions(ac.signal)
            .then((r) => {
                if (ac.signal.aborted) return;
                resp = r;
                loading = false;
            })
            .catch((e) => {
                if (ac.signal.aborted) return;
                error = (e as Error).message ?? 'Failed to load permissions';
                loading = false;
            });
        return () => ac.abort();
    });

    const groups = $derived(resp?.groups ?? []);
</script>

<div class="perms">
    {#if loading}
        <div class="state">Loading…</div>
    {:else if error}
        <div class="state error">{error}</div>
    {:else}
        <div class="perms-intro">
            <p>
                Turn capabilities on or off per tier. <strong>Owners</strong> always have every
                capability. Changes apply immediately — a user gains or loses the ability on their
                next action.
            </p>
        </div>

        {#if toggleError}
            <div class="role-error" role="alert">
                <span>{toggleError}</span>
                <button type="button" aria-label="Dismiss" onclick={() => (toggleError = null)}>✕</button>
            </div>
        {/if}

        {#each groups as group (group.group)}
            <section class="grp">
                <h3 class="grp-title">{group.group}</h3>
                <table class="matrix">
                    <colgroup>
                        <col class="c-cap" />
                        <col class="c-tier" />
                        <col class="c-tier" />
                        <col class="c-tier" />
                        <col class="c-tier" />
                    </colgroup>
                    <thead>
                        <tr>
                            <th class="h-cap">Capability</th>
                            {#each TIERS as t (t.key)}
                                <th class="h-tier">{t.label}</th>
                            {/each}
                            <th class="h-tier">Owner</th>
                        </tr>
                    </thead>
                    <tbody>
                        {#each group.capabilities ?? [] as cap (cap.id)}
                            <tr class:fixed={cap.owner_only_fixed}>
                                <td class="cap">
                                    <span class="cap-label">{cap.label}</span>
                                    <span class="cap-desc">{cap.description}</span>
                                </td>
                                {#each TIERS as t (t.key)}
                                    {@const cell = cellOf(cap, t.key)}
                                    <td class="cell">
                                        {#if !cell.applicable}
                                            <Toggle
                                                na
                                                checked={false}
                                                title="Not applicable to {t.label.toLowerCase()} users"
                                            />
                                        {:else}
                                            <span
                                                class="cell-wrap"
                                                class:modified={!cell.is_default && !cap.owner_only_fixed}
                                            >
                                                <Toggle
                                                    checked={cell.allowed ?? false}
                                                    disabled={cap.owner_only_fixed}
                                                    busy={busyKey === `${cap.id}:${t.key}`}
                                                    label="{cap.label} for {t.label}"
                                                    title={cap.owner_only_fixed
                                                        ? 'Owner-only — cannot be changed'
                                                        : undefined}
                                                    onchange={(n) => toggle(cap, t.key, n)}
                                                />
                                                {#if !cell.is_default && !cap.owner_only_fixed}
                                                    <button
                                                        type="button"
                                                        class="reset"
                                                        title="Reset to default"
                                                        aria-label="Reset {cap.label} for {t.label} to default"
                                                        onclick={() => reset(cap, t.key)}>↺</button
                                                    >
                                                {/if}
                                            </span>
                                        {/if}
                                    </td>
                                {/each}
                                <td class="cell owner-cell">
                                    <span class="owner-on" title="Owners always have this">On</span>
                                </td>
                            </tr>
                        {/each}
                    </tbody>
                </table>
            </section>
        {/each}
    {/if}
</div>

<style>
    .perms {
        display: flex;
        flex-direction: column;
        height: 100%;
        overflow-y: auto;
        padding-bottom: var(--s-6);
    }
    .state {
        padding: var(--s-12) 0;
        text-align: center;
        color: var(--text-muted);
        font-size: var(--fs-meta);
    }
    .state.error {
        color: var(--state-error-fg);
    }

    .perms-intro {
        padding: var(--s-4) var(--s-5) var(--s-2);
    }
    .perms-intro p {
        margin: 0;
        font-size: var(--fs-meta);
        color: var(--text-muted);
        max-width: 70ch;
    }
    .perms-intro strong {
        color: var(--text-secondary);
        font-weight: 600;
    }

    .role-error {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--s-3);
        margin: var(--s-2) var(--s-5) 0;
        padding: var(--s-2) var(--s-3);
        background: var(--state-error-bg, oklch(0.5 0.16 25 / 0.14));
        border: 1px solid var(--state-error-fg);
        border-radius: var(--r-2);
        color: var(--state-error-fg);
        font-size: var(--fs-meta);
    }
    .role-error button {
        background: transparent;
        border: 0;
        color: inherit;
        cursor: pointer;
        font-size: 12px;
        line-height: 1;
        padding: 2px 4px;
    }

    .grp {
        padding: var(--s-4) var(--s-5) 0;
    }
    .grp-title {
        margin: 0 0 var(--s-2);
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--text-faint);
        font-weight: 600;
    }

    .matrix {
        width: 100%;
        table-layout: fixed;
        border-collapse: collapse;
    }
    .c-cap {
        width: auto;
    }
    .c-tier {
        width: 104px;
    }
    .matrix th,
    .matrix td {
        text-align: left;
        padding: var(--s-2) var(--s-2);
        border-bottom: 1px solid var(--border-quiet);
        vertical-align: middle;
    }
    .h-cap,
    .h-tier {
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--text-faint);
        font-weight: 500;
    }
    .h-tier {
        text-align: center;
    }
    .cell {
        text-align: center;
    }
    .cell-wrap {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        position: relative;
        padding: 2px 4px;
        border-radius: var(--r-2);
    }
    .cell-wrap.modified {
        background: var(--accent-tint);
    }
    .reset {
        background: transparent;
        border: 0;
        color: var(--text-faint);
        cursor: pointer;
        font-size: 12px;
        line-height: 1;
        padding: 0 2px;
    }
    .reset:hover {
        color: var(--accent);
    }
    .cap-label {
        display: block;
        font-size: var(--fs-body);
        color: var(--text-primary);
    }
    .cap-desc {
        display: block;
        font-size: var(--fs-meta);
        color: var(--text-muted);
        margin-top: 1px;
    }
    .owner-cell .owner-on {
        display: inline-flex;
        align-items: center;
        height: 18px;
        padding: 0 8px;
        font-size: 10px;
        letter-spacing: 0.04em;
        color: var(--accent);
        background: var(--accent-tint);
        border-radius: 999px;
        font-variant-caps: all-small-caps;
    }
    tr.fixed .cap-label::after {
        content: ' · owner-only';
        font-size: 10px;
        color: var(--text-faint);
        letter-spacing: 0.03em;
    }
</style>
