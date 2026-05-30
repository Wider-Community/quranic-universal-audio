<script lang="ts">
    /**
     * A tiny replica of a validation-card action row, for the special ops
     * (Auto-fill / Ignore) section. Reuses the real `.val-*` action classes so
     * the buttons match what reviewers see on the validation cards.
     */
    interface Props {
        kind: 'autofill' | 'ignore';
    }
    let { kind }: Props = $props();

    const label = $derived(kind === 'autofill' ? 'Missing word' : 'Low confidence');
    const btn = $derived(kind === 'autofill' ? 'Auto-fill' : 'Ignore');
</script>

<div class="eg-val-card" aria-hidden="true">
    <div class="val-card-issue-label">{label}</div>
    <div class="val-card-actions">
        <button
            type="button"
            tabindex="-1"
            class="val-action-btn"
            class:val-action-btn-muted={kind === 'ignore'}
        >{btn}</button>
    </div>
</div>
