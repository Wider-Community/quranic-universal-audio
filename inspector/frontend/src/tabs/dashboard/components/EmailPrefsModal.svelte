<script lang="ts">
    /**
     * Email-notification preferences modal.
     *
     * Opened from the "Email notifs" button in the "My notifications" rail header
     * (available to everyone, incl. anonymous — subscriptions are keyed by email,
     * not the HF account). Lets the user set one destination address and opt into
     * no-reply emails for catalog + workflow events, against the
     * `/api/me/email-preferences` contract (`lib/api/email-prefs.ts`).
     *
     * One shared reciter selection powers every reciter-scoped event ("Choose"
     * mode); one shared riwayah follow-list powers both riwayah events — pick
     * once, applies to both.
     *
     * Identity: signed-in callers resolve by their HF cookie. Anonymous callers
     * resolve by a `manage_token` minted on first save — cached in localStorage
     * (so a returning visitor re-loads fresh server state) and passed via the
     * `manageToken` prop when the modal is opened from an email "manage" link.
     */
    import { i18n } from '../../../lib/i18n/locale.svelte';
    import * as m from '../../../lib/paraglide/messages';
    import {
        type EmailPrefs,
        type EmailScope,
        fetchEmailPrefs,
        isValidEmail,
        saveEmailPrefs,
    } from '../../../lib/api/email-prefs';
    import ChipMultiSelect from '../../../lib/components/ChipMultiSelect.svelte';
    import Modal from '../../../lib/components/Modal.svelte';
    import Segmented from '../../../lib/components/Segmented.svelte';
    import Toggle from '../../../lib/components/Toggle.svelte';
    import { pushToast } from '../../../lib/stores/toast';
    import type { SelectOption } from '../../../lib/types/ui';
    import { titleCaseSlug } from '../../../lib/utils/delivery-label';
    import { catalogData, loadCatalog } from '../stores/catalog-data';

    interface Props {
        open: boolean;
        onclose: () => void;
        /** When opened from an email "manage" link, the subscription's token. */
        manageToken?: string | null;
    }
    let { open, onclose, manageToken = null }: Props = $props();

    // Reading i18n.locale keeps the component's m.*() calls reactive on switch.
    const closeLabel = $derived((i18n.locale, m.common_action_close()));

    let working = $state<EmailPrefs | null>(null);
    let baseline = $state('');
    let loading = $state(false);
    let saving = $state(false);
    let loadError = $state<string | null>(null);
    let saveError = $state<string | null>(null);

    // The manage token cached in this browser (anonymous re-management). The
    // server resolves signed-in callers by cookie, so this is only consulted
    // when no `manageToken` prop was passed.
    const TOKEN_KEY = 'qua_email_manage_token';
    function readCachedToken(): string | null {
        try {
            return localStorage.getItem(TOKEN_KEY);
        } catch {
            return null;
        }
    }
    function cacheToken(token: string | null): void {
        try {
            if (token) localStorage.setItem(TOKEN_KEY, token);
        } catch {
            /* storage unavailable — token round-trips via the server next save */
        }
    }

    const SCOPE_OPTS = $derived<{ value: EmailScope; label: string }[]>([
        { value: 'off', label: (i18n.locale, m.dashboard_email_prefs_scope_off()) },
        { value: 'all', label: m.dashboard_email_prefs_scope_all() },
        { value: 'selected', label: m.dashboard_email_prefs_scope_choose() },
    ]);

    const reciterOptions = $derived<SelectOption[]>(
        [...$catalogData.reciters]
            .sort((a, b) => a.name.localeCompare(b.name))
            .map((r) => ({ value: r.reciter_id, label: r.name })),
    );

    const riwayahOptions = $derived.by<SelectOption[]>(() => {
        const set = new Set<string>();
        for (const r of $catalogData.reciters) for (const rw of r.riwayat) set.add(rw);
        return [...set].sort().map((v) => ({ value: v, label: titleCaseSlug(v) }));
    });

    const dirty = $derived(working ? JSON.stringify(working) !== baseline : false);
    const anyReciterScopeChooses = $derived(
        !!working &&
            (working.recitation_published === 'selected' ||
                working.timestamps_regenerated === 'selected'),
    );
    const anyRiwayahEvent = $derived(
        !!working && (working.riwayah_new_recitation || working.riwayah_first_available),
    );
    const anyEnabled = $derived(
        !!working &&
            (working.request_aligned ||
                working.recitation_published !== 'off' ||
                working.timestamps_regenerated !== 'off' ||
                working.github_release ||
                anyRiwayahEvent),
    );
    const emailFilled = $derived(!!working && working.email.trim() !== '');
    const emailOk = $derived(
        !working ? false : emailFilled ? isValidEmail(working.email) : !anyEnabled,
    );
    const canSave = $derived(dirty && emailOk && !saving);

    let wasOpen = false;
    $effect(() => {
        if (open && !wasOpen) {
            wasOpen = true;
            void load();
        } else if (!open) {
            wasOpen = false;
        }
    });

    async function load(): Promise<void> {
        loading = true;
        loadError = null;
        saveError = null;
        void loadCatalog();
        try {
            const token = manageToken ?? readCachedToken();
            const loaded = await fetchEmailPrefs({ manageToken: token });
            working = loaded.prefs;
            baseline = JSON.stringify(loaded.prefs);
            cacheToken(loaded.manageToken);
        } catch (e) {
            loadError = (e as Error).message ?? m.dashboard_email_prefs_load_error_fallback();
            working = null;
        } finally {
            loading = false;
        }
    }

    async function save(): Promise<void> {
        if (!working || !canSave) return;
        saving = true;
        saveError = null;
        try {
            const saved = await saveEmailPrefs(working);
            working = saved.prefs;
            baseline = JSON.stringify(saved.prefs);
            cacheToken(saved.manageToken);
            pushToast({ kind: 'success', text: m.dashboard_email_prefs_saved_toast() });
            onclose();
        } catch (e) {
            saveError = (e as Error).message ?? m.dashboard_email_prefs_save_error_fallback();
        } finally {
            saving = false;
        }
    }

    function setScope(field: 'recitation_published' | 'timestamps_regenerated', v: string): void {
        if (working) working[field] = v as EmailScope;
    }
</script>

<Modal {open} title={m.dashboard_email_prefs_modal_title()} size="narrow" {closeLabel} on:close={onclose}>
    {#if loading}
        <div class="pad">
            <div class="skel-intro"></div>
            {#each Array.from({ length: 5 }, (_, i) => i) as i (i)}
                <div class="skel-row">
                    <div class="skel-text">
                        <span class="skel-bar w60"></span>
                        <span class="skel-bar w85"></span>
                    </div>
                    <span class="skel-ctrl"></span>
                </div>
            {/each}
        </div>
    {:else if loadError}
        <div class="pad state-block">
            <p class="state-msg">{loadError}</p>
            <button type="button" class="btn-default" onclick={() => void load()}>{m.common_action_try_again()}</button>
        </div>
    {:else if working}
        <div class="pad">
            <p class="intro">{m.dashboard_email_prefs_intro()}</p>

            <div class="email-field">
                <label class="email-label" for="emailpref-send-to">{m.dashboard_email_prefs_send_to_label()}</label>
                <input
                    id="emailpref-send-to"
                    class="email-input"
                    class:invalid={emailFilled && !isValidEmail(working.email)}
                    type="email"
                    inputmode="email"
                    autocomplete="email"
                    placeholder={m.dashboard_email_prefs_email_placeholder()}
                    bind:value={working.email} />
                {#if emailFilled && !isValidEmail(working.email)}
                    <p class="email-note error">{m.dashboard_email_prefs_email_invalid()}</p>
                {:else if anyEnabled && !emailFilled}
                    <p class="email-note error">{m.dashboard_email_prefs_email_required()}</p>
                {:else}
                    <p class="email-note">{m.dashboard_email_prefs_email_help()}</p>
                {/if}
            </div>

            <!-- Your contributions -->
            <section class="group">
                <h3 class="group-title">{m.dashboard_email_prefs_group_contributions()}</h3>
                <div class="row">
                    <div class="row-text">
                        <p class="row-title">{m.dashboard_email_prefs_request_processed_title()}</p>
                        <p class="row-desc">{m.dashboard_email_prefs_request_processed_desc()}</p>
                    </div>
                    <div class="row-ctrl">
                        <Toggle
                            checked={working.request_aligned}
                            label={m.dashboard_email_prefs_request_processed_toggle_label()}
                            onchange={(v) => working && (working.request_aligned = v)} />
                    </div>
                </div>
            </section>

            <!-- Publishing -->
            <section class="group">
                <h3 class="group-title">{m.dashboard_email_prefs_group_publishing()}</h3>
                <div class="row">
                    <div class="row-text">
                        <p class="row-title">{m.dashboard_email_prefs_recitation_published_title()}</p>
                        <p class="row-desc">{m.dashboard_email_prefs_recitation_published_desc()}</p>
                    </div>
                    <div class="row-ctrl">
                        <Segmented
                            options={SCOPE_OPTS}
                            value={working.recitation_published}
                            ariaLabel={m.dashboard_email_prefs_recitation_published_aria()}
                            onchange={(v) => setScope('recitation_published', v)} />
                    </div>
                </div>

                <div class="row">
                    <div class="row-text">
                        <p class="row-title">{m.dashboard_email_prefs_timestamps_regenerated_title()}</p>
                        <p class="row-desc">{m.dashboard_email_prefs_timestamps_regenerated_desc()}</p>
                    </div>
                    <div class="row-ctrl">
                        <Segmented
                            options={SCOPE_OPTS}
                            value={working.timestamps_regenerated}
                            ariaLabel={m.dashboard_email_prefs_timestamps_regenerated_aria()}
                            onchange={(v) => setScope('timestamps_regenerated', v)} />
                    </div>
                </div>

                {#if anyReciterScopeChooses}
                    <div class="subpanel">
                        <div class="sub-head">
                            <span class="sub-label">{m.dashboard_email_prefs_chosen_reciters_label()}</span>
                            <span class="sub-help">{m.dashboard_email_prefs_chosen_reciters_help()}</span>
                        </div>
                        <ChipMultiSelect
                            options={reciterOptions}
                            selected={working.reciters}
                            placeholder={m.dashboard_email_prefs_add_reciter_placeholder()}
                            ariaLabel={m.dashboard_email_prefs_chosen_reciters_aria()}
                            emptyHint={m.dashboard_email_prefs_chosen_reciters_empty_hint()}
                            onchange={(next) => working && (working.reciters = next)} />
                        {#if working.reciters.length === 0}
                            <p class="warn">{m.dashboard_email_prefs_reciters_warn()}</p>
                        {/if}
                    </div>
                {/if}

                <div class="row">
                    <div class="row-text">
                        <p class="row-title">{m.dashboard_email_prefs_github_release_title()}</p>
                        <p class="row-desc">{m.dashboard_email_prefs_github_release_desc()}</p>
                    </div>
                    <div class="row-ctrl">
                        <Toggle
                            checked={working.github_release}
                            label={m.dashboard_email_prefs_github_release_toggle_label()}
                            onchange={(v) => working && (working.github_release = v)} />
                    </div>
                </div>
            </section>

            <!-- Riwayahs you follow -->
            <section class="group">
                <h3 class="group-title">{m.dashboard_email_prefs_group_riwayahs()}</h3>
                <div class="subpanel flush">
                    <ChipMultiSelect
                        options={riwayahOptions}
                        selected={working.riwayahs}
                        placeholder={m.dashboard_email_prefs_add_riwayah_placeholder()}
                        ariaLabel={m.dashboard_email_prefs_riwayahs_aria()}
                        emptyHint={m.dashboard_email_prefs_riwayahs_empty_hint()}
                        onchange={(next) => working && (working.riwayahs = next)} />
                </div>

                <div class="row">
                    <div class="row-text">
                        <p class="row-title">{m.dashboard_email_prefs_riwayah_new_recitation_title()}</p>
                        <p class="row-desc">{m.dashboard_email_prefs_riwayah_new_recitation_desc()}</p>
                    </div>
                    <div class="row-ctrl">
                        <Toggle
                            checked={working.riwayah_new_recitation}
                            label={m.dashboard_email_prefs_riwayah_new_recitation_toggle_label()}
                            onchange={(v) => working && (working.riwayah_new_recitation = v)} />
                    </div>
                </div>

                <div class="row">
                    <div class="row-text">
                        <p class="row-title">{m.dashboard_email_prefs_riwayah_first_available_title()}</p>
                        <p class="row-desc">{m.dashboard_email_prefs_riwayah_first_available_desc()}</p>
                    </div>
                    <div class="row-ctrl">
                        <Toggle
                            checked={working.riwayah_first_available}
                            label={m.dashboard_email_prefs_riwayah_first_available_toggle_label()}
                            onchange={(v) => working && (working.riwayah_first_available = v)} />
                    </div>
                </div>

                {#if anyRiwayahEvent && working.riwayahs.length === 0}
                    <p class="warn">{m.dashboard_email_prefs_riwayahs_warn()}</p>
                {/if}
            </section>
        </div>
    {/if}

    <svelte:fragment slot="footer">
        <span class="foot-status" aria-live="polite">
            {#if saveError}
                <span class="foot-err">{saveError}</span>
            {:else if dirty}
                <span class="dot" aria-hidden="true"></span>{m.dashboard_email_prefs_unsaved_changes()}
            {:else if working}
                {m.dashboard_email_prefs_all_saved()}
            {/if}
        </span>
        <span class="foot-actions">
            <button type="button" class="btn-ghost" onclick={onclose}>{m.common_action_cancel()}</button>
            <button type="button" class="btn-primary" disabled={!canSave} onclick={() => void save()}>
                {saving ? m.common_status_saving() : m.dashboard_email_prefs_save_button()}
            </button>
        </span>
    </svelte:fragment>
</Modal>

<style>
    .pad {
        padding: var(--s-5) var(--s-6) var(--s-6);
    }

    .intro {
        margin: 0 0 var(--s-5);
        font-size: var(--fs-body);
        line-height: var(--lh-normal);
        color: var(--text-secondary);
        max-width: 60ch;
    }

    /* ---------- Email field ---------- */
    .email-field {
        display: flex;
        flex-direction: column;
        gap: var(--s-2);
        padding-bottom: var(--s-5);
        border-bottom: 1px solid var(--border-quiet);
    }
    .email-label {
        font-size: var(--fs-meta);
        font-weight: 600;
        letter-spacing: 0.01em;
        color: var(--text-secondary);
    }
    .email-input {
        width: 100%;
        box-sizing: border-box;
        padding: 8px 11px;
        background: var(--panel);
        border: 1px solid var(--border-default);
        border-radius: var(--r-2);
        color: var(--text-primary);
        font-size: var(--fs-row);
        transition:
            border-color var(--t-fast),
            box-shadow var(--t-fast);
    }
    .email-input::placeholder {
        color: var(--text-muted);
    }
    .email-input:focus {
        outline: none;
        border-color: var(--accent);
        box-shadow: 0 0 0 3px var(--accent-tint);
    }
    .email-input.invalid {
        border-color: var(--state-error-fg);
    }
    .email-note {
        margin: 0;
        font-size: var(--fs-meta);
        color: var(--text-muted);
    }
    .email-note.error {
        color: var(--state-error-fg);
    }

    /* ---------- Groups & rows ---------- */
    .group {
        padding: var(--s-5) 0 var(--s-2);
        border-bottom: 1px solid var(--border-quiet);
    }
    .group:last-child {
        border-bottom: none;
        padding-bottom: 0;
    }
    .group-title {
        margin: 0 0 var(--s-2);
        font-size: var(--fs-meta);
        font-weight: 600;
        letter-spacing: 0.02em;
        color: var(--text-muted);
    }

    .row {
        display: flex;
        align-items: center;
        gap: var(--s-4);
        padding: var(--s-3) 0;
    }
    .row-text {
        min-width: 0;
        flex: 1 1 auto;
    }
    .row-title {
        margin: 0;
        font-size: var(--fs-row);
        font-weight: 500;
        color: var(--text-primary);
        line-height: 1.3;
    }
    .row-desc {
        margin: 2px 0 0;
        font-size: var(--fs-meta);
        color: var(--text-muted);
        line-height: var(--lh-normal);
        max-width: 52ch;
    }
    .row-ctrl {
        flex: 0 0 auto;
        display: flex;
        align-items: center;
    }

    /* ---------- Shared-selection subpanels ---------- */
    .subpanel {
        margin: var(--s-2) 0 var(--s-3);
        padding: var(--s-3) var(--s-3) var(--s-4);
        background: var(--canvas-inset);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        animation: reveal var(--t-slow) var(--ease-out-quart);
    }
    .subpanel.flush {
        margin-top: var(--s-1);
        background: transparent;
        border: none;
        padding: 0 0 var(--s-2);
        animation: none;
    }
    .sub-head {
        display: flex;
        align-items: baseline;
        flex-wrap: wrap;
        gap: var(--s-2);
        margin-bottom: var(--s-2);
    }
    .sub-label {
        font-size: var(--fs-meta);
        font-weight: 600;
        color: var(--text-secondary);
    }
    .sub-help {
        font-size: var(--fs-meta);
        color: var(--text-muted);
    }
    .warn {
        margin: var(--s-2) 0 0;
        font-size: var(--fs-meta);
        color: var(--state-error-fg);
    }
    @keyframes reveal {
        from {
            opacity: 0;
            transform: translateY(-4px);
        }
        to {
            opacity: 1;
            transform: none;
        }
    }
    @media (prefers-reduced-motion: reduce) {
        .subpanel {
            animation: none;
        }
    }

    /* ---------- Footer ---------- */
    .foot-status {
        display: inline-flex;
        align-items: center;
        gap: var(--s-2);
        font-size: var(--fs-meta);
        color: var(--text-muted);
        min-width: 0;
    }
    .foot-err {
        color: var(--state-error-fg);
    }
    .dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: var(--accent);
        flex-shrink: 0;
    }
    .foot-actions {
        display: inline-flex;
        align-items: center;
        gap: var(--s-2);
    }

    /* ---------- Buttons ---------- */
    .btn-primary,
    .btn-default,
    .btn-ghost {
        font-size: var(--fs-body);
        font-weight: 500;
        padding: 7px 14px;
        border-radius: var(--r-2);
        cursor: pointer;
        border: 1px solid transparent;
        transition:
            background var(--t-fast),
            color var(--t-fast),
            opacity var(--t-fast);
    }
    .btn-primary {
        background: var(--accent);
        color: var(--accent-fg);
    }
    .btn-primary:hover:not(:disabled) {
        background: var(--accent-strong);
    }
    .btn-primary:disabled {
        opacity: 0.45;
        cursor: not-allowed;
    }
    .btn-default {
        background: var(--panel);
        color: var(--text-primary);
        border-color: var(--border-default);
    }
    .btn-default:hover {
        background: var(--panel-2);
    }
    .btn-ghost {
        background: transparent;
        color: var(--text-secondary);
    }
    .btn-ghost:hover {
        color: var(--text-primary);
        background: var(--panel);
    }
    .btn-primary:focus-visible,
    .btn-default:focus-visible,
    .btn-ghost:focus-visible {
        outline: none;
        box-shadow: 0 0 0 2px var(--accent);
    }

    /* ---------- Loading skeleton ---------- */
    .skel-intro,
    .skel-bar,
    .skel-ctrl {
        background: var(--panel-2);
        border-radius: var(--r-1);
        animation: pulse 1.3s ease-in-out infinite;
    }
    .skel-intro {
        height: 14px;
        width: 70%;
        margin-bottom: var(--s-5);
    }
    .skel-row {
        display: flex;
        align-items: center;
        gap: var(--s-4);
        padding: var(--s-3) 0;
    }
    .skel-text {
        flex: 1 1 auto;
        display: flex;
        flex-direction: column;
        gap: 6px;
    }
    .skel-bar {
        height: 11px;
    }
    .skel-bar.w60 {
        width: 60%;
    }
    .skel-bar.w85 {
        width: 85%;
    }
    .skel-ctrl {
        width: 60px;
        height: 22px;
        flex: 0 0 auto;
    }
    @keyframes pulse {
        0%,
        100% {
            opacity: 1;
        }
        50% {
            opacity: 0.5;
        }
    }
    @media (prefers-reduced-motion: reduce) {
        .skel-intro,
        .skel-bar,
        .skel-ctrl {
            animation: none;
        }
    }

    /* ---------- Load-error block ---------- */
    .state-block {
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: var(--s-4);
    }
    .state-msg {
        margin: 0;
        font-size: var(--fs-body);
        color: var(--state-error-fg);
    }
</style>
