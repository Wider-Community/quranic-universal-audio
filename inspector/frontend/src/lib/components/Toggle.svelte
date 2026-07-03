<script lang="ts">
    /**
     * Accessible on/off switch (Svelte 5 runes). Generic — no permissions
     * coupling — so it can back any boolean setting.
     *
     * - `na` renders a static "N/A" marker (NOT a switch) for cells where the
     *   option doesn't apply (e.g. anonymous on an action capability), keeping
     *   the a11y tree honest.
     * - `disabled` hard-locks the control (lock glyph, no pointer).
     * - `busy` shows an in-flight spinner and suppresses input.
     */
    import { i18n } from '../i18n/locale.svelte';
    import * as m from '../paraglide/messages';

    interface Props {
        checked: boolean;
        disabled?: boolean;
        busy?: boolean;
        na?: boolean;
        label?: string;
        title?: string;
        onchange?: (_next: boolean) => void;
    }

    let {
        checked,
        disabled = false,
        busy = false,
        na = false,
        label,
        title,
        onchange,
    }: Props = $props();

    // Reading i18n.locale keeps the N/A marker + aria-label reactive on switch.
    const naAriaLabel = $derived((i18n.locale, label ?? m.common_toggle_na_aria_label()));

    function fire(): void {
        if (disabled || busy || na) return;
        onchange?.(!checked);
    }

    function onKey(e: KeyboardEvent): void {
        if (e.key === ' ' || e.key === 'Enter') {
            e.preventDefault();
            fire();
        }
    }
</script>

{#if na}
    <span class="toggle-na" {title} aria-label={naAriaLabel}>{m.common_toggle_na_marker()}</span>
{:else}
    <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        aria-busy={busy}
        {title}
        class="toggle"
        class:on={checked}
        class:busy
        class:locked={disabled}
        {disabled}
        onclick={fire}
        onkeydown={onKey}
    >
        <span class="track">
            <span class="thumb">
                {#if busy}<span class="spinner" aria-hidden="true"></span>{/if}
            </span>
        </span>
        {#if disabled}<span class="lock" aria-hidden="true">🔒</span>{/if}
    </button>
{/if}

<style>
    .toggle {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 0;
        background: transparent;
        border: 0;
        cursor: pointer;
        line-height: 0;
    }
    .toggle:disabled,
    .toggle.locked {
        cursor: not-allowed;
    }
    .track {
        position: relative;
        display: inline-block;
        width: 32px;
        height: 18px;
        border-radius: 999px;
        background: var(--border-strong);
        transition: background var(--t-fast);
    }
    .toggle.on .track {
        background: var(--accent);
    }
    .toggle.locked .track {
        opacity: 0.45;
    }
    .thumb {
        position: absolute;
        top: 2px;
        /* inset-inline-start flips with dir: the knob rests at the start edge
           (left in LTR, right in RTL) and slides to the far edge when on, so
           the switch travels the correct way under RTL without a transform. */
        inset-inline-start: 2px;
        width: 14px;
        height: 14px;
        border-radius: 50%;
        background: var(--accent-fg, var(--ink-on-color));
        box-shadow: var(--knob-shadow);
        transition: inset-inline-start var(--t-fast);
        display: flex;
        align-items: center;
        justify-content: center;
    }
    .toggle.on .thumb {
        /* 32px track − 14px thumb − 2px inset = 16px */
        inset-inline-start: 16px;
    }
    .toggle.busy .track {
        opacity: 0.7;
    }
    .toggle:focus-visible {
        outline: none;
    }
    .toggle:focus-visible .track {
        box-shadow: 0 0 0 2px var(--accent);
    }
    .spinner {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        border: 1.5px solid var(--text-faint);
        border-top-color: var(--accent);
        animation: toggle-spin 0.6s linear infinite;
    }
    @keyframes toggle-spin {
        to {
            transform: rotate(360deg);
        }
    }
    .lock {
        font-size: 9px;
        opacity: 0.6;
    }
    .toggle-na {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 32px;
        font-size: 10px;
        letter-spacing: 0.04em;
        color: var(--text-faint);
        font-variant-caps: all-small-caps;
        cursor: default;
    }
</style>
