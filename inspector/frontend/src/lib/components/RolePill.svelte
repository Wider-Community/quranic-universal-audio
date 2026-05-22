<script lang="ts">
    /** Role badge: hue + label + dot-shape (contributor square) so role is
     * distinguishable without colour. Reusable across admin surfaces. */
    let { role = 'contributor' }: { role?: string } = $props();
    const label = $derived(role.charAt(0).toUpperCase() + role.slice(1));
</script>

<span class="role {role}">{label}</span>

<style>
    .role {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 2px 9px;
        border-radius: 999px;
        font-size: 11px;
        font-weight: 500;
        letter-spacing: 0.01em;
        white-space: nowrap;
    }
    .role::before {
        content: '';
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: currentColor;
    }
    .role.owner { color: oklch(0.84 0.11 300); background: oklch(0.84 0.11 300 / 0.14); }
    .role.maintainer { color: var(--accent); background: var(--accent-tint); }
    .role.contributor { color: var(--text-secondary); background: oklch(0.62 0.02 268 / 0.16); }
    /* square dot — extra non-colour cue for contributor */
    .role.contributor::before { border-radius: 1px; }
</style>
