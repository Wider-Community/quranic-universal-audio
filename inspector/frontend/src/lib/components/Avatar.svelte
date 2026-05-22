<script lang="ts">
    /** Initial chip, role-tinted. Reusable wherever a user is shown. */
    interface Props {
        login?: string | null;
        role?: string;
        size?: number;
    }
    let { login = null, role = 'contributor', size = 30 }: Props = $props();

    const initial = $derived(
        (login ?? '').replace(/^@/, '').charAt(0).toUpperCase() || '?',
    );
    const tint = $derived(role === 'owner' || role === 'maintainer' ? role : '');
</script>

<span class="avatar {tint}" style="--sz:{size}px" aria-hidden="true">{initial}</span>

<style>
    .avatar {
        width: var(--sz, 30px);
        height: var(--sz, 30px);
        border-radius: 50%;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-size: calc(var(--sz, 30px) * 0.4);
        font-weight: 600;
        flex-shrink: 0;
        background: var(--panel-2);
        color: var(--text-secondary);
        border: 1px solid var(--border-quiet);
        line-height: 1;
    }
    .avatar.owner {
        background: oklch(0.84 0.11 300 / 0.16);
        color: oklch(0.84 0.11 300);
        border-color: oklch(0.84 0.11 300 / 0.4);
    }
    .avatar.maintainer {
        background: var(--accent-tint);
        color: var(--accent);
        border-color: oklch(0.785 0.13 220 / 0.4);
    }
</style>
