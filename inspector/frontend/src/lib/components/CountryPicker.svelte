<script module lang="ts">
    // Per-instance id counter so the input's aria-controls points at its own
    // listbox even when two pickers are mounted (request form vs submit wizard).
    let _seq = 0;
</script>

<script lang="ts">
    /**
     * Locale-aware country combobox. Replaces the native `<input list>` +
     * `<datalist>` (which can only filter English option values) so search matches
     * the ISO-2 code, the English short-name, AND the localized name — the reason a
     * user in Arabic couldn't find their country by typing Arabic.
     *
     * Two-way binds `value` as the display label (localized). Callers resolve the
     * ISO-2 code from `value` via `countryByName(value, locale)`; the stored wire
     * value stays the code, so the display language never changes what's persisted.
     * Mirrors the old focus-stash dance: focusing blanks the field to reveal the
     * full list, and an untouched blur restores the prior selection.
     */
    import { filterCountries, type CountryOption } from '$lib/utils/countries';

    interface Props {
        value?: string;
        locale?: string;
        placeholder?: string;
        disabled?: boolean;
        id?: string;
    }
    let {
        value = $bindable(''),
        locale = 'en',
        placeholder = '',
        disabled = false,
        id,
    }: Props = $props();

    let open = $state(false);
    let activeIdx = $state(0);
    let stash: string | null = null;
    const listboxId = `country-listbox-${_seq++}`;

    const options = $derived<CountryOption[]>(filterCountries(value, locale));

    function select(opt: CountryOption): void {
        value = opt.label;
        stash = null;
        open = false;
    }
    function onFocus(): void {
        if (disabled) return;
        stash = value;
        value = '';
        open = true;
        activeIdx = 0;
    }
    function onBlur(): void {
        // Delay so a pointer selection lands before the list unmounts.
        setTimeout(() => {
            if (!value && stash != null) value = stash;
            stash = null;
            open = false;
        }, 120);
    }
    function onInput(): void {
        open = true;
        activeIdx = 0;
    }
    function onKeydown(e: KeyboardEvent): void {
        if (!open) return;
        if (e.key === 'ArrowDown') {
            activeIdx = Math.min(activeIdx + 1, options.length - 1);
            e.preventDefault();
        } else if (e.key === 'ArrowUp') {
            activeIdx = Math.max(activeIdx - 1, 0);
            e.preventDefault();
        } else if (e.key === 'Enter') {
            const opt = options[activeIdx];
            if (opt) {
                select(opt);
                e.preventDefault();
            }
        } else if (e.key === 'Escape') {
            open = false;
        }
    }
</script>

<div class="country-combo">
    <input
        {id}
        type="text"
        role="combobox"
        aria-controls={listboxId}
        aria-expanded={open}
        aria-autocomplete="list"
        autocomplete="off"
        {placeholder}
        {disabled}
        bind:value
        onfocus={onFocus}
        onblur={onBlur}
        oninput={onInput}
        onkeydown={onKeydown}
    />
    {#if open && options.length > 0}
        <ul id={listboxId} class="country-list" role="listbox">
            {#each options.slice(0, 60) as opt, i (opt.code)}
                <li>
                    <button
                        type="button"
                        role="option"
                        aria-selected={i === activeIdx}
                        class="country-opt"
                        class:active={i === activeIdx}
                        onpointerdown={() => select(opt)}
                        onmouseenter={() => (activeIdx = i)}
                    >
                        <span class="country-opt-name">{opt.label}</span>
                        <span class="country-opt-code">{opt.code}</span>
                    </button>
                </li>
            {/each}
        </ul>
    {/if}
</div>

<style>
    .country-combo {
        position: relative;
    }
    .country-list {
        position: absolute;
        z-index: 20;
        top: calc(100% + 2px);
        left: 0;
        right: 0;
        margin: 0;
        padding: var(--s-1);
        list-style: none;
        max-height: 240px;
        overflow-y: auto;
        background: var(--canvas);
        border: 1px solid var(--border-strong);
        border-radius: var(--r-2);
        box-shadow: var(--shadow-2, 0 6px 24px rgba(0, 0, 0, 0.3));
    }
    .country-opt {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: var(--s-3);
        width: 100%;
        padding: 6px var(--s-2);
        background: transparent;
        border: 0;
        border-radius: var(--r-1);
        color: var(--text-secondary);
        font: inherit;
        text-align: start;
        cursor: pointer;
    }
    .country-opt.active,
    .country-opt:hover {
        background: var(--panel-2);
        color: var(--text-primary);
    }
    .country-opt-code {
        font-family: var(--font-mono);
        font-size: var(--fs-meta);
        color: var(--text-faint);
        flex-shrink: 0;
    }
</style>
