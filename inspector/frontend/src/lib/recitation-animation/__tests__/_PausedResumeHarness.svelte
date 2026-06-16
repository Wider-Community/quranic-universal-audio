<script lang="ts">
    /**
     * Test-only wrapper: holds `playing` as local `$state` and forwards it to a
     * single, stable AyahFilmstrip instance, so a test can flip play state (and
     * call `refresh()`) WITHOUT re-mounting the filmstrip — faithfully modelling
     * the real parent (`NowReciting`), where the same instance's `playing` prop
     * toggles via the store. (`rerender()` re-mounts, which would drop the
     * in-flight glide under test.)
     */
    import type { ComponentProps } from 'svelte';

    import AyahFilmstrip from '../AyahFilmstrip.svelte';

    let { inner }: { inner: Omit<ComponentProps<typeof AyahFilmstrip>, 'playing'> } = $props();
    let playing = $state(false);
    let fs = $state<ReturnType<typeof AyahFilmstrip> | undefined>(undefined);

    export function setPlaying(v: boolean): void { playing = v; }
    export function refresh(): void { fs?.refresh(); }
</script>

<AyahFilmstrip bind:this={fs} {...inner} {playing} />
