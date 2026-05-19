/**
 * Submit-recitation wizard state. Single open-at-a-time dialog whose
 * dashboard toolbar entry routes new-reciter / new-combination contributions
 * through a 3-step flow. Submit is a no-op until the backend ingest path
 * lands; everything below is FE state only.
 */
import { writable } from 'svelte/store';

export type WizardStep = 1 | 2 | 3;

export type ReciterMode = 'existing' | 'new';

export type SourceMethod = 'upload' | 'links' | 'playlist' | null;

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

export interface SubmitWizardState {
    open: boolean;
    step: WizardStep;

    reciterMode: ReciterMode;
    existingReciterSlug: string | null;
    newReciter: NewReciterFields;

    sourceMethod: SourceMethod;
    uploadedCount: number;       // dummy: file-drop counter
    links: LinkRow[];            // length 114, 1-indexed by chapter
    playlistUrl: string;

    combination: CombinationFields;
    comments: string;
    autoClaim: boolean;
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
    reciterMode: 'existing',
    existingReciterSlug: null,
    newReciter: { name_en: '', name_ar: '', countryName: '' },
    sourceMethod: null,
    uploadedCount: 0,
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
