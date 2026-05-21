<script lang="ts">
    /**
     * WordTranslation — the per-word "meaning" tier shown above the Arabic word
     * in Analysis view. Presentational only: takes a gloss and renders a quiet
     * chip cohesive with the letter/phoneme tiers but warmer (meaning, not
     * phonetics). `dir="auto"` keeps RTL glosses (Urdu, Persian, Arabic) correct
     * while English stays LTR. Styling lives in styles/timestamps.css so the
     * `.mega-block.active` cross-selector can brighten it during playback.
     *
     * Width is established by the word / letter / phoneme tiers (see the
     * `width: 0; min-width: 100%` rule); the gloss wraps to that width and only
     * breaks onto new lines when it genuinely overflows.
     */
    let { text = '' }: { text?: string } = $props();
</script>

<div class="word-translation" class:is-empty={!text} dir="auto" title={text || undefined}>
    {text}
</div>
