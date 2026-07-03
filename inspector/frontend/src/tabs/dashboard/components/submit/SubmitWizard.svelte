<script lang="ts">
    /**
     * Submit-recitation wizard shell — modal + step orchestration + motion.
     *
     * Owns its own modal chrome (rather than wrapping the global Modal
     * component) because the wizard's dimensions, padding, and stepper
     * header are distinct from the bigger reciter-detail modal. Focus
     * trap, Esc-to-close, and body scroll lock mirror Modal.svelte.
     *
     * Submit posts the built payload to the intake API (submitIntake);
     * on success it toasts and closes, surfacing any backend warnings.
     */
    import { onDestroy, tick } from 'svelte';
    import { fade, fly } from 'svelte/transition';

    import { localeStore, tr } from '$lib/i18n/locale-store';
    import * as m from '$lib/paraglide/messages';
    import { submitIntake } from '../../../../lib/api/submit-recitation';
    import { pushToast } from '../../../../lib/stores/toast';
    import type { IntakeSubmission } from '../../../../lib/types/generated/schemas';
    import { countryByName } from '../../../../lib/utils/countries';
    import { isPlausibleUrl } from '../../../../lib/utils/url';
    import { openDetail } from '../../stores/dashboard-state';
    import {
        closeSubmitWizard,
        setStep,
        submitWizard,
        type WizardStep,
    } from '../../stores/submit-wizard';
    import StepConfirm from './StepConfirm.svelte';
    import StepDetails from './StepDetails.svelte';
    import StepReciter from './StepReciter.svelte';
    import StepSource from './StepSource.svelte';

    let modalEl: HTMLDivElement | null = null;
    let previouslyFocused: HTMLElement | null = null;
    let scrollLocked = false;

    $: state = $submitWizard;
    $: open = state.open;
    $: void manageOpen(open);

    $: lang = $localeStore;
    $: closeLabel = tr(lang, m.common_action_close());
    $: backLabel = tr(lang, m.common_action_back());
    $: cancelLabel = tr(lang, m.common_action_cancel());
    $: continueLabel = tr(lang, m.common_action_continue());
    $: submitLabel = tr(lang, submitting ? m.common_status_submitting() : m.common_action_submit());
    $: wizardAria = tr(lang, m.dashboard_submit_wizard_aria());
    $: wizardTitle = tr(lang, m.dashboard_submit_wizard_title());
    $: stepperAria = tr(lang, m.dashboard_submit_stepper_aria());
    $: requestLabel = tr(lang, m.dashboard_submit_request_button());
    $: stepLabel = ((_l: unknown) => (n: number): string =>
        n === 1
            ? m.dashboard_submit_step_reciter()
            : n === 2
              ? m.dashboard_submit_step_source()
              : n === 3
                ? m.dashboard_submit_step_details()
                : m.dashboard_submit_step_confirm())(lang);

    async function manageOpen(o: boolean): Promise<void> {
        if (o) {
            previouslyFocused = document.activeElement as HTMLElement | null;
            lockScroll();
            await tick();
            focusFirst();
        } else {
            unlockScroll();
            previouslyFocused?.focus?.();
            previouslyFocused = null;
        }
    }

    function lockScroll(): void {
        if (scrollLocked) return;
        scrollLocked = true;
        document.body.style.overflow = 'hidden';
    }
    function unlockScroll(): void {
        if (!scrollLocked) return;
        scrollLocked = false;
        document.body.style.overflow = '';
    }
    function focusFirst(): void {
        if (!modalEl) return;
        const focusable = getFocusable();
        (focusable[0] ?? modalEl).focus();
    }
    function getFocusable(): HTMLElement[] {
        if (!modalEl) return [];
        return Array.from(
            modalEl.querySelectorAll<HTMLElement>(
                'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
            ),
        );
    }
    function onKey(e: KeyboardEvent): void {
        if (e.key === 'Escape') {
            e.preventDefault();
            closeSubmitWizard();
            return;
        }
        if (e.key !== 'Tab') return;
        const focusable = getFocusable();
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (!first || !last) { e.preventDefault(); return; }
        const active = document.activeElement as HTMLElement | null;
        if (e.shiftKey && active === first) {
            e.preventDefault();
            last.focus();
        } else if (!e.shiftKey && active === last) {
            e.preventDefault();
            first.focus();
        }
    }
    function onBackdropClick(e: MouseEvent): void {
        if (e.target === e.currentTarget) closeSubmitWizard();
    }

    // ---- step navigation ----

    $: step = state.step as WizardStep;

    // Track direction of last step transition so the fly transition slides
    // the right way.
    let prevStep: WizardStep = 1;
    let dir: 1 | -1 = 1;
    $: {
        if (step !== prevStep) {
            dir = step > prevStep ? 1 : -1;
            prevStep = step;
        }
    }

    $: canAdvanceStep1 = (() => {
        if (state.reciterMode === 'existing_combo') {
            return !!state.existingReciterSlug && !!state.existingComboSlug;
        }
        if (state.reciterMode === 'existing_reciter') {
            return !!state.existingReciterSlug;
        }
        return state.newReciter.name_en.trim().length > 0;
    })();
    // Step 2 gates on valid URLs (the hard errors the backend would reject) but
    // NOT on full 114-chapter coverage — missing chapters are an allowed warning.
    $: linksFilled = state.links.filter((r) => r.url.trim().length > 0);
    $: anyMalformed = linksFilled.some((r) => !isPlausibleUrl(r.url));
    $: canAdvanceStep2 =
        state.sourceMethod === 'playlist'
            ? isPlausibleUrl(state.playlistUrl)
            : state.sourceMethod === 'links' && linksFilled.length > 0 && !anyMalformed;
    $: canAdvanceStep3 = !!state.combination.riwayah && !!state.combination.style;
    $: canSubmit =
        state.attestations.distribution_rights &&
        state.attestations.links_verified &&
        state.attestations.storage_rights &&
        (state.sourceMethod !== 'playlist' || state.attestations.playlist_public);
    // existing_combo skips source + details — the canonical edit path lives in
    // RequestForm. We don't need step 2/3/4 for that mode.
    $: skipSourceAndDetails = state.reciterMode === 'existing_combo';

    /** Whether step n is reachable given the gates for the steps before it. */
    function canReach(n: number): boolean {
        if (n <= 1) return true;
        if (n === 2) return canAdvanceStep1;
        if (n === 3) return canAdvanceStep1 && canAdvanceStep2;
        return canAdvanceStep1 && canAdvanceStep2 && canAdvanceStep3;
    }
    function goToStep(n: number): void {
        if (n === step) return;
        if (n < step || canReach(n)) setStep(n as WizardStep);
    }

    function next(): void {
        if (step === 1 && canAdvanceStep1) setStep(2);
        else if (step === 2 && canAdvanceStep2) setStep(3);
        else if (step === 3 && canAdvanceStep3) setStep(4);
    }
    function back(): void {
        if (step === 2) setStep(1);
        else if (step === 3) setStep(2);
        else if (step === 4) setStep(3);
    }
    function requestExistingCombo(): void {
        // existing_combo path: hand off to the reciter-detail's RequestForm
        // for the picked combination. ReciterDetail auto-opens the form when
        // `openRequest` is true, matching the modal users get from the
        // "Request alignment" button inside the detail view.
        const reciterId = state.existingReciterSlug;
        const comboSlug = state.existingComboSlug;
        if (!reciterId || !comboSlug) return;
        closeSubmitWizard();
        openDetail(reciterId, comboSlug, { openRequest: true });
    }

    // ---- submit ----

    let submitting = false;
    let submitErrors: string[] = [];

    function buildPayload(): IntakeSubmission {
        const kind =
            state.reciterMode === 'new' ? 'new_reciter' : 'existing_reciter_new_combo';
        const c = state.combination;
        const proposed_edits: IntakeSubmission['proposed_edits'] = {
            riwayah: c.riwayah || null,
            style: c.style || null,
            recording_context: c.recording_context || null,
            recording_year: c.recording_year === '' ? null : Number(c.recording_year),
        };
        if (kind === 'new_reciter') {
            proposed_edits.name_en = state.newReciter.name_en.trim() || null;
            proposed_edits.name_ar = state.newReciter.name_ar.trim() || null;
            proposed_edits.country =
                countryByName(state.newReciter.countryName)?.code ?? null;
        }
        const links = state.links
            .filter((r) => r.url.trim().length > 0)
            .map((r) => ({ chapter: r.chapter, url: r.url.trim() }));
        return {
            kind,
            reciter_id: kind === 'existing_reciter_new_combo' ? state.existingReciterSlug : null,
            proposed_edits,
            source: {
                method: state.sourceMethod ?? 'links',
                links,
                playlist_url: state.playlistUrl.trim() || null,
            },
            comments: state.comments.trim() || null,
            auto_claim: state.autoClaim,
            attestations: { ...state.attestations },
        };
    }

    async function submit(): Promise<void> {
        if (submitting) return;
        submitting = true;
        submitErrors = [];
        try {
            const result = await submitIntake(buildPayload());
            if (!result.ok) {
                submitErrors = result.errors ?? [m.dashboard_submit_failed_fallback()];
                return;
            }
            for (const w of result.warnings) {
                pushToast({ kind: 'warn', text: w, ttl: 7000 });
            }
            pushToast({
                kind: 'success',
                text: m.dashboard_submit_queued_toast(),
            });
            closeSubmitWizard();
        } catch (e) {
            submitErrors = [e instanceof Error ? e.message : m.dashboard_submit_failed_fallback()];
        } finally {
            submitting = false;
        }
    }

    onDestroy(() => unlockScroll());
</script>

{#if open}
    <div
        class="backdrop"
        role="presentation"
        on:click={onBackdropClick}
        on:keydown={onKey}
        transition:fade={{ duration: 160 }}
    >
        <div
            class="wizard"
            bind:this={modalEl}
            role="dialog"
            aria-modal="true"
            aria-label={wizardAria}
            tabindex="-1"
            in:fly={{ y: 12, duration: 280, opacity: 0 }}
            out:fly={{ y: 6, duration: 180, opacity: 0 }}
        >
            <header>
                <div class="title-row">
                    <h2>{wizardTitle}</h2>
                    <button
                        type="button"
                        class="close"
                        aria-label={closeLabel}
                        on:click={closeSubmitWizard}
                    >×</button>
                </div>
                {#if !skipSourceAndDetails}
                    <ol class="stepper" aria-label={stepperAria}>
                        {#each [1, 2, 3, 4] as n (n)}
                            <li
                                class="dot"
                                class:done={n < step}
                                class:active={n === step}
                                class:reachable={canReach(n)}
                                aria-current={n === step ? 'step' : undefined}
                            >
                                <button
                                    type="button"
                                    class="dot-btn"
                                    disabled={!canReach(n) && n > step}
                                    on:click={() => goToStep(n)}
                                >
                                    <span class="dot-num">{n}</span>
                                    <span class="dot-label">{stepLabel(n)}</span>
                                </button>
                            </li>
                        {/each}
                        <span class="stepper-track" data-step={step} aria-hidden="true"></span>
                    </ol>
                {/if}
            </header>

            <div class="body">
                {#key step}
                    <div
                        class="step-wrap"
                        in:fly={{ x: dir * 14, duration: 220, opacity: 0 }}
                        out:fly={{ x: -dir * 14, duration: 180, opacity: 0 }}
                    >
                        {#if step === 1}
                            <StepReciter />
                        {:else if step === 2}
                            <StepSource />
                        {:else if step === 3}
                            <StepDetails />
                        {:else}
                            <StepConfirm />
                        {/if}
                    </div>
                {/key}
            </div>

            {#if submitErrors.length > 0}
                <div class="submit-errors" role="alert" transition:fade={{ duration: 140 }}>
                    {#each submitErrors as err (err)}
                        <span>{err}</span>
                    {/each}
                </div>
            {/if}

            <footer>
                <div class="left">
                    {#if step > 1}
                        <button type="button" class="ghost" on:click={back} disabled={submitting}>{backLabel}</button>
                    {/if}
                </div>
                <div class="right">
                    <button type="button" class="ghost" on:click={closeSubmitWizard}>{cancelLabel}</button>
                    {#if skipSourceAndDetails}
                        <!-- existing_combo mode: skip steps 2-4 and hand off
                             straight to the RequestForm hosted by ReciterDetail
                             for the picked combination. -->
                        <button
                            type="button"
                            class="primary"
                            on:click={requestExistingCombo}
                            disabled={!canAdvanceStep1}
                        >
                            {requestLabel}
                            <span class="primary-glyph" aria-hidden="true">›</span>
                        </button>
                    {:else if step < 4}
                        <button
                            type="button"
                            class="primary"
                            on:click={next}
                            disabled={step === 1
                                ? !canAdvanceStep1
                                : step === 2
                                  ? !canAdvanceStep2
                                  : !canAdvanceStep3}
                        >
                            {continueLabel}
                            <span class="primary-glyph" aria-hidden="true">›</span>
                        </button>
                    {:else}
                        <button
                            type="button"
                            class="primary"
                            on:click={submit}
                            disabled={!canSubmit || submitting}
                        >
                            {submitLabel}
                        </button>
                    {/if}
                </div>
            </footer>
        </div>
    </div>
{/if}

<style>
    .backdrop {
        position: fixed;
        inset: 0;
        background: oklch(0.06 0.005 268 / 0.72);
        backdrop-filter: blur(3px);
        z-index: 120;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: var(--s-6);
    }
    .wizard {
        width: min(760px, 94vw);
        max-height: min(88vh, 880px);
        background: var(--canvas);
        border: 1px solid var(--border-default);
        border-radius: var(--r-3);
        display: flex;
        flex-direction: column;
        overflow: hidden;
        box-shadow: 0 32px 80px oklch(0 0 0 / 0.45),
                    0 2px 8px oklch(0 0 0 / 0.3);
    }

    header {
        padding: var(--s-4) var(--s-6) var(--s-2);
        border-bottom: 1px solid var(--border-quiet);
        background: linear-gradient(to bottom, var(--panel), var(--canvas));
    }
    .title-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
    }
    h2 {
        margin: 0;
        font-size: var(--fs-h3);
        font-weight: 500;
        color: var(--text-primary);
    }
    .close {
        width: 30px;
        height: 30px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        color: var(--text-muted);
        border-radius: var(--r-2);
        font-size: 18px;
        line-height: 1;
        transition: color var(--t-fast), background var(--t-fast);
    }
    .close:hover {
        color: var(--text-primary);
        background: var(--panel);
    }

    .stepper {
        position: relative;
        list-style: none;
        margin: var(--s-3) 0 var(--s-1);
        padding: 0;
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: var(--s-2);
    }
    .stepper-track {
        position: absolute;
        bottom: -3px;
        inset-inline-start: 0;
        width: calc(100% / 4);
        height: 2px;
        background: var(--accent);
        border-radius: 2px;
        transition: transform var(--t-slow) var(--ease-out-expo);
    }
    .stepper-track[data-step='2'] { transform: translateX(100%); }
    .stepper-track[data-step='3'] { transform: translateX(200%); }
    .stepper-track[data-step='4'] { transform: translateX(300%); }
    /* Under RTL the track starts at the logical (right) edge, so later steps
       advance toward the left — negate the slide. */
    :global([dir='rtl']) .stepper-track[data-step='2'] { transform: translateX(-100%); }
    :global([dir='rtl']) .stepper-track[data-step='3'] { transform: translateX(-200%); }
    :global([dir='rtl']) .stepper-track[data-step='4'] { transform: translateX(-300%); }
    .dot {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        padding-bottom: var(--s-2);
        color: var(--text-faint);
        transition: color var(--t-base) var(--ease-out-quart);
    }
    .dot-btn {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        background: transparent;
        border: 0;
        padding: 0;
        font: inherit;
        color: inherit;
        cursor: pointer;
    }
    .dot-btn:disabled { cursor: default; }
    .dot.reachable .dot-btn:not(:disabled):hover { color: var(--text-primary); }
    .dot.active { color: var(--text-primary); }
    .dot.done { color: var(--text-secondary); }
    .dot-num {
        width: 22px;
        height: 22px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border: 1px solid var(--border-default);
        border-radius: 50%;
        font-family: var(--font-mono);
        font-size: 11px;
        background: var(--canvas);
        transition: border-color var(--t-base) var(--ease-out-quart),
                    color var(--t-base) var(--ease-out-quart),
                    background var(--t-base) var(--ease-out-quart);
    }
    .dot.active .dot-num {
        border-color: var(--accent);
        color: var(--accent);
        background: var(--accent-tint-soft);
    }
    .dot.done .dot-num {
        border-color: var(--accent);
        color: var(--accent-fg);
        background: var(--accent);
    }
    .dot-label {
        font-size: var(--fs-meta);
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }

    .body {
        padding: var(--s-4) var(--s-6) var(--s-5);
        flex: 1;
        min-height: 0;
        overflow-y: auto;
        position: relative;
    }
    .step-wrap { will-change: transform, opacity; }

    .submit-errors {
        display: flex;
        flex-direction: column;
        gap: 2px;
        margin: 0 var(--s-6);
        padding: var(--s-2) var(--s-3);
        background: var(--state-error-bg, oklch(0.3 0.08 25 / 0.18));
        border: 1px solid var(--state-error-fg);
        border-radius: var(--r-2);
        color: var(--state-error-fg);
        font-size: var(--fs-meta);
    }

    footer {
        padding: var(--s-3) var(--s-6);
        border-top: 1px solid var(--border-quiet);
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--s-3);
        background: var(--panel);
    }
    .left, .right {
        display: flex;
        align-items: center;
        gap: var(--s-2);
    }

    button.ghost, button.primary {
        padding: 7px 14px;
        border-radius: var(--r-2);
        font: inherit;
        font-size: var(--fs-meta);
        border: 1px solid var(--border-default);
        transition: background var(--t-fast), color var(--t-fast), border-color var(--t-fast), transform var(--t-fast);
    }
    button.ghost {
        background: transparent;
        color: var(--text-muted);
    }
    button.ghost:hover {
        color: var(--text-primary);
        border-color: var(--border-strong);
    }
    button.primary {
        background: var(--accent);
        color: var(--accent-fg);
        border-color: var(--accent);
        display: inline-flex;
        align-items: center;
        gap: 6px;
        font-weight: 500;
    }
    button.primary:hover:not(:disabled) {
        background: var(--accent-strong);
        border-color: var(--accent-strong);
    }
    button.primary:active:not(:disabled) {
        transform: translateY(1px);
    }
    button.primary:disabled {
        opacity: 0.45;
        cursor: not-allowed;
    }
    .primary-glyph {
        font-size: 16px;
        line-height: 1;
        transition: transform var(--t-base) var(--ease-out-quart);
    }
    button.primary:hover:not(:disabled) .primary-glyph {
        transform: translateX(2px);
    }
</style>
