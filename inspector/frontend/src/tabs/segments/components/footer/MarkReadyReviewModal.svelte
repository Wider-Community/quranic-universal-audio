<script lang="ts">
    /**
     * MarkReadyReviewModal — read-only view of a reviewer's mark-ready notes.
     *
     * Opened from the owner "marked ready — reviewer left notes" notification
     * (deep-link ``openMarkReadyReview``). Shows ONLY the contributor's two
     * free-text comment boxes (+ an owner-bypass pill when applicable) — NOT
     * the checklist. Fetches the same payload the admin Reviews drawer uses
     * (``GET /api/admin/reviews/<slug>`` → ``current_claim.mark_ready_submission``)
     * which the server gates on ``reviews.view``.
     */
    import { fetchAdminReviewDetail } from '../../../../lib/api/admin-reviews';
    import type { AdminReviewDetail } from '../../../../lib/types/generated/schemas';
    import { relativeTime } from '../../../../lib/utils/relative-time';
    import { markReadyCopy } from '../../copy/mark-ready';

    let { slug, onClose }: { slug: string; onClose: () => void } = $props();

    let detail = $state<AdminReviewDetail | null>(null);
    let loading = $state(true);
    let error = $state<string | null>(null);

    const submission = $derived(detail?.current_claim?.mark_ready_submission ?? null);
    const hasNotes = $derived(
        !!(submission?.comment_checks?.trim() || submission?.comment_issues?.trim()),
    );

    $effect(() => {
        const target = slug;
        const ac = new AbortController();
        loading = true;
        error = null;
        detail = null;
        fetchAdminReviewDetail(target, ac.signal)
            .then((d) => {
                if (ac.signal.aborted) return;
                detail = d;
            })
            .catch((e: unknown) => {
                if (ac.signal.aborted) return;
                error = e instanceof Error ? e.message : 'Could not load the submission.';
            })
            .finally(() => {
                if (!ac.signal.aborted) loading = false;
            });
        return () => ac.abort();
    });

    function onKey(e: KeyboardEvent): void {
        if (e.key === 'Escape') onClose();
    }
</script>

<svelte:window onkeydown={onKey} />

<div class="backdrop" role="presentation" onclick={(e) => e.target === e.currentTarget && onClose()}>
    <div class="dialog" role="dialog" aria-modal="true" aria-labelledby="mrr-title">
        <header>
            <h2 id="mrr-title">Reviewer notes</h2>
            <button class="close" aria-label="Close" onclick={onClose}>×</button>
        </header>

        {#if loading}
            <p class="state">Loading…</p>
        {:else if error}
            <p class="state err" role="alert">{error}</p>
        {:else if !submission}
            <p class="state">This recitation isn't marked ready right now.</p>
        {:else}
            {#if submission.bypass_used}
                <span class="bypass-pill" title="Submitted with the owner-bypass capability">
                    owner bypass
                </span>
            {/if}
            {#if detail?.current_claim?.marked_ready_at}
                <p class="meta">Marked ready {relativeTime(detail.current_claim.marked_ready_at)}</p>
            {/if}

            {#if hasNotes}
                {#if (submission.comment_checks ?? '').trim()}
                    <div class="comment">
                        <div class="comment-label">{markReadyCopy.comments.checks.label}</div>
                        <blockquote class="comment-body">{submission.comment_checks}</blockquote>
                    </div>
                {/if}
                {#if (submission.comment_issues ?? '').trim()}
                    <div class="comment">
                        <div class="comment-label">{markReadyCopy.comments.issues.label}</div>
                        <blockquote class="comment-body">{submission.comment_issues}</blockquote>
                    </div>
                {/if}
            {:else}
                <p class="state">The reviewer left no written notes.</p>
            {/if}
        {/if}
    </div>
</div>

<style>
    .backdrop {
        position: fixed;
        inset: 0;
        z-index: 140;
        background: oklch(0.06 0.005 268 / 0.72);
        backdrop-filter: blur(3px);
        display: flex;
        align-items: center;
        justify-content: center;
        padding: var(--s-6);
        animation: backdrop-in var(--t-slow) var(--ease-out-quart);
    }
    @keyframes backdrop-in {
        from { opacity: 0; }
        to { opacity: 1; }
    }
    .dialog {
        width: min(560px, 96vw);
        max-height: 88vh;
        overflow: auto;
        background: var(--canvas);
        border: 1px solid var(--border-default);
        border-radius: var(--r-3);
        padding: var(--s-5);
        display: flex;
        flex-direction: column;
        gap: var(--s-3);
        box-shadow: 0 32px 80px oklch(0 0 0 / 0.45);
        animation: modal-in var(--t-slow) var(--ease-out-expo);
    }
    @keyframes modal-in {
        from { opacity: 0; transform: translateY(12px) scale(0.985); }
        to { opacity: 1; transform: none; }
    }
    header { display: flex; align-items: center; justify-content: space-between; }
    h2 { margin: 0; font-size: var(--fs-h3); font-weight: 500; color: var(--text-primary); }
    .close {
        width: 28px; height: 28px;
        display: inline-flex; align-items: center; justify-content: center;
        color: var(--text-muted); border-radius: var(--r-2);
        font-size: 18px; line-height: 1;
        background: transparent; border: 0; cursor: pointer;
    }
    .close:hover { color: var(--text-primary); background: var(--panel); }
    .state { margin: 0; font-size: var(--fs-meta); color: var(--text-muted); }
    .state.err { color: var(--state-error-fg); }
    .meta { margin: 0; font-size: var(--fs-meta); color: var(--text-faint); }
    .bypass-pill {
        align-self: flex-start;
        font-size: 11px;
        color: var(--state-warn-fg);
        background: oklch(from var(--state-warn-fg) l c h / 0.12);
        border-radius: var(--r-pill);
        padding: 2px 8px;
    }
    .comment { display: flex; flex-direction: column; gap: 4px; }
    .comment-label { font-size: var(--fs-meta); color: var(--text-muted); }
    .comment-body {
        margin: 0;
        font-size: var(--fs-meta);
        color: var(--text-primary);
        line-height: var(--lh-normal);
        white-space: pre-wrap;
        border-left: 2px solid var(--border-default);
        padding: 4px 0 4px 10px;
    }
</style>
