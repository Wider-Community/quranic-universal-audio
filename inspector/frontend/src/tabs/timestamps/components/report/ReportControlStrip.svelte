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
    import * as m from '$lib/paraglide/messages';
    import { i18n } from '$lib/i18n/locale.svelte';
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
    import { pushToast } from '../../../../lib/stores/toast';
    import ReportIcon from './ReportIcon.svelte';

    let busy = $state(false);
    let error = $state('');

    const mode = $derived($reportMode);
    const stagedList = $derived([...$staged.values()]);

    function ruleLabel(tag: string): string {
        return badgeForTag(tag)?.tooltip() ?? silentTooltip(tag) ?? tag;
    }

    function cellLabel(a: StagedAnnotation): string {
        const wordIndex = 'wordIndex' in a ? a.wordIndex : a.gapWordIndex;
        const w = Math.max(0, wordIndex) + 1;
        if (a.target.kind === 'boundary') return m.ts_report_strip_gap_pause_label({ w });
        if (a.target.kind === 'word') return m.ts_report_strip_word_label({ w });
        return m.ts_report_strip_cell_label({
            w,
            cell: a.target.target_id,
        });
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
        return a.target.kind === 'bridge' ? 'merger' : '•';
    }
    // Attribute/text labels gated on i18n.locale so they re-render on a locale switch.
    const groupAriaLabel = $derived((i18n.locale, m.ts_report_strip_group_aria_label()));
    const cancelLabel = $derived((i18n.locale, m.common_action_cancel()));
    const removePhonemeTitle = $derived((i18n.locale, m.ts_report_strip_remove_phoneme_title()));
    const startBoundaryAriaLabel = $derived((i18n.locale, m.ts_report_strip_start_boundary_aria_label()));
    const endBoundaryAriaLabel = $derived((i18n.locale, m.ts_report_strip_end_boundary_aria_label()));
    const axisStartLabel = $derived((i18n.locale, m.ts_report_strip_axis_start_label()));
    const axisEndLabel = $derived((i18n.locale, m.ts_report_strip_axis_end_label()));
    const axisEarlyOption = $derived((i18n.locale, m.ts_report_strip_axis_early_option()));
    const axisLateOption = $derived((i18n.locale, m.ts_report_strip_axis_late_option()));
    const existingLabel = $derived((i18n.locale, m.ts_report_strip_existing_label()));
    const commentRequiredPlaceholder = $derived((i18n.locale, m.ts_report_strip_comment_required_placeholder()));
    const noteOptionalPlaceholder = $derived((i18n.locale, m.ts_report_strip_note_optional_placeholder()));
    const removeAriaLabel = $derived((i18n.locale, m.ts_report_strip_remove_aria_label()));

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

    // Submittable when every staged item is complete AND there's at least one
    // change to persist — a staged create or a pending removal (so a session that
    // removes all its seeded reports can still commit the deletions).
    const canSubmit = $derived(
        stagedList.every(isStagedComplete) && (stagedList.length > 0 || removedIds.length > 0),
    );

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

    const SUBTEXT: Partial<Record<string, () => string>> = {
        timing: m.ts_report_thanks_subtext_timing,
        silence: m.ts_report_thanks_subtext_silence,
    };

    async function submit(): Promise<void> {
        if (!canSubmit || busy) return;
        const ctx = $reportContext;
        if (!ctx) return;
        busy = true;
        error = '';
        const res = await submitReportSession(ctx.slug, ctx.verseKey, stagedList, removedIds);
        busy = false;
        if (res.ok) {
            await loadVerseReports(ctx.slug, ctx.verseKey);
            await loadReciterReports(ctx.slug);
            if (stagedList.length > 0) {
                const sub = SUBTEXT[mode.kind]?.() ?? '';
                pushToast({ kind: 'success', text: `${m.ts_report_thanks_toast()}${sub ? ' ' + sub : ''}` });
            }
            exitReportMode();
        } else {
            error = res.error ?? m.ts_report_submit_failed_fallback();
        }
    }

    const SILENCE_LABELS: Record<string, () => string> = {
        pause_boundary: m.ts_report_silence_pause_boundary_label,
        pause_wasl: m.ts_report_silence_pause_wasl_label,
        pause_missed: m.ts_report_silence_pause_missed_label,
    };
    const subtypeLabel = $derived(
        mode.kind === 'tajweed'
            ? mode.subtype === 'wrong_rule'
                ? m.ts_report_tajweed_wrong_rule_label()
                : m.ts_report_tajweed_missing_rule_label()
            : mode.kind === 'silence'
              ? (SILENCE_LABELS[mode.subtype]?.() ?? '')
              : '',
    );
    const headTitle = $derived(
        mode.kind === 'tajweed'
            ? m.ts_report_strip_head_title_tajweed()
            : mode.kind === 'phonemes'
              ? m.ts_report_strip_head_title_phonemes()
              : mode.kind === 'silence'
                ? m.ts_report_strip_head_title_silence()
                : m.ts_report_strip_head_title_timing(),
    );
    const SILENCE_INSTRUCTIONS: Record<string, () => string> = {
        pause_boundary: m.ts_report_strip_instruction_pause_boundary,
        pause_wasl: m.ts_report_strip_instruction_pause_wasl,
        pause_missed: m.ts_report_strip_instruction_pause_missed,
    };
    const instruction = $derived(
        mode.kind === 'timing'
            ? m.ts_report_strip_instruction_timing()
            : mode.kind === 'phonemes'
              ? m.ts_report_strip_instruction_phonemes()
              : mode.kind === 'silence'
                ? (SILENCE_INSTRUCTIONS[mode.subtype]?.() ?? '')
                : mode.kind === 'tajweed' && mode.subtype === 'wrong_rule'
                  ? m.ts_report_strip_instruction_tajweed_wrong_rule()
                  : m.ts_report_strip_instruction_tajweed_missing_rule(),
    );
    const emptyText = $derived(
        mode.kind === 'phonemes'
            ? m.ts_report_strip_empty_phonemes()
            : mode.kind === 'silence'
              ? m.ts_report_strip_empty_silence()
              : m.ts_report_strip_empty_default(),
    );
    const submitCount = $derived(stagedList.length + removedIds.length);
    const submitLabel = $derived(
        busy
            ? m.ts_report_strip_saving_label()
            : stagedList.length === 0 && removedIds.length > 0
              ? m.ts_report_strip_confirm_delete_label({ count: removedIds.length })
              : m.ts_report_strip_submit_label({ count: submitCount }),
    );
</script>

<div class="strip" role="group" aria-label={groupAriaLabel}>
    <header class="head">
        <div class="title-wrap">
            <span class="flag-ic"><ReportIcon name="flag" size={15} /></span>
            <h3>{headTitle}</h3>
            {#if subtypeLabel}<span class="subtype">{subtypeLabel}</span>{/if}
        </div>
        <div class="actions">
            <button type="button" class="btn ghost" onclick={exitReportMode} disabled={busy}>{cancelLabel}</button>
            <button type="button" class="btn primary" onclick={submit} disabled={!canSubmit || busy}>
                {submitLabel}
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
                        <span class="cell-lbl">{m.ts_report_strip_word_label({ w: g.wordIndex + 1 })}</span>
                        <div class="chips">
                            {#each g.items as a (a.cellKey)}
                                <button
                                    type="button"
                                    class="ph-chip"
                                    title={removePhonemeTitle}
                                    aria-label={m.ts_report_strip_remove_phoneme_aria_label({ glyph: chipLabel(a) })}
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
                                    <span class="axis-cap">{axisStartLabel}</span>
                                    <div class="seg" role="group" aria-label={startBoundaryAriaLabel}>
                                        <button type="button" class="opt" class:on={a.onset === 'early'}
                                            aria-pressed={a.onset === 'early'} onclick={() => setAxis(a, 'onset', 'early')}>{axisEarlyOption}</button>
                                        <button type="button" class="opt" class:on={a.onset === 'late'}
                                            aria-pressed={a.onset === 'late'} onclick={() => setAxis(a, 'onset', 'late')}>{axisLateOption}</button>
                                    </div>
                                    <span class="axis-cap">{axisEndLabel}</span>
                                    <div class="seg" role="group" aria-label={endBoundaryAriaLabel}>
                                        <button type="button" class="opt" class:on={a.offset === 'early'}
                                            aria-pressed={a.offset === 'early'} onclick={() => setAxis(a, 'offset', 'early')}>{axisEarlyOption}</button>
                                        <button type="button" class="opt" class:on={a.offset === 'late'}
                                            aria-pressed={a.offset === 'late'} onclick={() => setAxis(a, 'offset', 'late')}>{axisLateOption}</button>
                                    </div>
                                    {#if a.onset || a.offset}
                                        <span class="derived">{timingLabel(a.onset, a.offset)}</span>
                                    {/if}
                                {:else if a.kind === 'silence'}
                                    <!-- Binary subtypes (waṣl / missed) — no control, just the stance. -->
                                    <span class="derived">{SILENCE_LABELS[a.subtype]?.() ?? ''}</span>
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
                                    <span class="existing-lbl">{existingLabel}</span>
                                    {#each a.ruleOptions as tag (tag)}
                                        <span class="rule-chip">{ruleLabel(tag)}</span>
                                    {/each}
                                {/if}
                            </div>
                            {#if a.kind !== 'silence'}
                                <!-- Silence reports carry no comment (selection-only). -->
                                <input
                                    class="cmt" type="text"
                                    placeholder={a.kind === 'tajweed' ? commentRequiredPlaceholder : noteOptionalPlaceholder}
                                    value={a.comment}
                                    oninput={(e) => editComment(a, e.currentTarget.value)}
                                />
                            {/if}
                        {/if}
                        <button type="button" class="row-x" aria-label={removeAriaLabel} onclick={(e) => removeRow(a, e)}>
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
    .actions { margin-inline-start: auto; display: inline-flex; gap: var(--s-2); }

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
        padding: var(--s-2); border: 1px solid var(--border-default); border-inline-start: 3px solid var(--border-default);
        border-radius: var(--r-2); background: var(--panel-2);
    }
    .row.focused { border-color: var(--accent); border-inline-start-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-tint); }
    .row.invalid { border-inline-start-color: var(--state-missing-fg); }
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
