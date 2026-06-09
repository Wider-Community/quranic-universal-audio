<script lang="ts">
    /**
     * Read-only reviewer view for a Releases row expansion — current reviewer,
     * mark-ready submission, and closed-claim history. Lifted from the Reviews
     * General drawer; here it is purely informational (claim mutation stays in
     * the Reviews tab / the Ready-to-generate row's Send-back).
     */
    import type { AdminReviewDetail } from '../../../../../lib/types/generated/schemas';
    import {
        CHECKLIST_ORDER,
        type ChecklistKey,
        markReadyCopy,
    } from '../../../../segments/copy/mark-ready';

    let { detail }: { detail: AdminReviewDetail } = $props();

    function checklistLabelFor(key: ChecklistKey): string {
        return markReadyCopy.checklist.find((c) => c.key === key)?.label ?? key;
    }

    function initials(login: string | null | undefined): string {
        const t = (login ?? '').trim();
        if (!t) return '?';
        return (t.replace(/[^a-z0-9]/gi, '').slice(0, 2) || t.slice(0, 2)).toUpperCase();
    }

    function fmtDate(iso: string | null | undefined): string {
        if (!iso) return '';
        const d = new Date(iso);
        return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(undefined, {
            year: 'numeric', month: 'short', day: 'numeric',
        });
    }

    function fmtDuration(from: string | null | undefined, to: string | null | undefined): string {
        if (!from || !to) return '';
        const a = Date.parse(from), b = Date.parse(to);
        if (Number.isNaN(a) || Number.isNaN(b)) return '';
        const secs = Math.max(0, Math.floor((b - a) / 1000));
        const days = Math.floor(secs / 86400);
        if (days >= 1) return `${days}d`;
        const hrs = Math.floor(secs / 3600);
        if (hrs >= 1) return `${hrs}h`;
        return `${Math.floor(secs / 60)}m`;
    }

    const history = $derived((detail.claim_history ?? []).filter((c) => c.released_at !== null));
    const submission = $derived(detail.current_claim?.mark_ready_submission ?? null);
</script>

<div class="rev">
    <section class="rsec">
        <h4 class="rhead">Current reviewer</h4>
        {#if detail.current_claim}
            <div class="claim">
                <span class="avatar">{initials(detail.current_claim.login)}</span>
                <div class="meta">
                    <div class="who">{detail.current_claim.login ?? 'Unknown'}</div>
                    <div class="since">
                        claimed {fmtDate(detail.current_claim.claimed_at)}
                        {#if detail.current_claim.marked_ready_at}· marked ready {fmtDate(detail.current_claim.marked_ready_at)}{/if}
                    </div>
                </div>
            </div>
        {:else}
            <div class="empty">No open claim.</div>
        {/if}
    </section>

    {#if submission}
        {@const checklist = submission.checklist}
        <section class="rsec mr" class:bypass={submission.bypass_used}>
            <h4 class="rhead">
                Mark-ready submission
                {#if submission.bypass_used}<span class="pill">owner bypass</span>{/if}
            </h4>
            {#if submission.bypass_used || !checklist}
                <p class="bypass-line">Submitted via owner bypass — the checklist and zero-count gates were skipped.</p>
            {:else}
                <ul class="checklist">
                    {#each CHECKLIST_ORDER as key (key)}
                        <li class:done={checklist[key]}>
                            <span class="glyph" aria-hidden="true">{checklist[key] ? '✓' : '·'}</span>
                            <span>{checklistLabelFor(key)}</span>
                        </li>
                    {/each}
                </ul>
            {/if}
            {#if (submission.comment_checks ?? '').trim()}
                <div class="comment">
                    <div class="comment-lbl">{markReadyCopy.comments.checks.label}</div>
                    <blockquote>{submission.comment_checks}</blockquote>
                </div>
            {/if}
            {#if (submission.comment_issues ?? '').trim()}
                <div class="comment">
                    <div class="comment-lbl">{markReadyCopy.comments.issues.label}</div>
                    <blockquote>{submission.comment_issues}</blockquote>
                </div>
            {/if}
        </section>
    {/if}

    <section class="rsec">
        <h4 class="rhead">Reviewer history <span class="aside">{history.length} closed</span></h4>
        {#if history.length === 0}
            <div class="empty">No prior claims.</div>
        {:else}
            <ul class="hist">
                {#each history as h (`${h.assignee_id}_${h.claimed_at}`)}
                    <li>
                        <span class="avatar small">{initials(h.login)}</span>
                        <div class="meta">
                            <div class="who">{h.login ?? 'Unknown'}</div>
                            <div class="dates">
                                {fmtDate(h.claimed_at)} · {fmtDate(h.released_at)}
                                {#if h.close_reason}<span class="reason">{h.close_reason.replace(/_/g, ' ')}</span>{/if}
                            </div>
                        </div>
                        <div class="dur">{fmtDuration(h.claimed_at, h.released_at)}</div>
                    </li>
                {/each}
            </ul>
        {/if}
    </section>

    {#if (detail.flagged_issues_count ?? 0) > 0}
        <section class="rsec">
            <h4 class="rhead">Flagged issues <span class="flagged">{detail.flagged_issues_count}</span></h4>
            <div class="empty">
                {detail.flagged_issues_count} {detail.flagged_issues_count === 1 ? 'segment' : 'segments'}
                flagged for a second look in the Segments editor.
            </div>
        </section>
    {/if}
</div>

<style>
    .rev { display: flex; flex-direction: column; gap: var(--s-4); padding: var(--s-2) var(--s-1); }
    .rsec { display: flex; flex-direction: column; gap: var(--s-2); }
    .rhead {
        margin: 0;
        font-family: var(--font-mono);
        font-size: 10px;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        color: var(--text-faint);
        display: flex;
        align-items: center;
        gap: var(--s-2);
    }
    .rhead .aside { text-transform: none; letter-spacing: 0; }
    .empty { font-size: var(--fs-meta); color: var(--text-faint); }
    .claim { display: flex; align-items: center; gap: var(--s-3); }
    .avatar {
        width: 26px; height: 26px; border-radius: 50%;
        background: var(--accent-tint); color: var(--accent-strong);
        display: inline-flex; align-items: center; justify-content: center;
        font-size: 11px; font-weight: 600; flex: 0 0 auto;
    }
    .avatar.small { width: 20px; height: 20px; font-size: 9px; background: var(--panel-2); color: var(--text-muted); }
    .who { font-size: var(--fs-body); color: var(--text-primary); }
    .since, .dates { font-size: 10.5px; color: var(--text-muted); font-family: var(--font-mono); margin-top: 2px; }
    .reason { color: var(--text-faint); font-style: italic; margin-left: 6px; }
    .hist { list-style: none; margin: 0; padding: 0; }
    .hist li {
        display: grid; grid-template-columns: 26px 1fr auto; gap: var(--s-3);
        padding: var(--s-2) 0; border-bottom: 1px dashed var(--border-quiet); align-items: center;
    }
    .hist li:last-child { border-bottom: 0; }
    .dur { font-family: var(--font-mono); font-size: 10.5px; color: var(--text-faint); font-variant-numeric: tabular-nums; }

    .mr {
        padding: var(--s-3);
        background: var(--canvas-inset);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
    }
    .mr.bypass { border-color: oklch(0.86 0.130 75 / 0.4); }
    .pill {
        font-size: 9.5px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase;
        color: var(--state-error-fg);
        background: var(--state-error-bg);
        border: 1px solid oklch(0.86 0.130 75 / 0.4);
        border-radius: 999px; padding: 1px 7px;
    }
    .bypass-line { margin: 0; font-size: var(--fs-meta); font-style: italic; color: var(--text-secondary); }
    .checklist { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
    .checklist li { display: flex; align-items: flex-start; gap: var(--s-2); font-size: var(--fs-meta); color: var(--text-secondary); }
    .checklist li.done span:last-child { color: var(--text-primary); }
    .glyph { flex: 0 0 14px; font-family: var(--font-mono); color: var(--text-faint); text-align: center; }
    .checklist li.done .glyph { color: var(--accent); font-weight: 600; }
    .comment { margin-top: var(--s-2); display: flex; flex-direction: column; gap: 3px; }
    .comment-lbl { font-size: 10px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; }
    .comment blockquote {
        margin: 0; padding: var(--s-2) var(--s-3); background: var(--panel);
        border-radius: var(--r-1); font-size: var(--fs-meta); color: var(--text-primary);
        white-space: pre-wrap; word-break: break-word;
    }
    .flagged {
        font-family: var(--font-mono); font-size: 11px; font-weight: 600;
        color: var(--state-error-fg); background: var(--state-error-bg);
        border: 1px solid oklch(0.86 0.130 75 / 0.4); border-radius: 999px; padding: 1px 7px;
    }
</style>
