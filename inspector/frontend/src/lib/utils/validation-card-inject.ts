/**
 * Shared segment-card injection helper for validation error subcomponents.
 *
 * Renders a segment card via the imperative renderSegCard() and appends it
 * to a container, optionally inserting before an existing element. Also
 * registers any canvas children with the waveform IntersectionObserver so
 * waveforms load lazily as usual.
 */

import type { Segment } from '../../types/domain';
import { renderSegCard } from './segments/render-seg-card';
import { _ensureWaveformObserver } from './segments/waveform-utils';

export interface InjectCardOptions {
    showGotoBtn?: boolean;
    isContext?: boolean;
    contextLabel?: string;
    readOnly?: boolean;
}

/**
 * Render a segment card into `container`, optionally before `insertBeforeEl`.
 * Registers canvas elements with the waveform IntersectionObserver.
 *
 * @returns The injected card element.
 */
export function injectCard(
    container: HTMLElement,
    seg: Segment,
    opts: InjectCardOptions = {},
    insertBeforeEl?: HTMLElement | null,
): HTMLElement {
    const card = renderSegCard(seg, {
        showChapter: true,
        showPlayBtn: true,
        showGotoBtn: opts.showGotoBtn ?? false,
        isContext: opts.isContext ?? false,
        contextLabel: opts.contextLabel ?? '',
        readOnly: opts.readOnly ?? false,
    });
    if (insertBeforeEl) {
        container.insertBefore(card, insertBeforeEl);
    } else {
        container.appendChild(card);
    }
    card.querySelectorAll<HTMLCanvasElement>('canvas[data-needs-waveform]').forEach((c) => {
        _ensureWaveformObserver().observe(c);
    });
    return card;
}
