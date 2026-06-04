<script lang="ts">
    /** Per-user detail, lazy-fetched on open. Slides over the table; the
     * caller renders the scrim + handles close. */
    import { fetchAdminUser } from '../../../../lib/api/admin-users';
    import Avatar from '../../../../lib/components/Avatar.svelte';
    import RolePicker from '../../../../lib/components/RolePicker.svelte';
    import Timeline from '../../../../lib/components/Timeline.svelte';
    import type { AdminUserDetail } from '../../../../lib/types/generated/schemas';
    import { compactAgo, fmtDate, fmtDuration } from '../../../../lib/utils/admin-format';

    type AssignableRole = 'contributor' | 'maintainer' | 'owner';

    interface Props {
        hfUserId: string;
        onclose: () => void;
        /** Owner-only: enable the header role picker. */
        canEditRole?: boolean;
        /** True while this user's role change is in flight. */
        roleBusy?: boolean;
        /** Live role from the parent's list row — reflects optimistic updates
         * and reverts without the drawer keeping its own copy. */
        roleOverride?: string | null;
        onrolechange?: (_role: AssignableRole) => void;
    }
    let {
        hfUserId,
        onclose,
        canEditRole = false,
        roleBusy = false,
        roleOverride = null,
        onrolechange = () => {},
    }: Props = $props();

    let detail = $state<AdminUserDetail | null>(null);
    let loading = $state(true);
    let error = $state<string | null>(null);

    /** Prefer the parent's live row role (optimistic) over the fetched snapshot. */
    const shownRole = $derived(roleOverride ?? detail?.role ?? 'contributor');

    $effect(() => {
        const id = hfUserId;
        const ac = new AbortController();
        loading = true;
        error = null;
        detail = null;
        fetchAdminUser(id, ac.signal)
            .then((d) => {
                if (ac.signal.aborted) return;
                detail = d;
                loading = false;
            })
            .catch((e) => {
                if (ac.signal.aborted) return;
                error = (e as Error).message ?? 'Failed to load user';
                loading = false;
            });
        return () => ac.abort();
    });

    function claimDot(outcome: string): string {
        if (outcome.includes('open')) return 'accent';
        if (outcome.includes('published')) return 'green';
        if (outcome.includes('reassigned') || outcome.includes('force')) return 'violet';
        return 'amber';
    }
    function eventDot(event: string): string {
        if (event.includes('published')) return 'green';
        if (event.includes('marked_ready') || event.includes('claimed')) return 'accent';
        if (event.includes('reassigned') || event.includes('force') || event.includes('unlocked'))
            return 'violet';
        return '';
    }
    function humanizeEvent(event: string): string {
        return event.replace(/^reciter\.|^claim\.|^admin\./, '').replace(/_/g, ' ');
    }

    const roleItems = $derived(
        (detail?.role_history ?? []).flatMap((r) => {
            const out = [
                {
                    dot: 'violet',
                    text: `Granted ${r.role}`,
                    by: r.granted_by ? `by @${r.granted_by}` : null,
                    when: fmtDate(r.granted_at),
                },
            ];
            if (r.revoked_at) {
                out.push({
                    dot: 'amber',
                    text: `Revoked ${r.role}`,
                    by: r.revoked_by ? `by @${r.revoked_by}` : null,
                    when: fmtDate(r.revoked_at),
                });
            }
            return out;
        }),
    );

    const claimItems = $derived(
        (detail?.claims_history ?? []).map((c) => ({
            dot: claimDot(c.outcome ?? ''),
            slug: c.slug,
            text: `— ${c.outcome ?? 'closed'}`,
            when: compactAgo(c.released_at ?? c.claimed_at) + ' ago',
        })),
    );

    const requestItems = $derived(
        (detail?.requests_history ?? []).map((r) => ({
            dot: '',
            slug: r.slug ?? null,
            text: r.kind.replace(/_/g, ' '),
            tag: { label: r.status, kind: r.status },
            when: compactAgo(r.submitted_at) + ' ago',
        })),
    );

    const activityItems = $derived(
        (detail?.recent_activity ?? []).map((a) => ({
            dot: eventDot(a.event),
            slug: a.slug ?? null,
            text: humanizeEvent(a.event),
            when: compactAgo(a.ts) + ' ago',
        })),
    );

    const requestsSummary = $derived.by(() => {
        const by = detail?.stats?.requests_by_status ?? {};
        const parts = Object.entries(by).map(([k, v]) => `${v} ${k}`);
        return parts.length ? parts.join(' · ') : 'none';
    });
</script>

<aside class="drawer" aria-label="User detail">
    {#if loading}
        <div class="state">Loading…</div>
    {:else if error}
        <div class="state error">{error}</div>
    {:else if detail}
        <header class="drawer-head">
            <button class="drawer-back" type="button" aria-label="Back to list" onclick={onclose}>‹</button>
            <div class="drawer-id">
                <Avatar login={detail.login} role={shownRole} size={40} />
                <div class="who">
                    <div class="top">
                        <span class="login">@{detail.login ?? 'unknown'}</span>
                        <RolePicker
                            role={shownRole}
                            editable={canEditRole}
                            busy={roleBusy}
                            onchange={(r) => onrolechange(r)}
                        />
                        {#if detail.login}
                            <a
                                class="hf-link"
                                href={`https://huggingface.co/${detail.login}`}
                                target="_blank"
                                rel="noopener"
                            >
                                huggingface.co/{detail.login}
                                <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.3" aria-hidden="true">
                                    <path d="M4 2h6v6" /><path d="M10 2 3 9" /><path d="M9 7v3H2V3h3" />
                                </svg>
                            </a>
                        {/if}
                    </div>
                    <div class="meta">
                        <span class="hid">{detail.hf_user_id}</span>
                        · joined {fmtDate(detail.joined)} · last active {compactAgo(detail.last_activity)} ago
                    </div>
                </div>
            </div>
        </header>

        <div class="drawer-scroll">
            <div class="stat-strip">
                <div class="stat"><div class="v">{detail.stats?.reviews ?? 0}</div><div class="k">Reviews</div><div class="sub">marked ready</div></div>
                <div class="stat"><div class="v">{detail.stats?.lifetime_claims ?? 0}</div><div class="k">Claims</div><div class="sub">lifetime</div></div>
                <div class="stat"><div class="v">{fmtDuration(detail.stats?.avg_turnaround_seconds)}</div><div class="k">Avg turnaround</div><div class="sub">claim → ready</div></div>
                <div class="stat"><div class="v">{detail.requests_history?.length ?? 0}</div><div class="k">Requests</div><div class="sub">{requestsSummary}</div></div>
            </div>

            {#if roleItems.length}
                <section class="d-section">
                    <h3>Role history</h3>
                    <Timeline items={roleItems} />
                </section>
            {/if}

            <section class="d-section">
                <h3>Claims <span class="n">{detail.stats?.lifetime_claims ?? 0}</span></h3>
                {#if claimItems.length}<Timeline items={claimItems} />{:else}<p class="none">No claims yet.</p>{/if}
            </section>

            <section class="d-section">
                <h3>Requests <span class="n">{detail.requests_history?.length ?? 0}</span></h3>
                {#if requestItems.length}<Timeline items={requestItems} />{:else}<p class="none">No requests.</p>{/if}
            </section>

            <section class="d-section">
                <h3>Recent activity</h3>
                {#if activityItems.length}<Timeline items={activityItems} />{:else}<p class="none">No activity.</p>{/if}
            </section>
        </div>
    {/if}
</aside>

<style>
    .drawer {
        position: absolute;
        top: 0; right: 0; bottom: 0;
        width: 62%;
        min-width: 520px;
        z-index: 5;
        background: var(--canvas);
        border-left: 1px solid var(--border-default);
        box-shadow: -24px 0 60px oklch(0 0 0 / 0.4);
        display: flex;
        flex-direction: column;
        animation: drawer-in var(--t-slow) var(--ease-out-expo);
    }
    @keyframes drawer-in {
        from { transform: translateX(24px); opacity: 0; }
        to { transform: none; opacity: 1; }
    }
    @media (prefers-reduced-motion: reduce) { .drawer { animation: none; } }

    .state { padding: var(--s-12); text-align: center; color: var(--text-muted); font-size: var(--fs-meta); }
    .state.error { color: var(--state-error-fg); }

    .drawer-head {
        display: flex; align-items: flex-start; gap: var(--s-3);
        padding: var(--s-4) var(--s-5);
        border-bottom: 1px solid var(--border-quiet);
        flex-shrink: 0;
    }
    .drawer-back {
        width: 30px; height: 30px;
        display: inline-flex; align-items: center; justify-content: center;
        color: var(--text-muted);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        background: transparent; cursor: pointer; flex-shrink: 0;
        transition: color var(--t-fast), border-color var(--t-fast);
    }
    .drawer-back:hover { color: var(--text-primary); border-color: var(--border-strong); }
    .drawer-id { display: flex; align-items: center; gap: var(--s-3); flex: 1; min-width: 0; }
    .who { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
    .who .top { display: flex; align-items: center; gap: var(--s-3); flex-wrap: wrap; }
    .who .login { font-size: var(--fs-h3); color: var(--text-primary); font-weight: 500; }
    .hf-link { display: inline-flex; align-items: center; gap: 4px; font-size: var(--fs-meta); color: var(--accent); text-decoration: none; }
    .hf-link:hover { color: var(--accent-strong); text-decoration: underline; text-underline-offset: 2px; }
    .hf-link svg { width: 11px; height: 11px; }
    .meta { font-size: var(--fs-meta); color: var(--text-muted); font-variant-numeric: tabular-nums; }
    .meta .hid { font-family: var(--font-mono); color: var(--text-faint); }

    .drawer-scroll { flex: 1; min-height: 0; overflow: auto; padding: var(--s-5); }

    .stat-strip { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--s-3); margin-bottom: var(--s-6); }
    .stat { padding: var(--s-3) var(--s-4); background: var(--panel); border: 1px solid var(--border-quiet); border-radius: var(--r-2); }
    .stat .v { font-family: var(--font-mono); font-size: 20px; font-variant-numeric: tabular-nums; color: var(--text-primary); line-height: 1.1; }
    .stat .k { margin-top: 4px; font-size: 10px; text-transform: uppercase; letter-spacing: 0.07em; color: var(--text-muted); }
    .stat .sub { margin-top: 3px; font-size: 10.5px; color: var(--text-faint); }

    .d-section { margin-bottom: var(--s-6); }
    .d-section > h3 {
        display: flex; align-items: baseline; gap: var(--s-2);
        margin: 0 0 var(--s-3);
        font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.08em;
        color: var(--text-muted); font-weight: 500;
    }
    .d-section > h3 .n { font-family: var(--font-mono); color: var(--text-faint); text-transform: none; letter-spacing: 0; }
    .none { margin: 0; color: var(--text-faint); font-size: var(--fs-meta); }
</style>
