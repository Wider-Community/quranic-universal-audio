<script lang="ts">
    /**
     * The "anatomy of a segment" diagram: one real-looking card plus a legend
     * that names every labelled part in plain language. Used once at the top of
     * the editing guide, right after the "what is a segment" intro.
     */
    import type { PeakBucket } from '../../../../lib/types/domain';
    import MockSegCard from './MockSegCard.svelte';

    interface Props {
        peaks: PeakBucket[];
    }
    let { peaks }: Props = $props();

    const parts: Array<{ dot: string; name: string; what: string }> = [
        { dot: '#4cc9f0', name: 'Waveform', what: 'the segment’s audio — play it, or drag its edges when adjusting.' },
        { dot: '#7a8aa0', name: 'Segment number', what: 'its position in the list (just an index).' },
        { dot: '#4cc9f0', name: 'Reference', what: 'which word(s) it covers, as surah:verse:word.' },
        { dot: '#4caf50', name: 'Confidence', what: 'how sure the match is — green is high, orange medium, red low.' },
        { dot: '#bbbbbb', name: 'Time & duration', what: 'where it starts and ends in the recording, and how long it is.' },
        { dot: '#eeeeee', name: 'Reference text', what: 'the actual Quran words the segment should contain.' },
    ];
</script>

<div class="eg-card-frame">
    <MockSegCard {peaks} />
</div>

<ul class="eg-legend">
    {#each parts as p (p.name)}
        <li class="eg-legend-item">
            <span class="eg-dot" style="background:{p.dot}"></span>
            <span><strong>{p.name}</strong> — {p.what}</span>
        </li>
    {/each}
</ul>
