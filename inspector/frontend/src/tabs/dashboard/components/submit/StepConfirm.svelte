<script lang="ts">
    /**
     * Wizard step 4 — contributor confirmations.
     *
     * Required consent gates recorded with the submission (audit trail): the
     * right to *share* (distribution / reciter permission), accuracy (links
     * verified), and the right to *store* (QUA download + permanent retention).
     * When the source is a playlist, a fourth gate is shown — the contributor
     * agreeing to keep their own playlist public. Every visible gate must be
     * checked before Submit enables.
     */
    import { fade } from 'svelte/transition';

    import { submitWizard, type Attestations } from '../../stores/submit-wizard';

    type Item = { key: keyof Attestations; text: string };

    $: a = $submitWizard.attestations;
    $: isPlaylist = $submitWizard.sourceMethod === 'playlist';

    function toggle(key: keyof Attestations): void {
        submitWizard.update((s) => ({
            ...s,
            attestations: { ...s.attestations, [key]: !s.attestations[key] },
        }));
    }

    const BASE_ITEMS: Item[] = [
        {
            key: 'distribution_rights',
            text: 'To the best of my knowledge, I have the reciter’s permission or the distribution rights to share these recordings publicly.',
        },
        {
            key: 'links_verified',
            text: 'I have verified that links work and play the correct chapters, and that the metadata is accurate.',
        },
        {
            key: 'storage_rights',
            text: 'I grant Quranic Universal Audio the right to download, process, distribute, and store this audio permanently, under CC By 4.0 license',
        },
    ];
    const PLAYLIST_ITEM: Item = {
        key: 'playlist_public',
        text: 'If this is my own playlist, I agree to keep it public so everyone can benefit from the audio and timings.',
    };

    $: items = isPlaylist ? [...BASE_ITEMS, PLAYLIST_ITEM] : BASE_ITEMS;
</script>

<div class="step" in:fade={{ duration: 180 }}>
    <p class="lede">A few confirmations before we queue this for review.</p>

    <ul class="checks">
        {#each items as item (item.key)}
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
