<script lang="ts">
    /**
     * Comment composer for a verse-level report category (audio / other).
     *
     * Shows the caller's existing report in this category on this verse (with
     * edit + remove) or an empty composer. A mandatory comment is required to
     * submit. Create is an upsert server-side, so "edit" re-POSTs; "remove" is a
     * soft delete that drops the report from every view. Anonymous callers are
     * keyed by a localStorage token so they can edit/remove across refreshes.
     */
    import { currentUser } from '../../../../lib/stores/current-user';
    import type { TsReport } from '../../../../lib/types/generated/schemas';
    import { getAnonToken } from '../../../../lib/utils/anon-token';
    import type { ReportCategoryDef } from '../../domain/report-categories';
    import { createReport, deleteReport } from '../../services/reports-client';
    import ReportIcon from './ReportIcon.svelte';

    let {
        slug,
        verseKey,
        category,
        verseReports,
        onchanged,
        onback,
    }: {
        slug: string;
        verseKey: string;
        category: ReportCategoryDef;
        verseReports: TsReport[];
        onchanged: () => void;
        onback: () => void;
    } = $props();

    const mine = $derived(
        verseReports.find(
            (r) => r.category === category.id && r.target.kind === 'verse' && r.mine,
        ) ?? null,
    );
    const othersCount = $derived(
        verseReports.filter((r) => r.category === category.id && !r.mine).length,
    );

    let draft = $state('');
    let editing = $state(false);
    let busy = $state(false);
    /** Reset the editor when the target report changes (verse/category switch). */
    let syncKey = $state('');

    $effect(() => {
        const key = `${slug}|${verseKey}|${category.id}|${mine?.id ?? 'none'}`;
        if (key !== syncKey) {
            syncKey = key;
            editing = false;
            draft = mine?.comment ?? '';
        }
    });

    function anonTokenIfNeeded(): string | null {
        return $currentUser.hf_user_id === null ? getAnonToken() : null;
    }

    const canSubmit = $derived(draft.trim().length > 0 && !busy);

    async function submit(): Promise<void> {
        if (!canSubmit) return;
        busy = true;
        try {
            const res = await createReport(slug, {
                verse_key: verseKey,
                category: category.id,
                subtype: null,
                target: { kind: 'verse' },
                comment: draft.trim(),
                anon_token: anonTokenIfNeeded(),
            });
            if (!res?.error) {
                editing = false;
                onchanged();
            }
        } finally {
            busy = false;
        }
    }

    async function remove(): Promise<void> {
        if (!mine || busy) return;
        busy = true;
        try {
            const ok = await deleteReport(slug, mine.id, anonTokenIfNeeded());
            if (ok) {
                draft = '';
                editing = false;
                onchanged();
            }
        } finally {
            busy = false;
        }
    }

    function startEdit(): void {
        draft = mine?.comment ?? '';
        editing = true;
    }
</script>

<div class="composer">
    <header class="head">
        <button type="button" class="back" onclick={onback} aria-label="Back to categories">
            <ReportIcon name="back" size={15} />
        </button>
        <span class="cat-ic"><ReportIcon name={category.id} size={15} /></span>
        <h4>{category.label}</h4>
    </header>

    {#if mine && !editing}
        <div class="saved">
            <p class="saved-body">{mine.comment}</p>
            <div class="saved-actions">
                <button type="button" class="link" onclick={startEdit} disabled={busy}>
                    <ReportIcon name="edit" size={13} /> Edit
                </button>
                <button type="button" class="link danger" onclick={remove} disabled={busy}>
                    <ReportIcon name="trash" size={13} /> Remove
                </button>
            </div>
        </div>
        <p class="note ok"><ReportIcon name="check" size={13} /> Reported. Reviewers will see this.</p>
    {:else}
        <textarea
            class="field"
            bind:value={draft}
            rows="3"
            placeholder={category.placeholder}
            aria-label={`Describe the ${category.label.toLowerCase()} issue`}
        ></textarea>
        <div class="composer-actions">
            {#if editing}
                <button type="button" class="btn ghost" onclick={() => (editing = false)} disabled={busy}>
                    Cancel
                </button>
            {/if}
            <button type="button" class="btn primary" onclick={submit} disabled={!canSubmit}>
                {editing ? 'Save changes' : 'Submit report'}
            </button>
        </div>
    {/if}

    {#if othersCount > 0}
        <p class="note">{othersCount} {othersCount === 1 ? 'other listener has' : 'other listeners have'} reported this.</p>
    {/if}
</div>

<style>
    .composer {
        display: flex;
        flex-direction: column;
        gap: var(--s-2);
    }
    .head {
        display: flex;
        align-items: center;
        gap: var(--s-2);
    }
    .head h4 {
        margin: 0;
        font-size: var(--fs-body);
        font-weight: 600;
        color: var(--text-primary);
    }
    .back {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 24px;
        height: 24px;
        padding: 0;
        color: var(--text-muted);
        background: transparent;
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-1);
        cursor: pointer;
        transition: color var(--t-fast), background var(--t-fast);
    }
    .back:hover { color: var(--text-primary); background: var(--panel-2); }
    .cat-ic { display: inline-flex; color: var(--text-secondary); }

    .field {
        width: 100%;
        resize: none;
        height: 66px;
        padding: var(--s-2);
        color: var(--text-primary);
        background: var(--canvas-inset);
        border: 1px solid var(--border-default);
        border-radius: var(--r-2);
        font: inherit;
        font-size: var(--fs-body);
        line-height: 1.5;
    }
    .field::placeholder { color: var(--text-faint); }
    .field:focus-visible {
        outline: none;
        border-color: var(--accent);
        box-shadow: 0 0 0 2px var(--accent-tint);
    }

    .composer-actions {
        display: flex;
        justify-content: flex-end;
        gap: var(--s-2);
    }
    .btn {
        padding: 5px var(--s-3);
        border-radius: var(--r-2);
        font: inherit;
        font-size: var(--fs-meta);
        font-weight: 600;
        cursor: pointer;
        border: 1px solid transparent;
        transition: background var(--t-fast), color var(--t-fast), border-color var(--t-fast);
    }
    .btn.primary { color: var(--accent-fg); background: var(--accent); }
    .btn.primary:hover:not(:disabled) { background: var(--accent-strong); }
    .btn.primary:disabled { opacity: 0.45; cursor: not-allowed; }
    .btn.ghost { color: var(--text-secondary); background: transparent; border-color: var(--border-default); }
    .btn.ghost:hover:not(:disabled) { color: var(--text-primary); background: var(--panel-2); }

    .saved {
        display: flex;
        flex-direction: column;
        gap: var(--s-2);
        padding: var(--s-2);
        background: var(--canvas-inset);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
    }
    .saved-body {
        margin: 0;
        max-height: 140px;
        overflow-y: auto;
        color: var(--text-primary);
        font-size: var(--fs-body);
        line-height: 1.5;
        white-space: pre-wrap;
        word-break: break-word;
    }
    .saved-actions { display: flex; gap: var(--s-3); }
    .link {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 0;
        color: var(--text-secondary);
        background: transparent;
        border: 0;
        cursor: pointer;
        font: inherit;
        font-size: var(--fs-meta);
    }
    .link:hover:not(:disabled) { color: var(--text-primary); }
    .link.danger:hover:not(:disabled) { color: var(--state-error); }
    .link:disabled { opacity: 0.5; cursor: default; }

    .note {
        margin: 0;
        color: var(--text-muted);
        font-size: var(--fs-meta);
    }
    .note.ok {
        display: flex;
        align-items: center;
        gap: 5px;
        color: var(--state-published);
    }
</style>
