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
     *
     * The bound `value` is never mutated except by an explicit selection or the
     * user's own typing — focusing just opens the list (full list until the user
     * types, then filtered), so a committed country is never transiently blanked.
     */
    import { clickOutside } from '$lib/actions/click-outside';
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
    // Has the user typed since focusing? Until they do, show the full list so a
    // committed value can be re-picked; once typing, filter by the input text.
    let dirty = $state(false);
    let activeIdx = $state(0);
    const listboxId = `country-listbox-${_seq++}`;

    const options = $derived<CountryOption[]>(
        open && !dirty ? filterCountries('', locale) : filterCountries(value, locale),
    );

    function commit(opt: CountryOption): void {
        value = opt.label;
        dirty = false;
        open = false;
    }
    function onFocus(): void {
        if (disabled) return;
        dirty = false;
        activeIdx = 0;
        open = true;
    }
    function onInput(): void {
        dirty = true;
        activeIdx = 0;
        open = true;
    }
    function close(): void {
        open = false;
    }
    function onKeydown(e: KeyboardEvent): void {
        if (!open && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
            open = true;
            return;
        }
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
                commit(opt);
                e.preventDefault();
            }
        } else if (e.key === 'Escape') {
            open = false;
        }
    }
</script>

<div class="country-combo" use:clickOutside={close}>
    <input
        {id}
        type="text"
        class="country-input"
        role="combobox"
        aria-controls={listboxId}
        aria-expanded={open}
        aria-autocomplete="list"
        autocomplete="off"
        {placeholder}
        {disabled}
        bind:value
        onfocus={onFocus}
        oninput={onInput}
        onblur={close}
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
                        onpointerdown={(e) => {
                            // Keep the input focused (no blur→close race) and commit.
                            e.preventDefault();
                            commit(opt);
                        }}
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
    /* Match the app's text inputs (the native box this replaced inherited the
       parent form's `input` rule, which scoped styles can't cross into here). */
    .country-input {
        width: 100%;
        box-sizing: border-box;
        background: var(--panel);
        border: 1px solid var(--border-default);
        color: var(--text-primary);
        border-radius: var(--r-2);
        padding: 8px 10px;
        font: inherit;
        transition:
            border-color var(--t-fast),
            background var(--t-fast);
    }
    .country-input::placeholder {
        color: var(--text-faint);
    }
    .country-input:focus {
        outline: none;
        border-color: var(--accent);
        background: var(--panel-2);
    }
    .country-input:disabled {
        opacity: 0.7;
        cursor: not-allowed;
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
