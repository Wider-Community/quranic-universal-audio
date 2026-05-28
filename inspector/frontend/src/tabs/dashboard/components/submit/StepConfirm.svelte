<script lang="ts">
    /**
     * Wizard step 4 — contributor confirmations.
     *
     * Three required consent gates recorded with the submission (audit trail):
     * the right to *share* (distribution / reciter permission), accuracy
     * (links verified), and the right to *store* (QUA download + permanent
     * retention). All three must be checked before Submit enables.
     */
    import { fade } from 'svelte/transition';

    import { submitWizard } from '../../stores/submit-wizard';

    $: a = $submitWizard.attestations;

    function toggle(key: keyof typeof a): void {
        submitWizard.update((s) => ({
            ...s,
            attestations: { ...s.attestations, [key]: !s.attestations[key] },
        }));
    }

    const ITEMS: { key: keyof typeof a; text: string }[] = [
        {
            key: 'distribution_rights',
            text: 'To the best of my knowledge, I have the reciter’s permission or the distribution rights to share these recordings publicly.',
        },
        {
            key: 'links_verified',
            text: 'I have verified that every link opens and plays the correct chapter, and that the metadata is accurate.',
        },
        {
            key: 'storage_rights',
            text: 'I grant Quranic Universal Audio the right to download, store, and process this audio permanently.',
        },
    ];
</script>

<div class="step" in:fade={{ duration: 180 }}>
    <p class="lede">A few confirmations before we queue this for review.</p>

    <ul class="checks">
        {#each ITEMS as item (item.key)}
            <li>
                <label class="check" class:checked={a[item.key]}>
                    <input
                        type="checkbox"
                        checked={a[item.key]}
                        on:change={() => toggle(item.key)}
                    />
                    <span class="box" aria-hidden="true"></span>
                    <span class="text">{item.text}</span>
                </label>
            </li>
        {/each}
    </ul>
</div>

<style>
    .step { display: flex; flex-direction: column; gap: var(--s-4); }
    .lede { margin: 0; font-size: var(--fs-meta); color: var(--text-muted); max-width: 60ch; }
    .checks { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--s-3); }
    .check {
        display: grid;
        grid-template-columns: auto 1fr;
        gap: var(--s-3);
        align-items: start;
        padding: var(--s-3);
        background: var(--canvas-inset);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        cursor: pointer;
        transition: border-color var(--t-fast), background var(--t-fast);
    }
    .check:hover { border-color: var(--border-default); }
    .check.checked { border-color: var(--accent); background: var(--accent-tint-soft); }
    .check input { position: absolute; opacity: 0; width: 0; height: 0; }
    .box {
        width: 18px; height: 18px; margin-top: 1px; border-radius: var(--r-1);
        border: 1px solid var(--border-default); background: var(--panel);
        flex-shrink: 0; position: relative;
        transition: border-color var(--t-fast), background var(--t-fast);
    }
    .check.checked .box { border-color: var(--accent); background: var(--accent); }
    .check.checked .box::after {
        content: '✓'; position: absolute; inset: 0;
        display: flex; align-items: center; justify-content: center;
        color: var(--accent-fg); font-size: 12px; line-height: 1;
    }
    .text { font-size: var(--fs-meta); color: var(--text-secondary); line-height: var(--lh-normal); }
    .check.checked .text { color: var(--text-primary); }
</style>
