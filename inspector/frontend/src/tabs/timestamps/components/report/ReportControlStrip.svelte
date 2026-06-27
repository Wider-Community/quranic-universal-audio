<script lang="ts">
    /**
     * Report-mode control strip — replaces the waveform while a timing/tajweed
     * report session is active. Shows the mode header (+ tajweed wrong/missing
     * toggle), the staged cells, and an annotation editor for the focused cell,
     * with Cancel (discard) and Submit (persist the batch). The grid below stays
     * the click surface; this strip never blocks it.
     */
    import {
        exitReportMode,
        focusedCellKey,
        removeStaged,
        reportContext,
        reportMode,
        setTajweedSubtype,
        staged,
        type StagedAnnotation,
        type TimingSubtype,
        upsertStaged,
    } from '../../stores/report-mode';
    import { currentVerseReports, loadReciterReports, loadVerseReports } from '../../stores/ts-reports';
    import { badgeForTag, silentTooltip } from '../../utils/tajweed-rules';
    import { targetCellKey } from '../../utils/report-target';
    import { submitReportSession } from '../../services/report-submit';
    import ReportIcon from './ReportIcon.svelte';

    const TIMING_OPTS: { id: TimingSubtype; icon: string; label: string }[] = [
        { id: 'too_long', icon: 'too_long', label: 'Too long' },
        { id: 'too_short', icon: 'too_short', label: 'Too short' },
        { id: 'other', icon: 'timing_other', label: 'Other' },
    ];

    let busy = $state(false);
    let error = $state('');

    const mode = $derived($reportMode);
    const stagedList = $derived([...$staged.values()]);
    const focused = $derived($focusedCellKey ? ($staged.get($focusedCellKey) ?? null) : null);

    function ruleLabel(tag: string): string {
        return badgeForTag(tag)?.tooltip ?? silentTooltip(tag) ?? tag;
    }

    function cellLabel(a: StagedAnnotation): string {
        if (a.target.kind === 'word') return `Word ${(a.target.word_index ?? 0) + 1}`;
        return `W${(a.target.word_index ?? 0) + 1}·cell ${a.target.cell_index ?? a.target.source_letter_index ?? '?'}`;
    }

    function valid(a: StagedAnnotation): boolean {
        if (a.kind === 'timing') {
            return a.subtype != null && (a.subtype !== 'other' || a.comment.trim().length > 0);
        }
        return a.comment.trim().length > 0; // every tajweed report needs a comment
    }
    const allValid = $derived(stagedList.length > 0 && stagedList.every(valid));

    const removedIds = $derived.by(() => {
        const cat = mode.kind === 'timing' ? 'timing' : 'tajweed';
        const keys = new Set($staged.keys());
        return $currentVerseReports
            .filter((r) => r.mine && r.status === 'open' && r.category === cat && !keys.has(targetCellKey(r.target)))
            .map((r) => r.id);
    });

    function setTimingSubtype(st: TimingSubtype): void {
        if (focused?.kind === 'timing') upsertStaged({ ...focused, subtype: st });
    }
    function setComment(val: string): void {
        if (focused) upsertStaged({ ...focused, comment: val });
    }
    function toggleRule(tag: string): void {
        if (focused?.kind !== 'tajweed') return;
        const sel = focused.selectedRuleTags.includes(tag)
            ? focused.selectedRuleTags.filter((t) => t !== tag)
            : [...focused.selectedRuleTags, tag];
        upsertStaged({ ...focused, selectedRuleTags: sel });
    }

    async function submit(): Promise<void> {
        if (!allValid || busy) return;
        const ctx = $reportContext;
        if (!ctx) return;
        busy = true;
        error = '';
        const res = await submitReportSession(ctx.slug, ctx.verseKey, stagedList, removedIds);
        busy = false;
        if (res.ok) {
            await loadVerseReports(ctx.slug, ctx.verseKey);
            await loadReciterReports(ctx.slug);
            exitReportMode();
        } else {
            error = res.error ?? 'Failed to submit';
        }
    }

    const headTitle = $derived(mode.kind === 'tajweed' ? 'Report a tajweed issue' : 'Report a timing issue');
    const instruction = $derived(
        mode.kind === 'timing'
            ? 'Click a letter or word to flag it, then say how its timing is off.'
            : mode.kind === 'tajweed' && mode.subtype === 'wrong_rule'
              ? 'Highlighted cells carry a rule — click one to flag the wrong rule.'
              : 'Click any cell where a rule should apply but is missing.',
    );
    const submitCount = $derived(stagedList.length + removedIds.length);
</script>

<div class="strip" role="group" aria-label="Report controls">
    <header class="head">
        <div class="title-wrap">
            <span class="flag-ic"><ReportIcon name="flag" size={15} /></span>
            <h3>{headTitle}</h3>
        </div>
        {#if mode.kind === 'tajweed'}
            <div class="seg" role="radiogroup" aria-label="Tajweed issue type">
                <button
                    type="button" class:on={mode.subtype === 'wrong_rule'}
                    aria-checked={mode.subtype === 'wrong_rule'} role="radio"
                    onclick={() => setTajweedSubtype('wrong_rule')}
                >Wrong rule</button>
                <button
                    type="button" class:on={mode.subtype === 'missing_rule'}
                    aria-checked={mode.subtype === 'missing_rule'} role="radio"
                    onclick={() => setTajweedSubtype('missing_rule')}
                >Missing rule</button>
            </div>
        {/if}
        <div class="actions">
            <button type="button" class="btn ghost" onclick={exitReportMode} disabled={busy}>Cancel</button>
            <button type="button" class="btn primary" onclick={submit} disabled={!allValid || busy}>
                {busy ? 'Saving…' : `Submit${submitCount ? ` ${submitCount}` : ''}`}
            </button>
        </div>
    </header>

    <p class="instruction">{instruction}</p>

    <div class="body">
        {#if stagedList.length === 0}
            <p class="empty">No cells flagged yet.</p>
        {:else}
            <div class="chips" role="list">
                {#each stagedList as a (a.cellKey)}
                    <span class="chip" class:focused={a.cellKey === $focusedCellKey} class:invalid={!valid(a)} role="listitem">
                        <button type="button" class="chip-main" onclick={() => focusedCellKey.set(a.cellKey)}>
                            {cellLabel(a)}{a.kind === 'timing' && a.subtype ? ` · ${a.subtype.replace('_', ' ')}` : ''}
                        </button>
                        <button type="button" class="chip-x" aria-label="Remove" onclick={() => removeStaged(a.cellKey)}>
                            <ReportIcon name="trash" size={12} />
                        </button>
                    </span>
                {/each}
            </div>
        {/if}

        {#if focused}
            <div class="editor">
                {#if focused.kind === 'timing'}
                    <div class="opts" role="radiogroup" aria-label="Timing problem">
                        {#each TIMING_OPTS as o (o.id)}
                            <button
                                type="button" class="opt" class:on={focused.subtype === o.id}
                                aria-checked={focused.subtype === o.id} role="radio"
                                onclick={() => setTimingSubtype(o.id)}
                            >
                                <ReportIcon name={o.icon} size={14} /> {o.label}
                            </button>
                        {/each}
                    </div>
                    <textarea
                        class="field" rows="2"
                        placeholder={focused.subtype === 'other' ? 'Describe the timing problem (required)…' : 'Add a note (optional)…'}
                        value={focused.comment}
                        oninput={(e) => setComment(e.currentTarget.value)}
                    ></textarea>
                {:else}
                    {#if focused.subtype === 'wrong_rule' && focused.ruleOptions.length > 0}
                        <div class="rules">
                            <span class="rules-lbl">Which rule is wrong?</span>
                            {#each focused.ruleOptions as tag (tag)}
                                <button
                                    type="button" class="rule" class:on={focused.selectedRuleTags.includes(tag)}
                                    aria-pressed={focused.selectedRuleTags.includes(tag)}
                                    onclick={() => toggleRule(tag)}
                                >{ruleLabel(tag)}</button>
                            {/each}
                        </div>
                    {/if}
                    <textarea
                        class="field" rows="2" placeholder="Describe the tajweed issue (required)…"
                        value={focused.comment}
                        oninput={(e) => setComment(e.currentTarget.value)}
                    ></textarea>
                {/if}
            </div>
        {/if}

        {#if error}<p class="err">{error}</p>{/if}
    </div>
</div>

<style>
    .strip {
        display: flex;
        flex-direction: column;
        gap: var(--s-2);
        height: 100%;
        min-height: 0;
        padding: var(--s-3);
        background: var(--panel);
        border: 1px solid var(--border-default);
        border-radius: var(--r-3);
        overflow-y: auto;
    }
    .head { display: flex; align-items: center; gap: var(--s-3); flex-wrap: wrap; }
    .title-wrap { display: inline-flex; align-items: center; gap: var(--s-2); }
    .flag-ic { display: inline-flex; color: var(--state-warn-fg); }
    .head h3 { margin: 0; font-size: var(--fs-title, 16px); font-weight: 600; color: var(--text-primary); }
    .actions { margin-left: auto; display: inline-flex; gap: var(--s-2); }

    .seg { display: inline-flex; border: 1px solid var(--border-default); border-radius: var(--r-2); overflow: hidden; }
    .seg button {
        padding: 4px var(--s-3); font: inherit; font-size: var(--fs-meta); color: var(--text-secondary);
        background: transparent; border: 0; cursor: pointer; transition: background var(--t-fast), color var(--t-fast);
    }
    .seg button:hover { color: var(--text-primary); background: var(--panel-2); }
    .seg button.on { color: var(--accent-fg); background: var(--accent); }

    .btn {
        padding: 5px var(--s-3); border-radius: var(--r-2); font: inherit; font-size: var(--fs-meta);
        font-weight: 600; cursor: pointer; border: 1px solid transparent; transition: background var(--t-fast);
    }
    .btn.primary { color: var(--accent-fg); background: var(--accent); }
    .btn.primary:hover:not(:disabled) { background: var(--accent-strong); }
    .btn.primary:disabled { opacity: 0.45; cursor: not-allowed; }
    .btn.ghost { color: var(--text-secondary); background: transparent; border-color: var(--border-default); }
    .btn.ghost:hover:not(:disabled) { color: var(--text-primary); background: var(--panel-2); }

    .instruction { margin: 0; font-size: var(--fs-meta); color: var(--text-muted); }
    .body { display: flex; flex-direction: column; gap: var(--s-2); min-height: 0; }
    .empty { margin: 0; color: var(--text-faint); font-size: var(--fs-meta); font-style: italic; }

    .chips { display: flex; flex-wrap: wrap; gap: var(--s-2); }
    .chip {
        display: inline-flex; align-items: stretch; border: 1px solid var(--state-missing-fg);
        border-radius: 999px; overflow: hidden; background: color-mix(in oklab, var(--state-missing-fg) 12%, var(--panel));
        font-size: var(--fs-meta);
    }
    .chip.focused { outline: 2px solid var(--accent); outline-offset: 1px; }
    .chip.invalid { border-style: dashed; }
    .chip-main { padding: 3px var(--s-2); background: transparent; border: 0; color: var(--text-primary); cursor: pointer; font: inherit; }
    .chip-x { display: inline-flex; align-items: center; padding: 0 6px; background: transparent; border: 0; border-left: 1px solid var(--border-quiet); color: var(--text-muted); cursor: pointer; }
    .chip-x:hover { color: var(--state-error); }

    .editor { display: flex; flex-direction: column; gap: var(--s-2); }
    .opts, .rules { display: flex; flex-wrap: wrap; gap: var(--s-2); align-items: center; }
    .rules-lbl { font-size: var(--fs-meta); color: var(--text-secondary); }
    .opt, .rule {
        display: inline-flex; align-items: center; gap: 5px; padding: 4px var(--s-3); font: inherit; font-size: var(--fs-meta);
        color: var(--text-secondary); background: var(--panel-2); border: 1px solid var(--border-default);
        border-radius: var(--r-2); cursor: pointer; transition: all var(--t-fast);
    }
    .opt:hover, .rule:hover { color: var(--text-primary); border-color: var(--border-strong); }
    .opt.on, .rule.on { color: var(--accent); background: var(--accent-tint); border-color: var(--accent); }

    .field {
        width: 100%; resize: vertical; min-height: 44px; padding: var(--s-2); color: var(--text-primary);
        background: var(--canvas-inset); border: 1px solid var(--border-default); border-radius: var(--r-2);
        font: inherit; font-size: var(--fs-body); line-height: 1.5;
    }
    .field::placeholder { color: var(--text-faint); }
    .field:focus-visible { outline: none; border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-tint); }
    .err { margin: 0; color: var(--state-error); font-size: var(--fs-meta); }
</style>
