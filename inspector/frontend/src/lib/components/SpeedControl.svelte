<script lang="ts">
    import { onMount } from 'svelte';

    /** The audio element whose playbackRate this widget controls. */
    export let audioElement: HTMLAudioElement | null = null;
    /** localStorage key for persisting the chosen speed. */
    export let lsKey: string;

    const speeds = [0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4, 5];
    let selected = 1;

    onMount(() => {
        const stored = localStorage.getItem(lsKey);
        if (stored) {
            const v = parseFloat(stored);
            if (!isNaN(v) && speeds.includes(v)) selected = v;
        }
        applySpeed(selected);
    });

    function applySpeed(speed: number): void {
        selected = speed;
        if (audioElement) audioElement.playbackRate = speed;
        localStorage.setItem(lsKey, String(speed));
    }

    function onChange(e: Event): void {
        const v = parseFloat((e.target as HTMLSelectElement).value);
        if (!isNaN(v)) applySpeed(v);
    }

    /** Cycle speed up or down. Callable from parent via bind:this + component ref. */
    export function cycle(direction: 'up' | 'down'): void {
        const idx = speeds.indexOf(selected);
        const cur = idx === -1 ? speeds.indexOf(1) : idx;
        const next = direction === 'up'
            ? Math.min(cur + 1, speeds.length - 1)
            : Math.max(cur - 1, 0);
        const newSpeed = speeds[next];
        if (newSpeed !== undefined) applySpeed(newSpeed);
    }
</script>

<label class="speed-label">
    Speed:
    <select class="speed-select" value={selected} on:change={onChange}>
        {#each speeds as s}
            <option value={s}>{s}x</option>
        {/each}
    </select>
</label>

<style>
    .speed-label {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        font-size: 0.9rem;
        color: #ccc;
    }
    .speed-select {
        background: #16213e;
        color: #eee;
        border: 1px solid #333;
        border-radius: 4px;
        padding: 3px 6px;
        font-size: 0.85rem;
        cursor: pointer;
    }
</style>
