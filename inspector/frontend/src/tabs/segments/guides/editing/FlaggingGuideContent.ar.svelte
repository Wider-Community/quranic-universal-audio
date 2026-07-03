<script lang="ts">
    /**
     * Arabic sibling of `FlaggingGuideContent.svelte` — the illustrated
     * "Flagging" guide body. Selected by `AccordionGuideModal` when the locale is
     * `ar`. Only the prose differs; the shared `MockSegCard` is locale-aware.
     */
    import MockSegCard from './MockSegCard.svelte';
    import { synthPeaks } from './synth-peaks';

    const wave = synthPeaks(150, 11);
</script>

<div class="eg-root">
    <p>
        معظم التعديلات تصلح شيئًا. أما <strong>الإبلاغ</strong> فيترك سؤالًا/تعليقًا فقط. استخدمه
        للحالات التي ليست إصلاحًا واضحًا، أو لشذوذ صوتي، أو لخطأ من القارئ. وأضف تعليقًا مع الإبلاغ.
    </p>

    <div class="eg-card-frame">
        <MockSegCard peaks={wave} emphasize={['flag']} />
    </div>

    <p>
        بمجرد ضبط الإبلاغ، يمكن لأي شخص الرد للمساعدة في حل المشكلة.
    </p>
    <div class="eg-card-frame">
        <MockSegCard peaks={wave} flagged showFlagComment />
    </div>
</div>
