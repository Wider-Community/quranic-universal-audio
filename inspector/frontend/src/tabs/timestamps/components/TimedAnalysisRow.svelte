<script lang="ts">
    import {
        AnalysisRow,
        parse,
        stripBoundaryMarks,
    } from '@quranic-phonemizer/cells';
    import { get } from 'svelte/store';
    import { tick } from 'svelte';

    import { dashPort } from '../../../lib/playback/dash-port';
    import { nativePayload } from '../../../lib/types/ts-client';
    import { i18n } from '$lib/i18n/locale.svelte';
    import {
        highlightWipe,
        showLetters,
        showPhonemes,
        showTranslations,
        tsHoveredElement,
        tsWaveformHoverTime,
        verseTranslations,
    } from '../stores/display';
    import { focusWaslGroup, loadedVerse } from '../stores/verse';
    import { loopTarget } from '../stores/playback';
    import {
        focusCell,
        focusedCellKey,
        reportMode,
        staged,
        upsertStaged,
    } from '../stores/report-mode';
    import { currentVerseReports } from '../stores/ts-reports';
    import { tajweedSettings } from '../stores/tajweed-settings';
    import { TS_CLICK_DELAY_MS } from '../utils/constants';
    import {
        buildTimedEntityCache,
        type ParsedReading,
        type TimedEntity,
    } from '../utils/timed-entities';
    import { defineInspectorRule } from '../utils/tajweed-rules';
    import {
        cellTargetFromEl,
        ruleIdsFromEl,
        targetCellKey,
    } from '../utils/report-target';
    import WordTranslation from './WordTranslation.svelte';

    let root: HTMLDivElement;
    let entities: TimedEntity[] = [];
    let entityByElement = new Map<HTMLElement, TimedEntity>();
    let clickTimer: ReturnType<typeof setTimeout> | null = null;

    const displayData = $derived($focusWaslGroup?.data ?? $loadedVerse?.data ?? null);
    const focusRef = $derived($focusWaslGroup?.focusRef ?? $loadedVerse?.data.verse_ref ?? '');
    const disabled = $derived(new Set(
        Object.entries($tajweedSettings).filter(([, value]) => !value.enabled).map(([key]) => key),
    ));

    const parsed = $derived.by((): ParsedReading[] => {
        void i18n.locale;
        const data = displayData;
        const text = new Map(data?.words.map((word) => [word.location, word.display_text]) ?? []);
        return data?.native.map((reading) => {
            const result = parse(nativePayload(reading), defineInspectorRule, {
                iqlabTanween: 'mini-meem',
                iqlabNoon: 'mini-meem',
                openTanween: true,
            });
            result.context.disabled = disabled;
            result.view.words.forEach((word, index) => {
                const boundary = result.view.boundaries[index];
                word.display_text = stripBoundaryMarks(text.get(word.location) ?? word.display_text, boundary);
            });
            return { reading, ...result };
        }) ?? [];
    });

    const verseOf = (location: string): string => location.split(':').slice(0, 2).join(':');
    const wordClass = (word: { location: string }): string =>
        verseOf(word.location) === focusRef ? '' : 'qc-context';

    function offsetSeconds(): number {
        const group = get(focusWaslGroup);
        if (group) return group.span[0] / 1000;
        return get(loadedVerse)?.tsSegOffset ?? 0;
    }

    function rebuildCache(): void {
        const cache = buildTimedEntityCache(
            root,
            parsed,
            displayData?.words ?? [],
            offsetSeconds(),
        );
        entities = cache.entities;
        entityByElement = cache.byElement;
        for (const entity of entities) {
            entity.element.tabIndex = 0;
            entity.element.setAttribute('role', 'button');
        }
    }

    function updateReportClasses(): void {
        const reports = new Map($currentVerseReports
            .filter((report) => report.status === 'open')
            .map((report) => [targetCellKey(report.target), report]));
        for (const entity of entities) {
            const key = `${entity.readingId}:${entity.kind}:${entity.id}`;
            const report = reports.get(key);
            entity.element.classList.toggle('report-flag-public', Boolean(report));
            entity.element.classList.toggle('report-flag-staged', $staged.has(key));
            entity.element.classList.toggle('report-focused', $focusedCellKey === key);
            if (report) entity.element.dataset.qcReportCategory = report.category;
            else delete entity.element.dataset.qcReportCategory;
        }
    }

    function updateLoopClasses(): void {
        const target = $loopTarget;
        for (const entity of entities) {
            const kindMatches = target?.kind === 'word' ? entity.kind === 'word'
                : target?.kind === 'phoneme' ? entity.kind === 'sound' || entity.kind === 'bridge'
                : entity.kind === 'column' || entity.kind === 'group';
            const spanMatches = target
                && Math.abs(entity.start - target.startSec) < 0.001
                && Math.abs(entity.end - target.endSec) < 0.001;
            entity.element.classList.toggle(
                'loop', Boolean(target && kindMatches && spanMatches && entity.wordIndex === target.wordIndex),
            );
        }
    }

    $effect(() => {
        void parsed;
        void displayData;
        void tick().then(() => {
            rebuildCache();
            updateReportClasses();
            updateLoopClasses();
        });
    });

    $effect(() => {
        void $currentVerseReports;
        void $staged;
        void $focusedCellKey;
        updateReportClasses();
    });

    $effect(() => {
        void $loopTarget;
        updateLoopClasses();
    });

    function currentTime(): number {
        const hover = get(tsWaveformHoverTime);
        if (hover != null && dashPort.paused) return hover;
        return dashPort.currentTimeMs() / 1000 - offsetSeconds();
    }

    export function updateHighlights(): void {
        const time = currentTime();
        const wipe = get(highlightWipe);
        for (const entity of entities) {
            const active = time >= entity.start && time < entity.end;
            entity.element.classList.toggle('active', active);
            if (entity.kind === 'word') entity.element.classList.toggle('past', time >= entity.end);
            if (wipe && active) {
                const fill = (time - entity.start) / Math.max(entity.end - entity.start, 0.001);
                entity.element.style.setProperty('--fill', String(Math.max(0, Math.min(fill, 1))));
            } else entity.element.style.removeProperty('--fill');
        }
        root?.classList.toggle('in-pause', entities.some((entity) =>
            entity.kind === 'boundary' && time >= entity.start && time < entity.end,
        ));
    }

    export function scrollActiveIntoView(): void {
        root?.querySelector<HTMLElement>('[data-qc-word-id].active')
            ?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    function entityOf(target: EventTarget | null): TimedEntity | null {
        let element = target instanceof HTMLElement ? target : null;
        while (element && element !== root) {
            const entity = entityByElement.get(element);
            if (entity) return entity;
            element = element.parentElement;
        }
        return null;
    }

    function seek(entity: TimedEntity): void {
        dashPort.seek((entity.start + offsetSeconds()) * 1000);
        if (dashPort.paused) dashPort.play();
        updateHighlights();
    }

    function loopFor(entity: TimedEntity) {
        return {
            kind: entity.kind === 'sound' || entity.kind === 'bridge' ? 'phoneme' as const
                : entity.kind === 'word' ? 'word' as const : 'letter' as const,
            startSec: entity.start,
            endSec: entity.end,
            wordIndex: entity.wordIndex,
            childIndex: entity.childIndex,
        };
    }

    function sameLoop(entity: TimedEntity): boolean {
        const current = get(loopTarget);
        const next = loopFor(entity);
        return current?.kind === next.kind
            && current.wordIndex === next.wordIndex
            && Math.abs(current.startSec - next.startSec) < 0.001
            && Math.abs(current.endSec - next.endSec) < 0.001;
    }

    function stageReport(targetElement: Element, entity: TimedEntity): boolean {
        const mode = get(reportMode);
        if (mode.kind === 'inactive') return false;
        if (targetElement.closest('.qc-context')) return true;
        const target = cellTargetFromEl(targetElement);
        if (!target) return true;
        const cellKey = targetCellKey(target);
        if (get(staged).has(cellKey)) {
            focusCell(cellKey);
            updateReportClasses();
            return true;
        }
        if (mode.kind === 'timing') {
            if (!['word', 'column', 'group', 'sound', 'bridge'].includes(target.kind)) return true;
            upsertStaged({
                kind: 'timing', cellKey, target, wordIndex: entity.wordIndex,
                onset: null, offset: null, comment: '',
            });
            loopTarget.set(loopFor(entity));
        } else if (mode.kind === 'tajweed') {
            if (!['column', 'group', 'bridge'].includes(target.kind)) return true;
            const rules = ruleIdsFromEl(targetElement);
            if (mode.subtype === 'wrong_rule' && rules.length === 0) return true;
            upsertStaged({
                kind: 'tajweed', cellKey, target, subtype: mode.subtype,
                wordIndex: entity.wordIndex, ruleOptions: rules,
                selectedRuleTags: [], comment: '',
            });
        } else if (mode.kind === 'phonemes') {
            if (target.kind !== 'sound' && target.kind !== 'bridge') return true;
            upsertStaged({
                kind: 'phonemes', cellKey, target, wordIndex: entity.wordIndex,
                glyph: entity.element.textContent?.trim() ?? '',
            });
        } else {
            if (target.kind !== 'boundary') return true;
            upsertStaged({
                kind: 'silence', cellKey, target, gapWordIndex: entity.wordIndex,
                subtype: mode.subtype, onset: null, offset: null,
            });
        }
        focusCell(cellKey);
        updateReportClasses();
        return true;
    }

    function onClick(event: MouseEvent): void {
        const entity = entityOf(event.target);
        if (!entity) return;
        if (event.target instanceof Element && stageReport(event.target, entity)) return;
        if (entity.kind === 'boundary') return;
        if (clickTimer) clearTimeout(clickTimer);
        clickTimer = setTimeout(() => {
            if (get(loopTarget)) loopTarget.set(loopFor(entity));
            seek(entity);
        }, TS_CLICK_DELAY_MS);
    }

    function onDoubleClick(event: MouseEvent): void {
        const entity = entityOf(event.target);
        if (!entity || entity.kind === 'boundary') return;
        if (clickTimer) clearTimeout(clickTimer);
        if (sameLoop(entity)) loopTarget.set(null);
        else {
            loopTarget.set(loopFor(entity));
            seek(entity);
        }
    }

    function onKeyDown(event: KeyboardEvent): void {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        const entity = entityOf(event.target);
        if (!entity) return;
        event.preventDefault();
        if (event.target instanceof Element && stageReport(event.target, entity)) return;
        if (entity.kind === 'boundary') return;
        if (event.key === ' ') {
            if (sameLoop(entity)) loopTarget.set(null);
            else loopTarget.set(loopFor(entity));
        }
        seek(entity);
    }

    function onPointerOver(event: PointerEvent): void {
        const entity = entityOf(event.target);
        if (!entity) return;
        tsHoveredElement.set({
            kind: entity.kind === 'sound' || entity.kind === 'bridge' ? 'phoneme' :
                entity.kind === 'word' ? 'word' : 'letter',
            startSec: entity.start,
            endSec: entity.end,
        });
    }

    function onPointerLeave(): void {
        tsHoveredElement.set(null);
    }
</script>

{#snippet addon(word: { location: string })}
    {#if $showTranslations}
        <WordTranslation text={$verseTranslations[word.location] ?? ''} />
    {/if}
{/snippet}

<div
    class="timed-analysis"
    role="toolbar"
    class:no-letters={!$showLetters}
    class:no-phonemes={!$showPhonemes}
    class:hl-track={$highlightWipe}
    class:report-mode={$reportMode.kind !== 'inactive'}
    bind:this={root}
    tabindex="-1"
    onclick={onClick}
    ondblclick={onDoubleClick}
    onkeydown={onKeyDown}
    onpointerover={onPointerOver}
    onpointerleave={onPointerLeave}
>
    {#each parsed as item, index (item.reading.id)}
        <div class="timed-reading" data-reading-id={item.reading.id} data-reading-index={index}>
            <AnalysisRow
                view={item.view}
                context={item.context}
                crossWordMergers="compact"
                verseFlow="inline"
                showTooltips={true}
                hostClasses={{ word: wordClass }}
                wordAddon={addon}
            />
        </div>
    {/each}
</div>
