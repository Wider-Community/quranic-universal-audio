<script lang="ts">
    /**
     * Dev-only role switcher. Rendered in the header when the backend
     * reports `dev_mode: true` (i.e. `INSPECTOR_DEV_MODE=1` locally). On
     * the deployed HF Space `dev_mode` is always false so this component
     * never mounts.
     *
     * The selected value is derived from `$currentUser.role` with a
     * `null` role mapping back to "anonymous" so the cookie-less /
     * signed-out case displays correctly.
     */
    import { DEV_ROLES, type DevRole,setDevRole } from '../api/dev-role';
    import { currentUser } from '../stores/current-user';

    let busy = false;
    let lastError: string | null = null;

    $: selected = (($currentUser.role ?? 'anonymous') as DevRole);

    async function onChange(e: Event): Promise<void> {
        const next = (e.target as HTMLSelectElement).value as DevRole;
        if (next === selected) return;
        busy = true;
        lastError = null;
        try {
            await setDevRole(next);
        } catch (err) {
            lastError = err instanceof Error ? err.message : String(err);
        } finally {
            busy = false;
        }
    }
</script>

<label class="dev-role" title="Local dev: synthetic user role. Not shown on the deployed Space.">
    <span class="dev-role__label">dev role</span>
    <select
        class="dev-role__select"
        value={selected}
        disabled={busy}
        on:change={onChange}
    >
        {#each DEV_ROLES as role}
            <option value={role}>{role}</option>
        {/each}
    </select>
    {#if lastError}
        <span class="dev-role__error" title={lastError}>!</span>
    {/if}
</label>

<style>
    .dev-role {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 4px 8px;
        border: 1px dashed var(--state-dev-fg);
        border-radius: 6px;
        background: var(--state-dev-bg);
        font-size: 0.85rem;
        color: var(--state-dev-fg);
    }
    .dev-role__label {
        text-transform: uppercase;
        letter-spacing: 0.05em;
        font-size: 0.7rem;
        font-weight: 600;
        opacity: 0.85;
    }
    .dev-role__select {
        background: var(--input-bg);
        color: var(--dev-select-fg);
        border: 1px solid var(--border-strong);
        border-radius: 4px;
        padding: 3px 6px;
        font-size: 0.85rem;
        cursor: pointer;
        text-transform: capitalize;
    }
    .dev-role__select:hover:not(:disabled) {
        border-color: var(--state-dev-fg);
    }
    .dev-role__select:disabled {
        opacity: 0.6;
        cursor: progress;
    }
    .dev-role__error {
        color: var(--bad-fg);
        font-weight: 700;
    }
</style>
