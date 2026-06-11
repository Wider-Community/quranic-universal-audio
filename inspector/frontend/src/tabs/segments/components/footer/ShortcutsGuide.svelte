<script lang="ts">
    /**
     * Footer keyboard-shortcuts popover — reference + inline editor.
     *
     * Lives left of the speed control in the Segments footer (mirrors the
     * Timestamps footer guide drop-up). Lists every shortcut grouped by
     * context (Playback / Editing / Inside a flagged card / While adjusting),
     * each row a label + its key chip. Rebindable chips are buttons: click one
     * to capture a new key (Esc cancels); conflicts within the same context are
     * refused with an inline note. A Reset link restores defaults once anything
     * is customised.
     */
    import { clickOutside } from '../../../../lib/actions/click-outside';
    import Icon from '../../../../lib/icons/Icon.svelte';
    import {
        actionById,
        SHORTCUT_SECTIONS,
        type ShortcutAction,
    } from '../../shortcuts/defaults';
    import {
        hasCustomBindings,
        isCustom,
        keyFor,
        prettyKey,
        resetAll,
        setBinding,
        tokenFromEvent,
    } from '../../shortcuts/store.svelte';

    let open = $state(false);
    let capturingId = $state<string | null>(null);
    let note = $state<string | null>(null);

    function close(): void {
        open = false;
        capturingId = null;
        note = null;
    }

    function startCapture(action: ShortcutAction): void {
        if (!action.rebindable) return;
        note = null;
        capturingId = capturingId === action.id ? null : action.id;
    }

    function onCaptureKey(e: KeyboardEvent): void {
        if (!capturingId) return;
        e.preventDefault();
        e.stopPropagation();
        if (e.code === 'Escape') {
            capturingId = null;
            return;
        }
        const token = tokenFromEvent(e);
        if (!token) return; // bare modifier — keep listening
        const id = capturingId;
        const res = setBinding(id, token);
        if (res.ok) {
            capturingId = null;
            note = null;
        } else if (res.conflict) {
            note = `${prettyKey(token)} is already “${res.conflict.label}”`;
        } else {
            note = 'That key can’t be used here';
        }
    }

    // Window-level capture only while a chip is listening, so the keypress is
    // intercepted before the global Segments dispatcher sees it.
    $effect(() => {
        if (!capturingId) return;
        window.addEventListener('keydown', onCaptureKey, true);
        return () => window.removeEventListener('keydown', onCaptureKey, true);
    });
</script>

<div class="sg-wrap" use:clickOutside={close}>
    <button
        type="button"
        class="sg-trigger"
        class:on={open}
        aria-haspopup="dialog"
        aria-expanded={open}
        title="Keyboard shortcuts"
        onclick={() => (open ? close() : (open = true))}
    >
        <Icon name="keyboard" size={16} />
    </button>

    {#if open}
        <div class="sg-pop" role="dialog" aria-label="Keyboard shortcuts">
            <div class="sg-head">
                <h3>Keyboard shortcuts</h3>
                {#if hasCustomBindings()}
                    <button type="button" class="sg-reset" onclick={() => { resetAll(); note = null; }}>
                        Reset to defaults
                    </button>
                {/if}
            </div>

            <div class="sg-grid">
                {#each SHORTCUT_SECTIONS as sec (sec.title)}
                    <section class="sg-sec">
                        <header class="sg-sec-head">
                            <h4>{sec.title}</h4>
                            <p>{sec.hint}</p>
                        </header>
                        <ul>
                            {#each sec.ids as id (id)}
                                {@const a = actionById(id)}
                                {#if a}
                                    <li class="sg-row">
                                        <span class="sg-label">{a.label}</span>
                                        {#if a.rebindable}
                                            <button
                                                type="button"
                                                class="sg-key sg-key-edit"
                                                class:listening={capturingId === id}
                                                class:custom={isCustom(id)}
                                                title="Click to rebind"
                                                onclick={() => startCapture(a)}
                                            >
                                                {capturingId === id ? 'Press a key…' : prettyKey(keyFor(id))}
                                            </button>
                                        {:else}
                                            <kbd class="sg-key sg-key-fixed">{prettyKey(keyFor(id))}</kbd>
                                        {/if}
                                    </li>
                                {/if}
                            {/each}
                        </ul>
                    </section>
                {/each}
            </div>

            <div class="sg-foot">
                {#if note}
                    <span class="sg-note">{note}</span>
                {:else}
                    <span class="sg-hint">Click a key to rebind · Esc to cancel</span>
                {/if}
            </div>
        </div>
    {/if}
</div>

<style>
    .sg-wrap {
        position: relative;
        display: inline-flex;
    }

    /* Trigger — matches the footer's .pref-cell icon buttons. */
    .sg-trigger {
        width: 26px;
        height: 26px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border: 0;
        border-radius: var(--r-2);
        background: transparent;
        color: var(--text-muted);
        cursor: pointer;
        transition: color var(--t-fast), background var(--t-fast);
    }
    .sg-trigger:hover { color: var(--text-primary); background: var(--panel-2); }
    .sg-trigger.on { color: var(--accent); background: var(--accent-tint); }

    .sg-pop {
        position: absolute;
        bottom: calc(100% + var(--s-2));
        left: 50%;
        transform: translateX(-50%);
        width: min(560px, calc(100vw - var(--s-4) * 2));
        background: var(--panel);
        border: 1px solid var(--border-default);
        border-radius: var(--r-3);
        box-shadow: 0 18px 52px oklch(0 0 0 / 0.5);
        padding: var(--s-3) var(--s-4) var(--s-3);
        z-index: 60;
        animation: sg-rise 140ms var(--ease-out-quart, ease-out);
    }
    @keyframes sg-rise {
        from { opacity: 0; transform: translate(-50%, 6px); }
        to   { opacity: 1; transform: translate(-50%, 0); }
    }
    @media (prefers-reduced-motion: reduce) {
        .sg-pop { animation: none; }
    }

    .sg-head {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: var(--s-3);
        margin-bottom: var(--s-3);
        padding-bottom: var(--s-2);
        border-bottom: 1px solid var(--border-quiet);
    }
    .sg-head h3 {
        margin: 0;
        font-size: var(--fs-row);
        font-weight: 600;
        color: var(--text-primary);
    }
    .sg-reset {
        border: 0;
        background: transparent;
        color: var(--accent);
        font-size: var(--fs-meta);
        cursor: pointer;
        padding: 0;
    }
    .sg-reset:hover { color: var(--accent-strong); text-decoration: underline; }

    .sg-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: var(--s-3) var(--s-4);
        align-items: start;
    }
    .sg-sec { min-width: 0; }
    .sg-sec-head { margin-bottom: 4px; }
    .sg-sec-head h4 {
        margin: 0;
        font-size: var(--fs-meta);
        font-weight: 600;
        color: var(--text-primary);
    }
    .sg-sec-head p {
        margin: 0;
        font-size: 10.5px;
        color: var(--text-muted);
        line-height: var(--lh-tight, 1.25);
    }
    .sg-sec ul {
        margin: 6px 0 0;
        padding: 0;
        list-style: none;
        display: flex;
        flex-direction: column;
        gap: 3px;
    }
    .sg-row {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        min-height: 22px;
    }
    .sg-label {
        flex: 1 1 auto;
        font-size: var(--fs-meta);
        color: var(--text-secondary);
        min-width: 0;
    }

    .sg-key {
        flex: 0 0 auto;
        min-width: 44px;
        text-align: center;
        padding: 2px 7px;
        font-family: var(--font-mono);
        font-size: 10.5px;
        line-height: 1.4;
        border-radius: var(--r-1);
        border: 1px solid var(--border-quiet);
        background: var(--panel-2);
        color: var(--text-secondary);
    }
    .sg-key-fixed { color: var(--text-faint); }
    .sg-key-edit { cursor: pointer; transition: border-color var(--t-fast), color var(--t-fast), background var(--t-fast); }
    .sg-key-edit:hover { color: var(--text-primary); border-color: var(--border-strong); }
    .sg-key-edit.custom { color: var(--accent); border-color: oklch(0.785 0.13 220 / 0.4); }
    .sg-key-edit.listening {
        color: var(--accent);
        border-color: var(--accent);
        background: var(--accent-tint);
        min-width: 88px;
    }

    .sg-foot {
        margin-top: var(--s-3);
        padding-top: var(--s-2);
        border-top: 1px solid var(--border-quiet);
        min-height: 16px;
    }
    .sg-hint { font-size: 10.5px; color: var(--text-faint); }
    .sg-note { font-size: var(--fs-meta); color: var(--state-warn-fg, var(--accent)); }

    @media (max-width: 600px) {
        .sg-grid { grid-template-columns: 1fr; }
    }
</style>
