<script lang="ts">
    import { onMount, untrack } from 'svelte';
    import { get } from 'svelte/store';

    import { editDeliveryCatalog, editReciterCatalog } from '../../../lib/api/admin-catalog';
    import CountryPicker from '../../../lib/components/CountryPicker.svelte';
    import { localeStore } from '../../../lib/i18n/locale-store';
    import * as m from '../../../lib/paraglide/messages';
    import type { AdminDelivery, AdminViewReciter } from '../../../lib/types/generated/schemas';
    import { countryName as countryLabel } from '../../../lib/utils/delivery-label';
    import { countryByCode, countryByName, normalizeCountry } from '../../../lib/utils/countries';

    interface Props {
        mode: 'reciter' | 'delivery';
        reciter: AdminViewReciter;
        delivery?: AdminDelivery | null;
        onSaved: () => void | Promise<void>;
        onClose: () => void;
    }

    interface Vocab {
        riwayat: Array<{ slug: string; name: string }>;
        styles: Array<{ slug: string; name: string }>;
        sources: Array<{ slug: string; name: string }>;
        channels: Array<{ slug: string; name: string }>;
        recording_contexts: Array<{ slug: string; name: string }>;
    }

    let { mode, reciter, delivery = null, onSaved, onClose }: Props = $props();
    let saving = $state(false);
    let error = $state<string | null>(null);
    let vocabLoading = $state(untrack(() => mode === 'delivery'));
    let vocab = $state<Vocab>({
        riwayat: [],
        styles: [],
        sources: [],
        channels: [],
        recording_contexts: [],
    });

    let nameEn = $state(untrack(() => reciter.name));
    let nameAr = $state(untrack(() => reciter.name_ar ?? ''));
    let countryInput = $state(untrack(() => countryDisplayValue(reciter.country)));
    let notes = $state(untrack(() => reciter.notes ?? ''));

    const lang = $derived($localeStore);
    const countryCode = $derived(countryByName(countryInput, lang)?.code ?? normalizeCountry(countryInput));
    const invalidCountry = $derived(!!countryInput.trim() && !countryByCode(countryCode));

    let riwayah = $state(untrack(() => delivery?.riwayah ?? ''));
    let style = $state(untrack(() => delivery?.style ?? ''));
    let context = $state(untrack(() => delivery?.recording_context ?? ''));
    let recordingYear = $state(untrack(() => numberText(delivery?.recording_year)));
    let variantLabel = $state(untrack(() => delivery?.variant_label ?? ''));
    let source = $state(untrack(() => delivery?.source ?? ''));
    let channel = $state(untrack(() => delivery?.channel ?? ''));
    let sourceUrl = $state(untrack(() => delivery?.source_url ?? ''));
    let audioCategory = $state(untrack(() => delivery?.audio_category ?? 'by_surah'));
    let chapterCount = $state(untrack(() => numberText(delivery?.chapter_count)));
    let codec = $state(untrack(() => delivery?.codec ?? 'mp3'));
    let container = $state(untrack(() => delivery?.container ?? 'mp3'));
    let sampleRate = $state(untrack(() => numberText(delivery?.sample_rate_hz)));
    let channels = $state(untrack(() => numberText(delivery?.channels)));
    let bitrateMode = $state(untrack(() => delivery?.bitrate_mode ?? 'unknown'));
    let bitrate = $state(untrack(() => numberText(delivery?.bitrate_kbps_nominal)));
    let duration = $state(untrack(() => numberText(delivery?.total_duration_sec)));

    function numberText(value: number | null | undefined): string {
        return value == null ? '' : String(value);
    }

    function optionalText(value: string): string | null {
        const normalized = value.trim();
        return normalized === '' ? null : normalized;
    }

    function optionalNumber(value: string): number | null {
        const normalized = value.trim();
        return normalized === '' ? null : Number(normalized);
    }

    function countryDisplayValue(raw: string | null | undefined): string {
        const code = normalizeCountry(raw);
        const known = countryByCode(code);
        return known ? countryLabel(known.code, get(localeStore)) : (raw ?? '');
    }

    onMount(() => {
        if (mode !== 'delivery') return;
        fetch('/api/static/catalog.json')
            .then((response) => {
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                return response.json() as Promise<{ vocab?: Vocab }>;
            })
            .then((payload) => {
                if (payload.vocab) vocab = payload.vocab;
            })
            .catch(() => {
                // The current values remain editable as text if the option
                // catalog is temporarily unavailable.
            })
            .finally(() => {
                vocabLoading = false;
            });
    });

    async function save(event: SubmitEvent): Promise<void> {
        event.preventDefault();
        if (saving) return;
        saving = true;
        error = null;
        try {
            if (mode === 'reciter') {
                if (invalidCountry) {
                    error = m.dashboard_request_country_invalid();
                    return;
                }
                await editReciterCatalog(reciter.reciter_id, {
                    name_en: nameEn.trim(),
                    name_ar: optionalText(nameAr),
                    country: countryCode || null,
                    notes: optionalText(notes),
                });
            } else if (delivery) {
                await editDeliveryCatalog(delivery.slug, {
                    riwayah: riwayah.trim(),
                    style: style.trim(),
                    recording_context: optionalText(context),
                    recording_year: optionalNumber(recordingYear),
                    variant_label: optionalText(variantLabel),
                    source: source.trim(),
                    channel: channel.trim(),
                    source_url: optionalText(sourceUrl),
                    audio_category: audioCategory,
                    chapter_count: Number(chapterCount),
                    codec: codec.trim(),
                    container: container.trim(),
                    sample_rate_hz: optionalNumber(sampleRate),
                    channels: optionalNumber(channels),
                    bitrate_mode: bitrateMode,
                    bitrate_kbps_nominal: optionalNumber(bitrate),
                    total_duration_sec: optionalNumber(duration),
                });
            }
            await onSaved();
        } catch (caught) {
            error = (caught as Error).message;
        } finally {
            saving = false;
        }
    }
</script>

<section class="editor" aria-label={mode === 'reciter' ? m.dashboard_catalog_edit_title_reciter() : m.dashboard_catalog_edit_title_delivery()}>
    <div class="editor-head">
        <h3>{mode === 'reciter' ? m.dashboard_catalog_edit_title_reciter() : m.dashboard_catalog_edit_title_delivery()}</h3>
        <button type="button" class="quiet" onclick={onClose}>{m.dashboard_catalog_edit_cancel()}</button>
    </div>

    {#if error}
        <p class="error" role="alert">{m.dashboard_catalog_edit_error({ message: error })}</p>
    {/if}

    {#if mode === 'delivery' && vocabLoading}
        <p class="loading">{m.dashboard_catalog_edit_load_vocab()}</p>
    {/if}

    <form onsubmit={save}>
        {#if mode === 'reciter'}
            <div class="fields identity-fields">
                <label>{m.dashboard_catalog_edit_name_en()}<input bind:value={nameEn} required /></label>
                <label>{m.dashboard_catalog_edit_name_ar()}<input bind:value={nameAr} dir="rtl" /></label>
                <label class="country-field">
                    <span>
                        {m.dashboard_catalog_edit_country()}
                        {#if countryCode && !invalidCountry}
                            <span class="label-meta">({countryCode})</span>
                        {:else if countryInput}
                            <span class="label-meta warn">{m.dashboard_request_country_unknown()}</span>
                        {/if}
                    </span>
                    <CountryPicker
                        bind:value={countryInput}
                        locale={lang}
                        placeholder={m.dashboard_request_country_placeholder()}
                    />
                </label>
                <label class="wide">{m.dashboard_catalog_edit_notes()}<textarea bind:value={notes} maxlength="500"></textarea></label>
            </div>
        {:else if delivery}
            <div class="fields">
                <label>{m.dashboard_catalog_edit_riwayah()}<select bind:value={riwayah}>{#each vocab.riwayat as item}<option value={item.slug}>{item.name}</option>{/each}</select></label>
                <label>{m.dashboard_catalog_edit_style()}<select bind:value={style}>{#each vocab.styles as item}<option value={item.slug}>{item.name}</option>{/each}</select></label>
                <label>{m.dashboard_catalog_edit_context()}<select bind:value={context}><option value="">—</option>{#each vocab.recording_contexts as item}<option value={item.slug}>{item.name}</option>{/each}</select></label>
                <label>{m.dashboard_catalog_edit_year()}<input bind:value={recordingYear} inputmode="numeric" /></label>
                <label>{m.dashboard_catalog_edit_variant()}<input bind:value={variantLabel} /></label>
                <label>{m.dashboard_catalog_edit_source()}<select bind:value={source}>{#each vocab.sources as item}<option value={item.slug}>{item.name}</option>{/each}</select></label>
                <label>{m.dashboard_catalog_edit_channel()}<select bind:value={channel}>{#each vocab.channels as item}<option value={item.slug}>{item.name}</option>{/each}</select></label>
                <label class="wide">{m.dashboard_catalog_edit_source_url()}<input bind:value={sourceUrl} type="url" /></label>
                <label>{m.dashboard_catalog_edit_audio_category()}<select bind:value={audioCategory}><option value="by_surah">by_surah</option><option value="by_ayah">by_ayah</option></select></label>
                <label>{m.dashboard_catalog_edit_chapter_count()}<input bind:value={chapterCount} inputmode="numeric" required /></label>
                <label>{m.dashboard_catalog_edit_codec()}<input bind:value={codec} required /></label>
                <label>{m.dashboard_catalog_edit_container()}<input bind:value={container} required /></label>
                <label>{m.dashboard_catalog_edit_sample_rate()}<input bind:value={sampleRate} inputmode="numeric" /></label>
                <label>{m.dashboard_catalog_edit_channels()}<input bind:value={channels} inputmode="numeric" /></label>
                <label>{m.dashboard_catalog_edit_bitrate_mode()}<select bind:value={bitrateMode}><option value="unknown">unknown</option><option value="cbr">cbr</option><option value="vbr">vbr</option><option value="mixed">mixed</option></select></label>
                <label>{m.dashboard_catalog_edit_bitrate()}<input bind:value={bitrate} inputmode="numeric" /></label>
                <label>{m.dashboard_catalog_edit_duration()}<input bind:value={duration} inputmode="numeric" /></label>
            </div>
        {/if}
        <div class="actions">
            <button type="button" class="quiet" onclick={onClose}>{m.dashboard_catalog_edit_cancel()}</button>
            <button type="submit" class="primary" disabled={saving}>{saving ? m.dashboard_catalog_edit_saving() : m.dashboard_catalog_edit_save()}</button>
        </div>
    </form>
</section>

<style>
    .editor {
        margin: var(--s-4) 0;
        padding: var(--s-4);
        border: 1px solid var(--border-default);
        border-radius: var(--r-2);
        background: var(--panel);
    }
    .editor-head, .actions { display: flex; align-items: center; justify-content: space-between; gap: var(--s-3); }
    .editor-head { margin-bottom: var(--s-3); }
    h3 { margin: 0; color: var(--text-primary); font-size: var(--fs-body); font-weight: 500; }
    .fields { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--s-3); }
    .identity-fields { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    label { display: flex; flex-direction: column; gap: var(--s-1); color: var(--text-muted); font-size: var(--fs-meta); }
    .wide { grid-column: 1 / -1; }
    .country-field > span { display: inline-flex; align-items: baseline; gap: var(--s-1); }
    .label-meta { color: var(--text-faint); font-family: var(--font-mono); font-size: var(--fs-meta); }
    .label-meta.warn { color: var(--state-warning-fg); font-family: inherit; }
    input, select, textarea { width: 100%; box-sizing: border-box; border: 1px solid var(--border-default); border-radius: var(--r-1); background: var(--canvas); color: var(--text-primary); padding: var(--s-2); font: inherit; }
    textarea { min-height: 64px; resize: vertical; }
    .actions { justify-content: flex-end; margin-top: var(--s-4); }
    button { font: inherit; cursor: pointer; }
    .quiet { border: 1px solid var(--border-default); border-radius: var(--r-1); padding: var(--s-2) var(--s-3); background: transparent; color: var(--text-secondary); }
    .primary { border: 1px solid var(--accent); border-radius: var(--r-1); padding: var(--s-2) var(--s-3); background: var(--accent); color: var(--canvas); }
    button:disabled { opacity: 0.55; cursor: wait; }
    .error { color: var(--state-error-fg); margin: 0 0 var(--s-3); font-size: var(--fs-meta); }
    .loading { color: var(--text-muted); font-size: var(--fs-meta); }
    @media (max-width: 720px) { .fields, .identity-fields { grid-template-columns: 1fr; } }
</style>
