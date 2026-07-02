<script lang="ts">
    /**
     * A tiny replica of a validation-card action row, for the special ops
     * (Auto-fill / Ignore) section. Reuses the real `.val-*` action classes so
     * the buttons match what reviewers see on the validation cards.
     */
    import { i18n } from '../../../../lib/i18n/locale.svelte';
    import * as m from '../../../../lib/paraglide/messages';

    interface Props {
        kind: 'autofill' | 'ignore';
    }
    let { kind }: Props = $props();

    const label = $derived(
        kind === 'autofill'
            ? (i18n.locale, m.segments_eg_mock_val_missing_word())
            : (i18n.locale, m.segments_eg_mock_val_low_confidence()),
    );
    const btn = $derived(
        kind === 'autofill'
            ? (i18n.locale, m.segments_eg_mock_val_autofill())
            : (i18n.locale, m.segments_eg_mock_val_ignore()),
    );
</script>

<div class="eg-val-card" dir="ltr" aria-hidden="true">
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
