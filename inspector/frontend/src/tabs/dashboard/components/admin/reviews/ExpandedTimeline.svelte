<script lang="ts">
    /**
     * Fully-expanded chronological event timeline for one recitation.
     *
     * Vertical layout (sibling of the horizontal StateTimeline) — every
     * transition appears as its own row, dot color tracks the destination
     * state where applicable, with two off-axis variants:
     *
     *   - admin   hollow ring + "admin" badge (force-release, reassign,
     *             merge-reject, unlock-for-revision, anything admin.* )
     *   - job     dashed ring (alignment-completed, timestamps-completed)
     *
     * The dot color tokens are the same as StateTimeline's transition pills
     * (--state-published-fg etc.) so the visual vocabulary is consistent.
     */
    import type { AdminReviewTransition } from '../../../../../lib/types/generated/schemas';

    let {
        transitions,
        newestFirst = true,
    }: {
        transitions: AdminReviewTransition[];
        newestFirst?: boolean;
    } = $props();

    type Tone = 'transition' | 'admin' | 'job';

    const ADMIN_EVENTS = new Set<string>([
        'claim.force_released',
        'claim.reassigned',
        'reciter.merge_rejected',
        'reciter.unpublished',
    ]);

    const JOB_EVENTS = new Set<string>([
        'reciter.alignment_completed',
    ]);

    function toneFor(event: string): Tone {
        if (event.startsWith('admin.')) return 'admin';
        if (ADMIN_EVENTS.has(event)) return 'admin';
        if (JOB_EVENTS.has(event)) return 'job';
        return 'transition';
    }

    function colorClassFor(to_state: string | null | undefined): string {
        switch (to_state) {
            case 'under_review': return 'under-review';
            case 'awaiting_review': return 'available';
            case 'released': return 'published';
            default: return '';
        }
    }

    // Display copy. Falls back to the raw event name if unmapped.
    const LABELS: Record<string, string> = {
        'reciter.requested':              'requested',
        'reciter.request_rejected_soft':  'request rejected (soft)',
        'reciter.request_rejected_hard':  'request rejected (hard)',
        'reciter.alignment_completed':    'alignment completed',
        'reciter.claimed':                'claimed under review',
        'reciter.released':               'released claim',
        'reciter.marked_ready':           'marked ready',
        'reciter.unmarked_ready':         'unmarked ready',
        'reciter.merge_rejected':         'sent back to under review',
        'reciter.published':              'published',
        'reciter.unpublished':            'unpublished',
        'reciter.discarded':              'discarded',
        'reciter.undiscarded':            'undiscarded',
        'claim.force_released':           'force-released claim',
        'claim.reassigned':               'reassigned claim',
        'admin.unlocked_for_revision':    'unlocked for revision',
        'catalog.added':                  'added to catalog',
        'catalog.edited':                 'catalog edited',
    };

    function labelFor(event: string): string {
        return LABELS[event] ?? event;
    }

    // ISO -> "2026-05-28 14:22"
    function fmtTs(iso: string): string {
        if (!iso) return '';
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return iso;
        const pad = (n: number) => String(n).padStart(2, '0');
        return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    }

    const ordered = $derived(
        newestFirst
            ? [...transitions].sort((a, b) => (b.ts ?? '').localeCompare(a.ts ?? ''))
            : [...transitions].sort((a, b) => (a.ts ?? '').localeCompare(b.ts ?? '')),
    );
</script>

<ol class="timeline">
    {#each ordered as t (`${t.ts}|${t.event}|${t.actor_login ?? ''}`)}
        {@const tone = toneFor(t.event)}
        {@const colorClass = tone === 'transition' ? colorClassFor(t.to_state) : ''}
        <li class="event">
            <span
                class="dot {tone} {colorClass}"
                aria-hidden="true"
            ></span>
            <span class="time">{fmtTs(t.ts)}</span>
            <div class="headline">
                {#if t.actor_login}
                    <span class="who">{t.actor_login}</span>
                {/if}
                <span class="detail">{labelFor(t.event)}</span>
                {#if tone === 'admin'}
                    <span class="badge">admin</span>
                {/if}
                {#if t.reason}
                    <span class="reason">· {t.reason}</span>
                {/if}
            </div>
        </li>
    {/each}
    {#if ordered.length === 0}
        <li class="empty">No transitions recorded.</li>
    {/if}
</ol>

<style>
    .timeline {
        list-style: none;
        padding: 0;
        margin: 0;
        position: relative;
    }
    .timeline::before {
        content: '';
        position: absolute;
        left: 5px;
        top: 6px;
        bottom: 6px;
        width: 1px;
        background: var(--border-quiet);
    }

    .event {
        position: relative;
        padding: 5px 0 5px 22px;
    }

    .dot {
        position: absolute;
        left: 0;
        top: 7px;
        width: 11px;
        height: 11px;
        border-radius: 50%;
        background: var(--panel-2);
        border: 2px solid var(--canvas);
        box-shadow: 0 0 0 1px var(--border-default);
        z-index: 1;
    }
    .dot.transition.under-review { background: var(--state-under-review-fg); box-shadow: 0 0 0 1px var(--state-under-review-fg); }
    .dot.transition.available    { background: var(--state-available-fg);    box-shadow: 0 0 0 1px var(--state-available-fg); }
    .dot.transition.published    { background: var(--state-published-fg);    box-shadow: 0 0 0 1px var(--state-published-fg); }
    .dot.admin {
        background: var(--canvas);
        box-shadow: 0 0 0 1.5px var(--text-muted);
    }
    .dot.job {
        background: transparent;
        border: 1.5px dashed var(--text-muted);
        box-shadow: none;
        width: 10px;
        height: 10px;
        top: 8px;
        left: 0.5px;
    }

    .time {
        font-family: var(--font-mono);
        font-size: 10.5px;
        color: var(--text-faint);
        display: block;
        letter-spacing: 0.02em;
        font-variant-numeric: tabular-nums;
    }

    .headline {
        font-size: var(--fs-body);
        color: var(--text-primary);
        margin-top: 2px;
        line-height: 1.4;
    }
    .headline .who {
        color: var(--text-secondary);
        font-weight: 500;
        margin-right: 4px;
    }
    .headline .detail { color: var(--text-muted); }
    .headline .reason {
        color: var(--text-faint);
        font-style: italic;
        margin-left: 4px;
    }
    .headline .badge {
        margin-left: 6px;
        font-size: 9px;
        font-family: var(--font-mono);
        color: var(--text-faint);
        letter-spacing: 0.06em;
        text-transform: uppercase;
        border: 1px solid var(--border-quiet);
        padding: 0 4px;
        border-radius: 2px;
        vertical-align: 1px;
    }

    .empty {
        font-size: var(--fs-meta);
        color: var(--text-faint);
        padding: var(--s-3) 0;
    }
</style>
