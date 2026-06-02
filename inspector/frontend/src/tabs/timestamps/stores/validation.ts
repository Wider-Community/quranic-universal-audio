/**
 * Verse-level ts-validation for the Timestamps-tab admin preview.
 *
 * Holds the current reciter's ``ts_validation.json`` (multi-beam generate-job
 * output) or ``null`` when the reciter has none / the user can't preview it.
 * Populated by ``TimestampsTab`` on reciter change (only for users holding
 * ``timestamps.view_validation`` — owner + maintainer by default), consumed
 * by ``TsValidationPanel``.
 */
import { writable } from 'svelte/store';

import type { TsValidationDoc } from '../../../lib/types/generated/schemas';

export const tsValidation = writable<TsValidationDoc | null>(null);
