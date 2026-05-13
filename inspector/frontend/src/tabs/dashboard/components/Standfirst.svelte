<script lang="ts">
    /**
     * Centered one-liner above the catalog.
     * "{N} reciters, {M} combinations across {K} channels."
     */
    export let reciterCount = 0;
    export let combinationCount = 0;
    export let channelCount = 0;
</script>

<header class="standfirst">
    <strong class="num">{reciterCount.toLocaleString()}</strong>
    {reciterCount === 1 ? 'reciter' : 'reciters'},
    <strong class="num">{combinationCount.toLocaleString()}</strong>
    {combinationCount === 1 ? 'combination' : 'combinations'}
    across
    <strong class="num">{channelCount}</strong>
    {channelCount === 1 ? 'channel' : 'channels'}.
</header>

<style>
    .standfirst {
        text-align: center;
        padding: var(--s-8) var(--gutter) var(--s-6);
        color: var(--text-secondary);
        font-size: var(--fs-body);
        line-height: 1.5;
    }
    .num {
        font-variant-numeric: tabular-nums;
        color: var(--text-primary);
        font-weight: 500;
    }
</style>
