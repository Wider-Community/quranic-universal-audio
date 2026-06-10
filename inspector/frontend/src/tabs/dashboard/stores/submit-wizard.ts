/**
 * Submit-recitation wizard state. Single open-at-a-time dialog whose
 * dashboard toolbar entry routes new-reciter / new-combination contributions
 * through a 3-step flow (reciter → source → details). Submit is a no-op
 * until the backend ingest path lands; everything below is FE state only.
 *
 * Browser file upload is intentionally absent — see StepSource.svelte for
 * the rationale (single-worker Space + 1–3 GB payloads = unworkable;
 * contributors host audio themselves and hand us URLs).
 */
import { writable } from 'svelte/store';

export type WizardStep = 1 | 2 | 3 | 4;

/**
 * Reciter mode tri-state.
 *  - existing_combo:   reciter exists AND the (riwayah, style) combo already
 *                      lives in the catalog. We route to the per-delivery
 *                      RequestForm flow rather than re-doing it here.
 *  - existing_reciter: reciter exists but this is a NEW combination.
 *  - new:              reciter not in catalog at all.
 */
export type ReciterMode = 'existing_combo' | 'existing_reciter' | 'new';

/**
 * How the recordings reach us. Browser file upload is deliberately
 * excluded — see StepSource.svelte's header comment.
 */
export type SourceMethod = 'links' | 'playlist' | null;

export interface LinkRow {
    chapter: number;
    url: string;
}

export interface NewReciterFields {
    name_en: string;
    name_ar: string;
    countryName: string;
}

export interface CombinationFields {
    riwayah: string;
    style: string;
    recording_context: string;
    recording_year: number | '';
}

/**
 * Step-4 consent gates. The first three are always required; `playlist_public`
 * is an extra gate shown + required only when `sourceMethod === 'playlist'`.
 */
export interface Attestations {
    distribution_rights: boolean;
    links_verified: boolean;
    storage_rights: boolean;
    playlist_public: boolean;
}

export interface SubmitWizardState {
    open: boolean;
    step: WizardStep;

    reciterMode: ReciterMode;
    existingReciterSlug: string | null;
    /** Picked combination slug when reciterMode === 'existing_combo'. */
    existingComboSlug: string | null;
    newReciter: NewReciterFields;

    sourceMethod: SourceMethod;
    links: LinkRow[];            // length 114, 1-indexed by chapter
    playlistUrl: string;

    combination: CombinationFields;
    comments: string;
    autoClaim: boolean;
    attestations: Attestations;
}

function emptyLinks(): LinkRow[] {
    return Array.from({ length: 114 }, (_, i) => ({
        chapter: i + 1,
        url: '',
    }));
}

const initial: SubmitWizardState = {
    open: false,
    step: 1,
    reciterMode: 'existing_reciter',
    existingReciterSlug: null,
    existingComboSlug: null,
    newReciter: { name_en: '', name_ar: '', countryName: '' },
    sourceMethod: 'links',
    links: emptyLinks(),
    playlistUrl: '',
    combination: {
        riwayah: '',
        style: '',
        recording_context: '',
        recording_year: '',
    },
    comments: '',
    autoClaim: false,
    attestations: {
        distribution_rights: false,
        links_verified: false,
        storage_rights: false,
        playlist_public: false,
    },
};

export const submitWizard = writable<SubmitWizardState>(initial);

export function openSubmitWizard(): void {
    submitWizard.set({ ...initial, open: true, links: emptyLinks() });
}

export function closeSubmitWizard(): void {
    submitWizard.update((s) => ({ ...s, open: false }));
}

export function setStep(step: WizardStep): void {
    submitWizard.update((s) => ({ ...s, step }));
}
