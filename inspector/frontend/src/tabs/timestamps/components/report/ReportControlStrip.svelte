<script lang="ts">
    /**
     * Report-mode control strip — replaces the waveform while a
     * timing/tajweed/phonemes report session is active. The subtype is fixed at
     * entry (shown as a static header label, not a toggle). Each staged cell is ONE
     * inline row (label · subtype/rule control · comment · remove). Phonemes are
     * the exception: they collapse to ONE row per word with each flagged phoneme a
     * compact removable chip (a verse-worth of tiny phonemes would otherwise clobber
     * the strip), no control, no comment. The focused row mirrors the grid
     * selection. Cancel discards, Submit persists the batch. The grid below stays
     * the click surface; this strip never blocks it.
     */
    import {
        exitReportMode,
        focusCell,
        focusedCellKey,
        isStagedComplete,
        removeStaged,
        reportContext,
        reportMode,
        staged,
        type StagedAnnotation,
        type StagedPhoneme,
        upsertStaged,
    } from '../../stores/report-mode';
    import { currentVerseReports, loadReciterReports, loadVerseReports } from '../../stores/ts-reports';
    import { badgeForTag, silentTooltip } from '../../utils/tajweed-rules';
    import { targetCellKey, type TimingDir, timingLabel } from '../../utils/report-target';
    import { submitReportSession } from '../../services/report-submit';
    import ReportIcon from './ReportIcon.svelte';

    let busy = $state(false);
    let error = $state('');

    const mode = $derived($reportMode);
    const stagedList = $derived([...$staged.values()]);

    function ruleLabel(tag: string): string {
        return badgeForTag(tag)?.tooltip ?? silentTooltip(tag) ?? tag;
    }

    function cellLabel(a: StagedAnnotation): string {
        const w = (a.target.word_index ?? 0) + 1;
        if (a.target.kind === 'gap') return `Pause after word ${w}`;
        if (a.target.kind === 'word') return `Word ${w}`;
        return `W${w}·cell ${a.target.cell_index ?? a.target.source_letter_index ?? '?'}`;
    }

    /** Phonemes group by word: one strip row per word, each flagged phoneme a chip
     *  (so a verse-worth of tiny phonemes stays compact, not one row each). */
    const phonemeGroups = $derived.by(() => {
        const byWord = new Map<number, StagedPhoneme[]>();
        for (const a of stagedList) {
            if (a.kind !== 'phonemes') continue;
            const arr = byWord.get(a.wordIndex);
            if (arr) arr.push(a);
            else byWord.set(a.wordIndex, [a]);
        }
        return [...byWord.entries()]
            .sort((x, y) => x[0] - y[0])
            .map(([wordIndex, items]) => ({ wordIndex, items }));
    });
    function chipLabel(a: StagedPhoneme): string {
        if (a.glyph) return a.glyph;
        return (a.target.phoneme_flat_index ?? -1) < 0 ? 'merger' : '•';
    }

    const allValid = $derived(stagedList.length > 0 && stagedList.every(isStagedComplete));

    const removedIds = $derived.by(() => {
        const cat = mode.kind === 'inactive' ? '' : mode.kind;
        // A silence session is single-subtype (target_key is subtype-free → one
        // stance per gap), so only reconcile removals within the active subtype —
        // never delete the user's other-subtype pause report on submit.
        const sub = mode.kind === 'silence' ? mode.subtype : null;
        const keys = new Set($staged.keys());
        return $currentVerseReports
            .filter(
                (r) =>
                    r.mine &&
                    r.status === 'open' &&
                    r.category === cat &&
                    (sub == null || r.subtype === sub) &&
                    !keys.has(targetCellKey(r.target)),
            )
            .map((r) => r.id);
    });

    /** Toggle a boundary axis: click the active direction again to clear it (the
     *  boundary is fine), or switch to the other direction. Used by timing rows and
     *  the silence pause_boundary row (both carry onset/offset). */
    function setAxis(a: StagedAnnotation, axis: 'onset' | 'offset', dir: TimingDir): void {
        if (a.kind !== 'timing' && !(a.kind === 'silence' && a.subtype === 'pause_boundary')) return;
        focusCell(a.cellKey);
        upsertStaged({ ...a, [axis]: a[axis] === dir ? null : dir });
    }
    function pickRule(a: StagedAnnotation, tag: string): void {
        if (a.kind !== 'tajweed') return;
        focusCell(a.cellKey);
        const sel = a.selectedRuleTags.includes(tag)
            ? a.selectedRuleTags.filter((t) => t !== tag)
            : [...a.selectedRuleTags, tag];
        upsertStaged({ ...a, selectedRuleTags: sel });
    }
    function editComment(a: StagedAnnotation, val: string): void {
        if (a.kind === 'phonemes' || a.kind === 'silence') return; // these carry no comment
        upsertStaged({ ...a, comment: val });
    }
    function removeRow(a: StagedAnnotation, e: MouseEvent): void {
        e.stopPropagation();
        removeStaged(a.cellKey);
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

    const SILENCE_LABELS: Record<string, string> = {
        pause_boundary: 'Pause timing off',
        pause_wasl: "Shouldn't be here",
        pause_missed: 'Missing pause',
    };
    const subtypeLabel = $derived(
        mode.kind === 'tajweed'
            ? mode.subtype === 'wrong_rule'
                ? 'Wrong rule'
                : 'Missing rule'
            : mode.kind === 'silence'
              ? SILENCE_LABELS[mode.subtype]
              : '',
    );
    const headTitle = $derived(
        mode.kind === 'tajweed'
            ? 'Report a tajweed issue'
            : mode.kind === 'phonemes'
              ? 'Report a phoneme issue'
              : mode.kind === 'silence'
                ? 'Report a pause issue'
                : 'Report a timing issue',
    );
    const SILENCE_INSTRUCTIONS: Record<string, string> = {
        pause_boundary: 'Click a highlighted pause, then mark how its start and/or end is off.',
        pause_wasl: "Click any pause that shouldn't be there (the words should connect).",
        pause_missed: 'Click where a pause is missing — a slot between words where the reciter stops.',
    };
    const instruction = $derived(
        mode.kind === 'timing'
            ? 'Click a letter or word, then mark how its start and/or end is off.'
            : mode.kind === 'phonemes'
              ? 'Click any phonemes that are wrong or mislabeled. Click again to remove.'
              : mode.kind === 'silence'
                ? SILENCE_INSTRUCTIONS[mode.subtype]
                : mode.kind === 'tajweed' && mode.subtype === 'wrong_rule'
                  ? 'Highlighted cells carry a rule — click one to flag the wrong rule.'
                  : 'Click any cell where a rule should apply but is missing.',
    );
    const emptyText = $derived(
        mode.kind === 'phonemes'
            ? 'No phonemes flagged yet.'
            : mode.kind === 'silence'
              ? 'No pauses flagged yet.'
              : 'Nothing flagged yet.',
    );
    const submitCount = $derived(stagedList.length + removedIds.length);
</script>

<div class="strip" role="group" aria-label="Report controls">
    <header class="head">
        <div class="title-wrap">
            <span class="flag-ic"><ReportIcon name="flag" size={15} /></span>
            <h3>{headTitle}</h3>
            {#if subtypeLabel}<span class="subtype">{subtypeLabel}</span>{/if}
        </div>
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
            <p class="empty">{emptyText}</p>
        {:else if mode.kind === 'phonemes'}
            <!-- One row per word; each flagged phoneme is a compact removable chip. -->
            <div class="rows" role="list">
                {#each phonemeGroups as g (g.wordIndex)}
                    <div class="prow" role="listitem">
                        <span class="cell-lbl">Word {g.wordIndex + 1}</span>
                        <div class="chips">
                            {#each g.items as a (a.cellKey)}
                                <button
                                    type="button"
                                    class="ph-chip"
                                    title="Remove phoneme"
                                    aria-label="Remove phoneme {chipLabel(a)}"
                                    onclick={(e) => removeRow(a, e)}
                                >
                                    <span class="ph-g">{chipLabel(a)}</span>
                                    <ReportIcon name="trash" size={11} />
                                </button>
                            {/each}
                        </div>
                    </div>
                {/each}
            </div>
        {:else}
            <div class="rows" role="list">
                {#each stagedList as a (a.cellKey)}
                    <div
                        class="row" class:focused={a.cellKey === $focusedCellKey}
                        class:invalid={!isStagedComplete(a)} role="listitem"
                        onfocusin={() => focusCell(a.cellKey)}
                    >
                        <span class="cell-lbl">{cellLabel(a)}</span>
                        {#if a.kind !== 'phonemes'}
                            <div class="ctl">
                                {#if a.kind === 'timing' || (a.kind === 'silence' && a.subtype === 'pause_boundary')}
                                    <span class="axis-cap">Start</span>
                                    <div class="seg" role="group" aria-label="Start boundary">
                                        <button type="button" class="opt" class:on={a.onset === 'early'}
                                            aria-pressed={a.onset === 'early'} onclick={() => setAxis(a, 'onset', 'early')}>early</button>
                                        <button type="button" class="opt" class:on={a.onset === 'late'}
                                            aria-pressed={a.onset === 'late'} onclick={() => setAxis(a, 'onset', 'late')}>late</button>
                                    </div>
                                    <span class="axis-cap">End</span>
                                    <div class="seg" role="group" aria-label="End boundary">
                                        <button type="button" class="opt" class:on={a.offset === 'early'}
                                            aria-pressed={a.offset === 'early'} onclick={() => setAxis(a, 'offset', 'early')}>early</button>
                                        <button type="button" class="opt" class:on={a.offset === 'late'}
                                            aria-pressed={a.offset === 'late'} onclick={() => setAxis(a, 'offset', 'late')}>late</button>
                                    </div>
                                    {#if a.onset || a.offset}
                                        <span class="derived">{timingLabel(a.onset, a.offset)}</span>
                                    {/if}
                                {:else if a.kind === 'silence'}
                                    <!-- Binary subtypes (waṣl / missed) — no control, just the stance. -->
                                    <span class="derived">{SILENCE_LABELS[a.subtype]}</span>
                                {:else if a.subtype === 'wrong_rule' && a.ruleOptions.length > 0}
                                    {#each a.ruleOptions as tag (tag)}
                                        <button
                                            type="button" class="rule" class:on={a.selectedRuleTags.includes(tag)}
                                            aria-pressed={a.selectedRuleTags.includes(tag)}
                                            onclick={() => pickRule(a, tag)}
                                        >{ruleLabel(tag)}</button>
                                    {/each}
                                {:else if a.subtype === 'missing_rule' && a.ruleOptions.length > 0}
                                    <!-- Read-only context: the rules already on the cell. -->
                                    <span class="existing-lbl">Existing:</span>
                                    {#each a.ruleOptions as tag (tag)}
                                        <span class="rule-chip">{ruleLabel(tag)}</span>
                                    {/each}
                                {/if}
                            </div>
                            {#if a.kind !== 'silence'}
                                <!-- Silence reports carry no comment (selection-only). -->
                                <input
                                    class="cmt" type="text"
                                    placeholder={a.kind === 'tajweed' ? 'Comment (required)…' : 'Note (optional)…'}
                                    value={a.comment}
                                    oninput={(e) => editComment(a, e.currentTarget.value)}
                                />
                            {/if}
                        {/if}
                        <button type="button" class="row-x" aria-label="Remove" onclick={(e) => removeRow(a, e)}>
                            <ReportIcon name="trash" size={13} />
                        </button>
                    </div>
                {/each}
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
    .subtype {
        padding: 2px var(--s-2); font-size: var(--fs-meta); font-weight: 600; color: var(--accent);
        background: var(--accent-tint); border-radius: var(--r-2);
    }
    .actions { margin-left: auto; display: inline-flex; gap: var(--s-2); }

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

    .rows { display: flex; flex-direction: column; gap: var(--s-2); }
    .row {
        display: flex; align-items: center; flex-wrap: wrap; gap: var(--s-2);
        padding: var(--s-2); border: 1px solid var(--border-default); border-left: 3px solid var(--border-default);
        border-radius: var(--r-2); background: var(--panel-2);
    }
    .row.focused { border-color: var(--accent); border-left-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-tint); }
    .row.invalid { border-left-color: var(--state-missing-fg); }
    .cell-lbl { font-size: var(--fs-meta); font-weight: 600; color: var(--text-primary); white-space: nowrap; }

    /* Phonemes: a compact word row of removable chips (not one row per phoneme). */
    .prow {
        display: flex; align-items: center; flex-wrap: wrap; gap: var(--s-2);
        padding: var(--s-2); border: 1px solid var(--border-default);
        border-radius: var(--r-2); background: var(--panel-2);
    }
    .chips { display: flex; flex-wrap: wrap; gap: 5px; }
    .ph-chip {
        display: inline-flex; align-items: center; gap: 5px; padding: 2px 5px 2px var(--s-2);
        font: inherit; font-size: var(--fs-meta); color: var(--accent);
        background: var(--accent-tint); border: 1px solid var(--accent);
        border-radius: var(--r-2); cursor: pointer; transition: background var(--t-fast);
    }
    .ph-chip:hover { background: color-mix(in oklab, var(--accent-tint), var(--state-error) 22%); color: var(--state-error); border-color: var(--state-error); }
    .ph-g { font-family: var(--font-mono); line-height: 1.2; }
    .ctl { display: inline-flex; flex-wrap: wrap; gap: 5px; align-items: center; }
    .opt, .rule {
        display: inline-flex; align-items: center; gap: 5px; padding: 3px var(--s-2); font: inherit; font-size: var(--fs-meta);
        color: var(--text-secondary); background: var(--panel); border: 1px solid var(--border-default);
        border-radius: var(--r-2); cursor: pointer; transition: all var(--t-fast);
    }
    .opt:hover, .rule:hover { color: var(--text-primary); border-color: var(--border-strong); }
    .opt.on, .rule.on { color: var(--accent); background: var(--accent-tint); border-color: var(--accent); }

    .axis-cap { font-size: var(--fs-meta); font-weight: 600; color: var(--text-muted); }
    .seg { display: inline-flex; gap: 3px; }
    .derived {
        padding: 2px var(--s-2); font-size: var(--fs-meta); font-weight: 600;
        color: var(--accent); background: var(--accent-tint); border-radius: var(--r-2);
    }

    .existing-lbl { font-size: var(--fs-meta); color: var(--text-muted); }
    .rule-chip {
        display: inline-flex; align-items: center; padding: 3px var(--s-2); font-size: var(--fs-meta);
        color: var(--text-secondary); background: var(--panel); border: 1px dashed var(--border-default);
        border-radius: var(--r-2);
    }

    .cmt {
        flex: 1 1 140px; min-width: 110px; padding: 4px var(--s-2); color: var(--text-primary);
        background: var(--canvas-inset); border: 1px solid var(--border-default); border-radius: var(--r-2);
        font: inherit; font-size: var(--fs-body);
    }
    .cmt::placeholder { color: var(--text-faint); }
    .cmt:focus-visible { outline: none; border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-tint); }
    .row-x {
        display: inline-flex; align-items: center; padding: 3px; background: transparent; border: 0;
        color: var(--text-muted); cursor: pointer;
    }
    .row-x:hover { color: var(--state-error); }
    .err { margin: 0; color: var(--state-error); font-size: var(--fs-meta); }
</style>
