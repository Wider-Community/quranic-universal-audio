<script lang="ts">
    /**
     * Reviews Ops drawer.
     *
     * State-aware action list. The vocabulary reads from the current state:
     * Marked-ready gets Publish (deferred) + Send-back variants; Published
     * gets Unpublish / Move-to-* (all deferred); Under-review gets just
     * Force-release. Disabled actions render styled with a tooltip naming
     * the deferred-doc item that's blocking them.
     *
     * Confirms are inline — clicking an action enters its confirm mode with
     * a reason input + Confirm/Cancel, no modal-stacked-on-modal. Only one
     * action can be armed at a time.
     */
    import {
        fetchAdminReviewDetail,
        forceReleaseClaim,
        sendBackToUnderReview,
    } from '../../../../../lib/api/admin-reviews';
    import { refreshReciterTask } from '../../../../../lib/api/reciter-task';
    import { isOwner,loadCurrentUser } from '../../../../../lib/stores/current-user';
    import type { AdminReviewDetail } from '../../../../../lib/types/generated/schemas';
    import { loadCatalog } from '../../../stores/catalog-data';

    let {
        slug,
        onclose,
        onaction,
    }: {
        slug: string;
        onclose: () => void;
        /** Fired after a successful mutating action — caller refetches list. */
        onaction?: () => void;
    } = $props();

    let detail = $state<AdminReviewDetail | null>(null);
    let loading = $state(true);
    let error = $state<string | null>(null);

    // Action identity that lets the UI track which one is armed for confirm.
    type ActionKey =
        | 'force_release'
        | 'send_back_ur'
        | 'send_back_available';

    let armed = $state<ActionKey | null>(null);
    let reason = $state('');
    let actionError = $state<string | null>(null);
    let busy = $state(false);

    $effect(() => {
        const target = slug;
        const ac = new AbortController();
        loading = true;
        error = null;
        detail = null;
        armed = null;
        reason = '';
        actionError = null;
        fetchAdminReviewDetail(target, ac.signal)
            .then((d) => {
                if (ac.signal.aborted) return;
                if (d === null) {
                    error = 'unknown slug';
                } else {
                    detail = d;
                }
                loading = false;
            })
            .catch((e: unknown) => {
                if (ac.signal.aborted) return;
                error = (e as Error).message ?? 'Failed to load detail';
                loading = false;
            });
        return () => ac.abort();
    });

    const markedReady = $derived(!!detail?.current_claim?.marked_ready_at);
    const currentState = $derived(detail?.state ?? '');
    const isPublished = $derived(
        currentState === 'awaiting_timestamps' || currentState === 'released',
    );

    function arm(key: ActionKey): void {
        armed = key;
        reason = '';
        actionError = null;
    }
    function disarm(): void {
        if (busy) return;
        armed = null;
        reason = '';
        actionError = null;
    }

    async function confirmAction(): Promise<void> {
        const r = reason.trim();
        if (r.length < 4) {
            actionError = 'reason must be at least 4 characters';
            return;
        }
        if (armed === null) return;
        busy = true;
        actionError = null;
        try {
            switch (armed) {
                case 'force_release':
                case 'send_back_available':
                    await forceReleaseClaim(slug, r);
                    break;
                case 'send_back_ur':
                    await sendBackToUnderReview(slug, r);
                    break;
            }
            // Propagate the state change to every surface that might be
            // displaying this slug right now — the Segments tab's reciter-
            // task store keeps a 30 s poll cadence, so without this push the
            // footer + claim affordance stay stale until its next tick. The
            // catalog refetch flips the bucket-derived footer chip; the
            // /api/me refetch flips ``active_claim``.
            await Promise.allSettled([
                refreshReciterTask(slug),
                loadCurrentUser(),
                loadCatalog(true),
            ]);
            // Refetch the local detail so the drawer reflects the new state;
            // the caller also refetches its list.
            armed = null;
            reason = '';
            const fresh = await fetchAdminReviewDetail(slug);
            if (fresh !== null) detail = fresh;
            onaction?.();
        } catch (e) {
            actionError = (e as Error).message ?? 'Action failed';
        } finally {
            busy = false;
        }
    }

    // Disabled-action tooltips reference the deferred-doc item — see
    // docs/planning/reviews-tab-deferred.md.
    const DEFERRED = {
        publish: 'Pending publish endpoint — see reviews-tab-deferred.md item 1',
        unpublish: 'Pending unpublish endpoint — see reviews-tab-deferred.md item 2',
        unlock: 'Pending unlock-for-revision endpoint — see reviews-tab-deferred.md item 3',
        move_to_ur: 'Pending state-machine event design — see reviews-tab-deferred.md item 4',
        refresh: 'Pending refresh-timestamps handler + endpoint — see reviews-tab-deferred.md item 5',
    } as const;
</script>

<aside class="drawer" aria-label="Recitation ops">
    <header class="drawer-head">
        <div class="drawer-context">
            <div class="drawer-title">Ops</div>
            {#if detail}
                {#if detail.name_ar}
                    <div class="recitation-ar" dir="rtl">{detail.name_ar}</div>
                {/if}
                <div class="recitation-meta">
                    {detail.riwayah} · {detail.style} · {detail.channel} · {detail.state.replace(/_/g, ' ')}
                </div>
            {/if}
        </div>
        <button class="drawer-close" type="button" onclick={onclose} aria-label="Close">×</button>
    </header>

    <div class="drawer-body">
        {#if loading}
            <div class="state">Loading…</div>
        {:else if error}
            <div class="state error" role="alert">{error}</div>
        {:else if detail}

            <!-- AVAILABLE: no actions; admin claim assignment lives in Users tab. -->
            {#if currentState === 'awaiting_review'}
                <div class="empty-block">
                    No admin actions for recitations <em>Available for review</em>.
                    Claim assignment happens in the Users tab.
                </div>
            {/if}

            <!-- UNDER REVIEW (not marked-ready): force-release only.
                 Owner-only — maintainers see an explainer in lieu of an
                 actionable button. The General drawer's reviewer popover
                 is the canonical entry point for both Change and Remove. -->
            {#if currentState === 'under_review' && !markedReady}
                <section class="dsection">
                    <h3 class="dsection-head">State</h3>
                    {#if $isOwner}
                        <div class="ops-actions">
                            <button
                                class="ops-action danger"
                                type="button"
                                onclick={() => arm('force_release')}
                                disabled={busy}
                            >
                                <div>
                                    <span class="name">Force-release claim</span>
                                    <span class="hint">Closes the open claim; recitation returns to <em>Available for review</em>. Tip: the General drawer also lets you click the reviewer to Change or Remove inline.</span>
                                </div>
                                <span class="arrow">→</span>
                            </button>
                            {#if armed === 'force_release'}
                                {@render confirmSlot('Force-release', 'Force-release this claim?')}
                            {/if}
                        </div>
                    {:else}
                        <div class="empty-block">
                            No admin actions available — claim management is <em>owner-only</em>. Escalate to an owner to force-release or reassign.
                        </div>
                    {/if}
                </section>
            {/if}

            <!-- MARKED READY: publish (deferred) + two send-back paths. -->
            {#if currentState === 'under_review' && markedReady}
                <section class="dsection">
                    <h3 class="dsection-head">State</h3>
                    <div class="ops-actions">
                        <button
                            class="ops-action primary"
                            type="button"
                            disabled
                            title={DEFERRED.publish}
                        >
                            <div>
                                <span class="name">Publish</span>
                                <span class="hint">Moves to <em>Published</em>. Copies wip → published, enqueues timestamps refresh.</span>
                            </div>
                            <span class="arrow">→</span>
                        </button>
                        <button
                            class="ops-action"
                            type="button"
                            onclick={() => arm('send_back_ur')}
                            disabled={busy}
                        >
                            <div>
                                <span class="name">Send back to under review</span>
                                <span class="hint">Clears marked-ready; reviewer keeps the claim.</span>
                            </div>
                            <span class="arrow">→</span>
                        </button>
                        {#if armed === 'send_back_ur'}
                            {@render confirmSlot('Send back to UR', 'Clear marked-ready on this claim?')}
                        {/if}
                        <!-- Send-back-to-available calls force-release under
                             the hood — owner-only for the same reason. -->
                        {#if $isOwner}
                            <button
                                class="ops-action"
                                type="button"
                                onclick={() => arm('send_back_available')}
                                disabled={busy}
                            >
                                <div>
                                    <span class="name">Send back to available</span>
                                    <span class="hint">Release the claim and unmark ready; recitation returns to <em>Available for review</em>. <span class="owner-tag">owner-only</span></span>
                                </div>
                                <span class="arrow">→</span>
                            </button>
                            {#if armed === 'send_back_available'}
                                {@render confirmSlot('Send back to available', 'Force-release this claim and unmark ready?')}
                            {/if}
                        {/if}
                    </div>
                </section>
            {/if}

            <!-- PUBLISHED: all actions deferred. -->
            {#if isPublished}
                <section class="dsection">
                    <h3 class="dsection-head">State</h3>
                    <div class="ops-actions">
                        <button class="ops-action danger" type="button" disabled title={DEFERRED.unpublish}>
                            <div>
                                <span class="name">Unpublish</span>
                                <span class="hint">Moves back to <em>Available for review</em>. Drops from public catalog and dataset.</span>
                            </div>
                            <span class="arrow">→</span>
                        </button>
                        <button class="ops-action" type="button" disabled title={DEFERRED.move_to_ur}>
                            <div>
                                <span class="name">Move to under review</span>
                                <span class="hint">Reopens the prior reviewer's claim. (Pending state-machine event.)</span>
                            </div>
                            <span class="arrow">→</span>
                        </button>
                        <button class="ops-action" type="button" disabled title={DEFERRED.unlock}>
                            <div>
                                <span class="name">Move to available for review</span>
                                <span class="hint">Releases the claim and unlocks for revision (preserves prior reviewer).</span>
                            </div>
                            <span class="arrow">→</span>
                        </button>
                    </div>
                </section>
            {/if}

            <!-- JOBS — disabled in every state until the handler comes back. -->
            <section class="dsection">
                <h3 class="dsection-head">Jobs</h3>
                <div class="ops-actions">
                    <button class="ops-action" type="button" disabled title={DEFERRED.refresh}>
                        <div>
                            <span class="name">Refresh timestamps</span>
                            <span class="hint">Re-run MFA alignment. Useful when the aligner or phonemizer has been updated.</span>
                        </div>
                        <span class="arrow">→</span>
                    </button>
                </div>
            </section>
        {/if}
    </div>
</aside>

{#snippet confirmSlot(verb: string, question: string)}
    <div class="confirm-slot">
        <div class="confirm-q">{question}</div>
        <label class="reason">
            <span>Reason</span>
            <input
                type="text"
                bind:value={reason}
                placeholder="Why?"
                disabled={busy}
            />
        </label>
        {#if actionError}
            <div class="confirm-error" role="alert">{actionError}</div>
        {/if}
        <div class="confirm-actions">
            <button
                class="btn-confirm"
                type="button"
                onclick={confirmAction}
                disabled={busy}
            >{busy ? `${verb}…` : verb}</button>
            <button
                class="btn-cancel"
                type="button"
                onclick={disarm}
                disabled={busy}
            >Cancel</button>
        </div>
    </div>
{/snippet}

<style>
    .drawer {
        position: absolute;
        top: 0; right: 0; bottom: 0;
        width: 62%;
        max-width: 720px;
        min-width: 440px;
        background: var(--panel);
        border-left: 1px solid var(--border-quiet);
        z-index: 5;
        display: flex;
        flex-direction: column;
        overflow: hidden;
    }
    .drawer-head {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        padding: var(--s-4) var(--s-5);
        border-bottom: 1px solid var(--border-quiet);
        gap: var(--s-3);
    }
    .drawer-context { min-width: 0; flex: 1; }
    .drawer-title {
        font-size: 11px;
        font-family: var(--font-mono);
        color: var(--text-faint);
        letter-spacing: 0.06em;
        text-transform: uppercase;
        margin-bottom: var(--s-2);
    }
    .recitation-ar {
        font-size: 17px;
        color: var(--text-primary);
        unicode-bidi: isolate;
        line-height: 1.25;
    }
    .recitation-meta {
        font-size: 10.5px;
        color: var(--text-faint);
        font-family: var(--font-mono);
        margin-top: 4px;
        letter-spacing: 0.02em;
    }
    .drawer-close {
        background: transparent;
        border: 0;
        color: var(--text-faint);
        cursor: pointer;
        font-size: 18px;
        line-height: 1;
        padding: 0 var(--s-2);
    }
    .drawer-close:hover { color: var(--text-primary); }

    .drawer-body {
        flex: 1;
        min-height: 0;
        overflow: auto;
        padding: var(--s-5);
    }

    .state {
        padding: var(--s-8) 0;
        text-align: center;
        color: var(--text-muted);
        font-size: var(--fs-meta);
    }
    .state.error { color: var(--state-error-fg); }

    .dsection { margin-bottom: var(--s-6); }
    .dsection:last-child { margin-bottom: 0; }
    .dsection-head {
        font-size: 10.5px;
        font-family: var(--font-mono);
        color: var(--text-faint);
        letter-spacing: 0.06em;
        text-transform: uppercase;
        margin: 0 0 var(--s-3);
        font-weight: 500;
    }

    .ops-actions {
        display: flex;
        flex-direction: column;
        gap: var(--s-2);
    }
    .ops-action {
        display: flex;
        align-items: center;
        gap: var(--s-3);
        padding: var(--s-3);
        background: var(--panel-2);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        cursor: pointer;
        text-align: left;
        color: var(--text-primary);
        font: inherit;
        font-size: var(--fs-body);
        transition: border-color var(--t-fast), background-color var(--t-fast);
    }
    .ops-action:hover:not(:disabled) { border-color: var(--border-default); }
    .ops-action.primary { border-color: var(--accent-tint); }
    .ops-action.primary:hover:not(:disabled) { border-color: var(--accent); }
    .ops-action.danger:hover:not(:disabled) { border-color: var(--state-error-fg); }
    .ops-action:disabled {
        opacity: 0.55;
        cursor: not-allowed;
    }
    .ops-action .name { font-weight: 500; }
    .ops-action .hint {
        display: block;
        font-size: 11px;
        color: var(--text-muted);
        margin-top: 4px;
        font-weight: 400;
        line-height: 1.45;
    }
    .ops-action .hint em { color: var(--accent-strong); font-style: normal; }
    .ops-action .hint .owner-tag {
        display: inline-block;
        margin-left: 6px;
        font-family: var(--font-mono);
        font-size: 9.5px;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: var(--accent-strong);
        background: var(--accent-tint-soft);
        border-radius: 999px;
        padding: 1px 6px;
        vertical-align: 1px;
    }
    .ops-action .arrow {
        margin-left: auto;
        color: var(--text-faint);
        font-family: var(--font-mono);
        flex: 0 0 auto;
    }

    .confirm-slot {
        background: var(--accent-tint-soft);
        border: 1px solid var(--accent-tint);
        border-radius: var(--r-2);
        padding: var(--s-3);
    }
    .confirm-q {
        font-size: var(--fs-body);
        color: var(--text-primary);
        margin-bottom: var(--s-2);
        line-height: 1.45;
    }
    .reason {
        display: flex;
        flex-direction: column;
        gap: 4px;
        margin-bottom: var(--s-2);
    }
    .reason span {
        font-size: 10.5px;
        color: var(--text-faint);
        font-family: var(--font-mono);
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }
    .reason input {
        background: var(--canvas);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-1);
        padding: 6px 10px;
        color: var(--text-primary);
        font: inherit;
        font-size: var(--fs-body);
    }
    .reason input:focus {
        outline: 0;
        border-color: var(--accent-tint);
        box-shadow: 0 0 0 2px var(--accent-tint-soft);
    }
    .confirm-error {
        color: var(--state-error-fg);
        font-size: var(--fs-meta);
        margin-bottom: var(--s-2);
    }
    .confirm-actions { display: flex; gap: var(--s-2); }
    .btn-confirm {
        background: var(--accent);
        color: var(--accent-fg);
        border: 0;
        padding: 5px 14px;
        border-radius: var(--r-1);
        cursor: pointer;
        font: inherit;
        font-size: var(--fs-meta);
        font-weight: 500;
    }
    .btn-confirm:hover:not(:disabled) { background: var(--accent-strong); }
    .btn-confirm:disabled { opacity: 0.6; cursor: not-allowed; }
    .btn-cancel {
        background: transparent;
        color: var(--text-secondary);
        border: 1px solid var(--border-default);
        padding: 4px 14px;
        border-radius: var(--r-1);
        cursor: pointer;
        font: inherit;
        font-size: var(--fs-meta);
    }
    .btn-cancel:disabled { opacity: 0.6; cursor: not-allowed; }

    .empty-block {
        font-size: var(--fs-body);
        color: var(--text-muted);
        padding: var(--s-3) 0;
        line-height: 1.5;
    }
    .empty-block em {
        color: var(--accent-strong);
        font-style: normal;
    }
</style>
